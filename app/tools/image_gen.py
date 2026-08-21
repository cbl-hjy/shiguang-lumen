"""生图工具（2026-08-21）：视觉学习配图——把抽象概念/学习内容生成图解。

模型：智谱 cogview-3-flash（免费 $0/图，与识图共用 ZHIPU_API_KEY）。
注意：免费版带水印（watermark=false 不生效，实测确认）——学习配图用途可接受。
返回图片 URL（智谱静态 URL，前端 react-markdown 直接渲染 ![](url)）。
"""
import json
import urllib.request

from app.config import ENV

ZHIPU_URL = "https://open.bigmodel.cn/api/paas/v4/images/generations"
ZHIPU_MODEL = "cogview-3-flash"
SUPPORTED_SIZES = {"1024x1024", "768x1344", "864x1152", "1344x768", "1152x864", "1440x720", "720x1440"}


def generate_image(prompt: str, size: str = "1024x1024") -> str:
    """把抽象概念/学习内容生成图解或示意图（视觉学习）。当用户需要"可视化理解"
    （把概念画成图、学习路径图、对比图解）时用。返回图片 URL（可用 markdown 图片语法展示）。
    仅在用户明确要图/图能更好表达时用——纯文字能讲清就不要生成图（省额度）。"""
    from app.tools.errors import arg_error, tool_err

    api_key = ENV.get("ZHIPU_API_KEY")
    if not api_key:
        return tool_err("生图", "未配置 ZHIPU_API_KEY（.env 加一行）")
    p = prompt.strip()
    if not p:
        return arg_error("生图", "描述内容为空", "描述想生成什么样的图")
    if size not in SUPPORTED_SIZES:
        size = "1024x1024"
    body = {"model": ZHIPU_MODEL, "prompt": p, "size": size}
    # 降级提示（2026-08-21）：生图失败 → 可改用 mermaid 代码块（前端自动渲染成图，免费即时）——
    # 结构性图解（流程图/架构/对比）mermaid 甚至更精准；AI 生图适合视觉丰富的插画
    _mermaid_hint = "可改用 mermaid 代码块画结构图/流程图（前端自动渲染），或稍后重试"
    try:
        req = urllib.request.Request(
            ZHIPU_URL,
            data=json.dumps(body).encode(),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=120) as r:
            d = json.loads(r.read())
        url = d.get("data", [{}])[0].get("url", "")
        if not url:
            return tool_err("生图", "返回为空", _mermaid_hint)
        return f"图片已生成：\n![{p[:30]}]({url})"
    except Exception as e:
        return tool_err("生图", f"生成失败: {str(e)[:80]}", _mermaid_hint)
