"""M2 学习搭子 agent：画像常驻注入 + JIT 检索 + 模型驱动画像更新
设计依据：docs/M2-DESIGN.md
- instructions 注入"画像摘要"（瘦身）而非全量记忆（上下文工程）
- search_memory 暴露给模型自主触发（Anthropic Memory tool 范式："需要细节先检索"）
- update_profile 内部调 LLM 压缩记忆 → 原地重写 profile（LangMem enable_inserts=False 语义）
"""
import functools

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
    register_analogy_writer,
    register_confusion_writer,
    register_continuation_writer,
    register_glint_writer,
    register_playbook_writer,
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
from app.tools.image_gen import generate_image
from app.tools.sandbox import python_sandbox
from app.tools.web_search import web_search
from app.tools.learning import generate_practice, grade_answer, spacing_signal, mastery_signal, teach_back
from app.tools.plan import plan_advance, plan_create, plan_status, plan_update
from app.agent.verifier import verify_answer
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

# 注入审计常量（2026-08-26 P0-1：静态长度模块级——build_dynamic_context 在 main 流程调用，
# 不再依赖 build_tutor_agent 内部缓存；工具总长保持 0（审计精度可接受，只观察不干预））
_STATIC_LEN = len(STATIC_PROMPT)
_TOOLS_LEN = 0

_tutor: Agent | None = None
_tutor_cache: dict = {}  # 2026-08-28 P0：按用户缓存 agent（画像 per-user，全局单例会导致跨用户串画像）


def _build_model():
    """统一工厂（fallback 链入口，见 app/agent/model.py）"""
    return get_model()


def _log_injection(state_line: str = "", wr_len: int = 0, pair_len: int = 0, total: int = 0,
                   capacity_len: int = 0, tools_len: int = 0, static_len: int = 0, health_len: int = 0):
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
                "health": health_len,
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
    except Exception as _e:
        print(f"[agent/tutor] 静默异常已可见化: {_e}", flush=True)


