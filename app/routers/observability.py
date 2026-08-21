"""星图观测台 API（2026-08-21）：拾光可观测性统一入口。
聚合 trace_log/token_usage/council_errors → 一键看全系统状态（harness 做厚，不约束 agent）。
数据源：
- data/trace_log.jsonl：工具调用（tool_start/end）、错误（error）、对话耗时（run_end）
- data/token_usage.csv：token 成本台账
- data/logs/council_errors.log：会议失败日志
"""
import csv
import json
from collections import defaultdict
from pathlib import Path

from fastapi import APIRouter

from app.config import DATA_DIR

router = APIRouter(prefix="/api/observability", tags=["observability"])

TRACE = DATA_DIR / "data" / "trace_log.jsonl"
TOKEN_CSV = DATA_DIR / "data" / "token_usage.csv"
COUNCIL_ERR = DATA_DIR / "data" / "logs" / "council_errors.log"


def _read_trace() -> tuple[list[dict], int]:
    """返回 (事件列表, 损坏行数)——损坏行计数供完整性校验（数据缺失可见）"""
    if not TRACE.exists():
        return [], 0
    out = []
    corrupt = 0
    for line in TRACE.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            corrupt += 1
    return out, corrupt


def _agg_trace(evs: list[dict]) -> dict:
    """聚合 trace：工具调用（次数/成功率/平均耗时）、LLM 调用、错误、对话延迟"""
    tools: dict[str, dict] = defaultdict(lambda: {"calls": 0, "ok": 0, "err": 0, "total_ms": 0})
    # LLM 调用（2026-08-21 补：对齐 GenAI operation.duration 语义——llm_start/llm_end 配对算耗时）
    llms: dict[str, dict] = defaultdict(lambda: {"calls": 0, "ok": 0, "err": 0, "total_ms": 0})
    starts: dict[tuple, str] = {}
    llm_starts: dict[tuple, str] = {}
    errors: dict[str, int] = defaultdict(int)
    run_durs: list[int] = []
    n_tools = 0
    runs_started = runs_ended = 0

    for ev in evs:
        t = ev.get("type")
        if t == "run_start":
            runs_started += 1
        elif t == "run_end":
            runs_ended += 1
            d = ev.get("dur_ms")
            if isinstance(d, (int, float)) and d > 0:
                run_durs.append(int(d))
        elif t == "llm_start":
            llm_starts[(ev.get("run_id"), ev.get("tag", "?"))] = ev.get("ts", "")
            llms[ev.get("tag", "?")]["calls"] += 1
        elif t == "llm_end":
            tag = ev.get("tag", "?")
            llms[tag][("ok" if ev.get("status", "ok") == "ok" else "err")] += 1
            key = (ev.get("run_id"), tag)
            if key in llm_starts:
                st = llm_starts.pop(key)
                ms = _ts_diff_ms(st, ev.get("ts", ""))
                if ms is not None:
                    llms[tag]["total_ms"] += ms
        elif t == "tool_start":
            key = (ev.get("run_id"), ev.get("name"))
            starts[key] = ev.get("ts", "")
            tools[ev.get("name", "?")]["calls"] += 1
            n_tools += 1
        elif t == "tool_end":
            name = ev.get("name", "?")
            status = ev.get("status", "")
            tools[name][("ok" if status == "done" else "err")] += 1
            # 工具失败计入错误分布（2026-08-21 补洞：tool_end status=error 不产生 error 事件，
            # 星图错误分布漏掉工具失败——sandbox 0% 成功率但错误卡显示 0）
            if status != "done":
                errors[f"tool:{name}"] += 1
            # 耗时：end 与最近的 start 配对（同 run 同名按出现顺序）
            key = (ev.get("run_id"), name)
            if key in starts:
                st = starts.pop(key)
                et = ev.get("ts", "")
                ms = _ts_diff_ms(st, et)
                if ms is not None:
                    tools[name]["total_ms"] += ms
        elif t == "error":
            errors[ev.get("where", "unknown")] += 1

    # 工具统计列表（按调用数排序）
    tool_stats = []
    for name, s in tools.items():
        calls = s["calls"]
        ok = s["ok"] + s["err"]
        rate = (s["ok"] / calls * 100) if calls else 0
        avg_ms = (s["total_ms"] / ok) if ok else 0
        tool_stats.append({"name": name, "calls": calls, "success": s["ok"], "fail": s["err"],
                           "success_rate": round(rate, 1), "avg_ms": round(avg_ms)})
    tool_stats.sort(key=lambda x: -x["calls"])

    # LLM 统计（tag=primary/fallback/子agent等）
    # 兼容性（2026-08-21）：llm_end 是新增事件，历史 llm_start 无配对——unfinished 单独标注，
    # 成功率只看有配对的（ok/(ok+err)），避免历史数据把成功率拉失真
    llm_stats = []
    for tag, s in llms.items():
        calls = s["calls"]
        ok = s["ok"] + s["err"]
        unfinished = calls - ok
        rate = (s["ok"] / ok * 100) if ok else 0
        avg_ms = (s["total_ms"] / ok) if ok else 0
        llm_stats.append({"tag": tag, "calls": calls, "success": s["ok"], "fail": s["err"],
                          "unfinished": max(0, unfinished),
                          "success_rate": round(rate, 1), "avg_ms": round(avg_ms)})
    llm_stats.sort(key=lambda x: -x["calls"])

    # 延迟：平均 + p95
    avg_ms = round(sum(run_durs) / len(run_durs)) if run_durs else 0
    p95 = 0
    if run_durs:
        run_durs.sort()
        p95 = run_durs[min(len(run_durs) - 1, int(len(run_durs) * 0.95))]

    return {
        "runs": len(run_durs),
        "runs_started": runs_started,
        "runs_ended": runs_ended,
        "tool_calls": n_tools,
        "tool_stats": tool_stats,
        "llm_stats": llm_stats,
        "errors": dict(sorted(errors.items(), key=lambda x: -x[1])),
        "avg_delay_ms": avg_ms,
        "p95_delay_ms": p95,
    }


