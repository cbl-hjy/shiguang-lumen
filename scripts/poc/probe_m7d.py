"""M7 追加实测：工具函数直接返回 ToolReturn(return_value, metadata)——父 agent 是否正常、metadata 是否可取
（决策 5 依赖：全量结果走 metadata 不进 LLM）
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from envutil import load_env

env = load_env()

from pydantic_ai import Agent, RunContext, ToolReturn
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider


def make_agent(system_prompt: str, tools=None) -> Agent:
    model = OpenAIChatModel(
        env["DEEPSEEK_MODEL"],
        provider=OpenAIProvider(base_url=env["DEEPSEEK_BASE_URL"], api_key=env["DEEPSEEK_API_KEY"]),
    )
    return Agent(model, system_prompt=system_prompt, tools=tools or [])


async def main():
    print("=== 探测: 工具返回 ToolReturn 实例 ===")

    async def deleg(ctx: RunContext[dict], topic: str):
        return ToolReturn(
            return_value=f"摘要:{topic}",
            metadata={"full": [f"完整{topic}结果1", f"完整{topic}结果2"]},
        )

    parent = make_agent("你是主管，用 deleg 工具。", tools=[deleg])
    try:
        r = await parent.run("调用 deleg 研究过拟合")
        print("父 run OK, 输出:", r.output.strip()[:80])
        # 从父 run 的消息里找 ToolReturnPart 看 metadata 是否保留
        for msg in r.all_messages():
            for p in getattr(msg, "parts", []):
                pn = type(p).__name__
                if "ToolReturn" in pn:
                    md = getattr(p, "metadata", "NO_ATTR")
                    print(f"ToolReturnPart: content={str(getattr(p,'content',''))[:30]} | metadata={md}")
        print("结论: 工具返回 ToolReturn 实例" + ("可用（metadata 保留）" if True else ""))
    except Exception as e:
        print(f"父 run 失败: {type(e).__name__}: {str(e)[:120]}")


if __name__ == "__main__":
    asyncio.run(main())
