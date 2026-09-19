"""M1 配置：pydantic-settings 加载（2026-08-27 从自建 .env 读取迁移——官方标准，类型校验+env 优先级）。
优先级：环境变量 > .env（BaseSettings 默认）——测试隔离注入 DATA_DIR 走环境变量即可覆盖。
兼容层：ENV dict（model_dump）保留——model.py/web_search/bocha_search 的 ENV.get() 引用点不破。
"""
import os as _os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# .env 路径（2026-08-25 打包适配）：默认项目根；打包后由启动器设 SHIGUANG_ENV_FILE
# 指向用户数据目录的 .env（_internal 只读，不可写 .env）
ENV_FILE = Path(_os.environ.get("SHIGUANG_ENV_FILE") or (PROJECT_ROOT / ".env"))


class Settings(BaseSettings):
    """拾光配置（字段名 = .env 键名小写；case_sensitive=False 兼容 Windows 大写环境变量）。"""

    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",  # .env 多余键静默忽略（原 load_env 容忍语义）
        case_sensitive=False,
    )

    # 主模型（必填）
    deepseek_model: str
    deepseek_base_url: str
    deepseek_api_key: str

    # 鉴权（P0 门锁，2026-08-12）：未配置=本地免鉴权（特性），日志警告
    shiguang_token: str = ""

    # 备用模型端点（fallback 链 P0：主模型挂/空返回时切换）
    fallback_model: str = ""
    fallback_base_url: str = ""
    fallback_api_key: str = ""

    # 搜索 API
    tavily_api_key: str = ""
    bocha_api_key: str = ""

    # bge-m3 本地快照（非标准 HF 路径）
    bge_m3_path: str = ""

    # 数据根目录：所有持久化路径统一走 DATA_DIR——主实例默认项目根；
    # 实验实例/测试注入走环境变量 DATA_DIR（env 优先级 > 默认值，物理隔离）
    data_dir: Path = PROJECT_ROOT

    # 实验模式（投递关闭）：铁律=绝不进系统 prompt（模型不知道自己在被测试）
    experiment_mode: bool = False

    # B 实验（提醒 MRT）门（2026-09-17）：默认关=零影响；开=投递前 50% 随机抽签
    # （设计 docs/2026-09-17-B-MRT-FORMAL-DESIGN.md；日志独立 data/mrt/log.jsonl）
    mrt_experiment: bool = False


if not ENV_FILE.exists():
    raise FileNotFoundError(f"缺少 {ENV_FILE}，请先配置 .env（可复制 .env.example）")

settings = Settings()

# ---- 模块级导出（引用点零改动） ----
DEEPSEEK_MODEL = settings.deepseek_model
DEEPSEEK_BASE_URL = settings.deepseek_base_url
DEEPSEEK_API_KEY = settings.deepseek_api_key
SHIGUANG_TOKEN = settings.shiguang_token.strip()
DATA_DIR = settings.data_dir
EXPERIMENT_MODE = settings.experiment_mode
MRT_EXPERIMENT = settings.mrt_experiment
if EXPERIMENT_MODE:
    print(f"[experiment] 实验模式：DATA_DIR={DATA_DIR}（隔离运行，投递关闭）", flush=True)

# ---- 模型档位（Phase 2 C-2，2026-08-29：注入预算显式化）----
# 依据：IBM 2603.10600 反面证据——强模型全量注入反而最优；弱模型信息过载决策质量下降。
# 弱模型从严（检索少给几条=甜点区），强模型放宽；未知模型从严（保守）。
MODEL_TIERS: dict[str, dict] = {
    "deepseek-v4-flash": {"search_top_k": 3, "inject_budget_chars": 9_000},
    "deepseek-v4-pro": {"search_top_k": 6, "inject_budget_chars": 14_000},
}
_DEFAULT_TIER = {"search_top_k": 3, "inject_budget_chars": 9_000}


def model_tier() -> dict:
    """当前模型档位（按 DEEPSEEK_MODEL 名匹配；未知模型回退从严档）。"""
    name = (DEEPSEEK_MODEL or "").lower()
    for key, tier in MODEL_TIERS.items():
        if key in name:
            return tier
    return dict(_DEFAULT_TIER)

# ENV dict 兼容层（model.py/web_search/bocha_search 用 ENV.get(...)；值类型保持 str 化）
ENV = {k: (str(v) if not isinstance(v, Path) else str(v)) for k, v in settings.model_dump().items()}
