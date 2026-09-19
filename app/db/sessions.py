"""M1 会话持久化：SQLite 极简版（sessions + messages JSON）
官方建议：权威历史服务端按 session_id 持久化
"""

import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from app.config import DATA_DIR
from app.user_data import user_db_path

# 2026-08-28 P0 多用户：路径 per-user 解析（uid=None 回退全局，兼容未迁移/未登录）

# 测试覆盖钩子（2026-08-28：存量测试从模块常量注入迁移——函数化后直接赋值会覆盖函数本身）
_DB_OVERRIDE: Path | None = None
_ARCHIVE_OVERRIDE: Path | None = None


def _db_path(uid: str | None) -> Path:
    if _DB_OVERRIDE is not None:
        return _DB_OVERRIDE
    return user_db_path(uid, "sessions.db") if uid else DATA_DIR / "data" / "sessions.db"


def _archive_dir(uid: str | None) -> Path:
    if _ARCHIVE_OVERRIDE is not None:
        return _ARCHIVE_OVERRIDE
    return user_db_path(uid, "archive") if uid else DATA_DIR / "data" / "archive"


_INITIALIZED: set[str | None] = set()  # 进程内记忆化：每个 uid 只验一次，避免每请求建表语句


def get_conn(uid: str | None = None) -> sqlite3.Connection:
    _db_path(uid).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_db_path(uid)))
    conn.execute("PRAGMA journal_mode=WAL")  # 2026-08-27 P1-7：读写并发优化（官方推荐，backup API 兼容）
    conn.row_factory = sqlite3.Row
    # 惰性自愈建表（2026-09-02）：启动期只初始化默认 uid，任何其他 uid（新用户/迁移/手工目录）
    # 首次访问时库表缺失会 500——建表幂等且按 uid 记忆化，重复调用零开销。
    if uid not in _INITIALIZED:
        try:
            _ensure_tables(conn)
            _INITIALIZED.add(uid)
        except Exception as e:  # 建表失败不该放大成接口 500（上层会给出真实错误）
            print(f"[db] 惰性建表失败（uid={uid}）：{e}", flush=True)
    return conn


@contextmanager
def db_session(uid: str | None = None):
    """连接会话：with 只管理事务不关闭连接（2026-08-18 测试 ResourceWarning 挖出）——
    这里补 finally close，杜绝连接泄漏（24 处调用点统一走此入口）。"""
    conn = get_conn(uid)
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def _ensure_tables(conn: sqlite3.Connection) -> None:
    """幂等建表 + 老库迁移（唯一实现：init_db 与惰性自愈共用，禁止第二份 DDL）。"""
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


def init_db(uid: str | None = None):
    with db_session(uid) as conn:
        _ensure_tables(conn)
    _INITIALIZED.add(uid)  # 启动期已建表 → 惰性路径不再重复验


def new_session(uid: str | None = None) -> str:
    sid = uuid.uuid4().hex[:12]
    with db_session(uid) as conn:
        conn.execute("INSERT INTO sessions (id) VALUES (?)", (sid,))
    return sid


def session_exists(sid: str, uid: str | None = None) -> bool:
    with db_session(uid) as conn:
        row = conn.execute("SELECT id FROM sessions WHERE id=?", (sid,)).fetchone()
    return row is not None


def save_user_message(sid: str, user_text: str, uid: str | None = None) -> None:
    """B1 消息级持久化（2026-08-20）：用户消息【无条件前置落库】——请求开始即调用，断流也不丢用户输入。
    与 save_assistant_message 配合（拆原 save_run）：用户消息先落，assistant 链 finally 兜底。
    去重：与最后一条 user 消息内容相同且 120s 内 → 跳过插入（重试语义在 assistant 层处理）。"""
    with db_session(uid) as conn:
        last = conn.execute(
            "SELECT id, content, created_at FROM messages WHERE session_id=? AND role='user' ORDER BY id DESC LIMIT 1",
            (sid,),
        ).fetchone()
        if last and _is_recent_duplicate(last, user_text):
            return  # 同内容重试/复读——不重复插 user 行
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


