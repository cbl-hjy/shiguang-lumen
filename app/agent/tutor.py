"""M2 学习搭子 agent：画像常驻注入 + JIT 检索 + 模型驱动画像更新
设计依据：docs/M2-DESIGN.md
- instructions 注入"画像摘要"（瘦身）而非全量记忆（上下文工程）
- search_memory 暴露给模型自主触发（Anthropic Memory tool 范式："需要细节先检索"）
- update_profile 内部调 LLM 压缩记忆 → 原地重写 profile（LangMem enable_inserts=False 语义）
"""
from pydantic_ai import Agent

from app.agent.model import get_model
from app.agent.delegation import deleg_study
from app.agent.evolution import (
    recent_pair,
    reflect_teaching,
    save_skill,
    search_skills,
)
from app.db.wakeups import log_learning, manage_wakeup
from app.memory.schema import WRITE_RULES

# 注入预算哨兵（2026-08-19 修正：3000 是拍脑袋数字，无依据——DeepTutor 实测 5232 字/窗口 5%
# 照样健康；我们 4004 字/128K 窗口 ~2%。改为"比例式 + 趋势"：绝对字数无意义，占比才有意义。
# system+tools > 窗口 5% 才提示膨胀（参考 DeepTutor context_budget 的相对预算哲学）。
# 依据：DeepSeek 128K token 窗口，中文约 0.6-0.7 token/字 → 128000 token ≈ 18-21 万字；
# 5% ≈ 9000-10500 字。哨兵只观察不干预（测量消费者=自己），趋势看 injection_log 比例字段。
BUDGET_WARN_RATIO = 0.05  # system+memory 注入 + tools 占窗口比例阈值
BUDGET_WARN_CHARS = 9000  # 5% 窗口 ≈ 9000 字（中文 0.6-0.7 token/字，128K×0.05≈6400 token）
from app.memory.store import (
    forget,
    register_confusion_writer,
    register_continuation_writer,
    register_glint_writer,
    register_profile_writer,
    register_relation_writer,
    register_teaching_writer,
    register_topics_writer,
    remember,
    search_memory,
)
from app.tools.documents import read_document
from app.tools.kb import kb_ingest, kb_search
from app.tools.ocr import ocr_image
from app.tools.vision import analyze_image
from app.tools.sandbox import python_sandbox
from app.tools.web_search import web_search
from app.tools.bocha_search import bocha_search
from app.memory.state import inject_state, update_state
from app.memory import store

MINIMAL_PROMPT = "你是我的成长搭子。自然回应我，像朋友一样，不客套。"

# 静态注入前缀（2026-08-19，借鉴 DeepTutor ChatPromptAssembler 的前缀稳定设计 + PromptManager 外置）：
# 内容外置在 app/prompts/static_prompt.yaml（可 git diff/审计/独立修改），代码只读不写死。
# 以 Agent(instructions=静态字符串) 传入 → dynamic=False → Pydantic AI 自动排序到最前，
# 字节完全稳定 → DeepSeek Context Caching 前缀命中 + 注意力不被动态块干扰（lost-in-middle 缓解）。
# 动态部分（时间戳/容量/经验对/状态轮）留在 @agent.instructions 装饰器（dynamic=True 自动排后）。
from app.prompts.loader import extractor_prompt, load_static_prompt

STATIC_PROMPT = load_static_prompt()

_tutor: Agent | None = None


def _build_model():
    """统一工厂（fallback 链入口，见 app/agent/model.py）"""
    return get_model()


