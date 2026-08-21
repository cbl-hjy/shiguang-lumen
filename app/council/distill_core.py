# -*- coding: utf-8 -*-
"""从原文蒸馏星笺的核心库（M3：用户自助蒸馏的引擎）。

从 scripts/council_distill.py 抽出，API 与 CLI 共用。管线：
分章 → 切块 → 块摘要（并行批 5）→ 章摘要 → 星笺生成 → 忠实度自检（代码级不变量）。
stream_distill 为 SSE 汇报进度的流式版（拆解/蒸馏/验证/完成 各阶段事件）。

断点续传（2026-08-20 最小落地清单①）：章节级落盘到 data/distill_jobs/<job_id>/——
每章摘要完成立即 append（原子），中断/服务重启后带同 job_id 重跑跳过已完成章节；
raw.txt 存盘=续传免重传书文本。完成即删 job 目录，中断保留（GET /distill/jobs 可列）。
"""
from __future__ import annotations

import asyncio
import json
import re
import shutil
import uuid
from datetime import datetime
from pathlib import Path

from pydantic_ai import Agent, UsageLimits

from app.agent.model import get_model
from app.config import DATA_DIR

CHUNK_CHARS = 3500
BATCH = 5  # 并行批大小（防 DeepSeek 429，借鉴 delegation MAX_SUBTASKS=5）
LLM_LIMITS = UsageLimits(request_limit=5, total_tokens_limit=12000)  # 三重验证字段使输出变长（9255 实测超 8000）

# ---------- 断点续传 job 存储（D 盘：DATA_DIR 在项目 D 盘，data/ 铁律）----------
JOBS_DIR = DATA_DIR / "data" / "distill_jobs"

CHUNK_PROMPT = (
    "You are summarizing a section of a book (Chinese/English ok). Output JSON only:\n"
    "{\"points\": [\"key claim 1\", ...], \"quotes\": [\"exact verbatim quote from the text\", ...]}\n"
    "Rules: points <= 6, each <= 30 words; quotes MUST be exact verbatim substrings of the input text "
    "(<= 60 words, <= 4); no fabrication."
)

CHAPTER_PROMPT = (
    "You are summarizing one chapter of a book. Given the chunk summaries, output JSON only:\n"
    "{\"chapter_points\": [\"key claims\", ...], \"best_quotes\": [\"exact verbatim quotes\", ...], "
    "\"method\": \"chapter's method in one sentence\"}\n"
    "Rules: chapter_points <= 8; best_quotes <= 6, must be verbatim."
)

SAGE_PROMPT = (
    "你是星宿蒸馏器：基于这本书的章节摘要，生成星笺。输出 JSON（不要输出其他内容）：\n"
    "{\"stance\": \"立场声明(一句话，中文)\", "
    "\"core_claims\": [{\"title\": \"观点名(中文)\", \"claim\": \"主张(中文，<=60字)\", "
    "\"quote\": \"原文引用(必须逐字来自输入的 best_quotes)\", \"source\": \"章节名\", "
    "\"evidence\": \"跨域佐证(至少 2 个独立章节/场景的佐证，V1)\", "
    "\"novel_question\": \"用它能回答的书里没明说的新问题(一句话，V2)\", "
    "\"derived_answer\": \"该新问题的推导答案(一句话，V2)\", "
    "\"novelty\": \"与常识的区别——为什么不是任何聪明人都会说的(一句话，V3)\"}], "
    "\"skeleton\": [\"方法论骨架(中文，3-7条)\"], "
    "\"boundaries\": {\"limits\": [时代局限], \"blindspots\": [立场盲点], \"unproven\": [未被证明假设], "
    "\"strongest_opposition\": \"最强反对意见(中文)\"}}\n"
    "规则：core_claims 8-12 条；每条 quote 必须逐字来自输入（忠实度自检会验证，编造=失败）；"
    "evidence/novel_question/derived_answer/novelty 是三重验证字段（V1 跨域/V2 预测力/V3 独特性，"
    "借鉴 cangjie 三重验证判据），必须真实填写；boundaries 每类 2-3 条。"
)


def extract_book(text: str) -> str:
    """去 Gutenberg 头尾 + 规范化空白，返回正文"""
    m = re.search(r"\*\*\* START OF THE PROJECT GUTENBERG EBOOK.*?\*\*\*(.*?)\*\*\* END OF THE PROJECT GUTENBERG EBOOK", text, re.S)
    body = m.group(1) if m else text
    body = re.sub(r"[ \t]+", " ", body)
    return body.strip()


