# -*- coding: utf-8 -*-
"""跨域类比引擎（路线图 v3.0 §4「差异化心脏」，2026-08-31）。

用户原话例子：「你学 React 的组件思维，和你练人际沟通的边界感，是同一个结构。」

分工（判断归模型 / 不变量归代码）：
- 判断归模型：找不找得到结构同构的跨域连接、连哪两个域（LLM 提炼器，prompt 外置
  extractors.yaml "analogy" 条目）；找不到输出『无』→ 不落盘（宁缺毋滥）。
- 不变量归代码：
  ① cadence：距上一条类比 < 7 天绝不触发（连 LLM 都不调，省 token）；
  ② 防臆造锚定：evidence_a/evidence_b 必须是近 30 天真实记忆条目内容的【逐字子串】，
     锚定不上 → 整条丢弃不落盘；
  ③ 绝不自动注入对话：build_dynamic_context 零变化，产出只进「它记得我」抽屉。

挂账（路线图 §4 / §12）：前 5 条产出需人工评审再定去留——评审在模块外人工进行，
本模块不做代码评审门，只在 docstring 留痕。

存储：per-user memory_dir()/analogies.jsonl（append-only，cadence 台账=文件本身最后一行的
date 字段，不另建台账文件）；写 change_log（action="analogy"）。
"""
import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path

from app.memory.schema import memory_dir

CADENCE_DAYS = 7  # 距上一条类比的最小间隔（宁缺毋滥，路线图 §4「每周反思钩子产 ≤1 条」）
MATERIAL_DAYS = 30  # 跨域素材窗口：近 30 天记忆

_ANALOGY_OVERRIDE: Path | None = None  # 测试注入点（同 store._MF_OVERRIDE 模式）


def _analogy_file() -> Path:
    if _ANALOGY_OVERRIDE is not None:
        return _ANALOGY_OVERRIDE
    return memory_dir() / "analogies.jsonl"


def read_analogies(limit: int | None = None) -> list[dict]:
    """读类比记录（倒序：最新在前）。文件不存在/坏行 → 跳过不崩。"""
    f = _analogy_file()
    if not f.exists():
        return []
    try:
        recs = []
        for ln in f.read_text(encoding="utf-8").splitlines():
            if not ln.strip():
                continue
            try:
                recs.append(json.loads(ln))
            except Exception as _e:
                    print(f'[analogy] 跳过异常项: {_e}', file=__import__('sys').stderr)
                    continue
        recs.reverse()
        return recs[:limit] if limit else recs
    except Exception:
        return []


def _last_analogy_date() -> date | None:
    """cadence 台账：最后一条类比的 date（无记录 → None=从未产过，必触发）。"""
    recs = read_analogies(limit=1)
    if not recs:
        return None
    try:
        return date.fromisoformat(str(recs[0].get("date", ""))[:10])
    except Exception:
        return None


def cadence_due(today: date | None = None) -> bool:
    """距上一条 ≥7 天（或从未产过）才到期。"""
    last = _last_analogy_date()
    if last is None:
        return True
    return ((today or date.today()) - last).days >= CADENCE_DAYS


def _recent_materials(today: date | None = None) -> tuple[list, list[dict]]:
    """跨域素材：近 30 天记忆条目 + 主题列表。异常 → 空（提炼器见空素材自会输出『无』）。"""
    from app.memory import store

    today = today or date.today()
    cutoff = today - timedelta(days=MATERIAL_DAYS)
    try:
        entries = []
        for e in store.read_entries():
            try:
                stale = date.fromisoformat(str(e.created_at)[:10]) < cutoff
            except Exception:
                stale = False  # 日期解析失败不剔除（锚定校验仍兜底）
            if stale:
                continue  # 超出 30 天窗口
            entries.append(e)
    except Exception:
        entries = []
    try:
        from app.memory.topics_store import view_topics

        topics = view_topics()
    except Exception:
        topics = []
    return entries, topics


def _anchored(rec: dict, entries: list) -> bool:
    """防臆造不变量（代码锁死）：evidence_a/b 必须逐字锚定在真实记忆条目内容里。"""
    ea, eb = str(rec.get("evidence_a", "")).strip(), str(rec.get("evidence_b", "")).strip()
    if not ea or not eb:
        return False
    pool = [e.content for e in entries]
    return any(ea in c for c in pool) and any(eb in c for c in pool)


def parse_analogy(out: str) -> dict | None:
    """解析模型输出（乱 JSON/缺字段/『无』→ None，与其他 _extract_* 同防御模式）。"""
    out = (out or "").strip()
    if not out or out == "无" or "无。" in out[:4]:
        return None
    m = re.search(r"\{.*\}", out, re.DOTALL)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except Exception:
        return None
    rec = {k: str(data.get(k, "")).strip() for k in ("analogy", "domain_a", "domain_b", "evidence_a", "evidence_b")}
    return rec if all(rec.values()) else None


async def _run_llm(user_input: str) -> str:
    """LLM 调用缝（测试 mock 点）：独立函数便于 AsyncMock 替换，零 LLM 单测不碰模型。"""
    from pydantic_ai import Agent

    from app.agent.model import get_model
    from app.prompts.loader import extractor_prompt

    extractor = Agent(get_model(), system_prompt=extractor_prompt("analogy"))
    r = await extractor.run(user_input)
    return (r.output or "").strip()


async def extract_analogy(dialogue: str = "") -> dict | None:
    """会话收尾提炼器（第 8 路，经 store.register_analogy_writer 注册，签名对齐其他提炼器——
    输入不看本对话而看近 30 天记忆+主题：类比是跨域连接，素材在记忆库不在单会话）。

    返回校验过的 {analogy, domain_a, domain_b, evidence_a, evidence_b} 或 None：
    - cadence 未到期（<7 天）→ None（LLM 不调）；
    - 模型输出『无』/乱 JSON/缺字段 → None；
    - evidence 锚定不上真实记忆 → None（防臆造，整条丢弃）。
    """
    if not cadence_due():
        return None
    entries, topics = _recent_materials()
    if len(entries) < 2:
        return None  # 素材不足两个域，无从连接（省一次 LLM 调用）
    mem_lines = "\n".join(f"- {e.content}" for e in entries[:60])
    topics_line = "；".join(str(t.get("name", "")) for t in topics[:20] if isinstance(t, dict)) or "（暂无）"
    user_input = f"【近期记忆】\n{mem_lines}\n\n【主题列表】\n{topics_line}"
    rec = parse_analogy(await _run_llm(user_input[:8000]))
    if not rec:
        return None
    if not _anchored(rec, entries):
        try:
            from app.memory.store import log_change

            log_change("analogy_dropped", "类比锚定失败（evidence 非真实记忆片段），整条丢弃")
        except Exception as _e:
            print(f"[agent/analogy] 静默异常已可见化: {_e}", flush=True)
        return None
    return rec


def append_analogy(rec: dict) -> str:
    """落盘一条类比（append-only jsonl + change_log）。返回状态串（供钩子打印/观测）。"""
    from app.memory.store import log_change

    f = _analogy_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    row = {
        "time": now.isoformat(timespec="seconds"),
        "date": now.date().isoformat(),  # cadence 台账字段
        "analogy": rec["analogy"],
        "domain_a": rec["domain_a"],
        "domain_b": rec["domain_b"],
        "evidence_a": rec["evidence_a"],
        "evidence_b": rec["evidence_b"],
    }
    with f.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(row, ensure_ascii=False) + "\n")
    summary = f"{rec['domain_a']} × {rec['domain_b']}: {rec['analogy'][:60]}"
    log_change("analogy", summary)
    return summary
