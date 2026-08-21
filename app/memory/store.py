"""M2 记忆存储：git 跟踪文件 + 画像摘要 + bge-m3 向量去重/JIT 检索
设计依据：docs/M2-DESIGN.md（三层存储 / 双轨去重 / LangMem 画像 / 护栏不是规则）
"""
import contextvars
import json
from datetime import date, datetime

from app.config import DATA_DIR
from app.memory import vector
from app.memory.schema import MEMORY_FILE, MEMORY_LINE_LIMIT, PROFILE_FILE, PROFILE_LIMIT, MemoryEntry, make_entry_id

# 记忆变更日志（2026-08-18 治理权#3）：append-only jsonl，记录每次记忆写操作——
# 用户能看见"谁改了什么记忆、前后什么样"（可观测性 L3 状态对比的落盘）。
# 操作者：model（工具调用）/ user（前端修正/删除）/ harness（S+1 增强等机器动作）
CHANGE_LOG = DATA_DIR / "data" / "change_log.jsonl"


def log_change(action: str, summary: str):
    """记一条记忆变更（尽力而为：失败静默——日志是观测不是主流程）。
    action=动作名（remember/forget/edit_memory/strength）——不编造操作者：
    forget/edit_memory 既被模型工具调也被前端 API 调，store 层无法区分调用方，诚实记录动作本身。"""
    try:
        CHANGE_LOG.parent.mkdir(parents=True, exist_ok=True)
        rec = {"time": datetime.now().isoformat(timespec="seconds"), "action": action, "summary": summary}
        with CHANGE_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def read_changes(limit: int = 20) -> list[dict]:
    """读最近 N 条记忆变更（倒序：最新的在前）——前端"最近变更"数据源"""
    if not CHANGE_LOG.exists():
        return []
    try:
        lines = [ln for ln in CHANGE_LOG.read_text(encoding="utf-8").splitlines() if ln.strip()]
        recs = []
        for ln in lines[-limit:]:
            try:
                recs.append(json.loads(ln))
            except Exception:
                continue
        return list(reversed(recs))
    except Exception:
        return []

# 防循环导入：update_profile 内部要调 LLM，由 tutor 注入回调
_profile_writer = None

# 困惑提炼回调（方案 C，2026-08-15）：会话收尾时提炼"本次核心困惑"（认知卡点，非情绪）。
# 触发归机器（会话结束+记忆变化），提炼归模型（LLM 按五判据判断）。
_confusion_writer = None

# 闪光提炼回调（2026-08-20，拾光=拾到我们没发现的闪光）：会话收尾提炼"用户没发现的自己"。
# 与困惑同构：提炼归模型（三判据），无闪光返回 None（零成本）；闪光≠夸奖≠困惑。
_glint_writer = None

# D1 事件兜底标记（v0.2，2026-08-13 → B4 加固 2026-08-20）：本请求轮是否有记忆变化。
# 串味修复：原模块级布尔跨请求共享——A 会话 remember 置位、B 会话钩子 consume 消费（A 画像不刷新/B 被误触发）；
# 改 contextvars.ContextVar——每个请求 task 独立值（uvicorn 每请求一 task），
# mark（对话中 remember/forget/edit/update_state）与 consume（同轮 _chat_stream 收尾）在同一 task，天然隔离。
_session_memory_changed: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "session_memory_changed", default=False
)


def register_profile_writer(fn):
    """tutor 模块注册"模型压缩记忆成画像"的回调（模型驱动，应用层零规则）"""
    global _profile_writer
    _profile_writer = fn


def register_confusion_writer(fn):
    """tutor 模块注册"会话核心困惑提炼"回调（方案 C，2026-08-15）。
    fn(对话文本) -> str | None：返回困惑描述（一句话，用户视角的开放问题），无困惑返回 None。"""
    global _confusion_writer
    _confusion_writer = fn


def register_glint_writer(fn):
    """tutor 模块注册"闪光提炼"回调（2026-08-20）。
    fn(对话文本) -> str | None：返回闪光描述（用户没发现的模式/潜力/洞见），无闪光返回 None。"""
    global _glint_writer
    _glint_writer = fn


async def extract_session_confusion(dialogue: str) -> str | None:
    """会话收尾调用：提炼本次核心困惑（认知卡点非情绪）。无困惑返回 None（零成本）。"""
    if _confusion_writer is None or not (dialogue or "").strip():
        return None
    try:
        return await _confusion_writer(dialogue)
    except Exception:
        return None


