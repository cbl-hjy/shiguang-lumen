# -*- coding: utf-8 -*-
"""评估体系 v1 聚合层（2026-08-30，设计 docs/2026-08-30-EVAL-SYSTEM-DESIGN.md §0-§4）——
把各机制台账聚合成一块能力仪表盘（scoreboard）。

最高红线（设计 §0）：同一仪器禁第二份实现——
- 学习 section 直接调 learning.calibration_summary / retention_summary（输出原文进 section，不重算）
- 四态分布逐条调 evolution._maturity_state（派生逻辑唯一实现，import 复用）
- 纠错循环四指标的唯一实现在本模块 error_loop_summary（自 scripts/error_loop_metrics.py 上移，
  脚本改为 import 本模块的瘦 CLI——不是两份）
- 预算口径引用 tutor.BUDGET_WARN_CHARS / BUDGET_WARN_RATIO（懒加载防循环 import）

输出规约（设计 §3）：
- 无数据的指标明确 "没有数据"，不省略不报 0
- meta.descriptive_only=true + note + gaps（N=1 无对照组，全是描述性指标，不做因果宣称）
- 台账文件可能不存在（新用户）——全部按「没有数据」处理，不崩

per-current-user：路径解析全部委托各源模块的 path 函数（auth contextvar 现有模式）。
测试注入点 _METRICS_OVERRIDE 指向隔离目录，scoreboard() 计算期间映射进各源模块的
*_OVERRIDE 钩子（钩子优先于 uid 解析——与 learning._LEDGER_OVERRIDE 等同一惯例），
源函数原样复用，测试零侵入生产路径。
"""
from __future__ import annotations

import contextlib
import json
from datetime import datetime, timedelta
from pathlib import Path

from app.auth_core import get_current_user_id
from app.config import DATA_DIR

NO_DATA = "没有数据"

# 测试注入点（对齐 learning._LEDGER_OVERRIDE / evolution._EVO_*_OVERRIDE 惯例）：
# 指向隔离目录，布局 = per-user 数据目录 + data/ 子目录放全局台账：
#   <dir>/mastery.jsonl            <dir>/plan.json          <dir>/memory/skills.md
#   <dir>/data/error_ledger.jsonl  <dir>/data/playbook_deltas.jsonl
#   <dir>/data/skill_grounding.jsonl  <dir>/data/injection_log.jsonl
_METRICS_OVERRIDE: Path | None = None

# 台账时间戳格式（injection_log / mastery 同一套字面量，见 learning._TS_FMT）
_TS_FMT = "%Y-%m-%d %H:%M:%S"

# gaps（设计 §3）：「应该有但没有」的指标显式列出，防"看不见=不存在"
GAPS = [
    "跨域类比引擎未落地——无数据",
    "verify 调用率统计未接——无数据",
]

META_NOTE = "N=1 无对照组：全部指标为描述性趋势，非因果证据"


@contextlib.contextmanager
def _isolation_hooks():
    """_METRICS_OVERRIDE 置位时，把隔离目录映射进各源模块的 *_OVERRIDE 钩子（算完恢复）。"""
    if _METRICS_OVERRIDE is None:
        yield
        return
    from app.agent import error_loop, evolution
    from app.tools import learning, plan

    base = _METRICS_OVERRIDE
    saved = (
        error_loop._LEDGER_OVERRIDE,
        evolution._EVO_SKILLS_OVERRIDE,
        evolution._EVO_DELTAS_OVERRIDE,
        evolution._EVO_GROUNDING_OVERRIDE,
        learning._LEDGER_OVERRIDE,
        plan._PLAN_OVERRIDE,
    )
    error_loop._LEDGER_OVERRIDE = base / "data" / "error_ledger.jsonl"
    evolution._EVO_SKILLS_OVERRIDE = base / "memory" / "skills.md"
    evolution._EVO_DELTAS_OVERRIDE = base / "data" / "playbook_deltas.jsonl"
    evolution._EVO_GROUNDING_OVERRIDE = base / "data" / "skill_grounding.jsonl"
    learning._LEDGER_OVERRIDE = base / "mastery.jsonl"
    plan._PLAN_OVERRIDE = base / "plan.json"
    try:
        yield
    finally:
        (
            error_loop._LEDGER_OVERRIDE,
            evolution._EVO_SKILLS_OVERRIDE,
            evolution._EVO_DELTAS_OVERRIDE,
            evolution._EVO_GROUNDING_OVERRIDE,
            learning._LEDGER_OVERRIDE,
            plan._PLAN_OVERRIDE,
        ) = saved


