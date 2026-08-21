"""博查 Bocha 联网搜索（2026-08-21）：中文/国内源 + 语义排序（DeepSeek 官方同款引擎）。

与 web_search（Tavily 国际源）互补：查中文/国内内容用博查，查英文/国际用 Tavily。
端点：POST https://api.bochaai.com/v1/web-search（Bearer 鉴权，freshness/summary/count 参数）
免费额度：2,000 次（注册送 1000 + 口令"博查搜索" 再领 1000）
"""
import requests

from app.config import ENV

MAX_RESULTS = 8


def bocha_search(query: str, max_results: int = 5, freshness: str = "noLimit") -> str:
    """联网搜索最新信息（中文/国内源优先）：查资料、验证事实、找最新进展时用。返回标题+链接+摘要。
    仅在需要最新/外部信息时调用——通用知识、闲聊、已有足够信息回答时不要调（省额度省时间）。"""
    from app.tools.errors import arg_error, net_error

    q = query.strip()
    if not q:
        return arg_error("博查搜索", "搜索内容为空")
    try:
        r = requests.post(
            "https://api.bochaai.com/v1/web-search",
            headers={
                "Authorization": f"Bearer {ENV.get('BOCHA_API_KEY', '')}",
                "Content-Type": "application/json",
            },
            json={
                "query": q,
                "count": max(1, min(max_results, MAX_RESULTS)),
                "summary": True,
                "freshness": freshness,
            },
            timeout=20,
        )
    except Exception as e:
        return net_error("博查搜索", str(e))
    if r.status_code != 200:
        return net_error("博查搜索", f"HTTP {r.status_code}")
    try:
        data = r.json()
        items = (data.get("data", {}).get("webPages", {}) or {}).get("value", []) or []
    except Exception as e:
        return net_error("博查搜索", f"响应解析失败: {e}")
    if not items:
        return "(博查搜索无结果——换关键词或改用 web_search 查英文源)"
    lines = []
    for it in items[: max(1, min(max_results, MAX_RESULTS))]:
        title = it.get("name", "").strip()
        url = it.get("url", "").strip()
        snippet = (it.get("summary") or it.get("snippet") or "").strip()
        site = it.get("siteName", "").strip()
        date = (it.get("datePublished") or "")[:10]
        parts = [f"- {title}", f"  {url}"]
        if date:
            parts.append(f"  ({date})")
        if snippet:
            parts.append(f"  {snippet[:150]}")
        lines.append("\n".join(parts))
    return "\n".join(lines)