async def extract_session_glint(dialogue: str) -> str | None:
    """会话收尾调用：提炼用户没发现的闪光（模式/潜力/洞见）。无闪光返回 None（零成本）。"""
    if _glint_writer is None or not (dialogue or "").strip():
        return None
    try:
        return await _glint_writer(dialogue)
    except Exception:
        return None


# 关系轨提炼回调（阶段1，2026-08-17）：会话收尾提炼"我们之间"的慢变状态（depth/last_topic/tone）。
# 只写 state.json（9.3 分工：慢变状态归状态轮，稳定原则才进记忆）；无实质关系信息返回 None。
_relation_writer = None


def register_relation_writer(fn):
    """tutor 模块注册"关系轨提炼"回调。
    fn(对话文本) -> dict | None：返回 {depth, last_topic, tone}，无关系信息返回 None。"""
    global _relation_writer
    _relation_writer = fn


async def extract_session_relation(dialogue: str) -> dict | None:
    """会话收尾调用：提炼关系轨。无关系信息返回 None（零成本）。"""
    if _relation_writer is None or not (dialogue or "").strip():
        return None
    try:
        return await _relation_writer(dialogue)
    except Exception:
        return None


# 任务轨续接点提炼回调（阶段2，2026-08-17）：会话收尾提炼"下次从哪继续"（学习/讨论线程）。
# 只写 state.json（快照语义滚动覆盖）；无未完成线程返回 None（NOOP 判别归模型）。
_continuation_writer = None


def register_continuation_writer(fn):
    """tutor 模块注册"续接点提炼"回调。
    fn(对话文本) -> str | None：返回"下次从哪继续"（一句话），无未完成线程返回 None。"""
    global _continuation_writer
    _continuation_writer = fn


async def extract_session_continuation(dialogue: str) -> str | None:
    """会话收尾调用：提炼续接点。无未完成线程返回 None（零成本）。"""
    if _continuation_writer is None or not (dialogue or "").strip():
        return None
    try:
        return await _continuation_writer(dialogue)
    except Exception:
        return None


# 教学经验提炼回调（第四路，2026-08-19 自主反思）：会话收尾提炼"教学经验"——
# reflection=这次讲解/沟通暴露了哪个坑（改进项）；skill=这次什么讲法/方式有效（可复用）。
# 触发归机器（每次会话末），判断归模型（五判据，返回 None 零落库）。反思/技能不再"等用户喂"。
_teaching_writer = None


def register_teaching_writer(fn):
    """tutor 模块注册"教学经验提炼"回调。
    fn(对话文本) -> dict | None：返回 {reflection, skill}，无教学经验返回 None。"""
    global _teaching_writer
    _teaching_writer = fn


async def extract_session_teaching(dialogue: str) -> dict | None:
    """会话收尾调用：提炼教学经验（反思/技能合一）。无经验返回 None（零成本）。"""
    if _teaching_writer is None or not (dialogue or "").strip():
        return None
    try:
        return await _teaching_writer(dialogue)
    except Exception:
        return None


# 主题提炼回调（第六路，2026-08-19 主题动态演化 P2）——意图驱动：
# 模型看对话语义识别主题 + 看已有主题列表归并，输出 [{name, intent, confidence}]；
# intent 四分类（learning/new/farewell/mention）——"提到≠想学"防误激活（体验关键）。
# 触发归机器（每次会话末），判断归模型；harness 只做意图分流 + 确定性验证。
_topics_writer = None


def register_topics_writer(fn):
    """tutor 模块注册"主题提炼"回调。
    fn(对话文本) -> dict | None：返回 {"topics": [{name, intent, confidence}]}，无主题返回 None。"""
    global _topics_writer
    _topics_writer = fn


async def extract_session_topics(dialogue: str) -> dict | None:
    """会话收尾调用：提炼主题（含意图）。无主题返回 None（零成本）。"""
    if _topics_writer is None or not (dialogue or "").strip():
        return None
    try:
        return await _topics_writer(dialogue)
    except Exception:
        return None


def mark_memory_changed():
    _session_memory_changed.set(True)


def consume_memory_changed() -> bool:
    """读取并清除本请求轮的会话记忆变化标记（会话收尾钩子调用一次）"""
    v = _session_memory_changed.get()
    _session_memory_changed.set(False)
    return v


