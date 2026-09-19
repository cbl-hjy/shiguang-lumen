"""token 用量统计（2026-08-17）：读 data/token_usage.csv，按日/周汇总打印。
用法：python scripts/usage_stats.py [today|week|all]
数据给觉察：给你看成本，不是系统考核。
"""
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

CSV = Path("data/token_usage.csv")


def _read():
    if not CSV.exists():
        print("暂无用量记录（data/token_usage.csv 不存在）")
        return []
    rows = []
    for i, ln in enumerate(CSV.read_text(encoding="utf-8").splitlines()):
        if i == 0 or not ln.strip():
            continue
        parts = ln.split(",")
        if len(parts) < 5:
            continue
        try:
            rows.append({
                "time": parts[0],
                "session": parts[1],
                "prompt": int(parts[2] or 0),
                "output": int(parts[3] or 0),
                "total": int(parts[4] or 0),
            })
        except ValueError:
            continue
    return rows


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "today"
    rows = _read()
    if not rows:
        return
    today = date.today()
    if mode == "today":
        keep = [r for r in rows if r["time"][:10] == today.isoformat()]
        label = f"今日 {today}"
    elif mode == "week":
        wk = today - timedelta(days=7)
        keep = [r for r in rows if r["time"][:10] >= wk.isoformat()]
        label = f"近 7 天（{wk} ~ {today}）"
    else:
        keep = rows
        label = "全部"

    by_day = defaultdict(lambda: [0, 0, 0])
    for r in keep:
        d = r["time"][:10]
        by_day[d][0] += r["prompt"]
        by_day[d][1] += r["output"]
        by_day[d][2] += r["total"]
    print(f"=== token 用量：{label}（{len(keep)} 轮）===")
    print(f"{'日期':<12}{'轮次':>5}{'prompt':>10}{'output':>10}{'total':>10}")
    for d in sorted(by_day):
        p, o, t = by_day[d]
        n = sum(1 for r in keep if r["time"][:10] == d)
        print(f"{d:<12}{n:>5}{p:>10}{o:>10}{t:>10}")
    tp = sum(r["prompt"] for r in keep)
    to = sum(r["output"] for r in keep)
    tt = sum(r["total"] for r in keep)
    print("-" * 48)
    print(f"{'合计':<12}{len(keep):>5}{tp:>10}{to:>10}{tt:>10}")


if __name__ == "__main__":
    main()