def _log_injection(state_line: str = "", wr_len: int = 0, pair_len: int = 0, total: int = 0,
                   capacity_len: int = 0, tools_len: int = 0, static_len: int = 0):
    """注入日志（append-only jsonl，2026-08-17，参考 DeepSeek Harness append-only session log）：
    记录每轮实际注入的块长度（静态前缀/状态行/WRITE_RULES/经验/容量提示/工具描述/总量）——
    审计"记忆怎么影响回答"、量化注入预算（总长趋势）。增强非必需：失败静默。
    tools_len/static_len 在 build_tutor_agent 时缓存传入（静态不变，不每轮重复统计）。"""
    try:
        import json
        from datetime import datetime

        from app.config import DATA_DIR

        rec = {
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "blocks": {
                "static": static_len,
                "state": len(state_line or ""),
                "write_rules": wr_len,
                "recent_pair": pair_len,
                "capacity": capacity_len,
                "tools": tools_len,
                "total": total + tools_len,
            },
        }
        # 预算哨兵（2026-08-19，借鉴 DeepTutor context_budget）：只观察不干预——
        # 超阈值打一条警告（让膨胀可见，"测量消费者=自己"），不改模型行为
        if total + tools_len > BUDGET_WARN_CHARS:
            print(
                f"[budget] ⚠️ 注入预算超阈值：system+memory {total}字 + tools {tools_len}字 "
                f"> {BUDGET_WARN_CHARS}——建议检查注入膨胀（分层治理的触发信号）",
                flush=True,
            )
        f = DATA_DIR / "data" / "injection_log.jsonl"
        f.parent.mkdir(parents=True, exist_ok=True)  # 目录可能不存在（隔离环境/首次），必须建（2026-08-18 集成测试发现）
        with open(f, "a", encoding="utf-8") as fp:
            fp.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


async def _summarize_to_profile(memory_text: str) -> str:
    """画像生成器（2026-08-19 增量模式）：输入 = 【当前画像】+【新增记忆】→ 输出更新后的完整画像。
    增量合并（meta-id-diff 前置）：模型看到已有画像（保全貌）+ 新增片段（防遗忘），
    输出合并更新后的画像——不再是"从零压缩全部记忆"（记忆量增长不炸）。
    对冲约束（2026-08-19 借鉴 DeepTutor L3）：规律性断言必须带证据密度、禁无证据绝对化。"""
    summarizer = Agent(
        _build_model(),
        system_prompt=extractor_prompt("profile"),
    )
    r = await summarizer.run(memory_text)
    return r.output.strip()


async def _extract_confusion(dialogue: str) -> str | None:
    """会话核心困惑提炼（方案 C，2026-08-15，五判据驱动）。
    输入=本会话对话文本；输出=一句话困惑描述（用户视角的开放问题），无困惑返回 None。
    记困惑不记情绪：认知卡点（怀疑方向/该不该/怎么选）才返回；情绪/纯事实/一次性能答的疑问不返回。"""
    extractor = Agent(
        _build_model(),
        system_prompt=extractor_prompt("confusion"),
    )
    r = await extractor.run(dialogue[:8000])
    out = (r.output or "").strip()
    if not out or out == "无" or "无。" in out[:4]:
        return None
    return out[:120]


async def _extract_glint(dialogue: str) -> str | None:
    """闪光提炼（2026-08-20，拾光=拾到我们没发现的闪光，三判据驱动）。
    输入=本会话对话文本；输出=闪光描述（用户没发现的模式/潜力/洞见），无闪光返回 None。
    判别边界：闪光≠夸奖（必须有发现的信息）；闪光≠困惑（困惑向上求助，闪光向下看见）。"""
    extractor = Agent(
        _build_model(),
        system_prompt=extractor_prompt("glint"),
    )
    r = await extractor.run(dialogue[:8000])
    out = (r.output or "").strip()
    if not out or out == "无" or "无。" in out[:4]:
        return None
    # 清理模型可能带的前缀（'闪光描述：'/'类型：xx\n'）——只保留描述本体
    out = out.replace("闪光描述：", "").replace("闪光描述:", "").replace("闪光：", "").strip()
    # 输出格式：第一行『类型：…』，第二行描述——只取描述（第二行起）
    lines = [l.strip() for l in out.split("\n") if l.strip()]
    if len(lines) >= 2:
        return " · ".join(lines[1:])[:120]
    return out[:120]


async def _extract_relation(dialogue: str) -> dict | None:
    """会话收尾关系轨提炼（阶段1，2026-08-17，A 关系轨）。
    输入=本会话对话文本；输出={depth, last_topic, tone}；无实质关系信息返回 None（NOOP 判别归模型）。
    只提炼"我们之间"的慢变状态（聊到什么深度/核心话题/相处基调），不提炼用户个人事实（那是记忆的活）。"""
    extractor = Agent(
        _build_model(),
        system_prompt=extractor_prompt("relation"),
    )
    r = await extractor.run(dialogue[:8000])
    out = (r.output or "").strip()
    if not out or out == "无" or "无。" in out[:4]:
        return None
    import json
    import re
    m = re.search(r"\{.*\}", out, re.DOTALL)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except Exception:
        return None
    rel = {k: str(v).strip() for k, v in data.items() if k in ("depth", "last_topic", "tone") and str(v).strip()}
    return rel if rel else None


