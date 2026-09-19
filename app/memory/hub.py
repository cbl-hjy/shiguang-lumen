"""记忆聚合中枢（Memory Hub，2026-08-19）——"天下大同，中央集权"

设计纲领（用户原话）：不能各做各的，分崩离析，要的就是天下大同，历史的中央集权。要深深的联动起来。
方案文档：docs/MEMORY-HUB-DESIGN.md

核心思想：读取端聚合，不改造写入端——
- 写入端零改动：模型照旧调 remember/update_state/forget（判断无墙不被触碰）
- 聚合是派生视图：按需从 5 文件计算，不落盘、不建新文件、永不过时
- 真相源仍是原文件（user_memory.md / state.json / profile.md / trash.md / change_log.jsonl）
- 主题归拢/状态推断 = 确定性规则（纯代码，零 LLM 调用）；画像内容仍归模型提炼

三视图共享一次计算：
- 主题视图（学习路径的真相源）：主题 + 状态机 + 联动数 + 最后活动
- 明细视图：点开主题 → 关联记忆 + 关联变更
- 画像视图：profile（由记忆变化触发重提炼，见 store.update_state 置位）
"""

from app.memory import store
from app.memory.state import read_state
from app.memory.topics_store import SEED_TOPICS

# 主题词典已迁移到 topics_store.SEED_TOPICS（P3，2026-08-19）：
# 归拢统一走 topics.json（aliases 精确命中），种子是 harness 初始认知、演化由模型接管。
# 保留 TOPIC_KEYWORDS 曾用名引用（防外部 import 破坏），内容以 topics_store 为准。
TOPIC_KEYWORDS: dict[str, list[str]] = {s["name"]: s.get("aliases", []) for s in SEED_TOPICS}

# 状态机推断词表（确定性规则；优先级：搁置 > 卡住 > 完成 > 进行中）
STATUS_TERMS: dict[str, list[str]] = {
    "搁置": ["放弃", "不学了", "不学", "搁置", "翻篇", "不碰", "作废", "不打算"],
    "卡住": ["卡住", "没懂", "学不动", "焦虑", "听不懂", "不会", "搞不懂", "不明白"],
    "完成": ["学完", "搞定", "通过了", "懂了", "会了", "掌握", "弄懂", "想通"],
}
DEFAULT_STATUS = "进行中"
RECENT_DAYS = (
    7  # 最近活动窗口（2026-08-20）：7 天内学过 → 状态活过来（覆盖历史搁置表达）；与主题观察期同口径
)

# 主题匹配缓存（P3）：load_topics 一次 + 建 name/aliases → 关键词映射（避免每记忆一次 JSON 读）
_topic_rules_cache: dict | None = None
_topic_rules_sig: tuple | None = (
    None  # (mtime_ns, size)——签名变化即失效（2026-08-19 修🔴缺口：原缓存永不过期，rename/merge 后归拢失效）
)


def _topic_rules() -> dict[str, list[str]]:
    """从 topics.json 构建 主题名→aliases 映射（含主题名本身）；无主题时回退种子词典。
    缓存失效：基于 TOPICS_FILE 的 mtime+size 签名——rename/merge/touch 都会改文件，
    签名变化即重建；文件不存在 → sig=None 每次重建（回退种子）。"""
    global _topic_rules_cache, _topic_rules_sig
    from app.memory.topics_store import SEED_TOPICS, TOPICS_FILE, load_topics

    try:
        st = TOPICS_FILE().stat()
        sig = (st.st_mtime_ns, st.st_size)
    except OSError:
        sig = None  # 文件不存在：每次重建（回退种子词典）
    if _topic_rules_cache is None or sig != _topic_rules_sig:
        data = load_topics()
        topics = data.get("topics") or []
        rules = {}
        if topics:
            for t in topics:
                kw = [t.get("name", "")] + [a for a in (t.get("aliases") or []) if a]
                rules[t.get("name", "")] = kw
        else:
            rules = {s["name"]: [s["name"]] + s.get("aliases", []) for s in SEED_TOPICS}
        _topic_rules_cache = rules
        _topic_rules_sig = sig
    return _topic_rules_cache


