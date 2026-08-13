"""M1 会话持久化：SQLite 极简版（sessions + messages JSON）
官方建议：权威历史服务端按 session_id 持久化
"""
import sqlite3
import uuid
from pathlib import Path
from app.config import DATA_DIR

DB_PATH = DATA_DIR / "data" / "sessions.db"
ARCHIVE_DIR = DATA_DIR / "data" / "archive"


def get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_conn() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, title TEXT, created_at TEXT DEFAULT (datetime('now','localtime')))"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS messages ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, role TEXT,"
            " content TEXT, messages_json TEXT, created_at TEXT DEFAULT (datetime('now','localtime')))"
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id)")
        # 老库迁移：sessions 缺 title 列则补（历史会话标题后置回填）
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(sessions)").fetchall()]
        if "title" not in cols:
            conn.execute("ALTER TABLE sessions ADD COLUMN title TEXT")
        # 老库迁移：sessions 缺 summary 列则补（长程 compaction：摘要文本，NULL=未压缩）
        if "summary" not in cols:
            conn.execute("ALTER TABLE sessions ADD COLUMN summary TEXT")
        # 标题回填：无标题会话取第一条用户消息（幂等）
        conn.execute(
            "UPDATE sessions SET title = ("
            " SELECT substr(m.content, 1, 20) FROM messages m"
            " WHERE m.session_id = sessions.id AND m.role = 'user' AND m.content <> ''"
            " ORDER BY m.id ASC LIMIT 1"
            ") WHERE title IS NULL OR title = ''"
        )


def new_session() -> str:
    sid = uuid.uuid4().hex[:12]
    with get_conn() as conn:
        conn.execute("INSERT INTO sessions (id) VALUES (?)", (sid,))
    return sid


def session_exists(sid: str) -> bool:
    with get_conn() as conn:
        row = conn.execute("SELECT id FROM sessions WHERE id=?", (sid,)).fetchone()
    return row is not None


def save_run(sid: str, user_text: str, messages_json: str, is_retry: bool = False):
    """流结束后保存：用户消息 + 完整对话链（all_messages_json 供下次重放）；首次消息生成会话标题。

    #6 去重：用户重试同一消息时不落双份——
    - is_retry=True（前端 X-Retry 标志，重试必带）：直接覆盖该轮 assistant 链
    - 无标志但最后一条 user 消息内容相同 且 120s 内：视为重试（时间窗口防"继续讲讲"复读误吞）
    - 否则：正常插入"""
    from datetime import datetime

    with get_conn() as conn:
        last = conn.execute(
            "SELECT id, content, created_at FROM messages WHERE session_id=? AND role='user' ORDER BY id DESC LIMIT 1",
            (sid,),
        ).fetchone()
        if last and (is_retry or _is_recent_duplicate(last, user_text)):
            # 覆盖：找到紧随该 user 消息的 assistant 行，替换 messages_json（成功链盖失败链），不新增行
            arow = conn.execute(
                "SELECT id FROM messages WHERE session_id=? AND role='assistant' AND id>? ORDER BY id LIMIT 1",
                (sid, last["id"]),
            ).fetchone()
            if arow:
                conn.execute(
                    "UPDATE messages SET messages_json=? WHERE id=?", (messages_json, arow["id"])
                )
            return
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM messages WHERE session_id=?", (sid,)
        ).fetchone()
        if row["c"] == 0:
            title = user_text.strip().replace("\n", " ")[:20] or "新会话"
            conn.execute("UPDATE sessions SET title=? WHERE id=?", (title, sid))
        conn.execute(
            "INSERT INTO messages (session_id, role, content, messages_json) VALUES (?,?,?,?)",
            (sid, "user", user_text, ""),
        )
        conn.execute(
            "INSERT INTO messages (session_id, role, content, messages_json) VALUES (?,?,?,?)",
            (sid, "assistant", "(streamed)", messages_json),
        )


