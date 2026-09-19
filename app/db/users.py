"""多用户账号表（2026-08-28 P0）：data/users.db —— 全局唯一（账号体系不分租户）。
- 密码只存 argon2id 哈希（永不存明文）
- 首个注册用户 = is_admin=1（管理员：PC 端重置密码/用户管理）
- email 唯一（登录凭据）；nickname 展示名
"""
from __future__ import annotations

import secrets
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime
from typing import Optional

from app.config import DATA_DIR

DB_PATH = DATA_DIR / "data" / "users.db"


def get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def db_session():
    conn = get_conn()
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def init_db():
    with db_session() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS users ("
            " id TEXT PRIMARY KEY,"
            " email TEXT UNIQUE NOT NULL,"
            " nickname TEXT NOT NULL,"
            " password_hash TEXT NOT NULL,"
            " is_admin INTEGER NOT NULL DEFAULT 0,"
            " created_at TEXT NOT NULL,"
            " avatar TEXT DEFAULT ''"
            ")"
        )
        # 2026-08-29 头像：老库无 avatar 列 → ALTER 补列（幂等：已有列会抛错，忽略）
        try:
            conn.execute("ALTER TABLE users ADD COLUMN avatar TEXT DEFAULT ''")
        except Exception:  # noqa: S110 —— 列已存在（新库 CREATE 已含），幂等迁移属预期路径
            pass
        # 邀请码（2026-08-28 P3 公网加固）：注册必填；max_uses=0 表示无限；used 已用次数
        conn.execute(
            "CREATE TABLE IF NOT EXISTS invite_codes ("
            " code TEXT PRIMARY KEY,"
            " max_uses INTEGER NOT NULL DEFAULT 1,"
            " used INTEGER NOT NULL DEFAULT 0,"
            " created_at TEXT NOT NULL"
            ")"
        )


def create_user(email: str, nickname: str, password_hash: str) -> tuple[str, bool]:
    """创建用户。返回 (user_id, is_admin)。首个用户自动成为管理员。"""
    with db_session() as conn:
        count = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
        uid = uuid.uuid4().hex[:12]
        is_admin = 1 if count == 0 else 0
        conn.execute(
            "INSERT INTO users (id, email, nickname, password_hash, is_admin, created_at)"
            " VALUES (?,?,?,?,?,?)",
            (uid, email.lower().strip(), nickname.strip(), password_hash, is_admin,
             datetime.now().isoformat(timespec="seconds")),
        )
        return uid, bool(is_admin)


def get_user_by_email(email: str) -> Optional[dict]:
    with db_session() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE email=?", (email.lower().strip(),)
        ).fetchone()
    return dict(row) if row else None


def get_user_by_id(uid: str) -> Optional[dict]:
    with db_session() as conn:
        row = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    return dict(row) if row else None


def user_count() -> int:
    with db_session() as conn:
        row = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()
    return row["c"]


def reset_password(uid: str, new_password_hash: str) -> bool:
    """管理员重置密码（PC 端脚本调用）"""
    with db_session() as conn:
        cur = conn.execute("UPDATE users SET password_hash=? WHERE id=?", (new_password_hash, uid))
        return cur.rowcount > 0


def create_invite_code(max_uses: int = 1) -> str:
    """管理员生成邀请码（返回 code）"""
    code = "SG-" + secrets.token_hex(6).upper()
    with db_session() as conn:
        conn.execute(
            "INSERT INTO invite_codes (code, max_uses, used, created_at) VALUES (?,?,0,?)",
            (code, max_uses, datetime.now().isoformat(timespec="seconds")),
        )
    return code


def list_invite_codes() -> list[dict]:
    with db_session() as conn:
        rows = conn.execute(
            "SELECT code, max_uses, used, created_at FROM invite_codes ORDER BY created_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def consume_invite_code(code: str) -> bool:
    """校验并消费一个邀请码（used < max_uses 才可用；max_uses=0=无限）"""
    code = code.strip().upper()
    with db_session() as conn:
        row = conn.execute("SELECT * FROM invite_codes WHERE code=?", (code,)).fetchone()
        if not row:
            return False
        if row["max_uses"] > 0 and row["used"] >= row["max_uses"]:
            return False
        conn.execute("UPDATE invite_codes SET used = used + 1 WHERE code=?", (code,))
        return True


def revoke_invite_code(code: str) -> bool:
    with db_session() as conn:
        cur = conn.execute("DELETE FROM invite_codes WHERE code=?", (code.strip().upper(),))
        return cur.rowcount > 0


def list_users() -> list[dict]:
    with db_session() as conn:
        rows = conn.execute(
            "SELECT id, email, nickname, is_admin, created_at FROM users ORDER BY created_at ASC"
        ).fetchall()
    return [dict(r) for r in rows]


def update_avatar(uid: str, avatar: str) -> bool:
    """更新用户头像（base64 data URI，128px 小图）；空串=清除。"""
    with db_session() as conn:
        cur = conn.execute("UPDATE users SET avatar=? WHERE id=?", (avatar, uid))
        return cur.rowcount > 0
