"""POC3: 多子 agent 并行 —— asyncio.gather 同时跑 3 个子 agent"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from envutil import load_env

env = load_env()

from openai import AsyncOpenAI
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider


def make_agent(system_prompt: str) -> Agent:
    model = OpenAIChatModel(
        env["DEEPSEEK_MODEL"],
        provider=OpenAIProvider(
            base_url=env["DEEPSEEK_BASE_URL"], api_key=env["DEEPSEEK_API_KEY"]
        ),
    )
    return Agent(model, system_prompt=system_prompt)


async def main():
    # 三个"子 agent"：概念解释 / 学习方法 / 常见误区（对应学习搭档的拆解场景）
    agents = [
        make_agent("你是概念讲解员，用日常类比解释术语。"),
        make_agent("你是学习规划师，给 3 步可执行建议。"),
        make_agent("你是误区侦探，列出 3 个最常见的误解。"),
    ]
    questions = [
        "什么是梯度下降？",
        "怎么入门机器学习？",
        "初学者学梯度下降最容易错在哪？",
    ]
    results = await asyncio.gather(*[a.run(q) for a, q in zip(agents, questions)])
    for i, (q, r) in enumerate(zip(questions, results), 1):
        print(f"--- 子agent{i} [{q[:12]}...] ---")
        print(r.output.strip()[:120])
    print("PASS-POC3 多子 agent 并行 OK（3 个 agent 并发完成）")
    return True


if __name__ == "__main__":
    ok = asyncio.run(main())
    sys.exit(0 if ok else 1)
