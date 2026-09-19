"""多用户认证 API（2026-08-28 P0 + P3 公网加固）：
- POST /api/auth/register：昵称 + 邮箱 + 密码（≥8）+ 邀请码 → 返回 JWT
  首用户需用服务端引导码（防公网陌生人抢占管理员）；之后需管理员生成的邀请码
- POST /api/auth/login：邮箱 + 密码 → JWT；登录限流（IP 10 分钟 5 次失败锁 1 小时）
- GET  /api/auth/me：当前用户信息（JWT 鉴权）
- 错误统一"邮箱或密码错误"（不泄露账号是否存在——官方最佳实践）
- 登录/注册事件落盘 data/access_log.jsonl（公网可追溯）
"""
from __future__ import annotations

import time
from collections import defaultdict

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field

from app import auth_core
from app.config import DATA_DIR
from app.db import users as users_db

router = APIRouter(prefix="/api/auth", tags=["auth"])


class RegisterIn(BaseModel):
    nickname: str = Field(min_length=1, max_length=24)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    invite_code: str = Field(min_length=6, max_length=64)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: str
    nickname: str
    email: str
    is_admin: bool
    avatar: str = ""  # 2026-08-29：base64 data URI（128px 小图）；空=未设置


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


def _user_out(u: dict) -> UserOut:
    return UserOut(
        id=u["id"],
        nickname=u["nickname"],
        email=u["email"],
        is_admin=bool(u["is_admin"]),
        avatar=u.get("avatar") or "",
    )


# ---------- 登录限流（P3 公网加固）：IP 10 分钟失败 5 次 → 锁 1 小时 ----------
_login_fail: dict[str, list[float]] = defaultdict(list)


def _login_ok(ip: str) -> bool:
    now = time.time()
    fails = [t for t in _login_fail.get(ip, []) if now - t < 3600]
    _login_fail[ip] = fails
    return len(fails) < 5


def _login_fail_record(ip: str) -> None:
    now = time.time()
    _login_fail[ip] = [t for t in _login_fail.get(ip, []) if now - t < 600] + [now]


# ---------- 访问日志（P3）：登录/注册事件落盘，可查可追溯 ----------
def _log_auth(event: str, email: str, ip: str, ok: bool) -> None:
    try:
        import json as _json

        log = DATA_DIR / "data" / "access_log.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as f:
            f.write(
                _json.dumps(
                    {
                        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "event": event,
                        "email": email,
                        "ip": ip,
                        "ok": ok,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    except Exception as _e:
        print(f"[routers/auth] 静默异常已可见化: {_e}", flush=True)


def _bootstrap_code() -> str:
    """首用户引导码：data/bootstrap_invite.txt（仅 users 空时可用）——公网后防止陌生人抢占管理员"""
    f = DATA_DIR / "data" / "bootstrap_invite.txt"
    try:
        return f.read_text(encoding="utf-8").strip() if f.exists() else ""
    except Exception:
        return ""


@router.post("/register", response_model=TokenOut)
def register(body: RegisterIn, request: Request):
    email = body.email.lower().strip()
    ip = request.client.host if request.client else "?"
    if users_db.get_user_by_email(email):
        raise HTTPException(status_code=409, detail="该邮箱已注册，请直接登录")
    # 邀请码校验（P3）：首用户=引导码；之后=管理员生成的邀请码（防公网陌生人注册）
    is_first = users_db.user_count() == 0
    if is_first:
        if body.invite_code.strip() != _bootstrap_code():
            raise HTTPException(status_code=403, detail="引导邀请码错误（首个注册需使用服务端引导码）")
    elif not users_db.consume_invite_code(body.invite_code):
        raise HTTPException(status_code=403, detail="邀请码无效或已用完，请联系管理员")
    uid, is_admin = users_db.create_user(email, body.nickname, auth_core.hash_password(body.password))
    _log_auth("register", email, ip, True)
    # 会话库初始化（必须同步：登录后立即可用）
    from app.db.sessions import init_db as sessions_init

    sessions_init(uid)
    # 首用户（管理员）数据迁移：后台执行——真实环境 archive/memory 复制可能耗时，
    # 同步会阻塞注册响应（移动端易超时误报"注册失败"）
    if is_admin:
        from threading import Thread

        from app.user_data import migrate_user_data

        def _migrate():
            try:
                moved = migrate_user_data(uid)
                print(f"[auth] 首用户 {uid[:8]} 注册：后台迁移全局数据 {moved} 项到个人目录", flush=True)
            except Exception as e:
                print(f"[auth] 首用户迁移失败（可重跑 migrate_user_data）: {e}", flush=True)

        Thread(target=_migrate, daemon=True).start()
    token = auth_core.create_access_token(uid)
    return TokenOut(
        access_token=token,
        user=UserOut(id=uid, nickname=body.nickname.strip(), email=email, is_admin=is_admin),
    )


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, request: Request):
    email = body.email.lower().strip()
    ip = request.client.host if request.client else "?"
    # 限流（P3）：IP 10 分钟失败 5 次 → 锁 1 小时
    if not _login_ok(ip):
        _log_auth("login_blocked", email, ip, False)
        raise HTTPException(status_code=429, detail="尝试过于频繁，请 1 小时后再试")
    user = users_db.get_user_by_email(email)
    # 通用错误：账号不存在/密码错误返回同一条（防账号枚举）
    if not user or not auth_core.verify_password(body.password, user["password_hash"]):
        _login_fail_record(ip)
        _log_auth("login_fail", email, ip, False)
        raise HTTPException(status_code=401, detail="邮箱或密码错误")
    _login_fail[ip] = []
    _log_auth("login_ok", email, ip, True)
    token = auth_core.create_access_token(user["id"])
    return TokenOut(access_token=token, user=_user_out(user))


@router.get("/me", response_model=UserOut)
def me(request: Request):
    uid = getattr(request.state, "user_id", None)
    if not uid:
        raise HTTPException(status_code=401, detail="未登录")
    user = users_db.get_user_by_id(uid)
    if not user:
        raise HTTPException(status_code=401, detail="账号不存在")
    return _user_out(user)


class AvatarIn(BaseModel):
    avatar: str  # base64 data URI（前端已压缩 128px）；空串=清除


@router.patch("/me", response_model=UserOut)
def update_me(body: AvatarIn, request: Request):
    """更新头像（2026-08-29）：PATCH /api/me——目前仅头像，扩展点预留。"""
    uid = getattr(request.state, "user_id", None)
    if not uid:
        raise HTTPException(status_code=401, detail="未登录")
    avatar = (body.avatar or "").strip()
    if avatar and not avatar.startswith("data:image/"):
        raise HTTPException(status_code=400, detail="头像须为图片 data URI")
    if len(avatar) > 200_000:  # 128px 小图 base64 ≈ 15KB；上限 200KB 防滥用
        raise HTTPException(status_code=400, detail="头像过大（限 200KB）")
    users_db.update_avatar(uid, avatar)
    user = users_db.get_user_by_id(uid)
    return _user_out(user)
