"""实验组：向量 top-k + 沿链接扩散一层，能否补上向量盲区
对照（已跑）：查询"面试机器学习基础复习什么"，纯向量 top-6 漏掉 [23] LR vs SVM（imp=8）
实验组：向量 top-3 → 对每条判链 → 扩散一层 → 合并召回，看能否补上 [23]
"""
import asyncio
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, ".")

QUERY = "面试机器学习基础复习什么"
# 期望盲区（向量漏掉的强相关）：[23] LR vs SVM（imp=8，面试前复习用）、[4] 梯度下降复习计划


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

    # 对照组：纯向量 top-3
    vec = (await aembed([QUERY]))[0]
    hits = search(vec, top_k=3)
    seed_ids = [_find_id(t, mems) for _, t, _ in hits]
    print("=== 对照组：纯向量 top-3 ===")
    for i, (_, t, s) in enumerate(hits, 1):
        print(f"  {i}. [{_find_id(t, mems)}] ({s:.2f}) {t[:45]}")

    # 实验组：对 top-3 每条判链，扩散一层
    judge = Agent(get_model(), system_prompt="你是记忆链接判定器，只输出 JSON。")
    expanded = set(seed_ids)
    print("\n=== 实验组：沿链接扩散一层 ===")
    for sid in seed_ids:
        if sid is None:
            continue
        prompt = f"""判断下面这条"种子记忆"与主库其他记忆是否有实质关联（同一主题/决策/因果/时间先后），该链接的列出来。

种子记忆：[{sid}] {mems[sid][:60]}

主库全部记忆：
{chr(10).join(f'  [{k}] {v[:45]}' for k, v in mems.items())}

只输出有实质关联（同主题/同一决策/因果/时间先后）的记忆编号，JSON 格式：{{"links":[{{"id":编号,"type":"类型"}}]}}"""
        try:
            r = await judge.run(prompt)
            out = r.output.strip()
            m = re.search(r"\{.*\}", out, re.DOTALL)
            links = json.loads(m.group(0)).get("links", []) if m else []
        except Exception as e:
            print(f"  [种子{sid}] 判链失败: {e}")
            continue
        linked = [x["id"] for x in links if x.get("id") not in (seed_ids + [None])]
        for lid in linked:
            if lid in mems and lid not in expanded:
                print(f"  [种子{sid}] 扩散→ [{lid}] ({mems[lid][:45]})")
                expanded.add(lid)

    print(f"\n=== 汇总 ===")
    print(f"对照组召回: {sorted(x for x in seed_ids if x)}")
    print(f"实验组召回: {sorted(expanded)}")
    # 关键：盲区记忆 [23] 是否被扩散补上
    for blind in [23, 4]:
        status = "✅ 扩散补上" if blind in expanded and blind not in seed_ids else ("(对照组已含)" if blind in seed_ids else "❌ 仍未召回")
        print(f"  盲区记忆 [{blind}] {mems[blind][:40]} → {status}")


if __name__ == "__main__":
    asyncio.run(main())