def _ts_diff_ms(start: str, end: str) -> int | None:
    """'YYYY-MM-DD HH:MM:SS' 时间戳差（毫秒）。格式不符返回 None。"""
    from datetime import datetime

    for s in (start, end):
        if not s or len(s) < 19:
            return None
    fmt = "%Y-%m-%d %H:%M:%S"
    try:
        a = datetime.strptime(start[:19], fmt)
        b = datetime.strptime(end[:19], fmt)
        return max(0, int((b - a).total_seconds() * 1000))
    except ValueError:
        return None


def _agg_token() -> dict:
    """token_usage.csv：按日汇总（近 14 天）+ 按角色汇总"""
    if not TOKEN_CSV.exists():
        return {"total": 0, "by_role": {}, "by_day": []}
    by_day: dict[str, int] = defaultdict(int)
    by_role: dict[str, int] = defaultdict(int)
    total = 0
    try:
        with open(TOKEN_CSV, encoding="utf-8", errors="replace") as f:
            for row in csv.reader(f):
                if len(row) < 5 or not row[0][:4].isdigit():
                    continue
                day, role = row[0][:10], row[1]
                try:
                    toks = int(row[4])
                except ValueError:
                    continue
                by_day[day] += toks
                by_role[role] += toks
                total += toks
    except Exception:
        pass
    days = sorted(by_day.keys())[-14:]
    return {"total": total, "by_role": dict(by_role), "by_day": [{"date": d, "tokens": by_day[d]} for d in days]}


def _agg_council_errors() -> int:
    if not COUNCIL_ERR.exists():
        return 0
    try:
        return sum(1 for _ in COUNCIL_ERR.open(encoding="utf-8", errors="replace"))
    except Exception:
        return 0


