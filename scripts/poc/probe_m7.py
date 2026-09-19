"""M7 关键未知项实测：①父流能否看到子 agent 事件 ②子 agent 异常是否中断父 run ③ToolReturn metadata API
决定进度卡方案与失败处理设计，不凭文档结论直接信，先实测。
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from envutil import load_env

env = load_env()

from pydantic_ai import Agent, ToolReturn
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider


def make_agent(system_prompt: str, tools=None) -> Agent:
    model = OpenAIChatModel(
        env["DEEPSEEK_MODEL"],
        provider=OpenAIProvider(base_url=env["DEEPSEEK_BASE_URL"], api_key=env["DEEPSEEK_API_KEY"]),
    )
    return Agent(model, system_prompt=system_prompt, tools=tools or [])


async def probe1_parent_stream_visibility():
    """父 agent run_stream_events：子 agent 内部事件是否可见？"""
    print("=== 探测1: 父流能否看到子 agent 事件 ===")
    sub = make_agent("你是子专家，一句话回答。")

    async def deleg(topic: str) -> str:
        r = await sub.run(f"关于{topic}的一句话结论")
        return r.output.strip()

    parent = make_agent("你是主管，用 deleg 工具并行研究。", tools=[deleg])
    seen = {}
    async with parent.run_stream_events("研究一下过拟合") as stream:
        async for ev in stream:
            et = type(ev).__name__
            seen[et] = seen.get(et, 0) + 1
    print("父流事件分布:", seen)
    has_inner = any("Part" in k and "Function" not in k for k in seen)
    print("结论: 父流是否含子 agent 内部 Part 事件 →", has_inner)


async def probe2_subagent_exception():
    """子 agent 抛异常：父 run 是否中断？"""
    print("\n=== 探测2: 子 agent 异常传播 ===")

    async def bad(topic: str) -> str:
        raise RuntimeError("子 agent 炸了")

    parent = make_agent("你是主管，用 bad 工具。", tools=[bad])
    try:
        r = await parent.run("调用一下 bad 工具")
        print("父 run 完成:", r.output.strip()[:60])
        print("结论: 子 agent 异常没有中断父 run")
    except Exception as e:
        print(f"父 run 中断! {type(e).__name__}: {str(e)[:100]}")
        print("结论: 子 agent 异常直接中断父 run → 必须 return_exceptions 兜底")


async def probe3_tool_return_metadata():
    """ToolReturn(return_value, metadata) API 是否存在"""
    print("\n=== 探测3: ToolReturn metadata API ===")
    try:
        tr = ToolReturn(tool_call_id="x", return_value="摘要", metadata={"full": ["a", "b"]})
        print("ToolReturn OK:", tr.return_value, "| metadata:", tr.metadata)
    except Exception as e:
        print(f"ToolReturn 失败: {type(e).__name__}: {str(e)[:80]}")


async def main():
    await probe1_parent_stream_visibility()
    await probe2_subagent_exception()
    await probe3_tool_return_metadata()


if __name__ == "__main__":
    asyncio.run(main())