def split_parts(body: str) -> list[tuple[str, str]]:
    """按章边界切分（支持 PART/章/一/二 等常见标题），退化：整书一块"""
    marks = [(m.start(), m.group(0).strip())
             for m in re.finditer(r"^(?:PART [IVX]+|第[一二三四五六七八九十]+[章部节]|CHAPTER \w+|Chapter \d+|Part \w+|Part \d+)\s*$", body, re.M)]
    if len(marks) < 2:
        return [("全书", body)]
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
    """LLM JSON 调用（复用项目 fallback 链——2026-08-19 培根蒸馏超时事故补）：
    主→备模型（无备用时同模型再试一次）+ JSON 解析重试 + 熔断记录 + 120s 硬超时护栏
    （2026-08-19 二次事故：DeepSeek 挂起不抛错不响应，无超时会无限等待——进程活着 0 输出）"""
    import asyncio

    from app.agent.model import circuit_record, get_fallback_model, get_model, should_fallback

    models = [get_model()]
    fb = get_fallback_model()
    models.append(fb if fb else get_model())  # 无备用时同模型重试一轮
    last_err: Exception | None = None
    for i, model in enumerate(models):
        agent = Agent(model, system_prompt=prompt)
        try:
            async with asyncio.timeout(120):  # 硬护栏：单次调用 120s 上限（主服务 240s 总护栏的脚本版）
                for attempt in (1, 2):  # JSON 解析失败重试（同一模型）
                    r = await agent.run(content, usage_limits=LLM_LIMITS)
                    data = _extract_json(r.output)
                    if data:
                        circuit_record(True)
                        return data
                    print(f"⚠ [{label}] JSON 解析失败（第 {attempt} 次）", flush=True)
        except Exception as e:
            last_err = e
            if i < len(models) - 1 and should_fallback(e):
                print(f"[fallback] [{label}] {str(e)[:100]} → 换模型重试", flush=True)
                circuit_record(False)
                continue
            print(f"⚠ [{label}] 模型调用失败: {str(e)[:120]}", flush=True)
            circuit_record(False)
    raise RuntimeError(f"[{label}] 模型调用连续失败: {last_err}")


async def _llm_json_retry(prompt: str, content: str, label: str, retries: int = 1) -> dict | Exception:
    """_llm_json 外再包一层重试（2026-08-20 断点续传 E 决策）：chunk 级失败自动重试 1 次
    （_llm_json 内部已有主→备+JSON 重试，这层是兜整次调用）；仍失败返回异常对象
    （与 asyncio.gather return_exceptions 同风格，调用方跳过并提示）。"""
    for i in range(retries + 1):
        try:
            return await _llm_json(prompt, content, label)
        except Exception as e:
            if i < retries:
                print(f"⚠ [{label}] 蒸馏失败，重试 {i + 1}/{retries}: {str(e)[:80]}", flush=True)
                continue
            return e
    raise RuntimeError("unreachable")


# ---------- 断点续传 job 管理（D 盘 data/distill_jobs/）----------
def _job_dir(job_id: str) -> Path:
    return JOBS_DIR / job_id