@router.get("/summary")
def observability_summary():
    evs, corrupt = _read_trace()
    trace = _agg_trace(evs)
    token = _agg_token()
    from app import observability as _obs
    from app.prompts.loader import prompt_version

    return {
        "trace": trace,
        "token": token,
        "council_errors": _agg_council_errors(),
        "prompt_version": prompt_version(),
        "integrity": {
            "events": len(evs),
            "corrupt_lines": corrupt,
            "write_fails": _obs.write_fail_count(),
            "runs_started": trace.get("runs_started", 0),
            "runs_ended": trace.get("runs_ended", 0),
        },
        "generated_at": __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


# ---------- 会话重放（参考 Langfuse trace/session 设计，2026-08-21）----------

def _db_conn():
    import sqlite3

    return sqlite3.connect(DATA_DIR / "data" / "sessions.db")


@router.get("/sessions")
def obs_sessions(limit: int = 30):
    """会话列表（sessions.db）+ 各会话的 trace 数——trace-driven debugging 的入口"""
    try:
        conn = _db_conn()
        rows = conn.execute(
            "SELECT id, created_at, title, summary FROM sessions ORDER BY created_at DESC LIMIT ?",
            (max(1, min(limit, 100)),),
        ).fetchall()
        conn.close()
    except Exception as e:
        return {"sessions": [], "error": str(e)}
    # trace 按 run_id 统计（run_start 的 sid 关联会话）
    run_map = {}
    for ev in _read_trace()[0]:
        if ev.get("type") == "run_start":
            run_map.setdefault(ev.get("sid", ""), 0)
        if ev.get("run_id"):
            pass
    sessions = []
    for sid, created, title, summary in rows:
        sessions.append({
            "id": sid, "created_at": created or "", "title": title or "",
            "summary": (summary or "")[:120],
        })
    return {"sessions": sessions}


@router.get("/session/{sid}/runs")
def obs_session_runs(sid: str):
    """会话的 run 列表（trace run_start 按 sid 匹配）——重放下钻：会话→run→事件流"""
    runs = []
    seen = set()
    for ev in _read_trace()[0]:
        if ev.get("type") == "run_start" and ev.get("sid", "").startswith(sid[:8]):
            rid = ev.get("run_id")
            if rid and rid not in seen:
                seen.add(rid)
                runs.append({"run_id": rid, "ts": ev.get("ts", ""), "text": str(ev.get("text", ""))[:60]})
    return {"sid": sid, "runs": runs[-20:]}


@router.get("/trace/{run_id}")
def obs_trace(run_id: str):
    """单个 run 的完整事件流（重放：按时间线展示，含耗时/状态/参数）"""
    evs = [e for e in _read_trace()[0] if e.get("run_id") == run_id]
    if not evs:
        return {"run_id": run_id, "events": [], "error": "run_id 不存在"}
    # 时间线排序（ts 字符串排序即可，ISO 格式可比较）
    evs.sort(key=lambda e: e.get("ts", ""))
    out = []
    for e in evs:
        out.append({
            "type": e.get("type"),
            "ts": e.get("ts", ""),
            "name": e.get("name") or e.get("tag") or e.get("where") or "",
            "status": e.get("status", ""),
            "detail": (str(e.get("args") or e.get("result") or e.get("msg") or e.get("text") or ""))[:120],
            "dur_ms": e.get("dur_ms"),
        })
    return {"run_id": run_id, "events": out}


# ---------- 记忆健康 + 注入审计（2026-08-21）----------

@router.get("/memory")
def obs_memory():
    """记忆健康：条目数/类别分布/画像大小/最近更新（数据给觉察）"""
    mem = DATA_DIR / "memory" / "user_memory.md"
    prof = DATA_DIR / "memory" / "profile.md"
    state = DATA_DIR / "memory" / "state.json"
    result = {"entries": 0, "categories": {}, "profile_chars": 0, "last_updated": ""}
    try:
        if mem.exists():
            lines = [l for l in mem.read_text(encoding="utf-8", errors="replace").splitlines() if l.startswith("- ")]
            result["entries"] = len(lines)
            cats = {}
            for l in lines:
                m = __import__("re").search(r"cat=([^|]+)", l)
                if m:
                    cats[m.group(1).strip()] = cats.get(m.group(1).strip(), 0) + 1
            result["categories"] = dict(sorted(cats.items(), key=lambda x: -x[1]))
            import os

            result["last_updated"] = __import__("time").strftime(
                "%Y-%m-%d %H:%M", __import__("time").localtime(os.path.getmtime(mem)))
    except Exception as e:
        result["error"] = str(e)
    try:
        result["profile_chars"] = len(prof.read_text(encoding="utf-8", errors="replace")) if prof.exists() else 0
    except Exception:
        pass
    return result


@router.get("/injection")
def obs_injection(limit: int = 50):
    """注入审计趋势（injection_log.jsonl 的 blocks.total——上下文预算观察）"""
    p = DATA_DIR / "data" / "injection_log.jsonl"
    rows = []
    if p.exists():
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                d = json.loads(line)
                blocks = d.get("blocks", {})
                rows.append({"time": d.get("time", ""), "total": blocks.get("total", 0),
                             "state": blocks.get("state", 0), "write_rules": blocks.get("write_rules", 0)})
            except json.JSONDecodeError:
                continue
    rows = rows[-max(1, min(limit, 200)):]
    return {"records": rows, "count": len(rows)}