async def _extract_continuation(dialogue: str) -> str | None:
    """会话收尾任务轨续接点提炼（阶段2，2026-08-17）。
    输入=本会话对话文本；输出="下次从哪继续"（一句话，学习/讨论线程的未完成点）；
    无明确未完成线程返回 None（NOOP 判别归模型）。"""
    extractor = Agent(
        _build_model(),
        system_prompt=extractor_prompt("continuation"),
    )
    r = await extractor.run(dialogue[:8000])
    out = (r.output or "").strip()
    if not out or out == "无" or "无。" in out[:4]:
        return None
    return out[:120]


async def _extract_teaching(dialogue: str) -> dict | None:
    """教学经验提炼（第四路，2026-08-19 自主反思——"不能等用户喂"）。
    输入=本会话对话文本；输出={reflection, skill_desc, skill_method}：
    reflection=这次讲解/沟通暴露了哪个坑（可改进项，复盘价值）；
    skill_desc=这次什么讲法有效（何时用）；skill_method=具体怎么讲（怎么讲）——两维度分开（P1 复盘缺陷2）。
    防噪音（闲聊/纯执行/已闭环不写）：①有真实教学互动 ②暴露了问题或有有效讲法
    ③内容具体可操作（泛泛而谈不写）。重复检测归 harness（向量查重），不在此列（模型看不到库，判据是空转——P1 复盘缺陷4）。
    都没有 → 输出『无』。JSON 输出：{"reflection":"…","skill_desc":"…","skill_method":"…"}，各自可为空。"""
    extractor = Agent(
        _build_model(),
        system_prompt=extractor_prompt("teaching"),
    )
    r = await extractor.run(dialogue[:8000])
    out = (r.output or "").strip()
    if not out or out == "无" or "无。" in out[:4]:
        return None
    import json as _json
    import re as _re

    m = _re.search(r"\{.*\}", out, _re.DOTALL)
    if not m:
        return None
    try:
        data = _json.loads(m.group(0))
    except Exception:
        return None
    result = {
        "reflection": str(data.get("reflection", "")).strip(),
        "skill_desc": str(data.get("skill_desc", "")).strip(),
        "skill_method": str(data.get("skill_method", "")).strip(),
    }
    if not result["reflection"] and not result["skill_desc"] and not result["skill_method"]:
        return None
    return result


async def _extract_topics(dialogue: str) -> dict | None:
    """主题提炼（第六路，2026-08-19 主题动态演化 P2）——意图驱动，源头归并。
    输入=对话文本 + 已有主题列表（name+aliases，供模型源头归并）；
    模型两环节一次完成：①看对话语义识别主题（"那个 L2 惩罚权重的东西"→"正则化"）
    ②看已有列表归并（能对上→输出已有名；对不上→新主题名）。
    输出=[{name, intent, confidence}]，intent∈{learning,new,farewell,mention}——
    "提到≠想学"：只提及不学 → mention（harness 不动，防误激活）。
    无主题 → 输出『无』。"""
    try:
        from app.memory.topics_store import view_topics
        existing = view_topics()
    except Exception:
        existing = []
    existing_line = "；".join(
        f"{t['name']}(别名:{'/'.join(t.get('aliases') or []) or '无'})" for t in existing[:20]
    ) or "（暂无）"
    extractor = Agent(
        _build_model(),
        system_prompt=extractor_prompt("topics").format(existing=existing_line),
    )
    r = await extractor.run(dialogue[:8000])
    out = (r.output or "").strip()
    if not out or out == "无" or "无。" in out[:4]:
        return None
    import json as _json
    import re as _re

    m = _re.search(r"\{.*\}", out, _re.DOTALL)
    if not m:
        return None
    try:
        data = _json.loads(m.group(0))
    except Exception:
        return None
    topics = data.get("topics") or []
    valid = []
    for t in topics:
        name = str(t.get("name", "")).strip()
        intent = str(t.get("intent", "")).strip().lower()
        confidence = str(t.get("confidence", "")).strip().lower()
        if not name or intent not in ("learning", "new", "farewell", "mention"):
            continue
        valid.append({"name": name, "intent": intent, "confidence": confidence})
    return {"topics": valid} if valid else None


