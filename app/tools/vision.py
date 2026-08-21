"""GLM 视觉理解（2026-08-21 升级 zai-sdk + glm-4.6v-flash）。

模型：glm-4.6v-flash（免费，128K 上下文，带思考，输出 16K，原生函数调用——比 4v-flash 强）；
  429 限流自动降级 glm-4v-flash（免费模型高峰访问量大，双模型保体验连续）。
SDK：zai-sdk（ZhipuAiClient，max_retries=3 内置重试，结构化异常）。
与 ocr_image（本地 RapidOCR 读字）互补：OCR 读字，analyze_image 看图。
降级（判断归模型）：智谱不可用时返回错误码 + ocr_image 提示，模型自主决定下一步。
base64 直传（实测支持，本地图片无需 URL）。
"""
import base64
from pathlib import Path

from app.config import ENV

ZHIPU_MODEL = "glm-4.6v-flash"
ZHIPU_MODEL_FALLBACK = "glm-4v-flash"  # 429 限流降级（免费模型高峰访问量大）
MAX_IMG_BYTES = 5 * 1024 * 1024
_MIME = {
    "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
    "webp": "image/webp", "gif": "image/gif", "bmp": "image/bmp",
}

_client = None


def _get_client():
    global _client
    if _client is None:
        from zai import ZhipuAiClient

        _client = ZhipuAiClient(api_key=ENV.get("ZHIPU_API_KEY"), max_retries=3, timeout=60)
    return _client


def _image_block(image_path: str) -> tuple[str, str] | None:
    """读图 → (mime, base64)。失败返回 None。"""
    p = Path(image_path)
    if not p.exists():
        return None
    data = p.read_bytes()
    if len(data) > MAX_IMG_BYTES:
        return None
    mime = _MIME.get(p.suffix.lower().lstrip("."), "image/jpeg")
    return mime, base64.b64encode(data).decode()


def analyze_image(image_path: str, question: str = "") -> str:
    """看图理解（图表/几何/错题/笔记/任何图片）。传入图片路径 + 想问的问题，返回模型分析。
    不传问题则让模型自由描述图片内容。
    降级链：glm-4.6v-flash → 429 自动降级 glm-4v-flash → 仍失败返回错误码 + ocr_image 提示（模型判断下一步）。
    """
    from app.tools.errors import arg_error, io_error, tool_err

    api_key = ENV.get("ZHIPU_API_KEY")
    if not api_key:
        return tool_err("看图", "未配置 ZHIPU_API_KEY（.env 加一行）", "可改用 ocr_image 提取图片文字")
    p = Path(image_path)
    if not p.exists():
        return io_error("看图", f"图片不存在: {image_path}")
    if not question.strip():
        question = "请详细描述这张图片的内容，包括文字、图表、结构等所有可读信息。"
    img = _image_block(image_path)
    if img is None:
        try:
            if p.stat().st_size > MAX_IMG_BYTES:
                return arg_error("看图", "图片超过 5M 限制", "压缩图片后重试；需要文字可改用 ocr_image")
            return io_error("看图", "图片读取失败", "检查文件后重试")
        except OSError as e:
            return io_error("看图", str(e))
    mime, b64 = img
    messages = [{
        "role": "user",
        "content": [
            {"type": "text", "text": question},
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
        ],
    }]

    def _call(model: str) -> str:
        resp = _get_client().chat.completions.create(model=model, messages=messages)
        return resp.choices[0].message.content.strip()

    try:
        return _call(ZHIPU_MODEL)
    except Exception as e:
        # 429 限流（免费模型高峰）→ 降级 4v-flash 再试
        if "429" in str(e) or "Limit" in type(e).__name__ or "1305" in str(e):
            try:
                return _call(ZHIPU_MODEL_FALLBACK)
            except Exception as e2:
                return tool_err("看图", f"智谱视觉分析限流（双模型均被限）: {str(e2)[:60]}", "稍后重试，或改用 ocr_image 提取图片文字")
        # 超时 / 其他（SDK 已内置重试 3 次，到这说明真失败）
        if "timeout" in type(e).__name__.lower() or "Timeout" in type(e).__name__:
            return tool_err("看图", "智谱视觉分析超时", "稍后重试，或改用 ocr_image 提取图片文字")
        return tool_err("看图", f"智谱视觉分析失败: {str(e)[:80]}", "稍后重试，或改用 ocr_image 提取图片文字")
