"""Tavily 联网搜索（直调 API，不装库；key 来自 .env）"""
import requests

from app.config import ENV

MAX_RESULTS = 8


def web_search(query: str, max_results: int = 5) -> str:
    """联网搜索最新信息：查资料、验证事实、找最新进展时用。返回标题+链接+摘要。"""
    q = query.strip()
    if not q:
        return "(搜索内容为空)"
    try:
        r = requests.post(
            "https://api.tavily.com/search",
            json={
                "api_key": ENV.get("TAVILY_API_KEY", ""),
                "query": q,
                "max_results": max(1, min(max_results, MAX_RESULTS)),
            },
            timeout=20,
        )
    except Exception as e:
        return f"(搜索失败: {e})"
    if r.status_code != 200:
        return f"(搜索失败: HTTP {r.status_code})"
    results = r.json().get("results", [])
    if not results:
        return "(没有搜到结果，可换个说法再试)"
    return "\n\n".join(
        f"[{i}] {it.get('title', '')}\n{it.get('url', '')}\n{it.get('content', '')[:250]}"
        for i, it in enumerate(results, 1)
    )
