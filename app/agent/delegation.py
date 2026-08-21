"""M7 多 agent delegation 工具层（L1 子 agent 工具化，2026-08-20 实施）
设计依据：docs/M7-DESIGN.md（官方文档调研 + 4 探针实测锁定）+ L1 蓝图（子 agent 工具化）
- deleg_study(ctx, goal, subtasks)：父 agent 自己拆好子任务传入（拆解归模型，零模板）
- 子 agent = 研究专员，带 3 只读工具（web_search/read_document/search_memory）——
  只读白名单（借鉴 Anthropic sub-agent tools 字段：Read/Grep/Glob 等价物）+ 零写工具（递归风险保持为零）
- 结构化结果：子 agent 输出 JSON {结论, 依据来源, 未查证项, 失败项}（借鉴 OpenAI output_type 思想，
  走项目已验证的 prompt+_extract_json 路径——DeepSeek thinking 不支持 output_type 是踩过的坑）
- 失败标注：工具失败走 errors.py 统一格式，子 agent 必须如实报告（不许假装成功）——
  对应 harness 三刀"失败可见"
- asyncio.gather return_exceptions：单子任务失败不中断整批（实测：异常会中断父 run）
- 进度上报走 ctx.deps 注入的 ProgressTracker（实测：子 agent 事件不透传父流）
- 输出双保险截断；全量走 ToolReturn.metadata（不进 LLM）
"""
import asyncio
import json
import re
import time

from pydantic_ai import Agent, RunContext, ToolReturn, UsageLimits

SUB_PROMPT = (
    "你是「拾光」派出的研究专员。专注完成这一个子任务，输出精炼结论（不超过 200 字），"
    "直接输出内容，不要客套、不要标题堆砌。\n"
    "硬性规则（2026-08-19 补强，借鉴 DeepTutor 调查员）:\n"
    "- 只报告你实际读到的内容：不臆造、不推断超出依据、不替用户下结论。\n"
    "- 引用来源时标注出处（如\"据某文档/某页面\"）；没查证到就明说\"未查证\"，绝不编造来源。\n"
    "- 你是被派出的研究专员，不是用户本人——不要用第一人称叙述用户做过的事（防身份混淆）。\n"
    "- 任务无法完成时明说卡在哪一步、缺什么，不要给空泛结论。\n"
    "\n"
    "工具使用（2026-08-20 L1 工具化，只读白名单——借鉴 Anthropic sub-agent 只读工具）:\n"
    "- 你有 4 个只读工具可用：web_search（联网查英文/国际资料）/ bocha_search（联网查中文/国内资料）/ read_document（读本地文档）/ search_memory（检索用户记忆）。\n"
    "- 需要资料就先查再写结论；工具返回错误时【必须如实报告】到\"失败项\"，不许假装查到或编造内容。\n"
    "- 你只有只读工具——不做任何写入/修改/执行操作。\n"
    "\n"
    "输出格式（结构化，借鉴 OpenAI output_type 思想）:\n"
    "先输出一段结论文本（≤200 字），然后在最后一行输出 JSON：\n"
    "{\"结论\": \"一句话总结\", \"依据来源\": [\"来自哪个工具的哪条证据\"], \"未查证项\": [...], \"失败项\": [\"哪步失败/工具错误原文\"]}\n"
    "JSON 必须合法（不要代码块包裹），没有未查证/失败就写 []。"
)

MAX_SUBTASKS = 5        # 限流：DeepSeek 429 风险
SUB_LIMITS = UsageLimits(request_limit=8, total_tokens_limit=24000)  # L1 工具循环（2026-08-20：2000→12000→24000，实测 15300 仍超——联网研究任务工具返回+thinking 消耗大；request_limit=8 是防失控主护栏）
OUTPUT_LIMIT = 600      # 代码层截断（双保险，prompt 已限 200 字 + JSON）
TTL = 300               # 完成 5 分钟后清理
MAX_KEEP = 20           # 进程内最多保留条数

# 进程内进度表（单 worker uvicorn；deps 每请求独立实例，避免并发互踩）
_store: dict[str, dict] = {}
_lock = asyncio.Lock()


async def _gc():
    """惰性清理：TTL 过期 + 只留最近 MAX_KEEP 条（防内存泄漏）"""
    now = time.time()
    for rid in list(_store.keys()):
        if now - _store[rid]["updated"] > TTL:
            del _store[rid]
    if len(_store) > MAX_KEEP:
        for rid in sorted(_store, key=lambda r: _store[r]["updated"])[
            : len(_store) - MAX_KEEP
        ]:
            del _store[rid]


