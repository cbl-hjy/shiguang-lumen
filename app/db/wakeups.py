"""M6 督促闭环数据层：wakeups（模型自注册唤醒）/ notifications（待投递）/ daily_activity（学习日志）
设计依据：docs/M6-DESIGN.md
红线：应用层零"该不该提醒"判断——时间与理由全由模型写（schedule_wakeup 工具）；这里只存与投递
"""

import json
import re
import sqlite3
import sys
import uuid
from datetime import datetime, timedelta
from contextlib import contextmanager

from app.config import DATA_DIR
from app.auth_core import get_current_user_id
from app.user_data import get_user_data_dir
from pathlib import Path


_DB_OVERRIDE: Path | None = None  # 测试注入点（2026-08-28：存量测试从模块常量注入迁移）


def DB_PATH() -> Path:
    if _DB_OVERRIDE is not None:
        return _DB_OVERRIDE
    uid = get_current_user_id()
    if uid:
        return get_user_data_dir(uid) / "wakeups.db"
    return DATA_DIR / "data" / "wakeups.db"

# at 格式说明（工具 docstring 引用，护栏校验用）
AT_FORMAT = "YYYY-MM-DDTHH:MM 或 YYYY-MM-DDTHH:MM:SS（本地时间，如 2026-08-12T09:00；相对时间请按现在时刻转绝对时间）"


# 2026-08-28 根治 per-user 库表缺失（/api/notifications 500 + traceback 刷屏 1.7MB）：
# P0 多用户改造把 wakeups 库 per-user 化后，启动时 init_db 只建了全局库——用户库首次访问时表不存在。
# 懒初始化：任何库首次连接即建表（幂等），_ready 缓存路径只做一次，零重复开销。
_ready: set = set()


def get_conn() -> sqlite3.Connection:
    p = DB_PATH()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.execute("PRAGMA journal_mode=WAL")  # 2026-08-27 P1-7
    conn.row_factory = sqlite3.Row
    key = str(p)
    if key not in _ready:
        try:
            _ensure_tables(conn)
            conn.commit()
            _ready.add(key)
        except Exception as _e:
            print(f"[db/wakeups] 静默异常已可见化: {_e}", flush=True)
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


_TABLES_SQL = (
    "CREATE TABLE IF NOT EXISTS wakeups ("
    " id TEXT PRIMARY KEY, reason TEXT, at TEXT, status TEXT DEFAULT 'pending',"
    " created_at TEXT DEFAULT (datetime('now','localtime')))",
    "CREATE TABLE IF NOT EXISTS notifications ("
    " id INTEGER PRIMARY KEY AUTOINCREMENT, content TEXT,"
    " is_read INTEGER DEFAULT 0, created_at TEXT DEFAULT (datetime('now','localtime')))",
    "CREATE TABLE IF NOT EXISTS daily_activity ("
    " date TEXT PRIMARY KEY, topics TEXT, created_at TEXT DEFAULT (datetime('now','localtime')))",
    "CREATE INDEX IF NOT EXISTS idx_wakeups_status ON wakeups(status)",
)


def _ensure_tables(conn: sqlite3.Connection) -> None:
    """建表（幂等）——供 init_db 与 get_conn 懒初始化共用"""
    for sql in _TABLES_SQL:
        conn.execute(sql)


def init_db():
    with db_session() as conn:
        _ensure_tables(conn)


def _parse_at(at: str) -> datetime | None:
    """护栏：解析 at 为本地 datetime（支持到分钟或秒）；失败返回 None（错误信息交模型自纠，不替它修）

    2026-09-17 审计修复（发现 2）：此前"先试秒格式、再试分钟格式"的重试逻辑在**第一次
    尝试失败时就打印** stderr——正常路径（无秒格式）会误打"跳过异常项"，真异常被淹没。
    现改为：两种格式均失败时打印一次（真失败可见，正常路径静默）。
    """
    s = at.strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(s[:19], fmt)
        except ValueError:
            continue
    print(f"[wakeups] 时间解析失败: {at!r}", file=sys.stderr)
    return None


