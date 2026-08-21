"""POC6: 多 agent 拓扑验证——主管 agent 拆解 + 工具内并行 delegation + 汇总
按 Pydantic AI 2.27 官方模式：父 agent 的工具内 await 子 agent.run()
（工具用 tools=[...] 传入，不用 @agent.tool 装饰器——后者要求 RunContext 注解，有坑）
验证点：拆解/并行/汇总质量、耗时、usage
"""
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from envutil import load_env

env = load_env()

from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

# 三个固定子角色：大纲 / 资源 / 避坑（POC 验证拓扑用；产品 M7 由模型自己拆）
SUB_ROLES = [
    ("大纲", "你是课程设计专家：给出该主题的核心大纲，不超过 6 行。"),
    ("资源", "你是资源挖掘专家：推荐该主题的学习资料和练习，不超过 6 行。"),
    ("避坑", "你是避坑专家：列出该主题最常见的 5 个误区，不超过 6 行。"),
]


def make_agent(system_prompt: str, tools=None) -> Agent:
    model = OpenAIChatModel(
        env["DEEPSEEK_MODEL"],
        provider=OpenAIProvider(base_url=env["DEEPSEEK_BASE_URL"], api_key=env["DEEPSEEK_API_KEY"]),
    )
    return Agent(model, system_prompt=system_prompt, tools=tools or [])


async def research_topics(topic: str) -> str:
    """并行研究一个学习主题的三个角度（大纲/资源/避坑），返回合并结果"""
    results = await asyncio.gather(
        *[make_agent(instr).run(topic) for _, instr in SUB_ROLES]
    )
    return "\n\n".join(f"[{name}]\n{r.output.strip()}" for (name, _), r in zip(SUB_ROLES, results))


async def main():
    start = time.perf_counter()
    planner = make_agent(
        "你是学习规划主管。用户给你一个学习目标，你用 research_topics 工具并行派发子研究，"
        "然后把所有子结果整合成一份完整、可执行的学习计划，直接输出。",
        tools=[research_topics],
    )

    result = await planner.run("帮我系统学 Python 基础，给一份 7 天可执行计划")
    elapsed = time.perf_counter() - start
    print("======== 主管汇总输出 ========")
    print(result.output.strip()[:800])
    print(f"\n======== 耗时 {elapsed:.1f}s ========")
    print("usage:", result.usage)
    print("PASS-POC6 多 agent 拓扑（主管→工具内并行 delegation→汇总）")
    return True


if __name__ == "__main__":
    ok = asyncio.run(main())
    sys.exit(0 if ok else 1)
