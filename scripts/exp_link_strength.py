"""实验：链接强度分层——判链输出强/弱，只沿强链接扩散，能否"补盲区 + 不雪崩"
对照（已跑）：
  对照组 = 纯向量 top-3 → 召回 3 条，漏盲区 [23][4]
  实验组A = 全链接扩散 → 23 条，精确率 25%（雪崩）
本实验（实验组B）= 判链带 strong/weak 分级，只沿 strong 扩散
"""
import asyncio
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, ".")

QUERY = "面试机器学习基础复习什么"
GOLD_STRONG = {23, 4, 25, 24, 30, 31, 33}
GOLD_WEAK = {2, 3, 5, 6, 12, 13, 14, 15, 16, 17, 18, 19, 20, 32, 41, 42}


def load_memories() -> dict[int, str]:
    lines = [
        l for l in Path("memory/user_memory.md").read_text(encoding="utf-8").splitlines()
        if l.startswith("- ")
    ]
    return {i: l.split("|")[-1].strip() for i, l in enumerate(lines, 1)}


def _find_id(text: str, mems: dict) -> int | None:
    for k, v in mems.items():
        if v == text:
            return k
    return None


async def main():
    mems = load_memories()

    from app.memory.vector import aembed, search
    from app.agent.model import get_model
    from pydantic_ai import Agent

    vec = (await aembed([QUERY]))[0]
    hits = search(vec, top_k=3)
    seed_ids = [_find_id(t, mems) for _, t, _ in hits]
    print("种子（向量 top-3）:", seed_ids)

    judge = Agent(get_model(), system_prompt="你是记忆链接判定器，只输出 JSON。")
    strong, weak = set(), set()
    for sid in seed_ids:
        if sid is None:
            continue
        # 只给候选列表（排除种子自己），用候选的 [编号] 前缀，编号=记忆id
        cand = [k for k in mems if k != sid]
        cand_text = "\n".join(f"  [{k}] {mems[k][:50]}" for k in cand)
        prompt = f"""判断"种子记忆"与候选记忆的关联，分强度：
强链接(strong)：同一事件/同一决策/直接因果/同一具体话题的深入——检索到种子时这条"一定值得"一起出现
弱链接(weak)：同属一个大领域（如都属机器学习），但非同一事件/决策/话题

种子记忆[{sid}]：{mems[sid][:60]}

候选记忆（[编号] 编号=记忆id）：
{cand_text}

只输出有实质关联的（不要输出全部），JSON 格式：
{{"links":[{{"id":记忆id,"strength":"strong或weak","type":"同事件/同决策/因果/同话题"}}]}}"""
        try:
            r = await judge.run(prompt)
            m = re.search(r"\{.*\}", r.output.strip(), re.DOTALL)
            links = json.loads(m.group(0)).get("links", []) if m else []
        except Exception as e:
            import traceback
            print(f"  [种子{sid}] 判链失败: {type(e).__name__} {str(e)[:200]}", flush=True)
            traceback.print_exc()
            continue
        for x in links:
            lid = x.get("id")
            if not isinstance(lid, int) or lid not in mems or lid == sid:
                continue
            (strong if x.get("strength") == "strong" else weak).add(lid)

    print(f"\n强链接: {sorted(strong)}")
    print(f"弱链接: {sorted(weak)}")

    expanded = set(seed_ids) | strong
    print(f"\n=== 实验组B：只沿强链接扩散 ===")
    print(f"召回 {len(expanded)} 条: {sorted(expanded)}")

    recalled_strong = expanded & GOLD_STRONG
    recalled_noise = expanded & GOLD_WEAK
    precision = len(recalled_strong) / len(expanded) if expanded else 0
    blind_recovered = [b for b in [23, 4] if b in expanded and b not in seed_ids]
    print(f"\n=== 评估 ===")
    print(f"召回总数: {len(expanded)}（对照=3，实验组A全扩散=23）")
    print(f"强相关命中: {sorted(recalled_strong)}")
    print(f"噪声混入: {sorted(recalled_noise)}")
    print(f"精确率: {precision:.0%}（实验组A=25%，目标 70%+）")
    print(f"盲区补上: {blind_recovered if blind_recovered else '未补上'}")
    ok = precision >= 0.7 and len(blind_recovered) >= 1 and len(expanded) <= 10
    print(f"\n判定: {'✅ 强度分层成立（补盲区+不雪崩）' if ok else '❌ 未达标'}")


if __name__ == "__main__":
    asyncio.run(main())