def clear_old_chains(sid: str) -> int:
    """#5 存储 O(n²)→O(n)：压缩成功后清空旧 messages_json（重放只用最后一行，旧行全是浪费）。

    时序关键（用户补）：压缩发生在 save_run 之前——执行时 MAX(id) 是【上一轮】行，保留它（= 压缩输入链，
    也是重放源 + tail 源）；本轮 save_run 之后会再写一行新链。稳态非空行 ≤ 2（保留行 + 最新行）。
    清空条件 id < MAX(id)，绝不在 save_run 之后清（会把自己清掉）。
    archive：清空前把 MAX(id) 行旧链追加到 data/archive/<sid>.jsonl（append-only 日志性质，个人使用月级 MB；
    无清理机制——哪天嫌多再加阈值）。归档失败不阻塞主流程（保险不是主流程）。"""
    from datetime import datetime

    with get_conn() as conn:
        last = conn.execute(
            "SELECT MAX(id) m FROM messages WHERE session_id=?", (sid,)
        ).fetchone()["m"]
        if not last:
            return 0
        # 归档最后一行旧链（压缩输入链）
        try:
            ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
            row = conn.execute(
                "SELECT messages_json FROM messages WHERE id=?", (last,)
            ).fetchone()
            if row and row["messages_json"]:
                with open(ARCHIVE_DIR / f"{sid}.jsonl", "a", encoding="utf-8") as f:
                    f.write(
                        f"{datetime.now().isoformat(timespec='seconds')}\t{row['messages_json']}\n"
                    )
        except Exception as e:
            print(f"[archive] 会话 {sid[:8]} 归档失败（跳过，不阻塞压缩）: {e}", flush=True)
        conn.execute(
            "UPDATE messages SET messages_json='' WHERE session_id=? AND id<?", (sid, last)
        )
        return 1

def vacuum():
    """#5 文件收缩：清空旧链后 SQLite 文件不自动释放——VACUUM 重写（启动时调用，无并发锁库安全）"""
    with get_conn() as conn:
        conn.execute("VACUUM")


def _is_recent_duplicate(last_row, user_text: str) -> bool:
    """最后一条 user 消息内容相同 且在 120s 内 → 可能是重试（不是复读）。解析失败保守返回 False"""
    from datetime import datetime

    if last_row["content"] != user_text:
        return False
    try:
        ts = datetime.strptime(last_row["created_at"], "%Y-%m-%d %H:%M:%S")
        return (datetime.now() - ts).total_seconds() < 120
    except Exception:
        return False


def list_sessions(limit: int = 50) -> list[dict]:
    """历史会话列表（B）：id + 标题 + 时间 + 消息数，按最近排"""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT s.id, s.title, s.created_at,"
            " (SELECT COUNT(*) FROM messages m WHERE m.session_id = s.id) AS msg_count"
            " FROM sessions s ORDER BY s.created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def load_messages_json(sid: str) -> str | None:
    """取最近一次 run 的完整对话链 JSON（pydantic-ai ModelMessage 序列化）"""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT messages_json FROM messages WHERE session_id=? AND messages_json<>'' ORDER BY id DESC LIMIT 1",
            (sid,),
        ).fetchone()
    return row["messages_json"] if row else None


# ---------- 长程 compaction（Pi 机制轻量版：摘要 + 尾部保留）----------

def get_summary(sid: str) -> str | None:
    """已压缩会话的摘要；未压缩返回 None"""
    with get_conn() as conn:
        row = conn.execute("SELECT summary FROM sessions WHERE id=?", (sid,)).fetchone()
    return row["summary"] if row else None


def set_summary(sid: str, summary: str):
    """写入摘要（幂等；压缩后 messages 原样保留，仅上下文构建时用摘要替换）"""
    with get_conn() as conn:
        conn.execute("UPDATE sessions SET summary=? WHERE id=?", (summary, sid))


def messages_total_chars(sid: str) -> int:
    """该会话消息内容累计字符数（触发压缩的估算依据；中文≈1字符≈1 token 保守估）"""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(LENGTH(content)), 0) AS total FROM messages WHERE session_id=?",
            (sid,),
        ).fetchone()
    return row["total"]
