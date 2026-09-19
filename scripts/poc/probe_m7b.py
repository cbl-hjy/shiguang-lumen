"""M7 精确探测：①子 agent 的文本 delta 是否真的透传到父流（用独特标记验证）②ToolReturn 正确构造
"""
import asyncio
import inspect
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


async def probe_marker():
    """子 agent 输出独特标记 MARKER_XYZ_123，看父流 delta 是否出现"""
    print("=== 探测A: 子 agent 标记是否透传父流 ===")
    sub = make_agent("你是子专家，回答以 MARKER_XYZ_123 开头，一句话。")

    async def deleg(topic: str) -> str:
        r = await sub.run(f"关于{topic}的一句话结论")
        return r.output.strip()

    parent = make_agent("你是主管，用 deleg 工具研究。", tools=[deleg])
    marker_hits = 0
    delta_parts = 0
    async with parent.run_stream_events("研究一下过拟合") as stream:
        async for ev in stream:
            if type(ev).__name__ == "PartDeltaEvent":
                delta_parts += 1
                d = ev.delta
                text = getattr(d, "content_delta", "") or ""
                if "MARKER_XYZ_123" in text:
                    marker_hits += 1
    print(f"总 delta 事件: {delta_parts}, 含子标记的: {marker_hits}")
    print("结论: 子 agent 文本" + ("透传父流（进度卡可走事件）" if marker_hits else "不透传（进度卡必须自造上报）"))


async def probe_toolreturn():
    print("\n=== 探测B: ToolReturn 正确构造 ===")
    print("签名:", inspect.signature(ToolReturn.__init__))
    # 试两种构造
    try:
        tr = ToolReturn(return_value="摘要", metadata={"full": ["a"]})
        print("位置构造 OK:", tr.return_value, tr.metadata)
    except Exception as e:
        print(f"位置构造失败: {type(e).__name__}: {str(e)[:80]}")


async def main():
    await probe_marker()
    await probe_toolreturn()


if __name__ == "__main__":
    asyncio.run(main())
