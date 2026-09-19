"""脚本鉴权共享（2026-09-02 升级：静态令牌 → JWT，修复 8-28 鉴权迁移后的仪器腐烂）。

历史（2026-08-12）：读取 .env 的 SHIGUANG_TOKEN → 静态共享令牌。
问题（2026-09-02 实测发现）：后端 2026-08-28 已迁移到 JWT（HS256 + JWT_SECRET，
app/auth_core.create_access_token），静态令牌一律 401 → **自 8-28 起所有脚本的端到端
验证实际全是未授权失败**，而单测全绿掩盖了这一点（单测不走鉴权中间件）。

修复原则：**改仪器不改产品**——脚本用同一把 JWT_SECRET 自签短时效 JWT（claims 与后端
create_access_token 逐字一致：{"sub": uid, "exp": ...}），后端验签逻辑零改动，
不开任何新的产品级攻击面（不是新增 dev 后门，脚本只是持有本来就在 .env 里的密钥）。

用法：
    from _auth import token, headers_json, curl_auth

    token()              # 默认 uid（SHIGUANG_E2E_UID 或 e2e-probe）
    token(uid="xxx")     # 指定用户（多用户隔离场景）
    headers_json()       # curl 参数列表（保持原语义：["-H", ...]）
"""
from __future__ import annotations

import os
import time
from pathlib import Path

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
DEFAULT_UID = "e2e-probe"
JWT_EXPIRE_SECONDS = 1800  # 脚本短时效（长效凭据不该躺在脚本里）


def _read_env(key: str) -> str:
    """环境变量优先，其次 .env（与后端 auth_core 读取顺序一致）。"""
    val = os.environ.get(key, "")
    if val:
        return val.strip()
    try:
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith(f"{key}="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception as e:  # 无 .env 属正常（纯环境变量部署）——静默回退但留痕，满足 S110
        print(f"[_auth] 读取 {key} 失败（回退空值）：{e}", flush=True)
    return ""


def secret() -> str:
    """JWT_SECRET：与后端同一把密钥。"""
    return _read_env("JWT_SECRET")


def token(uid: str | None = None) -> str:
    """返回可用的 Bearer 令牌：优先 JWT 自签；无 JWT_SECRET 时回退旧静态令牌。"""
    sub = uid or os.environ.get("SHIGUANG_E2E_UID", "").strip() or DEFAULT_UID
    sec = secret()
    if sec:
        import jwt

        payload = {"sub": sub, "exp": int(time.time()) + JWT_EXPIRE_SECONDS}
        return jwt.encode(payload, sec, algorithm="HS256")
    return _read_env("SHIGUANG_TOKEN")  # 兼容未迁移环境


def curl_auth(uid: str | None = None) -> list[str]:
    """返回 curl 鉴权参数（无 token 时为空列表 = 免鉴权兼容）"""
    t = token(uid)
    return ["-H", f"Authorization: Bearer {t}"] if t else []


def headers_json(uid: str | None = None) -> list[str]:
    """JSON 请求头 + 鉴权头（curl 参数列表，保持 2026-08-12 起的原语义）"""
    return ["-H", "Content-Type: application/json"] + curl_auth(uid)