def _capacity_hint() -> str:
    """容量软阈值提示（治理权#4，2026-08-18）：记忆 ≥ MEMORY_SOFT_LIMIT 时返回整理提示，
    否则空串。提供信息不替模型决定（判断无墙）；异常静默（提示缺失不影响对话）。"""
    from app.memory.schema import MEMORY_SOFT_LIMIT

    try:
        n = len(store.read_entries())
        if n < MEMORY_SOFT_LIMIT:
            return ""
        return (
            f"记忆已达 {n}/{MEMORY_SOFT_LIMIT} 条软阈值——先整理再新增："
            f"用 search_memory 找可合并/过时/低价值的条目，edit_memory 合并或 forget 删除（删前确认）。"
        )
    except Exception:
        return ""


def build_tutor_agent() -> Agent:
    global _tutor
    if _tutor is not None:
        return _tutor

    register_profile_writer(_summarize_to_profile)
    register_confusion_writer(_extract_confusion)
    register_glint_writer(_extract_glint)
    register_relation_writer(_extract_relation)
    register_continuation_writer(_extract_continuation)
    register_teaching_writer(_extract_teaching)
    register_topics_writer(_extract_topics)
    model = _build_model()

    # D1 事件兜底（v0.2，2026-08-13）：remember 只标记"本会话记忆变化"，
    # 提炼由会话收尾钩子（main.py）触发——触发时机归机器（事件），提炼内容归模型（LLM 压缩）。
    # 粒度 = 会话结束 + 本会话有记忆变化（不是每次 remember 立即提炼，成本可控）。
    async def _remember_mark(note, source="user", importance=5, category="note"):
        r = await remember(note, source, importance, category)
        return r  # mark_memory_changed 已在 store.remember 写入成功后置位

    # 工具列表（16 个，2026-08-19 审计 ~759 tok）：顶层复用，供 Agent 装配 + 预算长度统计
    tool_funcs = [
        _remember_mark,
        search_memory,
        forget,
        update_state,
        web_search,
        bocha_search,
        python_sandbox,
        ocr_image,
        analyze_image,
        read_document,
        kb_search,
        kb_ingest,
        manage_wakeup,
        log_learning,
        deleg_study,
        reflect_teaching,
        save_skill,
        search_skills,
    ]

    agent = Agent(
        model,
        system_prompt=MINIMAL_PROMPT,
        instructions=STATIC_PROMPT,  # 静态前缀（dynamic=False，字节稳定——缓存/注意力双收益，2026-08-19）
        tools=tool_funcs,
    )
    # 工具描述长度缓存（context_budget，2026-08-19）：工具列表静态，build 时算一次——
    # 近似 schema 长度（函数名+docstring），供注入预算记账/哨兵用
    _tools_len = sum(len(getattr(f, "__name__", "")) + len(getattr(f, "__doc__", "") or "") for f in tool_funcs)
    _static_len = len(STATIC_PROMPT)

    @agent.instructions
    def inject_context() -> str:
        from datetime import datetime

        from app.memory.state import inject_state

        now = datetime.now()
        state_line = inject_state()
        if state_line:
            state_line = f"当前状态：{state_line}"
        pair = recent_pair()
        capacity_line = _capacity_hint()
        # 动态部分（2026-08-19 起）：只含每轮变化的内容——静态前缀已固化在
        # Agent(instructions=STATIC_PROMPT)，Pydantic AI 自动排静态在前（前缀稳定）
        text = f"""现在是 {now.strftime('%Y-%m-%d %H:%M')}（周{'一二三四五六日'[now.weekday()]}）。

{capacity_line}

我的经验（失败教训按它改进，成功讲法可参考不必套用）：
{pair}

{state_line}"""
        _log_injection(
            state_line=state_line,
            wr_len=len(WRITE_RULES),
            pair_len=len(pair),
            total=len(text) + _static_len,
            capacity_len=len(capacity_line or ""),
            tools_len=_tools_len,
            static_len=_static_len,
        )
        return text

    _tutor = agent
    return _tutor