def _ledger_paths() -> dict[str, Path]:
    """各台账路径——非注入模式全部委托源模块的 path 函数（同一仪器禁第二份实现）。"""
    if _METRICS_OVERRIDE is not None:
        base = _METRICS_OVERRIDE
        return {
            "error_ledger": base / "data" / "error_ledger.jsonl",
            "mastery": base / "mastery.jsonl",
            "playbook_deltas": base / "data" / "playbook_deltas.jsonl",
            "skills": base / "memory" / "skills.md",
            "skill_grounding": base / "data" / "skill_grounding.jsonl",
            "plan": base / "plan.json",
            "injection_log": base / "data" / "injection_log.jsonl",
        }
    from app.agent import error_loop, evolution
    from app.tools import learning, plan

    return {
        "error_ledger": error_loop._ledger_path(),
        "mastery": learning.MASTERY_LEDGER(),
        "playbook_deltas": evolution.DELTAS_FILE(),
        "skills": evolution.SKILLS_FILE(),
        "skill_grounding": evolution.GROUNDING_FILE(),
        "plan": plan.PLAN_FILE(),
        "injection_log": DATA_DIR / "data" / "injection_log.jsonl",  # 全局台账（tutor 写入路径）
    }


def load_jsonl(path: Path) -> list[dict]:
    """读 jsonl 台账：文件不存在 → []；坏行跳过（append-only 台账单行损坏不拖死统计）。"""
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except Exception as _e:
                print(f'[capability] 跳过异常项: {_e}', file=__import__('sys').stderr)
                continue
        if isinstance(rec, dict):
            out.append(rec)
    return out


def _ratio(num: int, den: int) -> dict:
    """比率统一结构：{"pct", "num", "den"}——pct 为 0-1 小数，渲染归 CLI/前端。"""
    return {"pct": round(num / den, 4), "num": num, "den": den}


# ---------- 纠错循环（逻辑上移自 scripts/error_loop_metrics.py，全仓库唯一实现） ----------


def error_loop_summary(recs: list[dict]) -> dict:
    """error_ledger 四指标（设计 docs/2026-08-30-ERROR-LOOP-DESIGN.md §6，口径与原脚本逐行一致）：
    - 连续错误率：seq_end 序列长度 ≥2 的占比
    - 自我恢复率：seq_end 以 recovered 收尾的占比
    - 升级次数/升级准确率：n=3 升级次数可报；准确率需人工抽检语料（台账不含用户消息）→ 没有数据
    - 循环逃脱率：loop=true 序列中【换工具成功收尾】占比（近似：recovered_with != loop_tool）
    """
    seq_ends = [r for r in recs if r.get("event") == "seq_end"]
    errors = [r for r in recs if r.get("event") == "error"]
    out = {
        "records": {"errors": len(errors), "seq_ends": len(seq_ends)},
        "连续错误率": NO_DATA,
        "自我恢复率": NO_DATA,
        "升级次数": NO_DATA,
        "升级准确率": NO_DATA,
        "循环逃脱率": NO_DATA,
    }
    if not recs:
        return out
    escalated = sum(1 for r in errors if int(r.get("consecutive", 0)) == 3)
    out["升级次数"] = escalated  # 计数不是比率——有台账时 0 次是真实测量值
    if not seq_ends:
        return out
    ge2 = sum(1 for r in seq_ends if int(r.get("seq_len", 0)) >= 2)
    out["连续错误率"] = _ratio(ge2, len(seq_ends))
    rec = sum(1 for r in seq_ends if r.get("outcome") == "recovered")
    out["自我恢复率"] = _ratio(rec, len(seq_ends))
    loops = [r for r in seq_ends if r.get("loop")]
    if loops:
        escaped = sum(
            1
            for r in loops
            if r.get("outcome") == "recovered"
            and r.get("recovered_with")
            and r.get("recovered_with") != r.get("loop_tool")
        )
        out["循环逃脱率"] = _ratio(escaped, len(loops))
    return out