def _ensure_file():
    MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not MEMORY_FILE.exists():
        MEMORY_FILE.write_text("# 用户记忆（git 跟踪，人可审）\n", encoding="utf-8")


def read_entries() -> list[MemoryEntry]:
    _ensure_file()
    entries = []
    for line in MEMORY_FILE.read_text(encoding="utf-8").splitlines():
        e = MemoryEntry.from_line(line)
        if e:
            entries.append(e)
    return entries


_CAT_TAG = {
    "偏好": "偏好", "preference": "偏好",
    "目标": "目标", "goal": "目标",
    "进度": "进度", "progress": "进度",
    "错误记录": "错误", "mistake": "错误", "error": "错误",
    "学习记录": "学习", "learning": "学习",
}

_synced = False


async def _sync_backfill():
    """首次使用时把文件里已有的记忆回填向量库（迁移 M1 旧数据，懒执行一次）"""
    global _synced
    if _synced:
        return
    _synced = True
    entries = read_entries()
    if not entries:
        return
    try:
        have = vector.existing_ids()
    except Exception:
        return
    missing = [e for e in entries if vector.entry_id(e.content) not in have]
    if not missing:
        return
    try:
        vecs = await vector.aembed([e.content for e in missing])
        for e, v in zip(missing, vecs):
            vector.upsert(vector.entry_id(e.content), e.content, v)
    except Exception:
        pass


def entries_text() -> str:
    """全量记忆文本（供 update_profile 压缩用）"""
    entries = read_entries()
    if not entries:
        return "(暂无记忆)"
    lines = []
    for e in entries:
        tag = _CAT_TAG.get(e.category, "笔记")
        lines.append(f"[{e.created_at}|{tag}|imp={e.importance}] {e.content}")
    return "\n".join(lines)


def recall_profile() -> str:
    """画像摘要（常驻注入，瘦身）——不存在则引导模型生成"""
    if PROFILE_FILE.exists():
        text = PROFILE_FILE.read_text(encoding="utf-8").strip()
        if text:
            return text
    return "(画像未生成：积累记忆后调用 update_profile 生成我的画像)"


async def remember(note: str, source: str = "user", importance: int = 5, category: str = "笔记") -> str:
    """记住一条用户信息（用户明确说"记住/记一下"时）。source：用户原话→user；转述/代记→agent"""
    note = note.strip()
    if not note:
        return "内容为空，不写入"
    await _sync_backfill()
    if len(read_entries()) >= MEMORY_LINE_LIMIT:
        return f"记忆已达容量上限（{MEMORY_LINE_LIMIT} 条），请先整理：用 recall_profile 看画像、确认哪些可合并/删除"

    # 三层护栏（护栏=提供信息，不是替模型做决定）：
    # ① 字面完全重复（内容哈希相同）→ 硬拒（真重复，写了无意义）
    # ② ≥DEDUP_HARD(0.97) 语义等价 → 硬拒（2026-08-19 升级：真重复阻断是确定性不变量——
    #    系统已存在语义等价条目（系统状态）锁死代码，不靠模型自觉。GATE_1 案例 sim=0.9942 仅警告仍写入）
    #    拒绝信息引导 edit_memory 合并新信息（可争议性保留：有新信息不丢，只是不许再造重复条目）
    # ③ DEDUP_SOFT(0.85)~0.97 → 写穿 + 警告（判断区间留给模型——是否确有新信息）
    # ④ <0.85 → 正常写，无提示
    # 四原语映射（判断无墙）：NOOP=重复硬拒（字面/语义等价均系统状态）；UPDATE 由 edit_memory；此处只做 ADD
    same_note = next((e for e in read_entries() if e.content == note), None)
    if same_note:
        return f"已存在完全相同的内容（{same_note.content[:50]}……），不重复写入（NOOP）。如需修正可用 edit_memory。"
    similar = vector.find_similar(note, top_k=3)
    warn = ""
    if similar:
        near = [f"{old[:40]}({sim:.2f})" for _, old, sim in similar if sim >= vector.DEDUP_SOFT]
        hard = [(old, sim) for _, old, sim in similar if sim >= vector.DEDUP_HARD]
        if hard:
            # 语义等价硬拒（不变量无口）：系统已存等价条目 → 拒绝新增，引导合并
            old, sim = max(hard, key=lambda x: x[1])
            return (
                f"已存在语义等价的记忆（相似度 {sim:.2f} ≥ {vector.DEDUP_HARD:.2f}）："
                f"「{old[:50]}……」——不重复写入（真重复阻断）。"
                f"如果这条确实包含新信息，请用 edit_memory 把它合并进已有条目，而不是新增重复。"
            )
        if any(sim >= vector.DEDUP_SOFT for _, _, sim in similar):
            warn = f"。注：存在相似记忆（≥{vector.DEDUP_SOFT:.2f}）——{ '；'.join(near[:3]) }——若确有新信息可继续，或 edit_memory 合并"
    entry = MemoryEntry(
        content=note,
        created_at=date.today().isoformat(),
        source=source,
        importance=int(importance),
        category=category,
        entry_id=make_entry_id(note, date.today().isoformat()),  # 稳定 id（2026-08-19 meta-id-diff 前置）
    )
    _ensure_file()
    with open(MEMORY_FILE, "a", encoding="utf-8") as f:
        f.write(entry.to_line() + "\n")
    # 落向量（id 由内容哈希定，重复 upsert 幂等）
    try:
        vec = (await vector.aembed([note]))[0]
        vector.upsert(vector.entry_id(note), note, vec)
    except vector.OllamaUnavailableError:
        # 降级（B 方案）：文本已保存，索引暂缺——重启 Ollama 后仍可补（记忆文本是真相源）
        return f"已写入文件，但向量索引暂不可用（Ollama 未启动）——记忆文本已保存，重启 Ollama 后可补齐检索"
    except Exception as e:
        return f"已写入文件，但向量索引失败：{e}（记忆仍生效，可稍后重试）"
    # D1 事件兜底：写入成功 → 标记本会话记忆变化（会话收尾钩子消费，不立即提炼）
    mark_memory_changed()
    log_change("remember(ADD)", f"{category} imp={importance} | {note[:80]}")
    return f"已记住（{category}，imp={importance}）{warn}"