def save_assistant_message(
    sid: str, user_text: str, messages_json: str, is_retry: bool = False, uid: str | None = None
) -> None:
    """B1 finally 兜底（2026-08-20）：找该轮 user 消息后的 assistant 行——有则覆盖（重试）/ 无则插入。
    同步函数（无 await，CancelledError 只注入 await 点 → finally 里可可靠执行）。
    去重分工：user 行去重归 save_user_message（重试不插新 user 行）；assistant 行按"user 后有无行"判定——
    修正 2026-08-20：原按 120s 内容重复判定会把"本轮刚插的 user 行"误判成重试导致 assistant 不落（测试抓出）。"""
    with db_session(uid) as conn:
        last = conn.execute(
            "SELECT id, content, created_at FROM messages WHERE session_id=? AND role='user' ORDER BY id DESC LIMIT 1",
            (sid,),
        ).fetchone()
        if not last:
            return  # user 行未落（极端）——save_user_message 已尽力，assistant 不强插
        arow = conn.execute(
            "SELECT id FROM messages WHERE session_id=? AND role='assistant' AND id>? ORDER BY id LIMIT 1",
            (sid, last["id"]),
        ).fetchone()
        if arow:
            # 该轮已有 assistant 行（重试/复跑）——B2 修复（2026-08-20）：**失败不销毁**——
            # 空链（失败 messages_json=''）不覆盖非空链（可能是压缩保留行=早期上下文唯一载体，
            # 覆盖成空 → 下一轮读 None → 摘要注入不了 → 压缩前上下文永久丢失，复现见 B2）
            if messages_json:
                conn.execute(
                    "UPDATE messages SET messages_json=? WHERE id=?", (messages_json, arow["id"])
                )
            return
        conn.execute(
            "INSERT INTO messages (session_id, role, content, messages_json) VALUES (?,?,?,?)",
            (sid, "assistant", "(streamed)", messages_json),
        )


def clear_old_chains(sid: str, uid: str | None = None) -> int:
    """#5 存储 O(n²)→O(n)：压缩成功后清空旧 messages_json（重放只用最后一行，旧行全是浪费）。

    时序关键（用户补）：压缩发生在 save_run 之前——执行时 MAX(id) 是【上一轮】行，保留它（= 压缩输入链，
    也是重放源 + tail 源）；本轮 save_run 之后会再写一行新链。稳态非空行 ≤ 2（保留行 + 最新行）。
    清空条件 id < MAX(id)，绝不在 save_run 之后清（会把自己清掉）。
    archive：清空前把 MAX(id) 行旧链追加到 data/archive/<sid>.jsonl（append-only 日志性质，个人使用月级 MB；
    无清理机制——哪天嫌多再加阈值）。归档失败不阻塞主流程（保险不是主流程）。"""
    from datetime import datetime

    with db_session(uid) as conn:
        last = conn.execute("SELECT MAX(id) m FROM messages WHERE session_id=?", (sid,)).fetchone()[
            "m"
        ]
        if not last:
            return 0
        # 归档最后一行旧链（压缩输入链）
        try:
            _archive_dir(uid).mkdir(parents=True, exist_ok=True)
            row = conn.execute("SELECT messages_json FROM messages WHERE id=?", (last,)).fetchone()
            if row and row["messages_json"]:
                with open(_archive_dir(uid) / f"{sid}.jsonl", "a", encoding="utf-8") as f:
                    f.write(
                        f"{datetime.now().isoformat(timespec='seconds')}\t{row['messages_json']}\n"
                    )
        except Exception as e:
            print(f"[archive] 会话 {sid[:8]} 归档失败（跳过，不阻塞压缩）: {e}", flush=True)
        conn.execute(
            "UPDATE messages SET messages_json='' WHERE session_id=? AND id<?", (sid, last)
        )
        return 1


def vacuum(uid: str | None = None):
    """#5 文件收缩：清空旧链后 SQLite 文件不自动释放——VACUUM 重写（启动时调用，无并发锁库安全）"""
    with db_session(uid) as conn:
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