class ProgressTracker:
    """请求级进度上报器：由 main.py 创建并注入 deps"""

    def __init__(self, run_id: str):
        self.run_id = run_id

    async def register(self, tasks: list[str]):
        async with _lock:
            await _gc()
            _store[self.run_id] = {
                "tasks": {t: "pending" for t in tasks},
                "updated": time.time(),
            }

    async def mark(self, task: str, status: str):
        async with _lock:
            rec = _store.get(self.run_id)
            if rec and task in rec["tasks"]:
                rec["tasks"][task] = status
                rec["updated"] = time.time()

    async def snapshot(self) -> dict | None:
        async with _lock:
            await _gc()
            rec = _store.get(self.run_id)
            return dict(rec) if rec else None


async def _readonly_search(query: str, top_k: int = 3, category: str = "") -> str:
    """只读检索（A2-2 2026-08-20）：子 agent 专用——search_memory 的 _bump=False 变体，
    不 S+1 写回记忆文件（声明"只读"与行为一致；并行子 agent 无并发写竞态）。"""
    from app.memory.store import search_memory

    return await search_memory(query, top_k=top_k, category=category, _bump=False)


def _build_sub_agent() -> Agent:
    """子 agent：3 只读工具白名单（L1 工具化，2026-08-20——借鉴 Anthropic sub-agent tools 字段）。
    只读保证：web_search/read_document/只读检索全零写入零副作用（A2-2 2026-08-20：
    search_memory 本体有 S+1 写回——子 agent 用 _readonly_search 变体，声明与行为一致），
    不会触发 deleg_study 自身（递归风险保持为零）。"""
    from app.agent.model import get_model
    from app.tools.documents import read_document
    from app.tools.web_search import web_search
    from app.tools.bocha_search import bocha_search

    return Agent(
        get_model(),
        system_prompt=SUB_PROMPT,
        tools=[
            web_search,
            bocha_search,
            read_document,
            _readonly_search,
        ],
    )


async def _run_subtask(agent: Agent, task: str) -> str:
    """跑一个子任务：结构化输出兜底——能解析出 JSON 用 JSON，否则保留原文（fail loud 不静默）。"""
    r = await agent.run(task, usage_limits=SUB_LIMITS)
    # A2-5（2026-08-20）：子任务 token 记入统一成本台账（tag=subtask，成本觉察不再低估）
    try:
        from app import observability as obs

        # 注意：AgentRunResult.usage 是属性（非方法——与 stream.usage() 不同，pydantic-ai 2.27）
        obs.token_usage("subtask", r.usage, model="")
    except Exception:
        pass
    raw = (r.output or "").strip()
    # A2-1 加固（2026-08-20）：解析必须在截断之前——先截断会切坏尾部 JSON（超长输出时结构化结果静默丢失）
    data = None
    try:
        m = re.search(r"\{[\s\S]*\}", raw)
        if m:
            data = json.loads(m.group(0))
    except Exception:
        data = None
    out = raw[:OUTPUT_LIMIT]
    if data and isinstance(data, dict) and "结论" in data:
        return out  # 原文已含结构化 JSON，直接返回
    return out


async def deleg_study(
    ctx: RunContext[dict], goal: str, subtasks: list[str]
) -> str:
    """把大目标拆 2-5 个独立子任务并行研究。goal=目标；subtasks=子任务列表（2-5 个）"""
    goal = goal.strip()
    tasks = [s.strip() for s in (subtasks or []) if s.strip()]
    if not goal:
        return "(目标不能为空，请重试)"
    if len(tasks) < 2:
        return "(子任务太少：至少 2 个独立子任务才值得并行，请重新拆解)"
    tasks = tasks[:MAX_SUBTASKS]

    tracker: ProgressTracker | None = None
    try:
        tracker = ctx.deps.get("progress") if isinstance(ctx.deps, dict) else None
    except Exception:
        tracker = None
    if tracker:
        await tracker.register(tasks)

    agents = [_build_sub_agent() for _ in tasks]
    # return_exceptions：单个子任务失败不中断整批（实测：异常会直接中断父 run）
    try:
        results = await asyncio.gather(
            *[_run_subtask(a, t) for a, t in zip(agents, tasks)],
            return_exceptions=True,
        )
    except asyncio.CancelledError:
        # A2-4 兜底（2026-08-20）：外层取消（240s 总护栏）——进度不留永久 pending
        if tracker:
            for name in tasks:
                try:
                    await tracker.mark(name, "failed")
                except Exception:
                    pass
        raise

    parts: list[str] = []
    for name, res in zip(tasks, results):
        if isinstance(res, Exception):
            parts.append(f"[{name}]\n(子任务失败: {type(res).__name__})")
            if tracker:
                await tracker.mark(name, "failed")
        else:
            parts.append(f"[{name}]\n{res}")
            if tracker:
                await tracker.mark(name, "done")

    summary = "\n\n".join(parts)
    return ToolReturn(
        return_value=summary,
        metadata={
            "subtasks": tasks,
            "full_results": [p for p in parts],
        },
    )