# ---------- wakeups ----------
# 守门员护栏（2026-08-13 面试评审抓出）：语义判断（该不该提醒/什么时候）归模型，
# 但【硬性资源护栏】锁代码——判断无墙不变量无口：时段白名单 + 单日配额 + 相似去重。
# 没有这几条，模型抽风/越狱可在凌晨 3 点刷爆通知（"何时提醒归模型"≠"几点能发无限制"）。
WAKEUP_HOUR_MIN = 8  # 白名单时段 8:00-22:00
WAKEUP_HOUR_MAX = 22
WAKEUP_DAILY_LIMIT = 5  # 单日最多注册 5 条待触发提醒


def _normalize_reason(reason: str) -> str:
    """去重口径归一化（2026-09-17 审计修复，发现 1）：删除所有空白 + 去首尾常见标点。

    防"排版变体"绕过同日去重（审计实测确认可绕过：中间空格 `复习 正则化`、尾部句点
    `复习正则化。`；尾随空格此前已被 reason.strip() 兜住）。中文场景空白不承载语义，
    首尾标点不改变提醒含义——归一化后比较，误拒风险可忽略。
    """
    s = re.sub(r"\s+", "", reason)
    return s.strip("。．.，,、；;：:！!？?～~—…·")


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
            "SELECT COUNT(*) c FROM wakeups WHERE status='pending' AND at LIKE ?", (day + "%",)
        ).fetchone()["c"]
        if cnt >= WAKEUP_DAILY_LIMIT:
            from app.tools.errors import arg_error

            return arg_error("提醒", f"当天提醒已达上限（{WAKEUP_DAILY_LIMIT} 条），请合并")
        # 守门员：相似去重（同一天相同理由的待触发提醒已存在 → 拒绝）
        # 2026-09-17 审计修复（发现 1）：改为**归一化后**比较（防空格/标点变体绕过）；
        # 当天 pending ≤ 配额 5 条，拉回 Python 层比较成本可忽略。
        rows = conn.execute(
            "SELECT reason FROM wakeups WHERE status='pending' AND at LIKE ?",
            (day + "%",),
        ).fetchall()
        _norm = _normalize_reason(reason)
        if any(_normalize_reason(r["reason"] or "") == _norm for r in rows):
            from app.tools.errors import arg_error

            return arg_error("提醒", "同一天已有相同理由的提醒（护栏去重）")
        wid = uuid.uuid4().hex[:12]
        # 统一存秒级格式（分钟输入补 :00），保证字符串比较对齐
        at_stored = dt.strftime("%Y-%m-%dT%H:%M:%S")
        conn.execute(
            "INSERT INTO wakeups (id, reason, at) VALUES (?,?,?)", (wid, reason, at_stored)
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


def due_wakeups_all(now: datetime | None = None) -> list[tuple[str | None, dict]]:
    """全部到期未触发的唤醒（多用户版，2026-09-17 修复投递断裂）：

    遍历全局库 + `data/users/*/wakeups.db`，返回 `[(uid, wakeup)]`——uid=None 表示全局库。

    背景：多用户改造（08-28）后用户提醒写 per-user 库，而调度器（无请求上下文）
    只扫全局库 → **注册的提醒永远不会触发**（2026-09-17 B 实验预审发现）。
    测试兼容：`_DB_OVERRIDE` 注入时只扫注入库（返回 [(None, row)]）。
    """
    if _DB_OVERRIDE is not None:
        return [(None, w) for w in due_wakeups(now)]

    _now = (now or datetime.now()).strftime("%Y-%m-%dT%H:%M:%S")
    out: list[tuple[str | None, dict]] = []

    def _scan(db: Path, uid: str | None) -> None:
        if not db.exists():
            return
        try:
            conn = sqlite3.connect(str(db))
            conn.row_factory = sqlite3.Row
            try:
                rows = conn.execute(
                    "SELECT * FROM wakeups WHERE status='pending' AND at<=?", (_now,),
                ).fetchall()
                out.extend((uid, dict(r)) for r in rows)
            finally:
                conn.close()
        except Exception as e:  # 单库失败不拖垮整个扫描（可见化）
            print(f"[db/wakeups] 用户库扫描失败 {db}: {e}", file=sys.stderr)

    _scan(DATA_DIR / "data" / "wakeups.db", None)
    users_dir = DATA_DIR / "data" / "users"
    if users_dir.exists():
        for d in sorted(users_dir.iterdir()):
            if d.is_dir():
                _scan(d / "wakeups.db", d.name)
    return out


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
