"""M1 配置：加载项目 .env（不依赖 python-dotenv）"""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_env(path: str | Path | None = None) -> dict:
    p = Path(path) if path else PROJECT_ROOT / ".env"
    d = {}
    if not p.exists():
        raise FileNotFoundError(f"缺少 {p}，请先配置 .env")
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            d[k.strip()] = v.strip().strip('"').strip("'")
    return d


ENV = load_env()

DEEPSEEK_MODEL = ENV["DEEPSEEK_MODEL"]
DEEPSEEK_BASE_URL = ENV["DEEPSEEK_BASE_URL"]
DEEPSEEK_API_KEY = ENV["DEEPSEEK_API_KEY"]

# 鉴权令牌（P0 门锁，2026-08-12）：/api/* 需 Authorization: Bearer <SHIGUANG_TOKEN>。
# 未配置（空串）= 鉴权关闭（本地开发免鉴权是特性）——但日志会警告；局域网/公网访问必须配置
SHIGUANG_TOKEN = ENV.get("SHIGUANG_TOKEN", "").strip()

# 数据根目录（模拟用户设施 0.5 隔离）：所有持久化路径统一走 DATA_DIR——
# 主实例默认项目根（现状不变）；实验实例 DATA_DIR=data-experiment 物理隔离，主库零污染
import os as _os

DATA_DIR = Path(_os.environ.get("DATA_DIR") or PROJECT_ROOT)
# 实验模式：投递层关闭真实世界副作用（提醒不投递/通知不触发）。
# 铁律：绝不允许进系统 prompt——模型不知道自己在被测试（否则行为变假）
EXPERIMENT_MODE = _os.environ.get("EXPERIMENT_MODE") == "1"
if EXPERIMENT_MODE:
    print(f"[experiment] 实验模式：DATA_DIR={DATA_DIR}（隔离运行，投递关闭）", flush=True)
