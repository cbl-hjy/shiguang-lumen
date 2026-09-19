# -*- coding: utf-8 -*-
"""记忆生命周期（2026-08-28 Phase1 M-3）：冷记忆降级出向量索引——不删文件，只退出检索。

设计依据（文献）：
- FadeMem（arXiv:2601.18642）：保留度 = 指数衰减 × 语义相关 × 访问频率，低于阈值降级而非删除
- Harvard 2505.16067：全量写入 < 无记忆——低质/无用的记忆必须能离开检索池

规则（保守，绝不误伤）：
- 从未被检索命中（access count==0 或缺失）且 年龄 > 类别半衰期 × 3（保留分 ≈ 5%）
  → 从向量库删除（文件保留在 user_memory.md，治理视图/用户可找回）
- 用过一次的记忆永不自动降级（访问频率是"它有用"的最强信号）
- 每轮上限 max_demote（渐进式，防一次性大扫除的意外）
"""
from datetime import date

from app.memory import access, vector
from app.memory.schema import cat_tau
from app.memory.store import read_entries


def demote_cold_memories(max_demote: int = 20) -> int:
    """扫描并降级冷记忆（原子删向量，文件不动）。返回降级条数。失败不中断。"""
    try:
        stats = access.stats()
        entries = read_entries()
        today = date.today()
        demoted = 0
        for e in entries:
            if demoted >= max_demote:
                break
            rec = stats.get(e.entry_id) or {}
            if int(rec.get("count", 0) or 0) > 0:
                continue  # 用过的不碰——访问频率是"有用"的最强信号
            try:
                days = max(0, (today - date.fromisoformat(e.created_at)).days)
            except Exception as _de:
                print(f"[lifecycle] 条目日期不可解析，跳过: {_de}", file=__import__('sys').stderr)
                continue
            tau = cat_tau(e.category)
            if days <= tau * 3:
                continue  # 未超龄（保留分仍 >5%）
            try:
                vector.delete(vector.entry_id(e.content))
                demoted += 1
            except Exception as _ve:
                print(f"[lifecycle] 单条降级失败（不中断整轮）: {_ve}", file=__import__('sys').stderr)
                continue
        if demoted:
            print(
                f"[lifecycle] 降级 {demoted} 条冷记忆出索引（文件保留，治理视图可找回）",
                flush=True,
            )
        return demoted
    except Exception as e:
        print(f"[lifecycle] 降级扫描失败（不影响主流程）: {e}", flush=True)
        return 0


def demote_entry(content: str) -> bool:
    """手动降级单条记忆（M-1 治理操作闭环，2026-08-29）：用户主动让某条记忆"休眠"——
    退出向量检索（文件保留可找回）。与自动降级同机制；不存在/已降级返回 False。"""
    try:
        # 幂等：向量库里没有这条 → 已降级/不存在
        if vector.entry_id(content) not in vector.existing_ids():
            return False
        vector.delete(vector.entry_id(content))
        print(f"[lifecycle] 手动降级: {content[:60]}", flush=True)
        return True
    except Exception as e:
        print(f"[lifecycle] 手动降级失败（不影响主流程）: {e}", flush=True)
        return False


def cold_memories_preview() -> list[dict]:
    """治理视图：当前会被降级的冷记忆清单（含原因），只读不动作。"""
    out = []
    try:
        stats = access.stats()
        today = date.today()
        for e in read_entries():
            rec = stats.get(e.entry_id) or {}
            if int(rec.get("count", 0) or 0) > 0:
                continue
            try:
                days = max(0, (today - date.fromisoformat(e.created_at)).days)
            except Exception as _de:
                print(f"[lifecycle] 条目日期不可解析，跳过: {_de}", file=__import__('sys').stderr)
                continue
            tau = cat_tau(e.category)
            if days > tau * 3:
                out.append(
                    {
                        "id": e.entry_id,
                        "content": e.content[:80],
                        "category": e.category,
                        "age_days": days,
                        "tau": tau,
                    }
                )
        out.sort(key=lambda x: x["age_days"], reverse=True)
    except Exception as e:
        print(f"[lifecycle] 冷记忆预览失败: {e}", flush=True)
    return out
