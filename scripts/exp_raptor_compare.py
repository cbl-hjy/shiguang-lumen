# -*- coding: utf-8 -*-
"""RAPTOR 树对比实验（2026-08-19，结果验证）：同一问题、同一星宿笛卡尔，
"有树（检索注入证据）vs 无树（纯立场卡）"各发言一次，比较引用具体性与证据强度。
用法: python scripts/exp_raptor_compare.py [--question "卡外问题"]"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pydantic_ai import Agent, UsageLimits

from app.agent.model import get_model
from app.council.engine import SAGE_LIMITS, _sage_input, _sage_prompt, load_sages
from app.council.raptor import query_tree

DEFAULT_QUESTION = "我怎么才能确定一个想法是真实的而不是我自欺？"


async def speak_with(card, question: str, with_tree: bool) -> str:
    evidence = ""
    if with_tree:
        hits = await query_tree(question, card.id, top_k=2)
        evidence = "\n".join(f"· {h['text']}" for h in hits)
        print(f"[{'有树' if with_tree else '无树'}] 检索到 {len(hits)} 个证据簇")
    agent = Agent(get_model(), system_prompt=_sage_prompt(card, 1, 400, evidence))
    r = await agent.run(_sage_input(question, []), usage_limits=SAGE_LIMITS)
    return r.output.strip()


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--question", default=DEFAULT_QUESTION)
    args = ap.parse_args()
    card = load_sages(["descartes"])[0]
    print(f"===== 问题：{args.question} =====\n")
    no_tree = await speak_with(card, args.question, with_tree=False)
    print(f"\n---------- 无树（纯立场卡）----------\n{no_tree}\n")
    with_tree = await speak_with(card, args.question, with_tree=True)
    print(f"\n---------- 有树（RAPTOR 检索注入）----------\n{with_tree}\n")


if __name__ == "__main__":
    asyncio.run(main())
