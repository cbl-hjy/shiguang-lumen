"""记忆治理 API（2026-08-27 HARNESS-V2：星图第 8 张卡"记忆治理"数据源）。
用户对记忆的知情与掌控=本地产品信任底线（Zep 治理 / Anthropic namespace 启示）。
只读列表 + 编辑/删除（带 reason）——删除进回收站可恢复，全部走 change_log 留痕。
"""

from fastapi import APIRouter

from app.memory import store
from app.memory.schema import memory_dir

router = APIRouter(prefix="/api/memory", tags=["memory"])

REASON_VOCAB = {"contradicted", "superseded", "stale", "low-signal", "user_request"}


def _safe_evolve(kind: str) -> tuple[list[dict], str]:
    """安全读取自进化条目（skills / reflections）：失败降级空数组 + 错误文案，端点绝不 500。

    2026-08-29 白屏事故：本端点曾只返回 profile/entries/count/categories，
    而前端 MemoryData（frontend/src/api/memory.ts）声明了 reflections/skills 两个数组字段，
    → 星图「成长轨迹」data.skills.length 抛 TypeError → React 18 渲染期异常卸载整棵树
    → 用户只看到 body 背景（项目当时无 ErrorBoundary 兜底）。
    惰性 import（同 panels.py 风格）：evolution 模块拉 chromadb/pydantic_ai，不在启动路径上。
    """
    try:
        from app.agent.evolution import list_reflections, list_skills
    except Exception as e:  # import 失败（依赖缺失/循环导入）也必须降级而非 500
        return [], f"{kind}: {str(e)[:100]}"
    try:
        items = list_skills() if kind == "skills" else list_reflections()
    except Exception as e:
        return [], f"{kind}: {str(e)[:100]}"
    return (items or []), ""


@router.get("")
def memory_root():
    """聚合视图（MemoryFeature / EvolveFeature 数据源）：画像 + 结构化条目 + 反思 + 技能。
    P1 改造后补的根路由——前端 fetch('/api/memory') 曾 404（记忆视图永远加载中）。
    契约与前端 MemoryData 严格对齐：profile / entries / reflections / skills 四个字段必在。"""
    errs: list[str] = []

    try:
        items = store.entries_structured()
    except Exception as e:
        items = []
        errs.append(f"entries: {str(e)[:100]}")

    pf = memory_dir() / "profile.md"
    try:
        profile = pf.read_text(encoding="utf-8").strip()[:2000] if pf.exists() else ""
    except Exception:
        profile = ""

    # 自进化层（技能/反思）：任一失败只降级为空数组（前端显示"暂无沉淀技能"），不影响其余字段
    skills, e_skills = _safe_evolve("skills")
    reflections, e_reflections = _safe_evolve("reflections")
    for m in (e_skills, e_reflections):
        if m:
            errs.append(m)

    cats = {}
    for i in items:
        cats[i["category"]] = cats.get(i["category"], 0) + 1
    return {
        "profile": profile,
        "entries": items,
        "count": len(items),
        "categories": cats,
        "reflections": reflections,
        "skills": skills,
        "error": " | ".join(errs),
    }


@router.get("/entries")
def memory_entries(category: str = ""):
    """结构化记忆条目列表（可 category 过滤；供治理卡展示）。"""
    try:
        items = store.entries_structured()
    except Exception as e:
        return {"entries": [], "error": str(e)[:100]}
    if category:
        items = [i for i in items if i["category"] == category]
    cats = {}
    for i in items:
        cats[i["category"]] = cats.get(i["category"], 0) + 1
    return {"entries": items, "count": len(items), "categories": cats}


@router.post("/entry/edit")
async def memory_edit(body: dict):
    """按 id 编辑记忆条目（内容修正 + 向量同步）。"""
    eid = str(body.get("id", "")).strip()
    new_content = str(body.get("new_content", "")).strip()
    if not eid:
        return {"ok": False, "msg": "缺少条目 id"}
    r = await store.edit_entry_by_id(eid, new_content)
    return {"ok": r == "已修正", "msg": r}


@router.post("/entry/delete")
async def memory_delete(body: dict):
    """按 id 删除记忆条目（reason 四类 + user_request；进回收站可恢复）。"""
    eid = str(body.get("id", "")).strip()
    reason = str(body.get("reason", "user_request")).strip().lower()
    if not eid:
        return {"ok": False, "msg": "缺少条目 id"}
    if reason not in REASON_VOCAB:
        reason = "user_request"
    r = await store.delete_entry_by_id(eid, reason)
    return {"ok": r == "已删除", "msg": r}


@router.post("/demote")
async def memory_demote(body: dict):
    """手动休眠单条记忆（Phase1 M-1 治理操作闭环，2026-08-29）：
    退出向量检索（文件保留可找回）——与自动降级同机制。"""
    content = str(body.get("content", "")).strip()
    if not content:
        return {"ok": False, "msg": "缺少内容"}
    from app.memory.lifecycle import demote_entry

    ok = demote_entry(content)
    return {"ok": ok, "msg": "已休眠（不再主动浮现，文件保留）" if ok else "未找到（可能已休眠）"}


@router.get("/trash")
def memory_trash():
    """回收站内容（最近删除可恢复参考）。"""
    p = memory_dir() / "trash.md"
    if not p.exists():
        return {"text": ""}
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
        return {"text": text[-3000:]}  # 只看尾部（最新删除）
    except Exception as e:
        return {"text": "", "error": str(e)[:100]}


@router.get("/stats")
def memory_stats():
    """记忆健康视图（Phase1 M-1/M-3 数据源，2026-08-28）：
    访问统计（谁被用过）+ 冷记忆预览（谁将被降级）——治理卡"记忆质量"展示用。"""
    from app.memory import access
    from app.memory.lifecycle import cold_memories_preview

    try:
        stats = access.stats()
    except Exception as e:
        stats, e_stats = {}, str(e)[:100]
    else:
        e_stats = ""
    try:
        cold = cold_memories_preview()
    except Exception as e:
        cold, e_cold = [], str(e)[:100]
    else:
        e_cold = ""
    return {
        "stats": stats,
        "cold_count": len(cold),
        "cold_preview": cold[:20],
        "error": e_stats or e_cold,
    }


@router.get("/profile")
def memory_profile():
    """当前画像（治理卡可读；模型自动维护，用户可查看不可直接改——改走对话更新）。"""
    pf = memory_dir() / "profile.md"
    if pf.exists():
        try:
            return {"text": pf.read_text(encoding="utf-8").strip()[:2000]}
        except Exception:
            return {"text": "(画像读取失败)"}
    return {"text": "(画像未生成)"}
