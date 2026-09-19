"""多用户账号体系核心（2026-08-28 P0）：
密码哈希（argon2id，pwdlib 官方推荐）+ JWT 签发/校验（PyJWT，官方推荐）+ 当前用户上下文（contextvar）。

设计要点：
- argon2id 防 GPU 破解（官方现行推荐；不用 passlib——有遗留问题）
- JWT HS256 固定 + 强制 exp（防 alg:none/无过期伪造）；密钥从 .env JWT_SECRET 读取（≥32 字节）
- current_user_id: contextvar —— 鉴权中间件在请求作用域设置，数据层路径解析读取
  （directory-per-tenant 模式：每个用户 data/users/<uid>/ 独立目录，数据层只拼路径零 SQL 改动）
- 兼容：.env 未配 JWT_SECRET 时自动生成持久化（写入 .env，防重启失效）
"""
from __future__ import annotations

import os
import secrets
import time
from contextvars import ContextVar
from pathlib import Path
from typing import Optional

import jwt
from pwdlib import PasswordHash

from app.config import PROJECT_ROOT

# ---------- 密码哈希 ----------
_password_hash = PasswordHash.recommended()  # argon2id

def hash_password(plain: str) -> str:
    return _password_hash.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _password_hash.verify(plain, hashed)
    except Exception:
        return False


# ---------- JWT 密钥（.env 持久化，防重启失效） ----------
def _load_or_create_secret() -> str:
    env_path = Path(os.environ.get("SHIGUANG_ENV_FILE") or (PROJECT_ROOT / ".env"))
    secret = os.environ.get("JWT_SECRET", "")
    if secret:
        return secret
    try:
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("JWT_SECRET="):
                    return line.split("=", 1)[1].strip()
        # 未配置 → 生成并持久化
        new_secret = secrets.token_hex(32)
        try:
            with env_path.open("a", encoding="utf-8") as f:
                f.write(f"\n# 多用户会话密钥（2026-08-28 P0 自动生成）\nJWT_SECRET={new_secret}\n")
        except Exception as e:
            print(f"[auth] JWT_SECRET 写入 .env 失败（使用内存密钥，重启后需重新登录）: {e}", flush=True)
        return new_secret
    except Exception as e:
        print(f"[auth] JWT_SECRET 读取失败，回退内存密钥: {e}", flush=True)
        return secrets.token_hex(32)


JWT_SECRET = _load_or_create_secret()
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_SECONDS = 30 * 24 * 3600  # 30 天（家人朋友场景，不搞双令牌复杂度）


def create_access_token(user_id: str) -> str:
    payload = {"sub": user_id, "exp": int(time.time()) + JWT_EXPIRE_SECONDS}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def verify_access_token(token: str) -> Optional[str]:
    """校验 JWT，返回 user_id；无效/过期返回 None（通用错误，不泄露原因）"""
    try:
        payload = jwt.decode(
            token, JWT_SECRET, algorithms=[JWT_ALGORITHM], options={"require": ["exp", "sub"]}
        )
        return payload["sub"]
    except Exception:
        return None


# ---------- 当前用户上下文（directory-per-tenant 路径解析用） ----------
_current_user_id: ContextVar[Optional[str]] = ContextVar("shiguang_current_user_id", default=None)


def set_current_user_id(uid: Optional[str]) -> None:
    _current_user_id.set(uid)


def get_current_user_id() -> Optional[str]:
    """数据层路径解析读取；未登录/豁免端点返回 None（此时全局数据路径兜底）"""
    return _current_user_id.get()


def current_user_required() -> str:
    """受保护数据层入口：无用户上下文时抛错（防止隔离失效静默写全局）"""
    uid = _current_user_id.get()
    if not uid:
        raise RuntimeError("当前请求无用户上下文——数据隔离失效风险，拒绝访问")
    return uid
