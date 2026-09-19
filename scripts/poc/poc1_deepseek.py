"""POC1: DeepSeek v4-flash 接入 Pydantic AI（OpenAI 兼容 base_url）"""
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


async def main():
    model = OpenAIChatModel(
        env["DEEPSEEK_MODEL"],
        provider=OpenAIProvider(
            base_url=env["DEEPSEEK_BASE_URL"], api_key=env["DEEPSEEK_API_KEY"]
        ),
    )
    agent = Agent(model, system_prompt="你是我的学习搭子，自然回应我。")
    result = await agent.run("一句话解释什么是过拟合？")
    print("PASS-POC1 DeepSeek 接入 OK | 模型:", env["DEEPSEEK_MODEL"])
    print("回答:", result.output.strip()[:200])
    return True


if __name__ == "__main__":
    ok = asyncio.run(main())
    sys.exit(0 if ok else 1)