async def search_memory(query: str, top_k: int = 3, category: str = "", _bump: bool = True) -> str:
    """检索记忆库：了解用户偏好/历史/进度/困惑时调用。
    默认返回 3 条；可传 category 限定类别（学习记录/进度/偏好/目标/困惑/关系/笔记），
    避免跨维度串扰（如查学习进度时困惑条目混入），不确定就留空=全量。
    **不要对通用知识问题调用本工具**（用户问"什么是 X"这种普适知识直接回答，不检索；
    检索只用于"涉及用户本人的进度/偏好/历史/状态"——2026-08-20 P1 联动）。
    _bump=False：只读检索（A2-2 2026-08-20，子 agent 用——不 S+1，声明与行为一致）。"""
    # 门控/排序依据（实验 2026-08-17）：默认 3 条=甜点区（>10 有害）；三因子 rel0.7+imp0.15+rec0.15
    try:
        await _sync_backfill()
        vec = (await vector.aembed([query]))[0]
        k = max(1, min(top_k, 10))
        entries = read_entries()
        hits = vector.search_ranked(vec, top_k=k, entries=entries, category=category or None)
    except vector.OllamaUnavailableError:
        # 降级（B 方案）：Ollama 挂 → 明确提示，对话不阻断（画像/状态轮常驻仍可用）
        return "(检索服务暂不可用：Ollama 未启动。对话可以继续，细节记忆暂时查不了——稍后会自动恢复)"
    except Exception as e:
        return f"(检索失败：{e})"
    if not hits:
        return "(没有检索到相关记忆)"
    # 用进废退（2026-08-18 补洞）：模型真正检索命中的记忆 S+1（封顶 5）——
    # 门槛 sim≥0.5（无关查询误中不算"用过"）；写回尽力而为（失败静默，检索不阻塞）
    if _bump:
        _bump_strength(hits)
    lines = []
    for i, (_, text, score) in enumerate(hits, 1):
        lines.append(f"[{i}] (相关度 {score:.2f}) {text}")
    return "\n".join(lines)


