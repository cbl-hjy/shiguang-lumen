"""M7 上报通道实测：①tools=[...] 传普通 async 函数 + RunContext 注解能否注入 ctx.deps（拿 run_id）
②ContextVar 在父 agent 工具内是否可读（备用方案）——决定进度卡架构
"""
import asyncio
import contextvars
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from envutil import load_env

env = load_env()

from pydantic_ai import Agent, RunContext
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

# ContextVar 备用方案
_run_var: contextvars.ContextVar[str] = contextvars.ContextVar("run_id", default="none")


def make_agent(system_prompt: str, tools=None) -> Agent:
    model = OpenAIChatModel(
        env["DEEPSEEK_MODEL"],
        provider=OpenAIProvider(base_url=env["DEEPSEEK_BASE_URL"], api_key=env["DEEPSEEK_API_KEY"]),
    )
    return Agent(model, system_prompt=system_prompt, tools=tools or [])


async def probe_ctx():
    """方案A: RunContext 注解注入"""
    print("=== 方案A: RunContext 注入 ===")

    async def deleg(ctx: RunContext[dict], topic: str) -> str:
        return f"run_id={ctx.deps.get('run_id')} | topic={topic}"

    parent = make_agent("你是主管，用 deleg 工具。", tools=[deleg])
    r = await parent.run("调用 deleg 工具研究过拟合", deps={"run_id": "RUN_TEST_001"})
    print("父输出:", r.output.strip()[:120])
    print("结论: RunContext 注入" + ("成功（官方方案可用）" if "RUN_TEST_001" in r.output else "失败"))


async def probe_cv():
    """方案B: ContextVar 传递"""
    print("\n=== 方案B: ContextVar ===")

    async def deleg2(topic: str) -> str:
        return f"cv={_run_var.get()} | topic={topic}"

    parent = make_agent("你是主管，用 deleg2 工具。", tools=[deleg2])

    async def run_with_cv():
        token = _run_var.set("CV_RUN_999")
        try:
            r = await parent.run("调用 deleg2 工具研究过拟合")
            return r.output
        finally:
            _run_var.reset(token)

    out = await run_with_cv()
    print("父输出:", out.strip()[:120])
    print("结论: ContextVar" + ("成功（备用方案可行）" if "CV_RUN_999" in out else "失败"))


async def main():
    await probe_ctx()
    await probe_cv()


if __name__ == "__main__":
    asyncio.run(main())
