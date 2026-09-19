# -*- coding: utf-8 -*-
"""从原文蒸馏星笺（M2：笛卡尔《谈谈方法》验证从零蒸馏路径）。

管线（简化 RAPTOR——不过度工程，先验证路径）：
1. 分章（按 PART 边界）→ 切块（~3500 字符）
2. 块摘要（LLM：要点 + 保留原文关键句）——并行分批（防 429，借鉴 delegation MAX_SUBTASKS=5）
3. 章摘要（块的摘要再摘要）
4. 星笺生成（LLM：立场/核心观点[带原文引用]/方法论/边界）——JSON 输出
5. 忠实度自检（代码级）：每条观点的原文引用必须能在原书中找到（不变量）——找不到标记 unverified（fail loud，不静默）

用法: python scripts/council_distill.py --src research/council-inputs/descartes-discourse.txt --out data/sages --id descartes
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

_PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJ))  # 项目根（import app.*）
sys.path.insert(0, str(_PROJ / "scripts"))  # 同目录模块（import council_recompose）
from council_recompose import to_markdown  # noqa: E402

from pydantic_ai import Agent, UsageLimits  # noqa: E402

from app.agent.model import get_model  # noqa: E402

CHUNK_CHARS = 3500
BATCH = 5  # 并行批大小（防 DeepSeek 429）
LLM_LIMITS = UsageLimits(request_limit=5, total_tokens_limit=8000)

CHUNK_PROMPT = (
    "You are summarizing a section of Descartes' *Discourse on the Method* (English, John Veitch translation).\n"
    "Output JSON only:\n"
    "{\"points\": [\"key claim 1\", \"key claim 2\", ...], "
    "\"quotes\": [\"direct quote from the text supporting a key point\", ...]}\n"
    "Rules: points <= 6, each <= 30 words; quotes must be EXACT verbatim substrings of the input text "
    "(copy words as-is, keep sentence fragments), <= 60 words each; quotes <= 4."
)

CHAPTER_PROMPT = (
    "You are summarizing one chapter (PART) of Descartes' *Discourse on the Method*.\n"
    "Given the chunk summaries of this chapter, output JSON only:\n"
    "{\"chapter_points\": [\"key claims\", ...], \"best_quotes\": [\"exact verbatim quotes from the text\", ...], "
    "\"method\": \"the chapter's method/message in one sentence\"}\n"
    "Rules: chapter_points <= 8, each <= 30 words; best_quotes <= 6, must be verbatim from original text."
)

SAGE_PROMPT = (
    "你是星宿蒸馏器：基于《谈谈方法》(Discourse on the Method, René Descartes) 六章摘要，生成星笺。\n"
    "输出 JSON（不要输出其他内容）：\n"
    "{\"stance\": \"立场声明(一句话，中文)\", "
    "\"core_claims\": [{\"title\": \"观点名(中文)\", \"claim\": \"主张(中文，<=60字)\", "
    "\"quote\": \"原文引用(英文，必须逐字来自输入摘要中的 quotes)\", \"source\": \"PART 编号(如 PART I)\"}], "
    "\"skeleton\": [\"方法论骨架(中文，3-7条)\"], "
    "\"boundaries\": {\"limits\": [时代局限], \"blindspots\": [立场盲点], \"unproven\": [未被证明假设], "
    "\"strongest_opposition\": \"最强反对意见(中文)\"}}\n"
    "规则：core_claims 8-12 条；每条 quote 必须逐字来自输入（用于忠实度自检，编造会导致验证失败）；"
    "boundaries 每类 2-3 条。"
)


def extract_book(text: str) -> str:
    """去掉 Gutenberg 头尾，规范化空白，返回正文"""
    m = re.search(r"\*\*\* START OF THE PROJECT GUTENBERG EBOOK.*?\*\*\*(.*?)\*\*\* END OF THE PROJECT GUTENBERG EBOOK", text, re.S)
    body = m.group(1) if m else text
    body = re.sub(r"[ \t]+", " ", body)
    return body.strip()


def split_parts(body: str) -> list[tuple[str, str]]:
    """按 PART 边界切章，返回 [(part_name, text)]"""
    marks = [(m.start(), m.group(0).strip()) for m in re.finditer(r"^PART [IVX]+$", body, re.M)]
    parts = []
    for i, (pos, name) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(body)
        parts.append((name, body[pos:end].strip()))
    return parts


def chunk_text(text: str, size: int = CHUNK_CHARS) -> list[str]:
    return [text[i : i + size] for i in range(0, len(text), size)]


def _extract_json(text: str) -> dict | None:
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


async def _llm_json(prompt: str, content: str, label: str) -> dict:
    agent = Agent(get_model(), system_prompt=prompt)
    r = await agent.run(content, usage_limits=LLM_LIMITS)
    data = _extract_json(r.output)
    if not data:
        print(f"⚠ [{label}] JSON 解析失败，重试一次", flush=True)
        r = await agent.run(content, usage_limits=LLM_LIMITS)
        data = _extract_json(r.output)
    if not data:
        raise RuntimeError(f"[{label}] JSON 解析连续失败")
    return data


async def _chunk_summary(prompt: str, chunk: str, label: str) -> dict:
    return await _llm_json(prompt, chunk, label)


async def distill(src: Path, sage_id: str, out_dir: Path) -> dict:
    raw = src.read_text(encoding="utf-8", errors="ignore")
    body = extract_book(raw)
    parts = split_parts(body)
    print(f"分章：{len(parts)} 个 PART（总 {len(body)//1000}K 字符）", flush=True)

    chapter_summaries = []
    for pname, ptext in parts:
        chunks = chunk_text(ptext)
        print(f"  {pname}：{len(ptext)//1000}K 字符 → {len(chunks)} 块", flush=True)
        chunk_results: list[dict | Exception] = []
        for i in range(0, len(chunks), BATCH):
            batch = chunks[i : i + BATCH]
            chunk_results.extend(
                await asyncio.gather(
                    *[_chunk_summary(CHUNK_PROMPT, c, f"{pname}-chunk{j}") for j, c in enumerate(batch)],
                    return_exceptions=True,
                )
            )
        ok = [c for c in chunk_results if not isinstance(c, Exception)]
        print(f"    块摘要完成 {len(ok)}/{len(chunks)}", flush=True)
        # 章摘要
        agg = json.dumps(ok, ensure_ascii=False)[:12000]
        cs = await _llm_json(CHAPTER_PROMPT, agg, f"{pname}-chapter")
        chapter_summaries.append({"part": pname, **cs})
        print(f"  {pname} 章摘要完成：{len(cs.get('chapter_points', []))} 点", flush=True)

    # 星笺生成
    all_summary = json.dumps(chapter_summaries, ensure_ascii=False)
    sage = await _llm_json(SAGE_PROMPT, all_summary, "sage-card")
    sage.update(
        {
            "id": sage_id,
            "name": "《谈谈方法》· 笛卡尔",
            "book": "谈谈方法（Discourse on the Method）",
            "author": "笛卡尔 (René Descartes)",
            "year": "1637",
            "audit": {
                "tool": "council_distill.py（递归摘要管线）",
                "recomposed_by": "M2 从零蒸馏",
                "user_confirmed": False,
                "claims_count": len(sage.get("core_claims", [])),
            },
        }
    )

    # 忠实度自检：quote 必须逐字出现在原书中（不变量，代码级）
    norm_body = re.sub(r"\s+", " ", body).lower()
    unverified = []
    for c in sage.get("core_claims", []):
        q = c.get("quote", "")
        norm_q = re.sub(r"\s+", " ", q).lower().strip()
        if not norm_q or norm_q not in norm_body:
            unverified.append(c.get("title", "?"))
    sage["audit"]["quote_verified"] = len(sage.get("core_claims", [])) - len(unverified)
    sage["audit"]["quote_unverified"] = unverified
    print(f"\n忠实度自检：{sage['audit']['quote_verified']}/{len(sage.get('core_claims', []))} 条引用逐字命中原文", flush=True)
    if unverified:
        print(f"⚠ 未命中（fail loud，人审时处理）：{unverified}", flush=True)

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{sage_id}.json").write_text(json.dumps(sage, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / f"{sage_id}.md").write_text(to_markdown(sage), encoding="utf-8")
    print(f"已生成星笺：{out_dir / sage_id}.md / .json", flush=True)
    return sage


async def _main() -> None:
    ap = argparse.ArgumentParser(description="从原文蒸馏星笺（M2）")
    ap.add_argument("--src", required=True, help="书本文本路径")
    ap.add_argument("--out", default="data/sages", help="输出目录")
    ap.add_argument("--id", default="descartes", help="星宿 id")
    args = ap.parse_args()
    await distill(Path(args.src), args.id, Path(args.out))


if __name__ == "__main__":
    asyncio.run(_main())