# 向量兜底阈值（P3 双通道，2026-08-19 校准实验：记忆句子 vs 主题名 正例均值 0.581/反例 0.328，
# 分离度 0.254；0.65 时零误伤但语义远关联漏——定位=第二通道只补"字面漏归"，宁缺毋滥）
VECTOR_FALLBACK_THRESHOLD = 0.65


def _match_topic(content: str) -> str:
    """主题归拢（P3 双通道 ①）：topics.json aliases 关键词精确命中 → 主题名；无命中 → 未归类。
    向量兜底（通道②）由 build_hub_view 对未归类记忆批量执行（逐条 embed 太慢）。"""
    low = content.lower()
    for topic, keywords in _topic_rules().items():
        if any(k.lower() in low for k in keywords if k):
            return topic
    return "未归类"


def _vector_bucket(unclassified: list, all_texts: list, topics: list) -> dict:
    """P3 双通道 ②：未归类记忆 vs 主题名 批量向量兜底（一次 embed 全部）。
    校准阈值 0.65：高置信才归，零误伤优先；embed 失败 → 保持未归类（不阻塞）。"""
    if not unclassified or not topics:
        return {}
    try:
        import asyncio

        import numpy as np

        from app.memory.vector import aembed

        async def _run():
            embs = await aembed(all_texts + topics)
            n = len(all_texts)
            mem_embs, topic_embs = embs[:n], embs[n:]
            result = {}
            for i, vec in enumerate(mem_embs):
                best, best_sim = None, 0.0
                for topic, te in zip(topics, topic_embs, strict=True):
                    s = float(np.dot(vec, te) / (np.linalg.norm(vec) * np.linalg.norm(te)))
                    if s > best_sim:
                        best, best_sim = topic, s
                if best and best_sim >= VECTOR_FALLBACK_THRESHOLD:
                    result[all_texts[i]] = best
            return result

        return asyncio.run(_run())
    except Exception:
        return {}


def _infer_status(
    memories: list, state: dict, topic: str = "", last_active: str = "", model_status: str = ""
) -> str:
    """状态机推断（2026-08-21 状态细粒度归模型——优先级重构）：
    模型 status（收尾输出，最近判断）> willingness 显式 > 最近活动覆盖 > 历史文本。
    原由：'卡住 vs 完成'是语义判断，关键词规则无信号（正则化 L2 已通但文本无'学完'词）——
    判断归模型（status 字段），规则只兜底粗粒度（活跃/搁置）。"""
    if model_status:
        return {"done": "完成", "stuck": "卡住", "shelved": "搁置"}.get(model_status, "")
    willingness = ""
    for dim_key in ("current", "last_session"):
        dim = (state.get(dim_key) or {}).get("willingness") or {}
        if isinstance(dim, dict):
            willingness = dim.get("value", "")
        if willingness:
            break
    if willingness and topic:
        # 只影响"意愿文本明确提到的主题"（"放弃正则化"→正则化搁置；梯度下降/Transformer 不受影响）。
        # 不做记忆文本匹配：主题名几乎必然出现在自己主题的记忆里（归拢按关键词），
        # 那会让意愿全局污染（2026-08-19 调试实证：梯度下降被误判搁置）
        if topic in willingness:
            if any(k in willingness for k in STATUS_TERMS["搁置"]):
                return "搁置"
    texts = " ".join(m.content for m in memories)
    # 最近活动窗口（与主题观察期 7 天同口径）：最近学过 → 实时状态优先（卡住/完成），
    # 历史"搁置"表达被覆盖（重新学 = 状态活过来）
    active_days = _days_since(last_active)
    has_recent = active_days is not None and active_days <= RECENT_DAYS
    if has_recent:
        for status, terms in [("卡住", STATUS_TERMS["卡住"]), ("完成", STATUS_TERMS["完成"])]:
            if any(k in texts for k in terms):
                return status
        return DEFAULT_STATUS  # 进行中
    # 无最近活动：历史表达推断（搁置优先——放弃表达比卡住/完成更"新"）
    for status, terms in [
        ("搁置", STATUS_TERMS["搁置"]),
        ("卡住", STATUS_TERMS["卡住"]),
        ("完成", STATUS_TERMS["完成"]),
    ]:
        if any(k in texts for k in terms):
            return status
    return DEFAULT_STATUS


