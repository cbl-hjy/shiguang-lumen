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


def _read_trace() -> list[dict]:
    if not TRACE.exists():
        return []
    out = []
    for line in TRACE.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _agg_trace(evs: list[dict]) -> dict:
    """聚合 trace：工具调用（次数/成功率/平均耗时）、错误、对话延迟"""
    tools: dict[str, dict] = defaultdict(lambda: {"calls": 0, "ok": 0, "err": 0, "total_ms": 0})
    # 工具耗时：按 (run_id, name) 顺序配对 start/end（trace 事件有 ts 时间戳）
    starts: dict[tuple, str] = {}
    errors: dict[str, int] = defaultdict(int)
    run_durs: list[int] = []
    n_tools = 0

    for ev in evs:
        t = ev.get("type")
        if t == "tool_start":
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
        elif t == "run_end":
            d = ev.get("dur_ms")
            if isinstance(d, (int, float)) and d > 0:
                run_durs.append(int(d))

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

    # 延迟：平均 + p95
    avg_ms = round(sum(run_durs) / len(run_durs)) if run_durs else 0
    p95 = 0
    if run_durs:
        run_durs.sort()
        p95 = run_durs[min(len(run_durs) - 1, int(len(run_durs) * 0.95))]

    return {
        "runs": len(run_durs),
        "tool_calls": n_tools,
        "tool_stats": tool_stats,
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
    evs = _read_trace()
    trace = _agg_trace(evs)
    token = _agg_token()
    return {
        "trace": trace,
        "token": token,
        "council_errors": _agg_council_errors(),
        "generated_at": __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