def save_new_job(job_id: str, sage_id: str, book_title: str, raw_text: str, total_parts: int) -> None:
    """新建任务：meta.json + raw.txt（续传免重传的凭据）。"""
    d = _job_dir(job_id)
    d.mkdir(parents=True, exist_ok=True)
    (d / "meta.json").write_text(
        json.dumps({
            "job_id": job_id, "sage_id": sage_id, "book_title": book_title,
            "created_at": datetime.now().isoformat(timespec="seconds"), "total_parts": total_parts,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (d / "raw.txt").write_text(raw_text, encoding="utf-8")


def load_job(job_id: str) -> dict | None:
    """读任务：meta + 已完成章节摘要；不存在返回 None。"""
    d = _job_dir(job_id)
    if not d.exists() or not (d / "meta.json").exists():
        return None
    try:
        meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    except Exception:
        return None
    summaries = []
    sf = d / "chapter_summaries.jsonl"
    if sf.exists():
        for line in sf.read_text(encoding="utf-8").splitlines():
            try:
                summaries.append(json.loads(line))
            except Exception:
                continue
    done_parts = {s.get("part", "") for s in summaries}
    return {"meta": meta, "summaries": summaries, "done_parts": done_parts}


def append_chapter(job_id: str, summary: dict) -> None:
    """章节摘要完成立即落盘（append-only，写完才算完成——原子性）。"""
    d = _job_dir(job_id)
    d.mkdir(parents=True, exist_ok=True)
    with (d / "chapter_summaries.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(summary, ensure_ascii=False) + "\n")


def delete_job(job_id: str) -> None:
    """蒸馏完成入库后清理 job 目录（中断的保留）。"""
    try:
        shutil.rmtree(_job_dir(job_id), ignore_errors=True)
    except Exception:
        pass


def list_jobs() -> list[dict]:
    """所有可续传任务（GET /distill/jobs）：job_id/书名/已完成章/总章/时间。"""
    jobs = []
    if not JOBS_DIR.exists():
        return jobs
    for d in sorted(JOBS_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not d.is_dir():
            continue
        job = load_job(d.name)
        if not job:
            continue
        meta = job["meta"]
        jobs.append({
            "job_id": meta.get("job_id", d.name),
            "sage_id": meta.get("sage_id", ""),
            "book_title": meta.get("book_title", ""),
            "created_at": meta.get("created_at", ""),
            "chapters_done": len(job["summaries"]),
            "chapters_total": meta.get("total_parts", 0),
        })
    return jobs


async def stream_distill(raw_text: str, sage_id: str, book_title: str = "", job_id: str | None = None) -> dict:
    """蒸馏一本已读入的书文本 → 星笺 dict。yield 阶段进度事件（SSE 用）。
    断点续传（2026-08-20）：job_id 存在且任务在 → 续传（跳过已完成章，raw 用存盘版，免重传）；
    job_id 不存在 → 新建任务落盘。每章完成立即 append（原子）。"""
    body = extract_book(raw_text)
    parts = split_parts(body)

    # ---------- 新建 or 续传 ----------
    summaries: list[dict] = []
    existing = load_job(job_id) if job_id else None
    if existing:
        done_parts = existing["done_parts"]
        summaries = list(existing["summaries"])
        meta = existing["meta"]
        # 续传：raw 用存盘版（前端只带 job_id，不重传文本），part 切分重新算（确定性）
        body = extract_book((_job_dir(job_id) / "raw.txt").read_text(encoding="utf-8"))
        parts = split_parts(body)
        yield {"type": "stage", "stage": "续传",
               "detail": f"从断点继续：已完成 {len(done_parts)}/{meta.get('total_parts', len(parts))} 章"}
    else:
        job_id = job_id or f"j-{uuid.uuid4().hex[:10]}"
        done_parts = set()
        save_new_job(job_id, sage_id, book_title, raw_text, len(parts))
        yield {"type": "stage", "stage": "拆解",
               "detail": f"识别到 {len(parts)} 个章节（{len(body)//1000}K 字符）"}

    for pname, ptext in parts:
        if pname in done_parts:
            continue  # 断点续传：已完成章节跳过（同输入重跑=白花钱）
        chunks = chunk_text(ptext)
        chunk_results: list[dict | Exception] = []
        for i in range(0, len(chunks), BATCH):
            batch = chunks[i : i + BATCH]
            chunk_results.extend(
                await asyncio.gather(
                    *[_llm_json_retry(CHUNK_PROMPT, c, f"{pname}-c{i+j}") for j, c in enumerate(batch)],
                    return_exceptions=True,
                )
            )
        ok = [c for c in chunk_results if not isinstance(c, Exception)]
        failed_n = len(chunk_results) - len(ok)
        agg = json.dumps(ok, ensure_ascii=False)[:12000]
        cs = await _llm_json(CHAPTER_PROMPT, agg, f"{pname}-chapter")
        summaries.append({"part": pname, **cs})
        append_chapter(job_id, {"part": pname, **cs})  # 立即落盘（断点续传凭据）
        detail = f"{pname} 完成（{len(cs.get('chapter_points', []))} 要点）"
        if failed_n:
            detail += f"，{failed_n} 段蒸馏失败已跳过"
        yield {"type": "stage", "stage": "蒸馏", "detail": detail}

    sage = await _llm_json(SAGE_PROMPT, json.dumps(summaries, ensure_ascii=False), "sage-card")
    sage.update(
        {
            "id": sage_id,
            "name": f"《{book_title}》" if book_title else sage_id,
            "book": book_title,
            "author": "",
            "year": "",
            "audit": {
                "tool": "council_distill（用户自助蒸馏）",
                "user_confirmed": False,
                "claims_count": len(sage.get("core_claims", [])),
            },
        }
    )
    yield {"type": "stage", "stage": "验证", "detail": "忠实度自检：逐条核对引用是否存在于原文"}

    norm_body = re.sub(r"\s+", " ", body).lower()
    unverified = []
    for c in sage.get("core_claims", []):
        q = c.get("quote", "")
        norm_q = re.sub(r"\s+", " ", q).lower().strip()
        if not norm_q or norm_q not in norm_body:
            unverified.append(c.get("title", "?"))
    sage["audit"]["quote_verified"] = len(sage.get("core_claims", [])) - len(unverified)
    sage["audit"]["quote_unverified"] = unverified
    yield {"type": "stage", "stage": "完成", "detail": f"{sage['audit']['quote_verified']}/{len(sage.get('core_claims', []))} 条引用逐字命中"}
    yield {"type": "done", "sage": sage, "job_id": job_id}


async def distill_to_file(raw_text: str, sage_id: str, book_title: str, out_dir: Path) -> dict:
    """蒸馏并落盘（CLI 用，无流式进度）。返回星笺 dict。"""
    return await _distill_impl(raw_text, sage_id, book_title, out_dir)


async def _distill_impl(raw_text: str, sage_id: str, book_title: str, out_dir: Path) -> dict:
    body = extract_book(raw_text)
    parts = split_parts(body)
    chapter_summaries = []
    for pname, ptext in parts:
        chunks = chunk_text(ptext)
        results: list[dict | Exception] = []
        for i in range(0, len(chunks), BATCH):
            batch = chunks[i : i + BATCH]
            results.extend(
                await asyncio.gather(
                    *[_llm_json(CHUNK_PROMPT, c, f"{pname}-c{i+j}") for j, c in enumerate(batch)],
                    return_exceptions=True,
                )
            )
        ok = [c for c in results if not isinstance(c, Exception)]
        cs = await _llm_json(CHAPTER_PROMPT, json.dumps(ok, ensure_ascii=False)[:12000], f"{pname}-chapter")
        chapter_summaries.append({"part": pname, **cs})
    sage = await _llm_json(SAGE_PROMPT, json.dumps(chapter_summaries, ensure_ascii=False), "sage-card")
    sage.update(
        {
            "id": sage_id,
            "name": f"《{book_title}》" if book_title else sage_id,
            "book": book_title,
            "author": "",
            "year": "",
            "audit": {
                "tool": "council_distill（用户自助蒸馏）",
                "user_confirmed": False,
                "claims_count": len(sage.get("core_claims", [])),
            },
        }
    )
    norm_body = re.sub(r"\s+", " ", body).lower()
    unverified = []
    for c in sage.get("core_claims", []):
        q = c.get("quote", "")
        norm_q = re.sub(r"\s+", " ", q).lower().strip()
        if not norm_q or norm_q not in norm_body:
            unverified.append(c.get("title", "?"))
    sage["audit"]["quote_verified"] = len(sage.get("core_claims", [])) - len(unverified)
    sage["audit"]["quote_unverified"] = unverified
    # 三重验证完整性（V1 跨域证据必填；V2 预测力/V3 独特性缺失记 warning，fail loud 不静默）
    no_evidence = [c.get("title", "?") for c in sage.get("core_claims", []) if not (c.get("evidence") or "").strip()]
    no_v2 = [c.get("title", "?") for c in sage.get("core_claims", []) if not c.get("novel_question")]
    no_v3 = [c.get("title", "?") for c in sage.get("core_claims", []) if not c.get("novelty")]
    sage["audit"]["triple_verify"] = {
        "v1_evidence_missing": no_evidence,
        "v2_predictive_missing": no_v2,
        "v3_novelty_missing": no_v3,
    }
    if no_evidence:
        print(f"⚠ 三重验证 V1 缺失（跨域佐证必填，人审前不可确认）：{no_evidence}", flush=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{sage_id}.json").write_text(json.dumps(sage, ensure_ascii=False, indent=2), encoding="utf-8")
    return sage