def _days_since(date_str: str) -> int | None:
    """last_active 距今天数（YYYY-MM-DD）；解析失败返回 None（视为无活动时间）。"""
    try:
        from datetime import date, datetime

        d = datetime.strptime(date_str[:10], "%Y-%m-%d").date()
        return (date.today() - d).days
    except Exception:
        return None


def _content_date(content: str) -> str:
    """从记忆内容提取"发生日"（双时间戳 P2，2026-08-19）：正则匹配 \\d{4}-\\d{2}-\\d{2}，
    无则空（前端只用 record_date）。确定性规则零 LLM；日期幻觉由并排显示暴露而非代码纠错。"""
    if not content:
        return ""
    import re

    m = re.search(r"(20\d{2})[-/年](\d{1,2})[-/月](\d{1,2})", content)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return ""


def _last_active(memories: list, touch: str = "") -> str:
    """主题最后活动日期：max(记忆日期, topics.json touch)——统一语义（🟡修复 2026-08-19：
    原双 last_active 同名异义：hub 记忆日期 vs topics touch 会话时间；两者都是活动信号，取最大，
    避免 touch 更新了但展示还停在记忆日期）"""
    dates = []
    for m in memories:
        if m.updated_at:
            dates.append(m.updated_at)
        if m.created_at:
            dates.append(m.created_at)
    if touch:
        dates.append(touch[:10])
    return max(dates) if dates else ""


# 续接点推导：只从"进度/卡点/困惑/目标"类记忆推导（排除笔记/偏好/闲聊——没有推进信息）
# 注意：成员必须来自 CAT_VOCAB（schema 锁死词汇表）——"卡点"不是词汇表成员（死字段，2026-08-19 复盘发现）
CONTINUATION_CATS = {"进度", "困惑", "目标", "学习记录"}
# 搁置/放弃信号词（续接点不该主动推荐这些主题——"从任意阶段学起"是用户主动选）
ABANDON_TERMS = ["放弃", "不学了", "搁置", "翻篇", "作废", "不打算"]


def _derive_continuation(memories: list) -> dict:
    """续接点从记忆推导（状态再生，2026-08-19）：取该主题最新一条进度/卡点/困惑类记忆。
    记忆是持久真相源——一年后重新归拢，续接点自动恢复，不依赖独立存储（旧全局单条续接点一年必被覆盖）。"""
    candidates = [m for m in memories if m.category in CONTINUATION_CATS]
    if not candidates:
        return {"text": "", "from_date": "", "abandoned": False}
    latest = max(candidates, key=lambda m: (m.updated_at or m.created_at))
    text = latest.content.strip()
    abandoned = any(k in text for k in ABANDON_TERMS)
    return {
        "text": text[:120],
        "from_date": latest.updated_at or latest.created_at,
        "abandoned": abandoned,
    }


def _evolve_items(kind: str) -> list[dict]:
    """反思/技能条目（进化层）：id/date/content；无则空列表（evolution 未导入时优雅降级）"""
    try:
        from app.agent.evolution import list_reflections, list_skills

        return list_reflections() if kind == "reflection" else list_skills()
    except Exception:
        return []