def list_sessions(uid: str | None = None, limit: int = 50) -> list[dict]:
    """历史会话列表（B）：id + 标题 + 时间 + 消息数，按最近排"""
    with db_session(uid) as conn:
        rows = conn.execute(
            "SELECT s.id, s.title, s.created_at,"
            " (SELECT COUNT(*) FROM messages m WHERE m.session_id = s.id) AS msg_count"
            " FROM sessions s ORDER BY s.created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def delete_session(sid: str, uid: str | None = None) -> bool:
    """用户治理权（2026-08-18 补洞）：删除一个会话。
    安全设计：归档先行（完整对话链追加到 data/archive/<sid>.jsonl），归档成功才删库行——
    删了也能找回（archive 是 append-only 日志性质），防误删=不可逆损失。
    返回 True=删除成功 / False=会话不存在（幂等）。"""
    from datetime import datetime

    with db_session(uid) as conn:
        row = conn.execute("SELECT title FROM sessions WHERE id=?", (sid,)).fetchone()
        if not row:
            return False
        # 1. 归档完整对话（所有非空 messages_json 链 + 标题头）
        try:
            _archive_dir(uid).mkdir(parents=True, exist_ok=True)
            chains = conn.execute(
                "SELECT messages_json FROM messages WHERE session_id=? AND messages_json<>'' ORDER BY id",
                (sid,),
            ).fetchall()
            with open(_archive_dir(uid) / f"{sid}.jsonl", "w", encoding="utf-8") as f:
                f.write(f"# title: {row['title'] or ''}\n")
                for ch in chains:
                    f.write(
                        f"{datetime.now().isoformat(timespec='seconds')}\t{ch['messages_json']}\n"
                    )
        except Exception as e:
            print(
                f"[archive] 会话 {sid[:8]} 删除前归档失败——放弃删除（不可逆操作需归档兜底）: {e}",
                flush=True,
            )
            return False
        # 2. 归档成功 → 删库行
        conn.execute("DELETE FROM messages WHERE session_id=?", (sid,))
        conn.execute("DELETE FROM sessions WHERE id=?", (sid,))
        return True


def load_messages_json(sid: str, uid: str | None = None) -> str | None:
    """取最近一次 run 的完整对话链 JSON（pydantic-ai ModelMessage 序列化）"""
    with db_session(uid) as conn:
        row = conn.execute(
            "SELECT messages_json FROM messages WHERE session_id=? AND messages_json<>'' ORDER BY id DESC LIMIT 1",
            (sid,),
        ).fetchone()
    return row["messages_json"] if row else None


# ---------- 先贤会议辩论消息（M3，2026-08-19：复用 messages 表，role='debate'）----------


def save_debate_event(sid: str, event_json: str, uid: str | None = None):
    """持久化一条辩论事件（budget/turn/verdict/report...）——role='debate' 行，按 id 保序"""
    if not sid:
        return
    with db_session(uid) as conn:
        conn.execute(
            "INSERT INTO messages (session_id, role, content) VALUES (?,?,?)",
            (sid, "debate", event_json),
        )


def load_debate_events(sid: str, uid: str | None = None) -> list[dict]:
    """会话的全部辩论事件（按 id 升序），用于前端消息流合并恢复"""
    with db_session(uid) as conn:
        rows = conn.execute(
            "SELECT id, content FROM messages WHERE session_id=? AND role='debate' ORDER BY id ASC",
            (sid,),
        ).fetchall()
    return [{"id": r["id"], "event": r["content"]} for r in rows]


# ---------- 长程 compaction（Pi 机制轻量版：摘要 + 尾部保留）----------


def get_summary(sid: str, uid: str | None = None) -> str | None:
    """已压缩会话的摘要；未压缩返回 None"""
    with db_session(uid) as conn:
        row = conn.execute("SELECT summary FROM sessions WHERE id=?", (sid,)).fetchone()
    return row["summary"] if row else None


def set_summary(sid: str, summary: str, uid: str | None = None):
    """写入摘要（幂等；压缩后 messages 原样保留，仅上下文构建时用摘要替换）"""
    with db_session(uid) as conn:
        conn.execute("UPDATE sessions SET summary=? WHERE id=?", (summary, sid))


def messages_total_chars(sid: str, uid: str | None = None) -> int:
    """该会话消息内容累计字符数（触发压缩的估算依据；中文≈1字符≈1 token 保守估）"""
    with db_session(uid) as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(LENGTH(content)), 0) AS total FROM messages WHERE session_id=?",
            (sid,),
        ).fetchone()
    return row["total"]
