"""读文档：PDF（pymupdf）+ Office/网页（MarkItDown），截断防上下文爆炸"""
from pathlib import Path

MAX_CHARS = 4000


def read_document(path: str, max_chars: int = MAX_CHARS) -> str:
    """读取本地文档文本（PDF/docx/pptx/xlsx/md/html 等）。返回文本（自动截断）。"""
    p = Path(path)
    if not p.exists():
        return f"(文件不存在: {path})"
    try:
        suffix = p.suffix.lower()
        if suffix == ".pdf":
            import pymupdf

            doc = pymupdf.open(str(p))
            text = "\n".join(page.get_text() for page in doc)
        else:
            from markitdown import MarkItDown

            text = MarkItDown().convert(str(p)).text_content
    except Exception as e:
        return f"(读取失败: {e})"
    if not text or not text.strip():
        return "(未能提取文字——可能是扫描件/图片型 PDF，可改用 OCR 识别)"
    if len(text) > max_chars:
        return text[:max_chars] + f"\n…(已截断，共 {len(text)} 字符)"
    return text
