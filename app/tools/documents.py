"""读文档：PDF（pymupdf）+ Office/网页（MarkItDown），截断防上下文爆炸"""

from pathlib import Path

MAX_CHARS = 4000


def _resolve_memory_path(path: str) -> Path:
    """记忆区相对路径解析（2026-09-19，BUG-pending-feed-loop 修复 · 方案 C）。

    `memory/` 前缀 → 解析到**当前用户数据目录**下。背景：动态注入以"记忆区文件
    memory/xxx"语义引用文件（`app/agent/tutor.py`），而本工具原按**工作目录**解析 →
    读不到 → 失败回灌待审 → 注入"待审 N 条"上涨 → 又去读（自我喂养循环）。

    边界：仅 `memory/` 前缀特判；**防穿越**（解析结果必须位于用户目录内，否则回退）；
    无 uid 上下文/解析异常 → 回退原语义（不破坏存量行为）。
    """
    p = Path(path)
    if p.parts and p.parts[0] == "memory":
        try:
            from app.auth_core import get_current_user_id
            from app.user_data import get_user_data_dir

            uid = get_current_user_id()
            if uid:
                base = get_user_data_dir(uid).resolve()
                resolved = (base / p).resolve()
                if resolved.is_relative_to(base):
                    return resolved
        except Exception as e:  # 解析失败回退原语义（不打断读取路径，失败可见）
            print(f"[tools/documents] 记忆区路径解析失败，回退工作目录语义: {e}", flush=True)
    return p


def read_document(path: str, max_chars: int = MAX_CHARS) -> str:
    """读取本地文档文本（PDF/docx/pptx/xlsx/md/html 等）。返回文本（自动截断）。"""
    from app.tools.errors import io_error, tool_err

    p = _resolve_memory_path(path)  # 2026-09-19：memory/ 前缀 → 用户数据目录（BUG-pending-feed-loop）
    if not p.exists():
        return io_error("读取文档", f"文件不存在: {path}")
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
        return tool_err("读取文档", str(e))
    if not text or not text.strip():
        return "(未能提取文字——可能是扫描件/图片型 PDF，可改用 OCR 识别)"
    if len(text) > max_chars:
        return text[:max_chars] + f"\n…(已截断，共 {len(text)} 字符)"
    return text