def build_dynamic_context() -> str:
    """每轮动态上下文（2026-08-26 P0-1 缓存优化，从 system 内 instructions 迁到 user 消息尾部）。

    动机（DeepSeek Context Caching 官方机制 + pydantic-ai 官方文档）：
    - DeepSeek 命中=前缀**完全匹配**缓存单元；system 里任何每轮变化的字节（时间戳/状态）都会
      切断其后全部历史的前缀命中（只能命中被公共前缀检测切出的静态小块）。
    - pydantic-ai 官方：静态 instructions 永远排动态之前（为 prompt caching 设计），但动态块
      仍在 system 消息内，其后内容无法从前缀命中受益。
    - 正解=动态块移到**本轮 user 消息尾部**（本来就会 miss 的新增部分）：system 纯静态 +
      history 完全稳定 → 第二轮起 system+全部历史轮次命中（输入成本 ×3%，97% 折扣）。
    调用方：main.py chat 流程拼进 user_text（落库/请求一致）；本函数保留注入审计（_log_injection）。"""
    from datetime import datetime


    now = datetime.now()
    # P0-3：待审修复提示（模型可见可决策——read_document 查看后自主决定采纳；不注入内容防 token 膨胀）
    try:
        from app.agent.evolution import pending_count

        _pend = pending_count()
    except Exception:
        _pend = 0
    state_line = inject_state()
    if state_line:
        state_line = f"当前状态：{state_line}"
    pair = recent_pair()
    capacity_line = _capacity_hint()
    # 接地纠错循环（2026-08-30 设计 §3.4）：工具健康信号——连续工具失败 ≥2 时出现（≤2 行，
    # 给事实与选项不给指令；成功清零后消失）。走既有 dynamic context 通道，不进系统 prompt（prompt 薄）。
    try:
        from app.agent import error_loop

        health_line = error_loop.health_signal()
    except Exception:
        health_line = ""
    _pend_line = (
        f"\n待审修复：{_pend} 条失败证据（记忆区文件 memory/pending_fixes.md——可 read_document 查看，自主决定是否修订技能/记忆）"
        if _pend
        else ""
    )
    # 2026-08-29 主题演化消费端闭环：活跃主题注入——模型知道用户在学什么，
    # 回答延续主题（不"从零开始"）；异常静默不阻断（注入是增强非主流程）
    try:
        from app.memory.topics_store import view_topics

        _active = [t["name"] for t in view_topics() if t.get("status") == "active"][:8]
        topics_line = (
            f"\n我当前的学习主题：{'、'.join(_active)}"
            if _active
            else "\n我当前的学习主题：（暂未形成——可帮我提炼正在学的东西）"
        )
    except Exception:
        topics_line = ""
    # 长任务 harness（2026-08-30，设计 §4）：有活跃学习计划时注入一行指针——
    # 模型知道「进行到哪了」，细节自调 plan_status（prompt 薄 + 分支 I 指针哲学）。
    # 无计划时空串 → 输出逐字节不变（硬约束，tests/unit/test_plan.py 有断言）；异常静默。
    try:
        from app.tools.plan import active_plan_line

        _pl = active_plan_line()
        plan_line = f"\n进行中计划：{_pl}" if _pl else ""
    except Exception:
        plan_line = ""
    # C-2（2026-08-29）：注入预算显式化——超档位上限逐块裁减（低优先级先裁：
    # 经验段落 → 状态行 → 主题行；时间戳/待审修复为信息锚点不裁），哨兵仍记录
    from app.agent.model import model_tier

    _budget = model_tier()["inject_budget_chars"]
    text = f"""现在是 {now.strftime('%Y-%m-%d %H:%M')}（周{'一二三四五六日'[now.weekday()]}）。
{_pend_line}
{topics_line}
{plan_line}
{health_line}
{capacity_line}

我的经验（失败教训按它改进，成功讲法可参考不必套用）：
{pair}

{state_line}"""
    if len(text) > _budget:
        # ① 裁经验段落（占最大头）
        if pair and len(text) > _budget:
            text = text.replace(f"\n\n我的经验（失败教训按它改进，成功讲法可参考不必套用）：\n{pair}", "")
        # ② 裁状态行
        if state_line and len(text) > _budget:
            text = text.replace(f"\n\n{state_line}", "")
        # ③ 裁主题行
        if topics_line and len(text) > _budget:
            text = text.replace(f"{topics_line}\n", "")
        print(
            f"[inject-budget] 注入 {len(text)} 字 > 档位上限 {_budget}，已裁减（经验→状态→主题）",
            flush=True,
        )
    _log_injection(
        state_line=state_line,
        wr_len=len(WRITE_RULES),
        pair_len=len(pair),
        total=len(text) + _STATIC_LEN,
        capacity_len=len(capacity_line or ""),
        health_len=len(health_line or ""),
        tools_len=_TOOLS_LEN,
        static_len=_STATIC_LEN,
    )
    return text


async def _summarize_to_profile(memory_text: str) -> str:
    """画像维护器（2026-08-21 四操作增量 diff——对齐 Mem0 DEFAULT_UPDATE_MEMORY_PROMPT）：
    输入 = 【当前画像】+【新增记忆】→ 输出四操作 JSON（ADD/UPDATE/DELETE/NONE 逐条决策），
    不再输出"更新后的完整画像"（全量重写是画像漂移的机制性根因）；
    store.py update_profile 按 event 应用 diff（NONE 原样保留，防漂移）。"""
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
        # 2026-08-21 修复：.format 会解析 prompt 里 JSON 示例花括号（{"topics":[...]} → KeyError 静默死亡 2 天）
        # 改用 .replace 只替换 {existing} 占位——代码不依赖 prompt 内容约定（对齐 Mem0 官方 f-string 转义精神，更不易错）
        system_prompt=extractor_prompt("topics").replace("{existing}", existing_line),
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
        status = str(t.get("status", "")).strip().lower()
        if not name or intent not in ("learning", "new", "farewell", "mention"):
            continue
        # status 白名单校验（2026-08-21 状态细粒度归模型）：乱值丢弃，仅三态落盘
        if status and status not in ("done", "stuck", "shelved"):
            status = ""
        valid.append({"name": name, "intent": intent, "confidence": confidence, "status": status})
    return {"topics": valid} if valid else None


