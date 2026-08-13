"""统一模型工厂 + fallback 链（P0 单点修复，2026-08-12）。
理念核查：全在 harness 层（机器厚度），不进 prompt、不碰任何用户判断——
错误分类/熔断/重试全是确定性不变量（HTTP 状态码/异常类型/连败计数），可锁死代码。

设计（调研 [R6-R9] 校准 + 用户拍板）：
- 错误分类：5xx/连接/超时/429/401 → 换备用重试（401 是换凭据语境，区别于官方同 key 语境的不重试）；
  400/403/404 → 不重试（请求本身问题）
- 熔断：连续 3 次失败 → 冷却 60s（冷却期只试主、快速失败省一次 API 调用）→ 半开试主一次，成功清零
- 超时：ModelSettings.timeout=180 是【单次模型调用】超时（抛异常进 fallback 分类）；
  #6 的 180s 是【整轮流】超时（asyncio.wait_for 包流消费）——两个层级，勿合并
- 日志 = 免费 API 健康探测器（woshi 洞察落地）：[fallback] 时间|原因|主→备|会话，触发率即 API 健康度
"""
import re
import time

from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from app.config import (
    DEEPSEEK_API_KEY,
    DEEPSEEK_BASE_URL,
    DEEPSEEK_MODEL,
    ENV,
)

# ---------- 模型版本 pin（集中一处：换模型只改 .env 的 DEEPSEEK_MODEL，回归门读它做版本指纹）----------
PIN_MODEL = DEEPSEEK_MODEL

# ---------- 备用端点（可选：未配置 = 无 fallback，行为与现状一致）----------
FALLBACK_MODEL = ENV.get("FALLBACK_MODEL", "").strip()
FALLBACK_BASE_URL = ENV.get("FALLBACK_BASE_URL", "").strip()
FALLBACK_API_KEY = ENV.get("FALLBACK_API_KEY", "").strip()

# ---------- 熔断器（进程级，不落盘；参数先粗后细，随时可调）----------
_CIRCUIT = {"fails": 0, "cool_until": 0.0}
CIRCUIT_MAX_FAILS = 3
CIRCUIT_COOL_SECONDS = 60

# ---------- 超时（单次模型调用层；整轮流超时在 main.py 用 asyncio.wait_for，勿合并）----------
MODEL_TIMEOUT_SECONDS = 180


def get_model() -> OpenAIChatModel:
    """主模型（唯一构建点——4 处重复构建收敛到这里）"""
    return OpenAIChatModel(
        PIN_MODEL,
        provider=OpenAIProvider(base_url=DEEPSEEK_BASE_URL, api_key=DEEPSEEK_API_KEY),
    )


def get_fallback_model() -> OpenAIChatModel | None:
    """备用模型；未配置返回 None（无 fallback）"""
    if not (FALLBACK_MODEL and FALLBACK_BASE_URL and FALLBACK_API_KEY):
        return None
    return OpenAIChatModel(
        FALLBACK_MODEL,
        provider=OpenAIProvider(base_url=FALLBACK_BASE_URL, api_key=FALLBACK_API_KEY),
    )


def circuit_open() -> bool:
    """冷却期：主失败后不再尝试备用（快速失败，省一次 API 调用）"""
    return time.time() < _CIRCUIT["cool_until"]


def circuit_record(ok: bool):
    """记录一次尝试结果：成功清零并立即恢复（含冷却解除）；失败累计，达阈值进冷却"""
    if ok:
        _CIRCUIT["fails"] = 0
        _CIRCUIT["cool_until"] = 0.0
    else:
        _CIRCUIT["fails"] += 1
        if _CIRCUIT["fails"] >= CIRCUIT_MAX_FAILS:
            _CIRCUIT["cool_until"] = time.time() + CIRCUIT_COOL_SECONDS
            print(f"[circuit] 连续 {CIRCUIT_MAX_FAILS} 次失败，熔断冷却 {CIRCUIT_COOL_SECONDS}s", flush=True)


def should_fallback(exc: Exception) -> bool:
    """错误分类：True=换备用重试，False=请求本身问题不重试。
    基于 str(exc) 提取 status_code（ModelHTTPError 无独立字段，格式稳定：status_code: NNN）"""
    msg = str(exc)
    m = re.search(r"status_code[: ]+(\d{3})", msg)
    code = m.group(1) if m else ""
    low = msg.lower()

    # 401：换凭据语境（主 key 失效 ≠ 备用失效）→ 重试；备用也 401 由熔断兜住，日志区分两层
    if code == "401" or "authentication" in low or ("invalid" in low and "api key" in low) or " is invalid" in low:
        return True
    # 请求本身问题：换端点白搭
    if code in ("400", "403", "404"):
        return False
    # 服务端/限流/连接/超时：重试
    if code in ("500", "502", "503", "504", "529", "429", "408", "409"):
        return True
    if any(k in low for k in ("connection", "timeout", "timed out", "connecterror")):
        return True
    # 未知错误：保守不重试（避免掩盖真 bug，宁可走 #4 error 事件暴露）
    return False
