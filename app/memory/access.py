# -*- coding: utf-8 -*-
"""记忆访问统计（2026-08-28 Phase1 M-1/M-2）：检索命中次数与最近访问日期。

- 数据源：衰减（rec）之外的"使用信号"与冷记忆降级判定依据
- 存 memory/access_stats.json：{entry_id: {"count": N, "last": "YYYY-MM-DD"}}
- 不动主文件格式（user_memory.md 零迁移风险）；写失败静默（统计是增强非主流程）
- 幂等防刷：同一天多次命中只更新 last，count 只 +1 一次（"用过的天数"更有意义）
"""
import json
from datetime import date
from pathlib import Path

from app.memory.schema import memory_dir
from app.utils.atomic_io import atomic_write_text

_STATS: dict | None = None
_DIRTY = False


def _path() -> Path:
    return memory_dir() / "access_stats.json"


def _load() -> dict:
    global _STATS
    if _STATS is None:
        try:
            p = _path()
            _STATS = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
        except Exception:
            _STATS = {}
    return _STATS


def touch(entry_id: str) -> None:
    """检索命中 → count+1（跨天）/ last=今天。幂等：同日多次命中只 +1 一次。"""
    global _DIRTY
    try:
        stats = _load()
        today = date.today().isoformat()
        rec = stats.get(entry_id)
        if rec is None:
            stats[entry_id] = {"count": 1, "last": today}
        else:
            if rec.get("last") != today:
                rec["count"] = int(rec.get("count", 0) or 0) + 1
            rec["last"] = today
        _DIRTY = True
    except Exception as e:
        print(f"[access] 统计 touch 失败（统计是增强，不影响主流程）: {e}", flush=True)


def flush() -> None:
    """落盘（原子写）。检索写回路径结束时调用一次，不每命中一次都写。"""
    global _DIRTY, _STATS
    if not _DIRTY or _STATS is None:
        return
    try:
        atomic_write_text(_path(), json.dumps(_STATS, ensure_ascii=False, indent=1))
        _DIRTY = False
    except Exception as e:
        print(f"[access] 统计落盘失败（统计是增强，不影响主流程）: {e}", flush=True)


def stats() -> dict:
    """全量统计（治理视图数据源）。"""
    return _load()


def never_used_ids() -> list[str]:
    """从未被检索命中的条目 id 列表（M-1 写入门槛数据化：count==0 = 疑似低价值）。"""
    stats = _load()
    return [eid for eid, rec in stats.items() if int(rec.get("count", 0) or 0) == 0]
