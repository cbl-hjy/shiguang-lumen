"""POC2: Pydantic AI MCP client —— 用 FastMCP 起一个本地 stdio 测试 server"""
from fastmcp import FastMCP

mcp = FastMCP("poc-demo-server")


@mcp.tool()
def add(a: int, b: int) -> int:
    """加法工具"""
    return a + b


@mcp.tool()
def current_time() -> str:
    """返回当前 UTC 时间字符串（模拟外部工具）"""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    mcp.run()
