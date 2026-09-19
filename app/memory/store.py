"""M2 记忆存储：git 跟踪文件 + 画像摘要 + bge-m3 向量去重/JIT 检索
设计依据：docs/M2-DESIGN.md（三层存储 / 双轨去重 / LangMem 画像 / 护栏不是规则）
"""

import contextvars
import json
from datetime import date, datetime
from pathlib import Path

from app.config import DATA_DIR
from app.memory import vector
from app.memory.schema import (
    MEMORY_LINE_LIMIT,
    PROFILE_LIMIT,
    MemoryEntry,
    make_entry_id,
    memory_dir,
)
from app.utils.atomic_io import atomic_write_text


def _mf() -> Path:
    """当前用户记忆文件（uid 经 memory_dir 解析：显式 > contextvar > legacy）"""
    if _MF_OVERRIDE is not None:
        return _MF_OVERRIDE  # 测试注入点（2026-08-28：存量测试从模块常量注入迁移而来）
    return memory_dir() / "user_memory.md"


def _pf() -> Path:
    if _PF_OVERRIDE is not None:
        return _PF_OVERRIDE  # 测试注入点
    return memory_dir() / "profile.md"


# 测试覆盖钩子（2026-08-28 P0 函数化后存量测试的注入兼容层：模块常量 → 覆盖钩子）
_MF_OVERRIDE: Path | None = None
_PF_OVERRIDE: Path | None = None
_CHANGE_LOG_OVERRIDE: Path | None = None


def _supersede() -> Path:
    return _mf().parent / "supersede.md"


# 记忆变更日志（2026-08-18 治理权#3）：append-only jsonl，记录每次记忆写操作——
# 用户能看见"谁改了什么记忆、前后什么样"（可观测性 L3 状态对比的落盘）。
# 操作者：model（工具调用）/ user（前端修正/删除）/ harness（S+1 增强等机器动作）
CHANGE_LOG = DATA_DIR / "data" / "change_log.jsonl"


def _change_log_path() -> Path:
    """变更日志路径（测试覆盖钩子优先——存量测试从模块常量注入迁移）。"""
    return _CHANGE_LOG_OVERRIDE if _CHANGE_LOG_OVERRIDE is not None else CHANGE_LOG


def log_change(action: str, summary: str):
    """记一条记忆变更（尽力而为：失败静默——日志是观测不是主流程）。
    action=动作名（remember/forget/edit_memory/strength）——不编造操作者：
    forget/edit_memory 既被模型工具调也被前端 API 调，store 层无法区分调用方，诚实记录动作本身。"""
    try:
        _cl = _change_log_path()
        _cl.parent.mkdir(parents=True, exist_ok=True)
        rec = {
            "time": datetime.now().isoformat(timespec="seconds"),
            "action": action,
            "summary": summary,
        }
        with _cl.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as _e:
        print(f"[memory/store] 静默异常已可见化: {_e}", flush=True)


def read_changes(limit: int = 20) -> list[dict]:
    """读最近 N 条记忆变更（倒序：最新的在前）——前端"最近变更"数据源"""
    _cl = _change_log_path()
    if not _cl.exists():
        return []
    try:
        lines = [ln for ln in _cl.read_text(encoding="utf-8").splitlines() if ln.strip()]
        recs = []
        for ln in lines[-limit:]:
            try:
                recs.append(json.loads(ln))
            except Exception as _je:
                print(f"[store] 跳过坏台账行: {_je}", file=__import__('sys').stderr)
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
    except Exception as e:
        log_change(
            "extractor_failed", f"confusion 提炼失败: {str(e)[:100]}"
        )  # 2026-08-21 留痕（防静默死亡）
        return None


