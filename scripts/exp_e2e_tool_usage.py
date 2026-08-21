"""端到端实验：模型自主使用 search_memory(category=...)（STATEFRESH-EXPERIMENT-DESIGN.md 反思补充①）
验证"判断无墙"的依赖点：模型能否自主决定 要不要检索 / 检索什么 / 要不要限定类别。

场景：6 应检索 + 2 不该检索（对照，测误伤率）。只注册 search_memory 一个工具（只读），
注入画像+状态模拟真实环境。评估：决策准确率 / category 正确率 / 误伤率。
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, ".")

ROOT = Path(".")

# 画像摘要（截自主库 profile.md，模拟 inject_context 的画像段）
PROFILE = """【用户画像摘要】
- 学习偏好：先直觉后公式（类比/故事/画面感再上公式）；喜欢具体数字序列演示抽象概念；被动听讲易"都会了"错觉，开口输出更准；深夜思绪活跃
- 目标：2026-08-11 决定系统学习正则化；准备算法岗面试（机器学习基础开始）；系统学 Transformer（4 子任务）
- 进度：交叉熵直觉已完成；面试复习从泛化/评估讲起
【上次会话结束状态】情绪=烦恼+自我怀疑（秋招投 Agent 岗大厂被拒，动摇方向）；snap_at=2026-08-15T12:53"""

# 场景：问题 / 期望行为 / 备注
SCENARIOS = [
    ("S1 学习续接", "我上次学到哪了？帮我接着复习", "应检索", "期望检索进度/学习记录，可限定类别"),
    ("S2 困惑", "我最近有点怀疑我选错方向了，你觉得我该继续吗", "应检索", "期望检索困惑/进度"),
    ("S3 偏好", "你觉得我怎么学新东西效果最好", "应检索", "期望检索偏好，或不检索（画像已含）"),
    ("S4 状态", "你记得我最近状态怎么样吗", "可检索可不检索", "状态在注入里，检索是额外保险"),
    ("S5 混合", "我想优化一下我的简历投递策略", "应检索", "期望检索进度/秋招相关"),
    ("S6 通用知识", "讲讲什么是过拟合和欠拟合", "不该检索", "模型知识足够，检索=误伤"),
    ("S7 学习+困惑", "我在复习机器学习基础，但总觉得方向不对，卡住了", "应检索", "期望检索进度+困惑，多类别"),
    ("S8 无关闲聊", "今天天气不错，你吃了吗", "不该检索", "无关话题，检索=误伤"),
]


async def main():
    from app.memory.store import search_memory
    from app.agent.model import get_model
    from pydantic_ai import Agent

    agent = Agent(
        get_model(),
        system_prompt=(
            "你是拾光，一个 AI 学习搭子。\n"
            "你的记忆体系：画像常驻注入；search_memory 用于按需检索用户的具体记忆（偏好/进度/困惑/目标等）。\n"
            "使用准则：需要了解用户具体历史/进度/困惑时才检索；通用知识问题（过拟合是什么）直接回答，不要检索；"
            "检索时可传 category 限定类别（学习记录/进度/偏好/目标/困惑/关系/笔记），不确定就留空=全量。\n\n"
            f"{PROFILE}"
        ),
        tools=[search_memory],
    )

    results = []
    for name, question, expect, note in SCENARIOS:
        r = await agent.run(question)
        # 提取工具调用
        calls = []
        for msg in r.all_messages():
            for part in getattr(msg, "parts", []):
                pn = type(part).__name__
                if "ToolCall" in pn:
                    calls.append({
                        "tool": getattr(part, "tool_name", "?"),
                        "args": str(getattr(part, "args", ""))[:120],
                    })
        answer = r.output.strip()[:150]
        print(f"===== {name}（期望：{expect}）=====")
        print(f"  工具调用: {calls if calls else '（无）'}")
        print(f"  回答: {answer}")
        print()
        results.append((name, question, expect, note, calls, answer))

    out = ROOT / "reports" / "expD_e2e_tool_usage.md"
    lines = ["# 实验 D：端到端工具调用（模型自主用 search_memory + category）\n"]
    for name, question, expect, note, calls, answer in results:
        lines.append(f"## {name}\n\n问题：{question}\n\n期望：{expect}（{note}）\n\n工具调用：{calls if calls else '无'}\n\n回答：{answer}\n")
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"原始输出已存: {out}")


asyncio.run(main())
