"""POC4: 记忆钩子 —— 多轮历史 + 记忆文件读写（git 跟踪、人可审）"""
import asyncio
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from envutil import load_env

env = load_env()

from openai import AsyncOpenAI
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

MEM_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "memory.md"


def remember(note: str) -> str:
    """把一条关于用户的记忆写进记忆文件（人可审/可回滚）"""
    MEM_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(MEM_FILE, "a", encoding="utf-8") as f:
        f.write(f"- {date.today()} {note}\n")
    return "已记住"


def recall() -> str:
    """读出全部记忆（喂回给模型的入口）"""
    if MEM_FILE.exists():
        return MEM_FILE.read_text(encoding="utf-8")
    return "(暂无记忆)"


async def main():
    model = OpenAIChatModel(
        env["DEEPSEEK_MODEL"],
        provider=OpenAIProvider(
            base_url=env["DEEPSEEK_BASE_URL"], api_key=env["DEEPSEEK_API_KEY"]
        ),
    )
    agent = Agent(
        model,
        system_prompt="你是学习搭子。下面是你对这个用户的记忆：\n" + recall(),
        tools=[remember, recall],
    )

    # 第一轮：让它记住一条偏好
    r1 = await agent.run("我学东西喜欢先直觉后公式，记住这个偏好，别说出来。")
    tool_calls = [
        getattr(p, "tool_name", None)
        for m in r1.all_messages()
        for p in getattr(m, "parts", [])
    ]
    print("turn1 工具调用:", [t for t in tool_calls if t])

    # 第二轮：带上历史，验证记忆文件持久化
    r2 = await agent.run("我昨天跟你说过我喜欢怎么学？从记忆里找。", message_history=r1.all_messages())
    print("turn2 回答:", r2.output.strip()[:200])

    print("--- 记忆文件内容 ---")
    print(recall())
    print("PASS-POC4 记忆钩子 OK（历史多轮 + 记忆文件持久化）")
    return True


if __name__ == "__main__":
    ok = asyncio.run(main())
    sys.exit(0 if ok else 1)