async def _extract_playbook(dialogue: str) -> list | None:
    """ACE Reflector 第 7 路（2026-08-30，设计 docs/2026-08-30-ACE-PLAYBOOK-DESIGN.md §3）：
    输入=对话 + 代码侧接地信号摘要（error_loop 序列/verify 结果/显式反馈/被检索技能——
    信号由 evolution.session_signal_summary 采集，模型只消费不生产）；
    输出=delta entries（add/revise——bump 计数由代码按接地信号推进，prompt 明确禁模型评计数）。
    解析防御归 evolution.parse_delta_entries（乱 JSON/乱值丢弃不崩，与其他 _extract_* 同模式）。"""
    from app.agent.evolution import parse_delta_entries, session_signal_summary

    signals = session_signal_summary()
    extractor = Agent(
        _build_model(),
        # 同 topics 教训（2026-08-21）：.format 会吞 JSON 示例花括号——只用 .replace 占位替换
        system_prompt=extractor_prompt("playbook").replace("{signals}", signals),
    )
    r = await extractor.run(dialogue[:8000])
    return parse_delta_entries(r.output or "")


async def _verify_tracked(task: str, answer: str, mode: str = "teach") -> str:
    """verify_answer 接地包装（2026-08-30）：评级落会话信号注册表（ACE 计数接地源之一）。
    consistent/inconsistent 才会推进被检索技能计数；partial/unknown 不计（信号不纯粹）。"""
    import re as _re

    from app.agent.evolution import on_verify_result

    r = await verify_answer(task, answer, mode)
    try:
        m = _re.search(r"验证结果：(\w+)", r or "")
        if m:
            on_verify_result(m.group(1))
    except Exception as _e:
        print(f"[agent/tutor] verify 评级登记失败（静默）: {_e}", flush=True)
    return r


# pydantic-ai 工具名取自 __name__——保留 verify_answer 的名字与 docstring（模型可见契约不变）
_verify_tracked = functools.wraps(verify_answer)(_verify_tracked)


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


def _error_tracked(fn):
    """接地纠错循环挂钩（2026-08-30，设计 docs/2026-08-30-ERROR-LOOP-DESIGN.md §3.1）：
    捕获工具异常与 "(错误|" 前缀返回串 → 记 error_loop 台账后【原样放行】（判断无墙：
    模型可见性不变，台账是 harness 的账本）。成功结果逐字节不变（零影响是硬约束，有单测）。
    冻结期（n=5 硬停止后一轮）：不执行工具，直接返回系统标识消息（HARD_STOP_MESSAGE）。
    嵌套顺序：_error_tracked 必须包在【最内层】（_cap 之外）——台账要看未截断原文
    （compressed ≤300 字取自原始错误串）；虽然 "(错误|domain|code|" 在头部、_cap 头尾
    保留截断也保得住 code，但内层不依赖 _cap 行为更稳；成功结果经内层原样穿透后由
    _cap 截断，与既有行为完全一致。"""
    import functools

    @functools.wraps(fn)
    async def wrapper(*a, **kw):
        from app.agent import error_loop

        if error_loop.is_frozen():
            return error_loop.HARD_STOP_MESSAGE
        name = getattr(fn, "__name__", "tool")
        try:
            r = fn(*a, **kw)
            if hasattr(r, "__await__"):
                r = await r
        except Exception as e:
            # 异常 = 未走 errors.py 格式化的失败：合成标准格式记账（code=UNKNOWN 保守类）
            error_loop.record_error(name, f"(错误|{name}|UNKNOWN|{type(e).__name__}: {e})")
            raise
        if error_loop.is_error_result(r):
            error_loop.record_error(name, r)
        else:
            error_loop.record_success(name)
        return r

    return wrapper


def _capped(limit: int):
    """工具结果压缩器（2026-08-27 HARNESS-V2，参考 DeepTutor 工具结果压缩器思想）：
    verbose 工具返回超限 → 头尾保留 + 截断提示（确定性，零额外 LLM 成本）。
    目的=防上下文爆炸（工具原始结果直接进历史是长对话死亡主因）；截断提示引导模型分段获取。"""

    def deco(fn):
        import functools

        @functools.wraps(fn)
        async def wrapper(*a, **kw):
            r = fn(*a, **kw)
            if hasattr(r, "__await__"):
                r = await r
            if isinstance(r, str) and len(r) > limit:
                head_len = max(1, int(limit * 0.6))
                tail_len = max(1, int(limit * 0.3))
                return (
                    f"{r[:head_len]}\n\n…(结果过长已截断 {len(r)}→{limit} 字符；"
                    f"需要完整内容可要求分段/说明要看哪部分)…\n\n{r[-tail_len:]}"
                )
            return r

        return wrapper

    return deco


