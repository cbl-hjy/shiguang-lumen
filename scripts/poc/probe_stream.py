"""探测 run_stream_events 的 PartDeltaEvent.delta 结构（M1 SSE 对接用）"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from envutil import load_env

env = load_env()

from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider


async def main():
    model = OpenAIChatModel(
        env["DEEPSEEK_MODEL"],
        provider=OpenAIProvider(base_url=env["DEEPSEEK_BASE_URL"], api_key=env["DEEPSEEK_API_KEY"]),
    )
    agent = Agent(model, system_prompt="你是学习搭子，简短回答。")
    n = 0
    async with agent.run_stream_events("一句话解释什么是过拟合") as stream:
        async for ev in stream:
            et = getattr(ev, "type", type(ev).__name__)
            if et == "PartDeltaEvent":
                d = ev.delta
                cd = getattr(d, "content_delta", None)
                print("delta kind:", getattr(d, "part_delta_kind", None), "| content_delta type:", type(cd).__name__, "| repr:", repr(cd)[:100])
            else:
                print("event:", et)
            n += 1
            if n > 60:
                break
    print("done, total", n)


if __name__ == "__main__":
    asyncio.run(main())
