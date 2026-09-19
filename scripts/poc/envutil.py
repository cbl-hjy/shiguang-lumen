"""POC 共享工具：加载项目 .env（不依赖 python-dotenv）"""
from pathlib import Path


def load_env(path: str = ".env") -> dict:
    d = {}
    p = Path(__file__).resolve().parent.parent.parent / path
    if not p.exists():
        raise FileNotFoundError(f"缺少 {p}，请先配置 .env")
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            d[k.strip()] = v.strip().strip('"').strip("'")
    return d
