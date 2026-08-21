"""M6 督促闭环数据层：wakeups（模型自注册唤醒）/ notifications（待投递）/ daily_activity（学习日志）
设计依据：docs/M6-DESIGN.md
红线：应用层零"该不该提醒"判断——时间与理由全由模型写（schedule_wakeup 工具）；这里只存与投递
"""
import json
import sqlite3
import uuid
from datetime import datetime, timedelta
from contextlib import contextmanager

from app.config import DATA_DIR

DB_PATH = DATA_DIR / "data" / "wakeups.db"

# at 格式说明（工具 docstring 引用，护栏校验用）
AT_FORMAT = "YYYY-MM-DDTHH:MM 或 YYYY-MM-DDTHH:MM:SS（本地时间，如 2026-08-12T09:00；相对时间请按现在时刻转绝对时间）"


def get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def db_session():
    """连接会话：with 只管理事务不关闭连接（2026-08-18 测试 ResourceWarning 挖出）——
    这里补 finally close，杜绝连接泄漏（24 处调用点统一走此入口）。"""
    conn = get_conn()
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def init_db():
    with db_session() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS wakeups ("
            " id TEXT PRIMARY KEY, reason TEXT, at TEXT, status TEXT DEFAULT 'pending',"
            " created_at TEXT DEFAULT (datetime('now','localtime')))"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS notifications ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT, content TEXT,"
            " is_read INTEGER DEFAULT 0, created_at TEXT DEFAULT (datetime('now','localtime')))"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS daily_activity ("
            " date TEXT PRIMARY KEY, topics TEXT, created_at TEXT DEFAULT (datetime('now','localtime')))"
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_wakeups_status ON wakeups(status)")


def _parse_at(at: str) -> datetime | None:
    """护栏：解析 at 为本地 datetime（支持到分钟或秒）；失败返回 None（错误信息交模型自纠，不替它修）"""
    s = at.strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(s[:19], fmt)
        except Exception:
            continue
    return None


# ---------- wakeups ----------
# 守门员护栏（2026-08-13 面试评审抓出）：语义判断（该不该提醒/什么时候）归模型，
# 但【硬性资源护栏】锁代码——判断无墙不变量无口：时段白名单 + 单日配额 + 相似去重。
# 没有这几条，模型抽风/越狱可在凌晨 3 点刷爆通知（"何时提醒归模型"≠"几点能发无限制"）。
WAKEUP_HOUR_MIN = 8    # 白名单时段 8:00-22:00
WAKEUP_HOUR_MAX = 22
WAKEUP_DAILY_LIMIT = 5  # 单日最多注册 5 条待触发提醒


def manage_wakeup(reason: str, at: str = "") -> str:
    """安排或取消拾光在指定时间主动找你（一个工具两个操作，2026-08-17 工具精简）：
    - 安排：reason=到点时说的话；at=触发时间（格式 {AT_FORMAT}）
    - 取消：at 留空=按理由模糊匹配取消最近一条待触发的提醒
    """
    if not (reason or "").strip():
        from app.tools.errors import arg_error
        return arg_error("提醒", "提醒理由不能为空")
    if at and at.strip():
        return schedule_wakeup(reason, at)
    return cancel_wakeup(reason)


def schedule_wakeup(reason: str, at: str) -> str:
    """安排拾光在指定时间主动找你。reason=到点时说的话；at=触发时间（格式 {AT_FORMAT}）"""
    reason = reason.strip()
    if not reason:
        from app.tools.errors import arg_error
        return arg_error("提醒", "提醒理由不能为空")
    dt = _parse_at(at)
    if dt is None:
        from app.tools.errors import arg_error
        return arg_error("提醒", f"时间格式不对，应为 {AT_FORMAT}")
    if dt <= datetime.now():
        from app.tools.errors import arg_error
        return arg_error("提醒", f"时间 {at} 已过去")
    # 守门员：时段白名单（8:00-22:00 之外拒绝注册）
    if dt.hour < WAKEUP_HOUR_MIN or dt.hour >= WAKEUP_HOUR_MAX:
        from app.tools.errors import arg_error
        return arg_error("提醒", "深夜提醒被护栏拒绝（8:00-22:00 之外）")
    with db_session() as conn:
        # 守门员：单日配额（同一天待触发提醒 ≤ 上限）
        day = dt.strftime("%Y-%m-%d")
        cnt = conn.execute(
            "SELECT COUNT(*) c FROM wakeups WHERE status='pending' AND at LIKE ?",
            (day + "%",),
        ).fetchone()["c"]
        if cnt >= WAKEUP_DAILY_LIMIT:
            from app.tools.errors import arg_error
            return arg_error("提醒", f"当天提醒已达上限（{WAKEUP_DAILY_LIMIT} 条），请合并")
        # 守门员：相似去重（同一天相同理由的待触发提醒已存在 → 拒绝）
        dup = conn.execute(
            "SELECT id FROM wakeups WHERE status='pending' AND at LIKE ? AND reason=?",
            (day + "%", reason),
        ).fetchone()
        if dup:
            from app.tools.errors import arg_error
            return arg_error("提醒", "同一天已有相同理由的提醒（护栏去重）")
        wid = uuid.uuid4().hex[:12]
        # 统一存秒级格式（分钟输入补 :00），保证字符串比较对齐
        at_stored = dt.strftime("%Y-%m-%dT%H:%M:%S")
        conn.execute(
            "INSERT INTO wakeups (id, reason, at) VALUES (?,?,?)",
            (wid, reason, at_stored),
        )
    return f"已安排提醒：{dt.strftime('%Y-%m-%d %H:%M:%S')} — {reason}（id={wid}）"


def cancel_wakeup(reason: str) -> str:
    """取消尚未触发的唤醒（按理由模糊匹配，取消最近一条）"""
    reason = reason.strip()
    if not reason:
        from app.tools.errors import arg_error
        return arg_error("提醒", "请给出要取消的提醒理由")
    with db_session() as conn:
        row = conn.execute(
            "SELECT id FROM wakeups WHERE status='pending' AND reason LIKE ? ORDER BY created_at DESC LIMIT 1",
            (f"%{reason}%",),
        ).fetchone()
        if not row:
            from app.tools.errors import tool_err
            return tool_err("提醒", "没有找到待触发的匹配提醒")
        conn.execute("UPDATE wakeups SET status='cancelled' WHERE id=?", (row["id"],))
    return f"已取消提醒：{reason}"


def due_wakeups(now: datetime | None = None) -> list[dict]:
    """到期未触发的唤醒（调度器每分钟扫一次）"""
    now = now or datetime.now()
    with db_session() as conn:
        rows = conn.execute(
            "SELECT * FROM wakeups WHERE status='pending' AND at<=?",
            (now.strftime("%Y-%m-%dT%H:%M:%S"),),
        ).fetchall()
    return [dict(r) for r in rows]


def mark_fired(wid: str):
    with db_session() as conn:
        conn.execute("UPDATE wakeups SET status='fired' WHERE id=?", (wid,))


def list_wakeups(limit: int = 10) -> list[dict]:
    with db_session() as conn:
        rows = conn.execute(
            "SELECT * FROM wakeups ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


# ---------- notifications ----------

def add_notification(content: str):
    with db_session() as conn:
        conn.execute("INSERT INTO notifications (content) VALUES (?)", (content,))


def notifications(limit: int = 20) -> list[dict]:
    with db_session() as conn:
        rows = conn.execute(
            "SELECT * FROM notifications ORDER BY is_read ASC, id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def mark_read(nid: int):
    with db_session() as conn:
        conn.execute("UPDATE notifications SET is_read=1 WHERE id=?", (nid,))


# ---------- daily_activity（streak 真数据）----------

def log_learning(topic: str) -> str:
    """记录今天学了什么（进度/streak 只认这里）。topic=内容主题。
    记进度/学完收尾→本工具；记事实/偏好→remember（remember 不进 streak）"""
    topic = topic.strip()
    if not topic:
        from app.tools.errors import arg_error
        return arg_error("学习日志", "学习主题不能为空")
    today = datetime.now().strftime("%Y-%m-%d")
    with db_session() as conn:
        row = conn.execute("SELECT topics FROM daily_activity WHERE date=?", (today,)).fetchone()
        if row:
            topics = json.loads(row["topics"] or "[]")
            if topic not in topics:
                topics.append(topic)
            conn.execute(
                "UPDATE daily_activity SET topics=? WHERE date=?",
                (json.dumps(topics, ensure_ascii=False), today),
            )
        else:
            conn.execute(
                "INSERT INTO daily_activity (date, topics) VALUES (?,?)",
                (today, json.dumps([topic], ensure_ascii=False)),
            )
    return f"已记录：{today} 学习「{topic}」（火焰又亮了一天）"


def streak_days() -> int:
    """连续学习天数：今天有记录从今天数；今天无记录但有昨天，从昨天数（火焰不灭）；否则 0"""
    with db_session() as conn:
        dates = {r["date"] for r in conn.execute("SELECT date FROM daily_activity").fetchall()}
    if not dates:
        return 0
    streak = 0
    day = datetime.now().date()
    if day.strftime("%Y-%m-%d") not in dates:
        day -= timedelta(days=1)
        if day.strftime("%Y-%m-%d") not in dates:
            return 0
    while day.strftime("%Y-%m-%d") in dates:
        streak += 1
        day -= timedelta(days=1)
    return streak


def has_learning_log() -> bool:
    with db_session() as conn:
        row = conn.execute("SELECT COUNT(*) AS c FROM daily_activity").fetchone()
    return (row["c"] or 0) > 0


def recent_activity(limit: int = 7) -> list[dict]:
    with db_session() as conn:
        rows = conn.execute(
            "SELECT * FROM daily_activity ORDER BY date DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def week_learning_days() -> int:
    """本周（周一至今天）学习天数（S3 ProgressRing 数据源，2026-08-19）。
    目标 6 天/周（贴用户周一至周六备考节奏）；daily_activity 有记录的日期数。"""
    from datetime import timedelta

    today = datetime.now().date()
    monday = today - timedelta(days=today.weekday())  # 周一
    with db_session() as conn:
        rows = conn.execute(
            "SELECT DISTINCT date FROM daily_activity WHERE date >= ? AND date <= ?",
            (monday.isoformat(), today.isoformat()),
        ).fetchall()
    return len(rows)
