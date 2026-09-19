# -*- coding: utf-8 -*-
"""B 实验（提醒 MRT）· 拦截层核心（2026-09-17）

设计依据：`docs/2026-09-17-EFFECT-MEASUREMENT-EXPERIMENT-DESIGN.md` §3（自然拦截制）。

- **判定 arm**：模型自主注册原样；每条提醒**投递前**经本层判定：
  - `sent`（抽中发）/ `suppressed`（抽中拦）——16:00–22:00 到期的提醒 50% 随机
  - `exempt_time`（非 16-22 点到期，照发）/ `exempt_kw`（含豁免词，永不抽签）
  - `off`（实验关=默认，不介入、不写日志）
- **保底规则（1+2+4）**：时段限定 + 关键词豁免（考试/报名/截止/面试/缴费/提交/重要）；不启用人工否决。
- **独立实验日志**：`data/mrt/log.jsonl`（不动生产表结构）；实验期不查看分配（盲化）。
- 红线：本层只决定"发/不发"，不改提醒内容与时机（模型决策不受干扰）。
"""
from __future__ import annotations

import json
import random
import time
from pathlib import Path

from app.config import DATA_DIR, MRT_EXPERIMENT

EXEMPT_WORDS = ["考试", "报名", "截止", "面试", "缴费", "提交", "重要"]
WINDOW_START, WINDOW_END = 16, 22  # 参与抽签的到期时段 [16, 22)


def log_path() -> Path:
    return DATA_DIR / "data" / "mrt" / "log.jsonl"


def decide(w: dict) -> str:
    """判定一条到期提醒的 arm。实验关 → "off"（不介入、不日志）。"""
    if not MRT_EXPERIMENT:
        return "off"
    reason = str(w.get("reason") or "")
    # 保底②：关键词豁免（永不抽签）
    if any(k in reason for k in EXEMPT_WORDS):
        return "exempt_kw"
    # 保底①：时段限定（非 16-22 点到期的照发）
    due_at = str(w.get("at") or "")
    try:
        hour = int(due_at[11:13])
    except ValueError:
        return "exempt_time"  # 格式异常=照发（保守）
    if not (WINDOW_START <= hour < WINDOW_END):
        return "exempt_time"
    # 抽签：50%/50%（真随机；分配记入日志，期末可统计校验 50% 比例）
    return "suppressed" if random.random() < 0.5 else "sent"


def log_point(uid: str | None, w: dict, arm: str) -> None:
    """写实验日志（独立文件）。失败不打断投递，但打点可见（不静默）。"""
    if arm == "off":
        return
    try:
        p = log_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "uid": uid,
            "wid": w.get("id"),
            "due_at": w.get("at"),
            "reason": str(w.get("reason") or "")[:40],
            "arm": arm,
            "settled": None,  # 结算后填 0/1（近端行为是否发生）
            "settled_ts": None,
        }
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"[mrt] 实验日志写入失败（不影响投递）: {e}", flush=True)


# ---------- 结算（逻辑在 app、脚本薄包装——唯一一份）----------
_FMT = "%Y-%m-%dT%H:%M:%S"


def _user_db(uid: str, name: str) -> Path:
    return DATA_DIR / "data" / "users" / uid / name


def settle_one(entry: dict, now_dt) -> dict | None:
    """结算单条：24h 窗口内近端行为（messages 主判定 / daily_activity 辅判定）。

    返回更新后的 entry；未到结算时点/不适用 → None。
    """
    import sqlite3
    from datetime import datetime, timedelta

    if entry.get("settled") is not None:
        return None
    if entry.get("arm") not in ("sent", "suppressed"):
        return None  # exempt_* 不参与分析（保留记录）
    uid = entry.get("uid")
    if not uid:
        return None
    try:
        due = datetime.strptime(entry["due_at"], _FMT)
    except (KeyError, TypeError, ValueError):
        return None
    end = due + timedelta(hours=24)
    if now_dt < end:
        return None  # 窗口未结束，等下次

    hit = 0
    sdb = _user_db(uid, "sessions.db")
    if sdb.exists():
        try:
            conn = sqlite3.connect(str(sdb))
            try:
                n = conn.execute(
                    "SELECT COUNT(*) FROM messages WHERE role='user' AND created_at>=? AND created_at<=?",
                    (due.strftime("%Y-%m-%d %H:%M:%S"), end.strftime("%Y-%m-%d %H:%M:%S")),
                ).fetchone()[0]
            finally:
                conn.close()
            hit = 1 if n > 0 else hit
        except Exception as e:
            print(f"[mrt] messages 查询失败 {uid}: {e}", flush=True)
    wdb = _user_db(uid, "wakeups.db")
    if not hit and wdb.exists():
        try:
            conn = sqlite3.connect(str(wdb))
            try:
                days = sorted({due.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")})
                n = conn.execute(
                    "SELECT COUNT(*) FROM daily_activity WHERE date IN (?,?)", days,
                ).fetchone()[0]
            finally:
                conn.close()
            hit = 1 if n > 0 else hit
        except Exception as e:
            print(f"[mrt] daily_activity 查询失败 {uid}: {e}", flush=True)

    entry["settled"] = hit
    entry["settled_ts"] = now_dt.strftime("%Y-%m-%d %H:%M:%S")
    return entry


def settle_entries(now_dt=None) -> tuple[int, int, int]:
    """结算全部：读日志 → 逐条 settle_one → 覆写回（不删文件）。

    返回 (updated, settled_total, total)。**盲化**：不输出分配详情。
    """
    from datetime import datetime

    now_dt = now_dt or datetime.now()
    p = log_path()
    if not p.exists():
        return (0, 0, 0)
    lines = [ln for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]
    entries = [json.loads(ln) for ln in lines]
    updated = 0
    for i, e in enumerate(entries):
        new = settle_one(e, now_dt)
        if new is not None:
            entries[i] = new
            updated += 1
    if updated:
        p.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in entries) + "\n",
                     encoding="utf-8")
    done = sum(1 for e in entries if e.get("settled") is not None)
    return (updated, done, len(entries))
