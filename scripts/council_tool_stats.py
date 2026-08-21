# -*- coding: utf-8 -*-
"""星宿工具调用率与成本观察（2026-08-20 观察机制，真实使用数据源）：
扫 data/debates/*.json（CLI 落盘）+ data/sessions.db role='debate'（API 落库）的 turn 事件，
输出：会议数 / 星宿发言轮数 / 工具调用率（调了工具的轮数占比）/ 每轮平均调用；
成本：data/token_usage.csv 的 council_* 标签汇总。
收官判据（见 docs/COUNCIL-IMPLEMENTATION.md §5）：≥3 场真实会议后，
调用率 ≥80% 且单场成本 ≤ 预算上限且发言失败率不升 → 方向收官。
用法: python scripts/council_tool_stats.py
"""
import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import DATA_DIR

DEBATES_DIR = DATA_DIR / "data" / "debates"
SESSIONS_DB = DATA_DIR / "data" / "sessions.db"
TOKEN_CSV = DATA_DIR / "data" / "token_usage.csv"


def _turns_from_debates() -> list[dict]:
    """CLI 落盘：data/debates/*.json 的 DebateRecord.turns"""
    turns = []
    if not DEBATES_DIR.exists():
        return turns
    for p in sorted(DEBATES_DIR.glob("*.json")):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        for t in rec.get("turns", []):
            turns.append({"src": f"debates/{p.name}", **t})
    return turns


def _turns_from_sessions() -> list[dict]:
    """API 落库：sessions.db messages role='debate' 的 turn 事件"""
    turns = []
    if not SESSIONS_DB.exists():
        return turns
    try:
        conn = sqlite3.connect(SESSIONS_DB)
        rows = conn.execute(
            "SELECT content FROM messages WHERE role='debate' ORDER BY id ASC"
        ).fetchall()
        conn.close()
    except Exception as e:
        print(f"⚠ sessions.db 读取失败: {e}")
        return turns
    for (content,) in rows:
        try:
            ev = json.loads(content)
        except Exception:
            continue
        if isinstance(ev, dict) and ev.get("type") == "turn":
            turns.append({"src": "sessions.db", **ev})
    return turns


def _council_cost() -> dict:
    """成本台账：token_usage.csv 中 council_* 标签汇总（按标签分组，天下大同单文件）"""
    if not TOKEN_CSV.exists():
        return {}
    agg: dict[str, dict] = defaultdict(lambda: {"calls": 0, "input": 0, "output": 0})
    for line in TOKEN_CSV.read_text(encoding="utf-8").splitlines()[1:]:  # 跳过表头
        parts = line.split(",")
        if len(parts) < 6:
            continue
        _, sid, u, o, _, _ = parts[:6]
        if sid.startswith("council_"):
            agg[sid]["calls"] += 1
            agg[sid]["input"] += int(u or 0)
            agg[sid]["output"] += int(o or 0)
    return dict(agg)


def main() -> None:
    turns = _turns_from_debates() + _turns_from_sessions()
    if not turns:
        print("（暂无会议数据——跑一场会议后再观察）")
        return

    sage_turns = [t for t in turns if t.get("tool_calls", 0) is not None]
    total = len(sage_turns)
    # 工具化后样本 = turn 含 tool_calls 字段（历史数据无此字段自然排除，口径不被旧数据污染）
    post_tool = [t for t in sage_turns if "tool_calls" in t]
    with_tool = sum(1 for t in post_tool if (t.get("tool_calls") or 0) > 0)
    total_calls = sum(int(t.get("tool_calls") or 0) for t in post_tool)

    print(f"===== 星宿工具调用观察（{len(turns)} 条发言轮）=====")
    print(f"数据源: debates/*.json {len(_turns_from_debates())} 条 + sessions.db {len(_turns_from_sessions())} 条")
    print(f"发言轮总数: {total}（其中工具化后含 tool_calls 字段 {len(post_tool)} 轮）")
    if post_tool:
        print(f"工具化后调用率: {with_tool}/{len(post_tool)} 轮（{with_tool / len(post_tool) * 100:.0f}%）")
        print(f"工具总调用次数: {total_calls}（平均 {total_calls / max(len(post_tool), 1):.1f} 次/轮）")
    else:
        print("（暂无工具化后的发言轮——跑一场新会议后再观察）")
    print("每轮明细（tool_calls>0 的）:")
    for t in sage_turns:
        tc = int(t.get("tool_calls") or 0)
        if tc > 0:
            print(f"  [{t['src']}] {t.get('sage_name', '?')} R{t.get('round')} 调 {tc} 次")

    print("\n===== 会议成本（token_usage.csv council_* 标签）=====")
    cost = _council_cost()
    if not cost:
        print("（暂无 council 成本记录）")
    for sid, c in sorted(cost.items()):
        total_tok = c["input"] + c["output"]
        print(f"  {sid:28s} {c['calls']:3d} 次调用  in {c['input']:>7,}  out {c['output']:>6,}  合计 {total_tok:>8,} tok（≈¥{total_tok * 0.000002:.3f}-{total_tok * 0.000004:.3f}）")

    # 收官判据检查（预判，真实样本 ≥3 场后看）
    print("\n===== 收官判据预检（真实会议 ≥3 场后正式判定）=====")
    print(f"样本会议数: {len(set(t['src'].split('/')[0] for t in turns))}（判据要求 ≥3 场真实会议）")


if __name__ == "__main__":
    main()
