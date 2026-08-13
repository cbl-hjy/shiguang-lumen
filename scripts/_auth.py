"""脚本鉴权共享（P0 门锁联动，2026-08-12）：读取 .env 的 SHIGUANG_TOKEN → curl 参数。
所有调后端的脚本 import 本模块——避免"改一处漏三处"（#26 发布漂移教训）。
用法：
    from _auth import curl_auth, headers_json
    subprocess.run(["curl", ...] + headers_json() + ["-d", body, ...])
"""
from pathlib import Path


def token() -> str:
    env_path = Path(__file__).resolve().parent.parent / ".env"
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("SHIGUANG_TOKEN="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return ""


def curl_auth() -> list[str]:
    """返回 curl 鉴权参数（无 token 时为空列表 = 免鉴权兼容）"""
    t = token()
    return ["-H", f"Authorization: Bearer {t}"] if t else []


def headers_json() -> list[str]:
    """JSON 请求头 + 鉴权头"""
    return ["-H", "Content-Type: application/json"] + curl_auth()