def build_hub_view() -> dict:
    """聚合中枢：从 5 文件计算统一视图（零落盘派生视图，三视图共享）"""
    entries = store.read_entries()
    try:
        state = read_state()
    except Exception:
        state = {}

    # 1. 主题归拢：逐条记忆 → 主题分组（aliases 通道）
    groups: dict[str, list] = {}
    for e in entries:
        topic = _match_topic(e.content)
        groups.setdefault(topic, []).append(e)

    # 1b. 向量兜底（P3 双通道 ②）：aliases 未归类的记忆批量向量归拢（一次 embed 全部）
    unclassified = groups.get("未归类", [])
    if unclassified:
        topics_list = list(_topic_rules().keys())
        texts = [e.content for e in unclassified]
        bucket = _vector_bucket(unclassified, texts, topics_list)
        if bucket:
            for e in unclassified:
                t2 = bucket.get(e.content)
                if t2:
                    groups["未归类"].remove(e)
                    groups.setdefault(t2, []).append(e)

    # 反思/技能按同一主题词典归拢（天下大同：记忆/反思/技能共用中央主键）
    reflections = _evolve_items("reflection")
    skills = _evolve_items("skill")
    refl_groups: dict[str, list] = {}
    skill_groups: dict[str, list] = {}
    for r in reflections:
        refl_groups.setdefault(_match_topic(r["content"]), []).append(r)
    for s in skills:
        skill_groups.setdefault(_match_topic(s["content"]), []).append(s)

    # 2. 主题视图（学习路径的真相源）
    topics = []
    for name, mems in groups.items():
        if name == "未归类":
            continue  # 未归类不进路径（避免噪音），但计数仍含
        mems.sort(key=lambda m: (m.updated_at or m.created_at), reverse=True)
        cont = _derive_continuation(mems)
        # parent（P3 树状数据源）：来自 topics.json（模型演化输出），无则空串（前端平铺）
        parent = ""
        try:
            from app.memory.topics_store import find_topic

            _t = find_topic(name)
            parent = (_t or {}).get("parent", "") or ""
            _touch = (_t or {}).get("last_active", "") or ""
            _mstatus = (_t or {}).get("status", "") or ""  # 模型收尾判断的状态（2026-08-21）
        except Exception:
            parent = ""
            _touch = ""
            _mstatus = ""
        topics.append(
            {
                "name": name,
                "parent": parent,
                "status": _infer_status(
                    mems, state, topic=name, last_active=_touch, model_status=_mstatus
                ),
                "last_active": _last_active(mems, _touch),
                "memory_count": len(mems),
                "memories": [
                    {
                        "content": m.content,
                        "category": m.category,
                        "date": m.updated_at or m.created_at,
                        # 双时间戳（P2，2026-08-19）：content_date=从内容正则提取的"发生日"
                        # （模型可信时用，如"08-12 学了正则化"）；record_date=created_at（机器可靠）。
                        # 不一致时前端并排显示——数据给觉察，不替模型改（防日期幻觉）。
                        "content_date": _content_date(m.content),
                    }
                    for m in mems
                ],
                # 续接点（从记忆推导，状态再生）：搁置主题 abandoned=True 前端不主动推荐
                "continuation": cont,
                # 反思/技能归拢（联动：该主题为什么卡住 / 怎么讲才懂）
                "reflections": [r["content"][:200] for r in refl_groups.get(name, [])],
                "skills": [s["content"][:200] for s in skill_groups.get(name, [])],
            }
        )
    topics.sort(key=lambda t: t["last_active"], reverse=True)

    # 3. 画像视图
    try:
        profile = store.recall_profile()
    except Exception:
        profile = ""

    # 4. 统计
    unclassified = len(groups.get("未归类", []))
    return {
        "topics": topics,
        "profile": profile,
        "stats": {
            "total": len(entries),
            "unclassified": unclassified,
            "topic_count": len(topics),
            "reflection_count": len(reflections),
            "skill_count": len(skills),
        },
    }