def _bump_strength(hits: list[tuple[str, str, float]]):
    """检索命中 → S+1 封顶 5（sim≥0.5 才算命中；旧数据无 S 字段默认 1）。
    幂等：S 已封顶不重复写。失败静默（写回是增强非主流程）。"""
    try:
        bumped = [h for h in hits if h[2] >= 0.5]
        if not bumped:
            return
        entries = read_entries()
        by_text = {e.content: e for e in entries}
        changed = False
        for _, text, _sim in bumped:
            e = by_text.get(text)
            if e is None:
                continue
            if e.strength < 5:
                first_use = e.strength == 1  # 仅首次使用（1→2）记日志，防检索刷屏
                e.strength += 1
                changed = True
                if first_use:
                    log_change("strength(S+1)", f"首次被检索到，开始变强 | {text[:60]}")
        if not changed:
            return
        # 整文件重写（保序，保留文件头注释）
        header = MEMORY_FILE.read_text(encoding="utf-8").splitlines()[:1]
        lines = header + [e.to_line() for e in entries]
        MEMORY_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except Exception as e:
        print(f"[strength] 命中增强写回失败（静默，不影响检索）: {e}", flush=True)


PROFILE_META_FILE = None  # 惰性初始化：DATA_DIR/memory/profile.meta.json