def build_tutor_agent(uid: str | None = None) -> Agent:
    """构建学习搭子 agent。uid=None → 单例 legacy（未登录场景）；
    uid 指定 → 按用户缓存（画像/记忆 per-user，agent 实例不可跨用户共享）"""
    if uid is None:
        global _tutor
        if _tutor is not None:
            return _tutor
    else:
        if uid in _tutor_cache:
            return _tutor_cache[uid]

    register_profile_writer(_summarize_to_profile)
    register_confusion_writer(_extract_confusion)
    register_glint_writer(_extract_glint)
    register_relation_writer(_extract_relation)
    register_continuation_writer(_extract_continuation)
    register_teaching_writer(_extract_teaching)
    register_topics_writer(_extract_topics)
    register_playbook_writer(_extract_playbook)  # ACE Reflector 第 7 路（2026-08-30）
    from app.agent.analogy import extract_analogy

    register_analogy_writer(extract_analogy)  # 跨域类比第 8 路（2026-08-31，路线图 v3.0 §4）
    model = _build_model()

    # D1 事件兜底（v0.2，2026-08-13）：remember 只标记"本会话记忆变化"，
    # 提炼由会话收尾钩子（main.py）触发——触发时机归机器（事件），提炼内容归模型（LLM 压缩）。
    # 粒度 = 会话结束 + 本会话有记忆变化（不是每次 remember 立即提炼，成本可控）。
    async def _remember_mark(note, source="user", importance=5, category="note"):
        r = await remember(note, source, importance, category)
        return r  # mark_memory_changed 已在 store.remember 写入成功后置位

    # 工具列表（27 个，2026-08-30：+4 长任务 harness plan_*；verbose 工具挂 capped 压缩器）
    # C-2（2026-08-29）：search_memory 默认 top_k 按模型档位（store 内部解析 config.model_tier，
    # 模型显式传 top_k 仍可覆盖——判断归模型，上限归 harness）。不能用 partial 包装——
    # pydantic-ai 工具内省要求原函数签名（partial 缺 takes_ctx 属性，实测 build 崩）。
    # 接地纠错循环（2026-08-30）：全部工具套 _error_tracked（最内层，理由见包装器 docstring）——
    # 台账/循环检测/预算升级归 error_loop；verbose 工具外层再叠 _cap 压缩器（既有行为不变）
    _cap = _capped
    _et = _error_tracked
    tool_funcs = [
        _et(_remember_mark),
        _et(search_memory),
        _et(forget),
        _et(update_state),
        _cap(4000)(_et(web_search)),
        _cap(4000)(_et(bocha_search)),
        _et(python_sandbox),  # 内部已有 4000 上限
        _et(ocr_image),
        _et(analyze_image),
        _et(generate_image),
        _cap(3000)(_et(read_document)),
        _cap(3000)(_et(kb_search)),
        _et(kb_ingest),
        _et(manage_wakeup),
        _et(log_learning),
        _et(deleg_study),
        _et(reflect_teaching),
        _et(save_skill),
        _et(search_skills),
        # 深度学习工具面（2026-08-27 HARNESS-V2：机制在 harness，模型自主决定何时用）
        _et(generate_practice),
        _et(grade_answer),
        _et(spacing_signal),
        _et(mastery_signal),
        _et(teach_back),  # 反向教学（2026-08-30）：AI 当学生用户当老师，学完主题后/复测前/用户主动
        # 长任务 harness 双模式（2026-08-30，docs/2026-08-30-LONGTASK-HARNESS-DESIGN.md）：
        # 学习计划=长任务；passes 只能经 plan_advance 且证据代码核验（不变量无口）
        _et(plan_create),
        _et(plan_status),
        _et(plan_advance),
        _et(plan_update),
        # 验证工具（2026-08-27 做精：把关轴工具化——模型重要输出后可自查，控制流归模型）
        # 2026-08-30 ACE：套 _verify_tracked——评级落会话信号注册表（playbook 计数接地源）
        _et(_verify_tracked),
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
        # 2026-08-26 P0-1 缓存优化：动态上下文迁到 user 消息尾部（main.py 拼 user_text），
        # system 保持纯静态（字节稳定 → DeepSeek Context Caching 前缀命中覆盖全部历史）。
        # 官方语义：返回空串 = 不添加该条 instruction（pydantic-ai 文档明确支持）。
        # 保留装饰器结构作为通道占位（防遗漏调用点），内容由 build_dynamic_context() 承担。
        return ""

    if uid is None:
        _tutor = agent
    else:
        _tutor_cache[uid] = agent
    return agent
