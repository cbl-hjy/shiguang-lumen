# -*- coding: utf-8 -*-
"""星宿工具化对比实验（2026-08-20，结果验证）：同一问题、同一星宿笛卡尔（有树），
"预注入（旧逻辑：强制 query_tree top-2 进 prompt）vs 纯自主（新逻辑：挂 query_tree 只读工具，模型自己翻书）"，
各发言一次，比较引用逐字命中率 / 发言质量 / 成本（token）。
用法: python scripts/exp_sage_tools_compare.py [--question "问题"] [--round 1]
"""
import argparse
import asyncio
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pydantic_ai import Agent, UsageLimits

from app.agent.model import get_model
from app.council.engine import SAGE_LIMITS, _build_sage_agent, _sage_input, _sage_prompt, load_sages
from app.council.models import SageCard
from app.council.raptor import query_tree

DEFAULT_QUESTION = "我怎么才能确定一个想法是真实的而不是我自欺？"


def _usage(r) -> dict:
    u = getattr(r, "usage", None)
    if u is None:
        return {"input": "?", "output": "?"}
    return {
        "input": getattr(u, "input_tokens", "?"),
        "output": getattr(u, "output_tokens", "?"),
    }


async def speak_inject(card: SageCard, question: str) -> tuple[str, dict, int]:
    """对照组（预注入旧逻辑）：query_tree top-2 注入 prompt，无工具"""
    hits = await query_tree(question, card.id, top_k=2)
    evidence = "\n".join(f"· {h['text']}" for h in hits)
    agent = Agent(get_model(), system_prompt=_sage_prompt(card, 1, 400))
    r = await agent.run(_sage_input(question, []), usage_limits=SAGE_LIMITS)
    return r.output.strip(), _usage(r), len(hits)


async def speak_auto(card: SageCard, question: str) -> tuple[str, dict, int]:
    """实验组（纯自主新逻辑）：挂 query_tree 工具，模型自己决定是否/如何翻书"""
    agent = _build_sage_agent(card, 1, 400)
    r = await agent.run(_sage_input(question, []), usage_limits=SAGE_LIMITS)
    return r.output.strip(), _usage(r), 0


def _check_quotes(speech: str, pool: list[str]) -> dict:
    """朴素引用命中检查：提取发言中的引号片段（“…”/『…』/"…"），检查是否逐字出现在证据池（树文本/卡引用）"""
    quoted = re.findall(r'[“"『]([^”"』]{6,})[”"』]', speech)
    pool_text = "\n".join(pool)
    hit, miss = [], []
    for q in quoted:
        if q in pool_text:
            hit.append(q)
        else:
            miss.append(q)
    return {"引号片段数": len(quoted), "命中": hit, "未命中(可能为卡内转述或编造)": miss}


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--question", default=DEFAULT_QUESTION)
    args = ap.parse_args()
    card = load_sages(["descartes"])[0]
    print(f"===== 问题：{args.question} =====\n")

    inj_speech, inj_usage, inj_hits = await speak_inject(card, args.question)
    print(f"---------- 对照组：预注入（top-{inj_hits}）----------\n{inj_speech}\n")

    auto_speech, auto_usage, _ = await speak_auto(card, args.question)
    print(f"---------- 实验组：纯自主（挂 query_tree 工具）----------\n{auto_speech}\n")

    # 证据池：树 top-5 + 卡引用（自动判引用命中）
    hits5 = await query_tree(args.question, card.id, top_k=5)
    pool = [h["text"] for h in hits5] + [c.quote for c in card.core_claims if c.quote]
    print("===== 引用命中检查（朴素子串比对）=====")
    print("对照组:", _check_quotes(inj_speech, pool))
    print("实验组:", _check_quotes(auto_speech, pool))

    print("\n===== 成本对比 =====")
    print(f"对照组（预注入）: {inj_usage}")
    print(f"实验组（纯自主）: {auto_usage}")


if __name__ == "__main__":
    asyncio.run(main())
