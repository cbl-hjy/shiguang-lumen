"""实验 A：记忆使用判断质量（STATEFRESH-EXPERIMENT-DESIGN.md）
H1：注入从 3 块（画像/状态/检索）加到 5 块（+relation+续接点），正确使用记忆的比例不降 >10%。

方法：7 真实场景问题 × 对照组（现状注入）/ 实验组（+两行模拟注入）→ 14 次 LLM 调用
评估：人工评 ✅正确使用 / ⚠️部分 / ❌错误使用（用错/被带偏/无视可用记忆）
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, ".")

ROOT = Path(".")

QUESTIONS = [
    ("Q1 我最近在困惑什么？", "困惑记忆"),
    ("Q2 我上次学到哪了？", "进度/续接点"),
    ("Q3 我的学习偏好是什么？", "偏好/画像"),
    ("Q4 我最近状态怎么样？", "状态轮"),
    ("Q5 讲讲交叉熵为什么用 log？", "学习记忆"),
    ("Q6 我现在该不该继续投大厂？", "困惑记忆"),
    ("Q7 你还记得我们上次聊到哪了吗？", "last_session/relation"),
]

# 实验组新增的两行模拟注入（贴合主库真实内容，手工构造）
RELATION_LINE = "我们之间（上次收尾）：深聊过秋招方向困惑；基调=会直接挑战、互相纠正过"
CONTINUATION_LINE = "续接点（上次收尾）：秋招投递策略讨论未完，下次从「中小厂分层怎么投」继续"


def _load_injection() -> str:
    """现状注入 = 画像 + 状态轮 + 困惑/进度检索结果（模拟 search_memory 返回）"""
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
        cur = d.get("current", {})
        last = d.get("last_session", {})
        state_parts = []
        for dim, v in last.items():
            if dim == "snap_at" or not isinstance(v, dict):
                continue
            state_parts.append(f"{dim}={v.get('value', '')[:60]}")
        if state_parts:
            parts.append(f"【上次会话结束状态（{last.get('snap_at', '?')}）】\n{'；'.join(state_parts)}")
        for dim, v in cur.items():
            if isinstance(v, dict) and v.get("value"):
                state_parts = [f"{dim}={v['value'][:60]}"]
        if cur:
            cur_parts = [f"{k}={v.get('value', '')[:60]}" for k, v in cur.items() if isinstance(v, dict) and v.get("value")]
            if cur_parts:
                parts.append(f"【本次会话状态】\n{'；'.join(cur_parts)}")
    # 困惑/进度检索结果（模拟 search_memory 的典型返回）
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
        system_prompt="你是拾光，一个 AI 学习搭子。回答用户问题时，基于注入的记忆信息回答；注入里没有的信息就如实说不知道或根据常识回答，不要编造。",
    )
    base_inj = _load_injection()
    print("=== 注入内容（对照组）===")
    print(base_inj[:300], "...")
    print()

    results = []
    for q, dim in QUESTIONS:
        ctrl_prompt = f"{base_inj}\n\n用户问：{q}"
        exp_prompt = f"{base_inj}\n\n{RELATION_LINE}\n{CONTINUATION_LINE}\n\n用户问：{q}"
        r_ctrl = await agent.run(ctrl_prompt)
        r_exp = await agent.run(exp_prompt)
        print(f"===== {q}（期望维度：{dim}）=====")
        print(f"【对照组】{r_ctrl.output[:160]}")
        print(f"【实验组】{r_exp.output[:160]}")
        print()
        results.append((q, dim, r_ctrl.output.strip(), r_exp.output.strip()))

    # 存盘供人工评估
    out = ROOT / "reports" / "expA_usage_raw.md"
    lines = ["# 实验 A 原始输出（人工评估用）\n"]
    for q, dim, c, e in results:
        lines.append(f"## {q}（期望维度：{dim}）\n\n**对照组**：\n{c}\n\n**实验组**：\n{e}\n")
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"原始输出已存: {out}")


asyncio.run(main())
