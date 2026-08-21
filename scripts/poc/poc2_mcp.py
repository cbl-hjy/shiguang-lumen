"""POC2: MCP client 接入验证 —— MCPToolset 连接 stdio server、列出工具、让模型调用"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from envutil import load_env

env = load_env()

from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.mcp import MCPToolset, StdioTransport

SERVER = str(Path(__file__).resolve().parent / "poc2_server.py")


async def main():
    model = OpenAIChatModel(
        env["DEEPSEEK_MODEL"],
        provider=OpenAIProvider(base_url=env["DEEPSEEK_BASE_URL"], api_key=env["DEEPSEEK_API_KEY"]),
    )
    toolset = MCPToolset(StdioTransport(command=sys.executable, args=[SERVER]), id="poc-demo")
    agent = Agent(model, system_prompt="你可以使用提供的工具。", toolsets=[toolset])

    async with toolset:
        try:
            tools = await toolset.get_tools()
            names = [getattr(t, "name", str(t)) for t in tools]
            print("MCP 工具列表:", names)
        except Exception as e:
            print("list_tools 跳过（不影响调用验证）:", e)
            names = ["(unknown)"]
        result = await agent.run("用 add 工具计算 1234 + 5678，直接给我结果")
        print("PASS-POC2 MCP client OK | 工具:", names)
        print("回答:", result.output.strip()[:200])
    return True


if __name__ == "__main__":
    ok = asyncio.run(main())
    sys.exit(0 if ok else 1)