async def extract_session_glint(dialogue: str) -> str | None:
    """会话收尾调用：提炼用户没发现的闪光（模式/潜力/洞见）。无闪光返回 None（零成本）。"""
    if _glint_writer is None or not (dialogue or "").strip():
        return None
    try:
        return await _glint_writer(dialogue)
    except Exception as e:
        log_change("extractor_failed", f"glint 提炼失败: {str(e)[:100]}")  # 2026-08-21 留痕
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
    except Exception as e:
        log_change("extractor_failed", f"relation 提炼失败: {str(e)[:100]}")  # 2026-08-21 留痕
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
    except Exception as e:
        log_change("extractor_failed", f"continuation 提炼失败: {str(e)[:100]}")  # 2026-08-21 留痕
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
    except Exception as e:
        log_change("extractor_failed", f"teaching 提炼失败: {str(e)[:100]}")  # 2026-08-21 留痕
        return None


# ACE playbook 提炼回调（第七路，2026-08-30，设计 docs/2026-08-30-ACE-PLAYBOOK-DESIGN.md）：
# 会话收尾提炼教学策略 delta（add/revise）；bump 计数不归模型——代码按接地信号推进。
_playbook_writer = None


def register_playbook_writer(fn):
    """tutor 模块注册"playbook delta 提炼"回调。
    fn(对话文本) -> list[dict] | None：返回 delta entries，无可提炼返回 None。"""
    global _playbook_writer
    _playbook_writer = fn


async def extract_session_playbook(dialogue: str) -> list | None:
    """会话收尾调用：提炼 playbook delta entries。无可提炼返回 None（零成本）。"""
    if _playbook_writer is None or not (dialogue or "").strip():
        return None
    try:
        return await _playbook_writer(dialogue)
    except Exception as e:
        log_change("extractor_failed", f"playbook 提炼失败: {str(e)[:100]}")
        return None


# 跨域类比提炼回调（第八路，2026-08-31，路线图 v3.0 §4）：会话收尾提炼跨域结构同构类比。
# cadence（≥7 天）/evidence 锚定校验/存储全归 app.agent.analogy；提炼归模型，找不到输出『无』。
_analogy_writer = None


def register_analogy_writer(fn):
    """tutor 模块注册"跨域类比提炼"回调。
    fn(对话文本) -> dict | None：返回 {analogy, domain_a, domain_b, evidence_a, evidence_b}，
    cadence 未到期/找不到/锚定失败返回 None。"""
    global _analogy_writer
    _analogy_writer = fn


async def extract_session_analogy(dialogue: str) -> dict | None:
    """会话收尾调用：提炼跨域类比。无可提炼返回 None（零成本）。"""
    if _analogy_writer is None:
        return None
    try:
        return await _analogy_writer(dialogue)
    except Exception as e:
        log_change("extractor_failed", f"analogy 提炼失败: {str(e)[:100]}")
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
    except Exception as e:
        log_change(
            "extractor_failed", f"topics 提炼失败: {str(e)[:100]}"
        )  # 2026-08-21 留痕（曾静默死 2 天）
        return None


def mark_memory_changed():
    _session_memory_changed.set(True)


def consume_memory_changed() -> bool:
    """读取并清除本请求轮的会话记忆变化标记（会话收尾钩子调用一次）"""
    v = _session_memory_changed.get()
    _session_memory_changed.set(False)
    return v


def _ensure_file():
    _mf().parent.mkdir(parents=True, exist_ok=True)
    if not _mf().exists():
        atomic_write_text(_mf(), "# 用户记忆（git 跟踪，人可审）\n")


def _count_entries(lines: list[str]) -> int:
    return sum(1 for ln in lines if MemoryEntry.from_line(ln))


def _warn_entry_collapse(before: int, after: int, action: str) -> None:
    """P0-2 写后校验（2026-08-28 止血）：条目数异常暴跌告警——静默失忆必须可见。
    规则：操作前 ≥4 条、操作后 < 一半 → 疑似异常删除/覆盖。只告警不阻断（不干预模型判断）。"""
    if before >= 4 and after < before / 2:
        msg = f"[memory] ⚠️ 条目数异常暴跌 {before} → {after}（{action}）——请立即检查！"
        print(msg, flush=True)
        try:
            log_change("collapse_warning", msg)
        except Exception as _e:
            print(f"[memory/store] 静默异常已可见化: {_e}", flush=True)


def read_entries() -> list[MemoryEntry]:
    _ensure_file()
    entries = []
    for line in _mf().read_text(encoding="utf-8").splitlines():
        e = MemoryEntry.from_line(line)
        if e:
            entries.append(e)
    return entries


