"""实验 B：注入膨胀 vs 回答质量（STATEFRESH-EXPERIMENT-DESIGN.md）
H2：注入组合从 3 块加到 5 块（总量仍 ≤2000 token），回答深度/贴合度不下降，复述倾向不增加。

方法：同一深度问题 × 三组注入（现状 / +relation / +relation+续接点）→ 3 次 LLM 调用
评估：人工评 深度（讲清核心机制）/ 贴合（用上个人化记忆）/ 复述倾向（照抄记忆原文）
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, ".")

ROOT = Path(".")
QUESTION = "讲讲交叉熵损失函数的直觉，它为什么用 log？"

RELATION_LINE = "我们之间（上次收尾）：深聊过秋招方向困惑；基调=会直接挑战、互相纠正过"
CONTINUATION_LINE = "续接点（上次收尾）：秋招投递策略讨论未完，下次从「中小厂分层怎么投」继续"


def _load_injection() -> str:
    parts = []
    profile = ROOT / "memory" / "profile.md"
    if profile.exists():
        text = profile.read_text(encoding="utf-8").strip()
        if text:
            parts.append(f"【用户画像】\n{text[:600]}")
    state = ROOT / "memory" / "state.json"
    if state.exists():
        import json
        d = json.loads(state.read_text(encoding="utf-8"))
        last = d.get("last_session", {})
        state_parts = []
        for dim, v in last.items():
            if dim == "snap_at" or not isinstance(v, dict):
                continue
            state_parts.append(f"{dim}={v.get('value', '')[:60]}")
        if state_parts:
            parts.append(f"【上次会话结束状态（{last.get('snap_at', '?')}）】\n{'；'.join(state_parts)}")
    um = ROOT / "memory" / "user_memory.md"
    if um.exists():
        confusions = [l.split("|")[-1].strip() for l in um.read_text(encoding="utf-8").splitlines()
                      if l.startswith("- ") and "cat=困惑" in l]
        if confusions:
            parts.append("【记忆检索结果】\n" + "\n".join(f"- {c[:80]}" for c in confusions[:3]))
    return "\n\n".join(parts)


async def main():
    from app.agent.model import get_model
    from pydantic_ai import Agent

    agent = Agent(
        get_model(),
        system_prompt="你是拾光，一个 AI 学习搭子。回答要讲清楚概念的核心直觉，善用类比；注入的记忆信息按需参考，不要照抄。",
    )
    base = _load_injection()
    groups = [
        ("A 现状（3块）", f"{base}\n\n用户问：{QUESTION}"),
        ("B +relation（4块）", f"{base}\n\n{RELATION_LINE}\n\n用户问：{QUESTION}"),
        ("C +relation+续接点（5块）", f"{base}\n\n{RELATION_LINE}\n{CONTINUATION_LINE}\n\n用户问：{QUESTION}"),
    ]
    out_lines = ["# 实验 B 原始输出（人工评估用）\n", f"问题：{QUESTION}\n"]
    for name, prompt in groups:
        r = await agent.run(prompt)
        print(f"===== {name} =====")
        print(r.output[:400])
        print()
        out_lines.append(f"## {name}\n\n{r.output.strip()}\n")
    out = ROOT / "reports" / "expB_injection_depth.md"
    out.write_text("\n".join(out_lines), encoding="utf-8")
    print(f"原始输出已存: {out}")


asyncio.run(main())