def _error_loop_section() -> dict:
    from app.agent import error_loop

    return error_loop_summary(load_jsonl(error_loop._ledger_path()))


# ---------- 学习（复用 learning 汇总函数，输出原文进 section——不重算） ----------


def _learning_section() -> dict:
    from app.tools import learning

    recs = learning._ledger_read()
    know = learning._knowledge_records(recs)
    topics = {str(r.get("topic", "")) for r in know if r.get("topic")}
    if topics:
        retested = {
            str(r.get("topic", "")) for r in know if r.get("is_retest") is True and r.get("topic")
        }
        coverage = _ratio(len(retested), len(topics))
        coverage["口径"] = "有复测记录的主题数 / 有练习记录的主题数（知识轨）"
    else:
        coverage = NO_DATA
    return {
        "calibration": learning.calibration_summary(recs),
        "retention": learning.retention_summary(recs),
        "retest_coverage": coverage,
    }


# ---------- ACE playbook（delta 采纳率新算；四态分布/净值复用 evolution 派生函数） ----------


def _playbook_section() -> dict:
    from app.agent import evolution

    # delta 采纳率（journal 口径：applied = add+bump+revise 操作数，rejected = dropped 操作数——
    # journal 格式见 evolution.apply_delta：{delta_id, ts, add, bump, revise, dropped}）
    deltas = load_jsonl(evolution.DELTAS_FILE())
    adoption = NO_DATA
    if deltas:
        applied = sum(
            int(d.get("add", 0)) + int(d.get("bump", 0)) + int(d.get("revise", 0)) for d in deltas
        )
        rejected = sum(int(d.get("dropped", 0)) for d in deltas)
        if applied + rejected:
            adoption = {
                "pct": round(applied / (applied + rejected), 4),
                "applied": applied,
                "rejected": rejected,
                "deltas": len(deltas),
            }

    blocks = evolution._blocks(evolution.SKILLS_FILE())
    if not blocks:
        return {"delta_adoption": adoption, "maturity_distribution": NO_DATA,
                "net_top3": NO_DATA, "net_bottom3": NO_DATA}

    # 四态分布：成熟度是 sid（谱系）级属性——每 sid 取最新版本计数，逐条调 _maturity_state
    # （派生逻辑唯一实现在 evolution，import 复用）；无 sid 旧格式块按 draft 计（同 list_skills 口径）
    sessions_map = evolution._sid_grounded_sessions()
    latest: dict[str, tuple[dict, str]] = {}  # sid → (meta, block)
    legacy_draft = 0
    for b in blocks:
        m = evolution._parse_meta(b)
        if m is None:
            legacy_draft += 1
            continue
        cur = latest.get(m["sid"])
        if cur is None or m["version"] > cur[0]["version"]:
            latest[m["sid"]] = (m, b)
    dist = {"draft": legacy_draft, "tested": 0, "mature": 0, "deprecated": 0}
    nets = []
    for sid, (m, b) in latest.items():
        state = evolution._maturity_state(m, len(sessions_map.get(sid, set())))
        dist[state] += 1
        nets.append(
            {
                "sid": sid,
                "desc": evolution._skill_desc(b)[:40],
                "helpful": m["helpful"],
                "harmful": m["harmful"],
                "net": m["helpful"] - m["harmful"],
                "state": state,
            }
        )
    nets.sort(key=lambda x: -x["net"])
    return {
        "delta_adoption": adoption,
        "maturity_distribution": dist,
        "net_top3": nets[:3] if nets else NO_DATA,
        "net_bottom3": list(reversed(nets[-3:])) if nets else NO_DATA,
    }


# ---------- 计划（完成度 + 证据档位构成） ----------