_CAT_TAG = {
    "偏好": "偏好",
    "preference": "偏好",
    "目标": "目标",
    "goal": "目标",
    "进度": "进度",
    "progress": "进度",
    "错误记录": "错误",
    "mistake": "错误",
    "error": "错误",
    "学习记录": "学习",
    "learning": "学习",
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
        for e, v in zip(missing, vecs, strict=True):
            vector.upsert(vector.entry_id(e.content), e.content, v)
    except Exception as _e:
        print(f"[memory/store] 静默异常已可见化: {_e}", flush=True)


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
    if _pf().exists():
        text = _pf().read_text(encoding="utf-8").strip()
        if text:
            return text
    return "(画像未生成：积累记忆后调用 update_profile 生成我的画像)"


async def remember(
    note: str, source: str = "user", importance: int = 5, category: str = "笔记"
) -> str:
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
            warn = f"。注：存在相似记忆（≥{vector.DEDUP_SOFT:.2f}）——{'；'.join(near[:3])}——若确有新信息可继续，或 edit_memory 合并"
    entry = MemoryEntry(
        content=note,
        created_at=date.today().isoformat(),
        source=source,
        importance=int(importance),
        category=category,
        entry_id=make_entry_id(
            note, date.today().isoformat()
        ),  # 稳定 id（2026-08-19 meta-id-diff 前置）
    )
    _ensure_file()
    with open(_mf(), "a", encoding="utf-8") as f:
        f.write(entry.to_line() + "\n")
    # 落向量（id 由内容哈希定，重复 upsert 幂等）
    try:
        vec = (await vector.aembed([note]))[0]
        vector.upsert(vector.entry_id(note), note, vec)
    except vector.OllamaUnavailableError:
        # 降级（B 方案）：文本已保存，索引暂缺——重启 Ollama 后仍可补（记忆文本是真相源）
        return "已写入文件，但向量索引暂不可用（Ollama 未启动）——记忆文本已保存，重启 Ollama 后可补齐检索"
    except Exception as e:
        return f"已写入文件，但向量索引失败：{e}（记忆仍生效，可稍后重试）"
    # D1 事件兜底：写入成功 → 标记本会话记忆变化（会话收尾钩子消费，不立即提炼）
    mark_memory_changed()
    log_change("remember(ADD)", f"{category} imp={importance} | {note[:80]}")
    return f"已记住（{category}，imp={importance}）{warn}"


def _neighbor_recall(
    hits: list[tuple[str, str, float]],
    entries: list,
    top_k: int,
) -> list[tuple[str, str, float]]:
    """P1-1 轻量记忆关联边（2026-08-27，对齐 MemGAS"关联检索>平面检索"共识）：
    命中条目的同 category 且 importance>=4 的邻居补入（最多 2 条、不挤原命中、尾部标 [关联]）。
    设计约束（MemGAS 自警：TopK 过大反引噪声）——只补高重要度同类别，宁缺毋滥。"""
    try:
        if not hits or len(hits) >= top_k + 2:
            return hits
        hit_texts = {t for _, t, _ in hits}
        hit_cats = {e.category for e in entries if e.content in hit_texts}
        if not hit_cats:
            return hits
        added: list[tuple[str, str, float]] = []
        for e in entries:
            if e.content in hit_texts:
                continue
            if e.category in hit_cats and (e.importance or 0) >= 4:
                added.append((e.entry_id, e.content, 0.0))  # score=0 标记 [关联]
            if len(added) >= 2:
                break
        return list(hits) + added if added else hits
    except Exception:
        return hits


async def search_memory(
    query: str, top_k: int | None = None, category: str = "", _bump: bool = True
) -> str:
    """检索记忆库：了解用户偏好/历史/进度/困惑时调用。
    默认返回条数按模型档位（C-2 2026-08-29：weak 3 条甜点区 / strong 6 条；config.model_tier）；
    可显式传 top_k 覆盖（判断归模型）；可传 category 限定类别（学习记录/进度/偏好/目标/困惑/关系/笔记），
    避免跨维度串扰（如查学习进度时困惑条目混入），不确定就留空=全量。
    **不要对通用知识问题调用本工具**（用户问"什么是 X"这种普适知识直接回答，不检索；
    检索只用于"涉及用户本人的进度/偏好/历史/状态"——2026-08-20 P1 联动）。
    _bump=False：只读检索（A2-2 2026-08-20，子 agent 用——不 S+1，声明与行为一致）。"""
    # 门控/排序依据（实验 2026-08-17）：默认 3 条=甜点区（>10 有害）；三因子 rel0.7+imp0.15+rec0.15
    if top_k is None:
        try:
            from app.config import model_tier

            top_k = model_tier()["search_top_k"]
        except Exception:
            top_k = 3
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
    # P1-1 轻量关联边（2026-08-27，MemGAS 关联检索简化）：命中条目的同类别高重要度邻居补入——
    # 关联检索 > 平面 TopK（记忆不是孤立点）；防噪音：importance>=4 + 最多补 2 + 不挤原命中
    hits = _neighbor_recall(hits, entries, top_k)
    lines = []
    for i, (_, text, score) in enumerate(hits, 1):
        tag = " (关联)" if score <= 0 else f" (相关度 {score:.2f})"
        lines.append(f"[{i}]{tag} {text}")
    return "\n".join(lines)


def _bump_strength(hits: list[tuple[str, str, float]]):
    """检索命中 → S+1 封顶 5（sim≥0.5 才算命中；旧数据无 S 字段默认 1）+ 访问统计 touch。
    幂等：S 已封顶不重复写。失败静默（写回是增强非主流程）。"""
    try:
        from app.memory import access

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
            access.touch(e.entry_id)  # Phase1 M-1/M-2：命中即"回血"，同时记使用统计
            if e.strength < 5:
                first_use = e.strength == 1  # 仅首次使用（1→2）记日志，防检索刷屏
                e.strength += 1
                changed = True
                if first_use:
                    log_change("strength(S+1)", f"首次被检索到，开始变强 | {text[:60]}")
        if not changed:
            access.flush()  # 统计照常落盘（S 封顶时也要记访问）
            return
        # 整文件重写（保序，保留文件头注释）
        header = _mf().read_text(encoding="utf-8").splitlines()[:1]
        lines = header + [e.to_line() for e in entries]
        atomic_write_text(_mf(), "\n".join(lines) + "\n")
        access.flush()
    except Exception as e:
        print(f"[strength] 命中增强写回失败（静默，不影响检索）: {e}", flush=True)


PROFILE_META_FILE = None  # 惰性初始化：DATA_DIR/memory/profile.meta.json


def _profile_meta() -> dict:
    """画像增量 meta（2026-08-19 meta-id-diff）：记 seen_entry_ids（上次提炼处理过哪些记忆 id）。
    纯 id 集合——对 mtime/时区/重放鲁棒；崩溃重启后 diff 仍正确（参考 DeepTutor L2Meta）。"""
    global PROFILE_META_FILE
    if PROFILE_META_FILE is None:
        PROFILE_META_FILE = _pf().parent / "profile.meta.json"
    try:
        if PROFILE_META_FILE.exists():
            import json as _json

            return _json.loads(PROFILE_META_FILE.read_text(encoding="utf-8"))
    except Exception as _e:
        print(f"[memory/store] 静默异常已可见化: {_e}", flush=True)
    return {"seen_entry_ids": []}


def _save_profile_meta(seen_ids: list):
    try:
        import json as _json

        PROFILE_META_FILE.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(
            PROFILE_META_FILE, _json.dumps({"seen_entry_ids": seen_ids}, ensure_ascii=False)
        )
    except Exception as _e:
        print(f"[memory/store] 静默异常已可见化: {_e}", flush=True)


_PROFILE_ID_RE = None  # 惰性初始化（避免模块加载期 import re）


def _profile_line_re():
    global _PROFILE_ID_RE
    if _PROFILE_ID_RE is None:
        import re as _r

        _PROFILE_ID_RE = _r.compile(r"^-\s+(.*?)\s*\[(p\d+)\]\s*$")
    return _PROFILE_ID_RE


def _parse_profile_lines(text: str) -> dict:
    """解析画像事实行 → {id: text}。格式：`- 内容 [p1]`。"""
    out = {}
    for ln in (text or "").splitlines():
        m = _profile_line_re().match(ln.strip())
        if m:
            out[m.group(2)] = m.group(1)
    return out


def _next_profile_id(used: set) -> str:
    """分配新画像 id（pN+1）。id 是确定性不变量——由代码分配，不由模型生成
    （Mem0 官方修过模型生成 id 的 UUID 幻觉——_resolve_mapped_id）。"""
    nums = [int(i[1:]) for i in used if i[1:].isdigit()]
    return f"p{max(nums) + 1 if nums else 1}"


def _trash_profile_line(text: str, eid: str) -> None:
    """画像被 DELETE 的行进回收站（可恢复；不打断流程，不依赖模型自觉——对齐 forget 的回收语义）。"""
    try:
        trash = _pf().parent / "trash.md"
        trash.parent.mkdir(parents=True, exist_ok=True)
        with trash.open("a", encoding="utf-8") as f:
            f.write(f"\n## {date.today()} profile {eid} 删除回收\n- {text}\n")
    except Exception as _e:
        print(f"[memory/store] 静默异常已可见化: {_e}", flush=True)


async def update_profile(force: bool = False) -> str:
    """更新用户画像（2026-08-21 四操作增量 diff——对齐 Mem0 DEFAULT_UPDATE_MEMORY_PROMPT 决策结构
    + Letta update_memory_if_changed_async 只更新变化块）：
    默认只处理"上次提炼后新增的记忆"；模型输出四操作 JSON（ADD/UPDATE/DELETE/NONE 逐条决策），
    代码只应用变化条目——NONE 原样保留（防漂移核心：不动的画像永不被重写）；
    force=True 走全量（画像损坏/用户显式要求时）。
    guards 运行时拦截：画像含绝对化词 → 拒绝写入 + 警告（旧画像保留，下次记忆变化重提炼）。"""
    if _profile_writer is None:
        return "画像写入器未注册，请先启动 tutor agent"
    entries = read_entries()
    seen = set(_profile_meta().get("seen_entry_ids", []))
    if force or not seen:
        # 全量：处理所有记忆（force=重建/兜底语义）；画像仍读现有（四操作 diff 需基于现有画像决策）
        new_entries = entries
        new_ids = [e.entry_id for e in entries if e.entry_id]
        new_text = entries_text()
        try:
            current_profile = _pf().read_text(encoding="utf-8").strip()
        except Exception:
            current_profile = ""
    else:
        new_entries = [e for e in entries if e.entry_id and e.entry_id not in seen]
        new_ids = [e.entry_id for e in new_entries]
        if not new_entries:
            return "画像无新记忆（无新增条目，不重提炼）"
        new_text = "\n".join(f"- {e.content}" for e in new_entries)
        try:
            current_profile = _pf().read_text(encoding="utf-8").strip()
        except Exception:
            current_profile = ""
    # 输入 = 已有画像 + 新增记忆（模型逐条决策，不重写全文）
    memory_text = f"【当前画像】\n{current_profile or '(空)'}\n\n【新增记忆】\n{new_text}"
    raw = await _profile_writer(memory_text)
    if not raw or not raw.strip():
        return "画像生成失败（模型返回空）"
    # 解析四操作 JSON（模型输出容错：取第一个 {…} 块）
    import re as _re

    m = _re.search(r"\{.*\}", raw, _re.DOTALL)
    if not m:
        return "画像更新失败（模型未返回 JSON）"
    try:
        ops = json.loads(m.group(0)).get("memory", [])
    except Exception:
        return "画像更新失败（JSON 解析失败）"
    if not isinstance(ops, list) or not ops:
        return "画像更新失败（memory 列表为空）"
    # 现有画像：注释头与事实行分离（头保留原样，事实行参与 diff）
    header_lines = [
        ln
        for ln in (current_profile or "").splitlines()
        if ln.strip() and not _profile_line_re().match(ln.strip())
    ]
    cur = _parse_profile_lines(current_profile)
    changes = {"ADD": 0, "UPDATE": 0, "DELETE": 0}
    applied: list[tuple] = []  # (eid or None, text, event)
    used_ids = set(cur.keys())
    for op in ops:
        if not isinstance(op, dict):
            continue
        eid = str(op.get("id", "")).strip()
        ev = str(op.get("event", "")).strip().upper()
        text = str(op.get("text", "")).strip()
        text = _re.sub(r"\s*\[p\d+\]\s*$", "", text)  # 清洗模型可能带上的 id 标记
        if ev == "NONE":
            # 防漂移校验：NONE 条目 text 必须与现有一致（模型偷偷改词 → 保留原样 + 记录）
            if eid in cur and text and text != cur[eid]:
                print(f"[guards] 画像 NONE 条目被改写（{eid}），保留原样", flush=True)
                log_change("guards(拦截)", f"画像 NONE 条目 {eid} 被模型改写已保留原样")
            if eid in cur:
                applied.append((eid, cur[eid], "NONE"))
        elif ev == "UPDATE":
            if eid in cur and text and text != cur[eid]:
                applied.append((eid, text, "UPDATE"))
                changes["UPDATE"] += 1
            elif eid in cur:
                applied.append((eid, cur[eid], "NONE"))
        elif ev == "DELETE":
            if eid in cur:
                applied.append((eid, cur[eid], "DELETE"))
                changes["DELETE"] += 1
        elif ev == "ADD":
            if text:
                applied.append((None, text, "ADD"))
                changes["ADD"] += 1
    if not any(changes.values()):
        # 无任何变化：仍记 seen（模型已看过这批新增，下次不重复喂）
        _save_profile_meta(list(seen | set(new_ids)))
        return "画像无变化（模型全部 NONE）"
    # 按原顺序重建：UPDATE 原位替换 / DELETE 移除进回收站 / ADD 追加尾部（新 id 代码分配）
    new_body = []
    for eid, text, ev in applied:
        if ev == "DELETE":
            _trash_profile_line(text, eid)
            continue
        if ev == "ADD":
            new_id = _next_profile_id(used_ids)
            used_ids.add(new_id)
            new_body.append(f"- {text} [{new_id}]")
            continue
        new_body.append(f"- {text} [{eid}]")
    new_profile = ("\n".join(header_lines) + "\n\n" + "\n".join(new_body)).strip()
    # guards 客观性护栏（判断无墙，不变量无口）：禁绝对化是代码拦不是判断
    try:
        from app.memory.guards import banned_hits

        hits = banned_hits(new_profile)
        if hits:
            print(
                f"[guards] 画像含绝对化用语，拒绝写入（命中: {hits}）——保留旧画像，下次记忆变化重提炼",
                flush=True,
            )
            # 治理反馈（2026-08-19）：拒绝进 change_log——前端"最近变更"可见（用户有权知道系统拦了什么）
            log_change("guards(拦截)", f"画像含绝对化用语拒绝写入（命中: {'/'.join(hits)}）")
            return f"画像含绝对化用语已拒绝写入（命中: {'/'.join(hits)}）——下次记忆变化会重提炼"
    except Exception as _e:
        print(f"[memory/store] 静默异常已可见化: {_e}", flush=True)
    if len(new_profile) > PROFILE_LIMIT:
        new_profile = new_profile[:PROFILE_LIMIT] + "\n(已截断)"
    _pf().parent.mkdir(parents=True, exist_ok=True)
    # 内容未变不重写（防 mtime 抖动 + 无意义 IO）
    if (
        _pf().exists()
        and _pf().read_text(encoding="utf-8").strip() == new_profile.strip()
    ):
        return "画像无变化（内容未变，不重写）"
    atomic_write_text(_pf(), new_profile.strip() + "\n")
    # 更新 meta（原子语义：写成功才记 seen；失败下次全量兜底）
    _save_profile_meta(list(seen | set(new_ids)))
    ch = " ".join(f"{k}{v}" for k, v in changes.items() if v)
    return f"画像增量更新（{ch}，{len(new_profile)} 字）"


def forget(content: str, reason: str = "user_request") -> str:
    """删除一条记忆（用户明确要删时）。先确认再删；误删进回收站可恢复。
    reason 四类（借鉴 DeepTutor delete reason，2026-08-19）：contradicted=与新记忆矛盾
    / superseded=被更新记忆取代 / stale=已过时 / low-signal=低价值冗余；用户主动删=user_request。"""
    _ensure_file()
    lines = _mf().read_text(encoding="utf-8").splitlines()
    kept, removed, removed_lines = [], False, []
    _before_n = _count_entries(lines)
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
        trash = _mf().parent / "trash.md"
        trash.parent.mkdir(parents=True, exist_ok=True)
        with trash.open("a", encoding="utf-8") as f:
            f.write(f"\n## {date.today()} forget 回收\n")
            f.write("\n".join(removed_lines) + "\n")
    atomic_write_text(_mf(), "\n".join(kept) + "\n")
    _warn_entry_collapse(_before_n, _count_entries(kept), "forget")
    log_change(
        "forget(DELETE)",
        f"[{reason}] 回收 {len(removed_lines)} 条 | {removed_lines[0][:80] if removed_lines else ''}",
    )
    mark_memory_changed()  # 🔴修复 2026-08-19：删除也是记忆变化，触发画像重提炼（治理操作后画像滞后）
    return "已删除"


async def edit_memory(old: str, new: str) -> str:
    """修正一条记忆：按内容匹配行，替换内容并同步向量（人可审可改，M5）"""
    _ensure_file()
    old = old.strip()
    new = new.strip()
    if not old or not new:
        return "修正内容为空"
    lines = _mf().read_text(encoding="utf-8").splitlines()
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
    atomic_write_text(_mf(), "\n".join(new_lines) + "\n")
    log_change("edit_memory(UPDATE)", f"{old[:40]} → {new[:40]}")
    mark_memory_changed()  # 🔴修复 2026-08-19：修正也是记忆变化，触发画像重提炼（与 forget/update_state 同源）
    return "已修正"


# -*- coding: utf-8 -*-
"""追加：治理 API 底座（2026-08-27 HARNESS-V2：星图第 8 张卡"记忆治理"）"""


def find_entry_by_id(eid: str) -> "MemoryEntry | None":
    """按稳定 id 查记忆条目（治理 API：查看/编辑/删除需要定位到条目）。"""
    for e in read_entries():
        if e.entry_id == eid:
            return e
    return None


async def delete_entry_by_id(eid: str, reason: str = "user_request") -> str:
    """按 id 删除记忆条目（治理 API）：回收站可恢复 + 向量同步删除 + 标记记忆变化。
    reason 四类（同 forget）：contradicted/superseded/stale/low-signal；用户主动删=user_request。"""
    _ensure_file()
    lines = _mf().read_text(encoding="utf-8").splitlines()
    kept, removed_lines = [], []
    _before_n = _count_entries(lines)
    for ln in lines:
        e = MemoryEntry.from_line(ln)
        if e and e.entry_id == eid:
            removed_lines.append(ln)
            try:
                vector.delete(vector.entry_id(e.content))
            except Exception as _e:
                print(f"[memory/store] 静默异常已可见化: {_e}", flush=True)
        else:
            kept.append(ln)
    if not removed_lines:
        return "未找到匹配的记忆条目"
    trash = _mf().parent / "trash.md"
    trash.parent.mkdir(parents=True, exist_ok=True)
    with trash.open("a", encoding="utf-8") as f:
        f.write(f"\n## {date.today()} 治理删除 [{reason}]\n")
        f.write("\n".join(removed_lines) + "\n")
    atomic_write_text(_mf(), "\n".join(kept) + "\n")
    _warn_entry_collapse(_before_n, _count_entries(kept), "治理删除")
    log_change("治理(DELETE)", f"[{reason}] 回收 {len(removed_lines)} 条 | {removed_lines[0][:60]}")
    mark_memory_changed()
    for ln in removed_lines:
        e = MemoryEntry.from_line(ln)
        if e:
            _append_supersede(e.entry_id, e.content, "<已删除>", f"delete:{reason}")
    return "已删除"


async def edit_entry_by_id(eid: str, new_content: str) -> str:
    """按 id 修正记忆条目（治理 API）：替换内容 + 同步向量 + 更新 updated_at。"""
    new_content = new_content.strip()
    if not new_content:
        return "修正内容为空"
    _ensure_file()
    lines = _mf().read_text(encoding="utf-8").splitlines()
    new_lines, edited, old_content = [], False, ""
    for ln in lines:
        e = MemoryEntry.from_line(ln)
        if e and e.entry_id == eid:
            old_content = e.content
            e.content = new_content
            e.updated_at = date.today().isoformat()
            new_lines.append(e.to_line())
            edited = True
            try:
                vector.delete(vector.entry_id(old_content))
                vec = (await vector.aembed([new_content]))[0]
                vector.upsert(vector.entry_id(new_content), new_content, vec)
            except Exception as e_vec:
                log_change(
                    "vector_sync_failed", f"edit_entry_by_id 向量同步失败: {str(e_vec)[:80]}"
                )
                print(f"[vector] 向量同步失败: {e_vec}", flush=True)
        else:
            new_lines.append(ln)
    if not edited:
        return "未找到匹配的记忆条目"
    atomic_write_text(_mf(), "\n".join(new_lines) + "\n")
    log_change("治理(UPDATE)", f"{old_content[:40]} -> {new_content[:40]}")
    mark_memory_changed()
    _append_supersede(eid, old_content, new_content, "user_edit")
    return "已修正"


def entries_structured() -> list:
    """结构化条目（治理 API：星图记忆治理卡展示用）——含 id/内容/类别/重要度/来源/时间/强度。
    最新在前（时间降序，2026-08-27 排序统一；文件追加序=旧在前 → 倒序返回）。"""
    out = []
    for e in read_entries():
        out.append(
            {
                "id": e.entry_id,
                "content": e.content,
                "category": e.category,
                "importance": e.importance,
                "source": e.source,
                "created_at": e.created_at,
                "updated_at": e.updated_at,
                "strength": e.strength,
            }
        )
    return list(reversed(out))


# ============ P0-4 supersede 修订轨迹（2026-08-27，对齐 MemCoE 抗稀释 + DCPM 信念修订链） ============

def _append_supersede(eid: str, old_content: str, new_content: str, reason: str) -> None:
    """记录记忆修订轨迹（append-only）：旧 → 新 + 原因——抗覆盖/稀释（MemCoE 74% vs 51% 实证）、
    治理可追溯（"这条记忆被改过几次、为什么"）。"""
    try:
        _supersede().parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%dT%H:%M")
        block = (
            f"## [{ts}] 修订 #{eid} [{reason}]\n"
            f"旧：{old_content[:150]}\n"
            f"新：{new_content[:150]}\n"
        )
        if _supersede().exists():
            cur = _supersede().read_text(encoding="utf-8")
            lines = cur.split("## [")
            if len(lines) > 500:  # 容量护栏
                cur = "## [" + "## [".join(lines[-250:])
        else:
            cur = ""
        with _supersede().open("a", encoding="utf-8") as f:
            f.write(block + "\n")
    except Exception as _e:
        print(f"[memory/store] 静默异常已可见化: {_e}", flush=True)


def read_supersede(limit: int = 50) -> list[dict]:
    """治理 API：读修订轨迹（最新在前）。"""
    out = []
    if not _supersede().exists():
        return out
    blocks = _supersede().read_text(encoding="utf-8", errors="replace").split("## [")
    for b in blocks[1:][-limit:][::-1]:
        lines = b.splitlines()
        head = lines[0] if lines else ""
        old_l = next((l[2:] for l in lines if l.startswith("旧：")), "")  # "旧：" 是 2 字符
        new_l = next((l[2:] for l in lines if l.startswith("新：")), "")
        if head:
            out.append({"ts": head.split("]")[0], "head": head.split("] ")[-1], "old": old_l, "new": new_l})
    return out

