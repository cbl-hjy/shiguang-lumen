"""进化层实测：v4-flash 的反思质量（论文警告弱模型 Reflexion 可能无效 0.26→0.26）
给一个教学失误场景，让反思 agent 产三段式反思，评估具体性/可执行性
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from envutil import load_env

env = load_env()

from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

REFLECT_PROMPT = """你是一位教育反思教练。基于"发生了什么 + 用户反馈"，写一段反思，严格三段式：
1) 什么错（指出具体错误/失误点，不笼统）
2) 为什么（根因分析）
3) 下次怎么改（具体可执行的改进，至少 2 条）
只输出反思本身，不要客套。"""

SCENARIOS = [
    "我（学习搭子）给用户讲过拟合，一上来就甩了公式 E_in - E_out 泛化误差分解，用户回'没听懂，你讲太快了，公式先放放'。",
    "用户问'学习率太大怎么办'，我回答'调小学习率'就结束了，没有给直觉、没有讲为什么、没有给调试方法，用户回'就这？太敷衍了'。",
    "我给用户讲梯度下降时把学习率说成'每次迭代更新的权重'（其实是步长），用户发现了并纠正我。",
]


def make_agent(system_prompt: str) -> Agent:
    model = OpenAIChatModel(
        env["DEEPSEEK_MODEL"],
        provider=OpenAIProvider(base_url=env["DEEPSEEK_BASE_URL"], api_key=env["DEEPSEEK_API_KEY"]),
    )
    return Agent(model, system_prompt=system_prompt)


async def main():
    agent = make_agent(REFLECT_PROMPT)
    for i, sc in enumerate(SCENARIOS, 1):
        print(f"===== 场景{i} =====")
        r = await agent.run(sc)
        print(r.output.strip()[:400])
        print()


if __name__ == "__main__":
    asyncio.run(main())