def _profile_meta() -> dict:
    """画像增量 meta（2026-08-19 meta-id-diff）：记 seen_entry_ids（上次提炼处理过哪些记忆 id）。
    纯 id 集合——对 mtime/时区/重放鲁棒；崩溃重启后 diff 仍正确（参考 DeepTutor L2Meta）。"""
    global PROFILE_META_FILE
    if PROFILE_META_FILE is None:
        PROFILE_META_FILE = PROFILE_FILE.parent / "profile.meta.json"
    try:
        if PROFILE_META_FILE.exists():
            import json as _json

            return _json.loads(PROFILE_META_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {"seen_entry_ids": []}


def _save_profile_meta(seen_ids: list):
    try:
        import json as _json

        PROFILE_META_FILE.parent.mkdir(parents=True, exist_ok=True)
        PROFILE_META_FILE.write_text(_json.dumps({"seen_entry_ids": seen_ids}), encoding="utf-8")
    except Exception:
        pass  # meta 失败不阻塞主流程（下次全量兜底）


async def update_profile(force: bool = False) -> str:
    """更新用户画像（2026-08-19 增量模式，meta-id-diff）：
    默认只处理"上次提炼后新增的记忆"（输入 = 已有画像 + 新增 → 模型合并更新，记忆量增长不炸）；
    force=True 走全量（画像损坏/用户显式要求时）。
    guards 运行时拦截：画像含绝对化词 → 拒绝写入 + 警告（旧画像保留，下次记忆变化重提炼）。"""
    if _profile_writer is None:
        return "画像写入器未注册，请先启动 tutor agent"
    entries = read_entries()
    seen = set(_profile_meta().get("seen_entry_ids", []))
    if force or not seen:
        # 全量：所有记忆 + 无已有画像（或 meta 缺失兜底）
        new_entries = entries
        new_ids = [e.entry_id for e in entries if e.entry_id]
        new_text = entries_text()
        current_profile = ""
    else:
        new_entries = [e for e in entries if e.entry_id and e.entry_id not in seen]
        new_ids = [e.entry_id for e in new_entries]
        if not new_entries:
            return "画像无新记忆（无新增条目，不重提炼）"
        new_text = "\n".join(f"- {e.content}" for e in new_entries)
        try:
            current_profile = PROFILE_FILE.read_text(encoding="utf-8").strip()
        except Exception:
            current_profile = ""
    # 输入 = 已有画像 + 新增记忆（模型合并更新，保全貌防遗忘）
    memory_text = f"【当前画像】\n{current_profile or '(空)'}\n\n【新增记忆】\n{new_text}"
    new_profile = await _profile_writer(memory_text)
    if not new_profile or not new_profile.strip():
        return "画像生成失败（模型返回空）"
    # guards 客观性护栏（判断无墙，不变量无口）：禁绝对化是代码拦不是判断
    try:
        from app.memory.guards import banned_hits

        hits = banned_hits(new_profile)
        if hits:
            print(f"[guards] 画像含绝对化用语，拒绝写入（命中: {hits}）——保留旧画像，下次记忆变化重提炼", flush=True)
            # 治理反馈（2026-08-19）：拒绝进 change_log——前端"最近变更"可见（用户有权知道系统拦了什么）
            log_change("guards(拦截)", f"画像含绝对化用语拒绝写入（命中: {'/'.join(hits)}）")
            return f"画像含绝对化用语已拒绝写入（命中: {'/'.join(hits)}）——下次记忆变化会重提炼"
    except Exception:
        pass  # guards 失败不阻塞主流程
    if len(new_profile) > PROFILE_LIMIT:
        new_profile = new_profile[:PROFILE_LIMIT] + "\n(已截断)"
    PROFILE_FILE.parent.mkdir(parents=True, exist_ok=True)
    # 内容未变不重写（防 mtime 抖动 + 无意义 IO）
    if PROFILE_FILE.exists() and PROFILE_FILE.read_text(encoding="utf-8").strip() == new_profile.strip():
        return "画像无变化（内容未变，不重写）"
    PROFILE_FILE.write_text(new_profile.strip() + "\n", encoding="utf-8")
    # 更新 meta（原子语义：写成功才记 seen；失败下次全量兜底）
    _save_profile_meta(list(seen | set(new_ids)))
    return f"画像已更新（{len(new_entries) if not force else len(entries)} 条新增，{len(new_profile)} 字）"


def forget(content: str, reason: str = "user_request") -> str:
    """删除一条记忆（用户明确要删时）。先确认再删；误删进回收站可恢复。
    reason 四类（借鉴 DeepTutor delete reason，2026-08-19）：contradicted=与新记忆矛盾
    / superseded=被更新记忆取代 / stale=已过时 / low-signal=低价值冗余；用户主动删=user_request。"""
    _ensure_file()
    lines = MEMORY_FILE.read_text(encoding="utf-8").splitlines()
    kept, removed, removed_lines = [], False, []
    for ln in lines:
        if content and content in ln:
            removed = True
            removed_lines.append(ln)
            # 尝试提取内容哈希删向量
            e = MemoryEntry.from_line(ln)
            if e:
                vector.delete(vector.entry_id(e.content))
        else:
            kept.append(ln)
    if not removed:
        return "未找到匹配的记忆"
    # 代码层安全垫：删除前把被删条目写入回收站（可恢复；不打断模型流程，不依赖模型自觉）
    if removed_lines:
        trash = MEMORY_FILE.parent / "trash.md"
        trash.parent.mkdir(parents=True, exist_ok=True)
        with trash.open("a", encoding="utf-8") as f:
            f.write(f"\n## {date.today()} forget 回收\n")
            f.write("\n".join(removed_lines) + "\n")
    MEMORY_FILE.write_text("\n".join(kept) + "\n", encoding="utf-8")
    log_change("forget(DELETE)", f"[{reason}] 回收 {len(removed_lines)} 条 | {removed_lines[0][:80] if removed_lines else ''}")
    mark_memory_changed()  # 🔴修复 2026-08-19：删除也是记忆变化，触发画像重提炼（治理操作后画像滞后）
    return "已删除"


async def edit_memory(old: str, new: str) -> str:
    """修正一条记忆：按内容匹配行，替换内容并同步向量（人可审可改，M5）"""
    _ensure_file()
    old = old.strip()
    new = new.strip()
    if not old or not new:
        return "修正内容为空"
    lines = MEMORY_FILE.read_text(encoding="utf-8").splitlines()
    new_lines = []
    edited = False
    for ln in lines:
        e = MemoryEntry.from_line(ln)
        if e and old in e.content:
            old_content = e.content
            e.content = new
            e.updated_at = date.today().isoformat()
            new_lines.append(e.to_line())
            edited = True
            try:
                vector.delete(vector.entry_id(old_content))
                vec = (await vector.aembed([new]))[0]
                vector.upsert(vector.entry_id(new), new, vec)
            except Exception as e_vec:
                # B6 fail loud（2026-08-20）：向量同步失败必须可见——文件已改但向量旧=幽灵向量
                # （检索命中旧内容用户不自知）；静默吞=错误影响最大化。记录后不阻塞（文本修正已成功）
                log_change("vector_sync_failed", f"edit_memory 向量同步失败: {str(e_vec)[:80]}")
                print(f"[vector] 向量同步失败: {e_vec}", flush=True)
        else:
            new_lines.append(ln)
    if not edited:
        return "未找到匹配的记忆"
    MEMORY_FILE.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    log_change("edit_memory(UPDATE)", f"{old[:40]} → {new[:40]}")
    mark_memory_changed()  # 🔴修复 2026-08-19：修正也是记忆变化，触发画像重提炼（与 forget/update_state 同源）
    return "已修正"
