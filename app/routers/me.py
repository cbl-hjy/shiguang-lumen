"""「它记得我」聚合视图（2026-08-28 前端重构）：
一次请求返回用户档案全量（画像 + 记忆 + 学习路径 + 成长 + 统计），
替代此前星图每卡单独拉数据（公网隧道 ~1.3s 延迟 × N 次 = 点哪都等）。
抽屉内切换标签 = 前端本地切换，零网络等待。
"""
from fastapi import APIRouter

from app.memory import store
from app.memory.hub import build_hub_view
from app.memory.schema import memory_dir

router = APIRouter(prefix="/api/me", tags=["me"])


def _read(path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip() if path.exists() else ""
    except Exception:
        return ""


@router.get("/overview")
def me_overview():
    """档案聚合：profile / memories / topics / growth / stats——一次给全，前端本地切换。"""
    md = memory_dir()
    errs = []

    # 画像（per-user 路径，已按用户隔离）
    profile = _read(md / "profile.md")

    # 记忆条目（结构化，带类别/重要性/强度）
    try:
        entries = store.entries_structured()
    except Exception as e:
        entries = []
        errs.append(f"记忆读取失败: {str(e)[:60]}")

    # 学习路径 + 统计（hub 聚合视图：topics/profile/stats）
    try:
        hub = build_hub_view()
        topics = hub.get("topics", [])
        stats = hub.get("stats", {})
        hub_profile = hub.get("profile", "")
    except Exception as e:
        topics, stats, hub_profile = [], {}, ""
        errs.append(f"路径读取失败: {str(e)[:60]}")

    # 成长（技能 + 反思）
    skills = _read(md / "skills.md")
    reflections = _read(md / "reflections.md")

    # 跨域类比（2026-08-31，路线图 v3.0 §4）：最近 5 条，抽屉可见——绝不注入对话
    try:
        from app.agent.analogy import read_analogies

        analogies = read_analogies(limit=5)
    except Exception as e:
        analogies = []
        errs.append(f"类比读取失败: {str(e)[:60]}")

    cats: dict = {}
    for e in entries:
        cats[e["category"]] = cats.get(e["category"], 0) + 1

    return {
        "profile": profile or hub_profile,
        "memories": entries[:20],
        "memory_count": len(entries),
        "categories": cats,
        "topics": topics[:12],
        "stats": stats,
        "growth": {
            "skills": skills,
            "reflections": reflections,
        },
        "analogies": analogies,
        "errors": errs,
    }