def _plan_section() -> dict:
    from app.tools import plan as plan_mod

    plan = plan_mod._load()
    items = plan.get("items") or []
    if not plan.get("goal") or not items:
        return {"completion": NO_DATA, "evidence_tiers": NO_DATA, "note": "当前无活跃计划"}
    done = sum(1 for it in items if it.get("passes"))
    tiers_raw = [
        it["evidence"]["type"]
        for it in items
        if it.get("passes")
        and isinstance(it.get("evidence"), dict)
        and it["evidence"].get("type") in plan_mod.EVIDENCE_TYPES
    ]
    if tiers_raw:
        tiers = {
            t: {"count": tiers_raw.count(t), "pct": round(tiers_raw.count(t) / len(tiers_raw), 4)}
            for t in plan_mod.EVIDENCE_TYPES
        }
    else:
        tiers = NO_DATA
    return {
        "goal": plan["goal"],
        "completion": _ratio(done, len(items)),
        "evidence_tiers": tiers,
    }


# ---------- 预算（injection_log 最近 7 天注入占比，口径参照 tutor 预算哨兵） ----------


def _budget_section(paths: dict[str, Path]) -> dict:
    from app.agent.tutor import BUDGET_WARN_CHARS, BUDGET_WARN_RATIO  # 懒加载防循环 import

    window_chars = BUDGET_WARN_CHARS / BUDGET_WARN_RATIO  # 5% 阈值反推窗口估算（字符）
    cutoff = datetime.now() - timedelta(days=7)
    samples: list[tuple[str, int]] = []
    for r in load_jsonl(paths["injection_log"]):
        try:
            ts = datetime.strptime(str(r.get("time", ""))[:19], _TS_FMT)
        except ValueError:
            continue
        total = (r.get("blocks") or {}).get("total")
        if ts >= cutoff and isinstance(total, (int, float)):
            samples.append((str(r.get("time", ""))[:10], int(total)))
    if not samples:
        return {"window_days": 7, "avg_total_chars": NO_DATA, "avg_window_ratio": NO_DATA,
                "daily": NO_DATA}
    avg_total = round(sum(t for _, t in samples) / len(samples))
    by_day: dict[str, list[int]] = {}
    for day, t in samples:
        by_day.setdefault(day, []).append(t)
    daily = [
        {"date": d, "avg_total_chars": round(sum(v) / len(v)),
         "avg_window_ratio": round(sum(v) / len(v) / window_chars, 4)}
        for d, v in sorted(by_day.items())
    ]
    return {
        "window_days": 7,
        "samples": len(samples),
        "avg_total_chars": avg_total,
        "avg_window_ratio": round(avg_total / window_chars, 4),
        "daily": daily,
    }


# ---------- 元指标：各台账最后写入时间（数据停了 = 机制可能没被用起来，盲区的盲区） ----------


def _freshness(paths: dict[str, Path]) -> dict:
    out = {}
    for name, p in paths.items():
        try:
            out[name] = (
                datetime.fromtimestamp(p.stat().st_mtime).strftime(_TS_FMT)
                if p.exists()
                else NO_DATA
            )
        except Exception:
            out[name] = NO_DATA
    return out


# ---------- 总装 ----------


def scoreboard() -> dict:
    """能力仪表盘（设计 §3 输出规约）——全部指标描述性，无告警/门控/达标判定。"""
    with _isolation_hooks():
        paths = _ledger_paths()
        sections = {
            "error_loop": _error_loop_section(),
            "learning": _learning_section(),
            "playbook": _playbook_section(),
            "plan": _plan_section(),
            "budget": _budget_section(paths),
            "freshness": _freshness(paths),
        }
    uid = get_current_user_id()
    return {
        "generated_at": datetime.now().strftime(_TS_FMT),
        "uid": uid or ("(测试注入)" if _METRICS_OVERRIDE is not None else "(未登录/全局)"),
        "sections": sections,
        "meta": {
            "descriptive_only": True,
            "note": META_NOTE,
            "gaps": list(GAPS),
        },
    }
