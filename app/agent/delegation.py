"""M7 多 agent delegation 工具层
设计依据：docs/M7-DESIGN.md（官方文档调研 + 4 探针实测锁定）
- deleg_study(ctx, goal, subtasks)：父 agent 自己拆好子任务传入（拆解归模型，零模板）
- 子 agent 纯文本研究专员（无工具=零递归风险），fresh context
- asyncio.gather return_exceptions：单子任务失败不中断整批（实测：异常会中断父 run）
- 进度上报走 ctx.deps 注入的 ProgressTracker（实测：子 agent 事件不透传父流）
- 输出双保险截断；全量走 ToolReturn.metadata（不进 LLM）
"""
import asyncio
import time
from typing import Any

from pydantic_ai import Agent, RunContext, ToolReturn, UsageLimits

from app.config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL

SUB_PROMPT = (
    "你是「拾光」派出的研究专员。专注完成这一个子任务，输出精炼结论（不超过 200 字），"
    "直接输出内容，不要客套、不要标题堆砌。"
)

MAX_SUBTASKS = 5        # 限流：DeepSeek 429 风险
SUB_LIMITS = UsageLimits(request_limit=5, total_tokens_limit=2000)  # 实测单任务 ~736 token（含 reasoning），2000 留余量
OUTPUT_LIMIT = 500      # 代码层截断（双保险，prompt 已限 200 字）
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


def _build_sub_agent() -> Agent:
    from app.agent.model import get_model

    return Agent(get_model(), system_prompt=SUB_PROMPT)


async def _run_subtask(agent: Agent, task: str) -> str:
    r = await agent.run(task, usage_limits=SUB_LIMITS)
    return r.output.strip()[:OUTPUT_LIMIT]


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
    results = await asyncio.gather(
        *[_run_subtask(a, t) for a, t in zip(agents, tasks)],
        return_exceptions=True,
    )

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
