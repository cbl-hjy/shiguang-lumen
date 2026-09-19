"""定位：tutor agent（instructions+工具）流式事件是否正常产出"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from app.agent.tutor import build_tutor_agent


async def main():
    agent = build_tutor_agent()
    counts = {}
    async with agent.run_stream_events("什么是过拟合？用一句话") as stream:
        async for ev in stream:
            cls = type(ev).__name__
            et = getattr(ev, "type", "NO_ATTR")
            counts[cls] = counts.get(cls, 0) + 1
            if et == "PartDeltaEvent":
                d = ev.delta
                kind = getattr(d, "part_delta_kind", None)
                text = getattr(d, "content_delta", None)
                if kind == "text" and text:
                    print("TEXT:", text, end="")
            elif "Delta" in cls or "Part" in cls:
                print(cls, "| type attr:", et, "| fields:", list(getattr(ev, "__dict__", {}).keys())[:6])
    print()
    print("事件分布:", counts)


if __name__ == "__main__":
    asyncio.run(main())
