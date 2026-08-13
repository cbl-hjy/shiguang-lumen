# -*- coding: utf-8 -*-
"""行为校准 v0.1：从真实使用会话统计行为分布，注入 persona（阶段 2）。

警告（写死）：
- woshi/模拟/回归门/脚本会话是失真数据，禁止用作校准源——用失真数据校准=固化失真
- 真实使用样本 <10 天 → 输出标"v0.1 样本不足，v0.2 待真实数据"
"""
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.db import sessions as S

# 失真来源排除（标题含这些 = 脚本/模拟/测试）
EXCLUDE = ["回归门", "去重测试", "woshi", "模拟", "探针", "GATE", "测试消息", "1+1", "讲一下什么是过拟合"]
QUESTION_MARKERS = ["？", "?", "为什么", "怎么", "如何", "是啥", "吗", "什么意思", "解释", "讲一下", "区别", "为什么"]
SHORT_LEN = 20  # 短回复阈值（字）


def is_real(msg: str, title: str) -> bool:
    if any(k in title for k in EXCLUDE):
        return False
    # 排除明显的脚本消息
    if len(msg) < 4 and msg not in {"你好", "继续", "嗯", "对"}:
        return False
    return True


def main():
    with S.get_conn() as c:
        rows = c.execute(
            "SELECT s.title, m.role, m.content FROM messages m JOIN sessions s ON s.id=m.session_id "
            "WHERE m.role='user' ORDER BY m.id"
        ).fetchall()

    # 按会话聚合用户消息序列
    sessions_seq = {}
    for r in rows:
        if r["role"] != "user" or not r["content"]:
            continue
        if not is_real(r["content"], r["title"] or ""):
            continue
        sessions_seq.setdefault(r["title"] or "(无标题)", []).append(r["content"])

    total_msgs = sum(len(v) for v in sessions_seq.values())
    days = c.execute("SELECT COUNT(DISTINCT substr(created_at,1,10)) d FROM sessions").fetchone()["d"]

    # 指标 1：追问率（疑问句占比）
    q = sum(1 for v in sessions_seq.values() for m in v if any(mk in m for mk in QUESTION_MARKERS))
    # 指标 2：短回复率
    s = sum(1 for v in sessions_seq.values() for m in v if len(m) < SHORT_LEN)
    # 指标 3：话题跳转率（相邻消息关键词重叠 <0.2 占比，简单词袋近似）
    def tokens(t: str) -> set:
        return set(re.findall(r"[\u4e00-\u9fa5]{2,}", t))

    jumps, pairs = 0, 0
    for v in sessions_seq.values():
        for a, b in zip(v, v[1:]):
            pairs += 1
            ta, tb = tokens(a), tokens(b)
            if not ta or not tb:
                continue
            overlap = len(ta & tb) / max(len(ta), len(tb))
            if overlap < 0.2:
                jumps += 1
    # 指标 4：会话结束时刻 + 平均轮数
    hours = Counter()
    with S.get_conn() as c2:
        last_hours = c2.execute(
            "SELECT s.id, MAX(m.created_at) t FROM messages m JOIN sessions s ON s.id=m.session_id "
            "WHERE m.role='user' GROUP BY s.id"
        ).fetchall()
        for r in last_hours:
            try:
                hours[int(r["t"][11:13])] += 1
            except Exception:
                pass

    profile = {
        "version": "0.1",
        "sample_days": days,
        "sample_warning": "v0.1 样本不足（<10 天），v0.2 待真实数据" if days < 10 else "",
        "total_real_messages": total_msgs,
        "追问率": round(q / total_msgs, 3) if total_msgs else 0,
        "短回复率": round(s / total_msgs, 3) if total_msgs else 0,
        "话题跳转率": round(jumps / max(pairs, 1), 3),
        "会话结束时刻分布": {f"{h:02d}点": c for h, c in sorted(hours.items())},
    }
    out = ROOT / "memory" / "personas" / "behavior_profile.json"
    out.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(profile, ensure_ascii=False, indent=2))
    print(f"\n→ 已写入 {out.relative_to(ROOT)}")
    # 合理性检查：全极端 = 筛选漏了失真会话
    if total_msgs and (profile["追问率"] > 0.95 or profile["短回复率"] < 0.05):
        print("⚠️ 分布全极端——筛选条件可能漏了失真会话，检查 EXCLUDE")


if __name__ == "__main__":
    main()
