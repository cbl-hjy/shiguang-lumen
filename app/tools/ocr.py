"""RapidOCR：本地 CPU 离线 OCR（识别截图/教材照片中的文字）"""
from pathlib import Path

_engine = None


def _get_engine():
    global _engine
    if _engine is None:
        from rapidocr_onnxruntime import RapidOCR

        _engine = RapidOCR()
    return _engine


def ocr_image(image_path: str) -> str:
    """识别图片中的文字（截图/教材照片/公式页）。传入图片路径，返回识别文本。"""
    p = Path(image_path)
    if not p.exists():
        return f"(图片不存在: {image_path})"
    try:
        result, _ = _get_engine()(str(p))
    except Exception as e:
        return f"(OCR 失败: {e})"
    if not result:
        return "(未识别到文字)"
    return "\n".join(line[1] for line in result)
