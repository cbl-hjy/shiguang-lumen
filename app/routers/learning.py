"""学习数据 API（B1 2026-08-27）：mastery 掌握台账可视化——深度学习工具面（练习/批改/间隔信号）的台账展示闭环。

用户拍板 B 类全做：掌握度数据不能只落盘不展示（机制做了=白做）。
"""

from fastapi import APIRouter
from pydantic import BaseModel

from app.tools.learning import _capped_rate, _is_correct, _knowledge_records, _ledger_read

router = APIRouter(prefix="/api/learning")


class MasteryItem(BaseModel):
    topic: str
    total: int  # 知识轨练习次数（正答率的分母）
    ok: int
    rate: float  # 正答率 0-1（只统计知识轨）
    last_ts: str
    trend: str  # 近 5 次正答率文本（近因参考）
    practice: int = 0  # 实践轨记录条数：不计入正答率，但必须看得见（2026-08-30 双轨）


class MasterySummary(BaseModel):
    total_records: int
    topics: int
    items: list[MasteryItem]
    judge_dist: dict[str, int]
    practice_records: int = 0  # 实践轨总条数（与知识轨分开报，前端别再笼统称"N 次练习"）


@router.get("/mastery")
def mastery_summary() -> MasterySummary:
    """掌握台账聚合：按 topic 分组（次数/正答率/最近时间/近因趋势）+ 判定分布。"""
    recs = _ledger_read()
    if not recs:
        return MasterySummary(total_records=0, topics=0, items=[], judge_dist={})

    by_topic: dict[str, list] = {}
    for r in recs:
        by_topic.setdefault(str(r.get("topic", "未分类")), []).append(r)

    items = []
    practice_total = 0
    for topic, rs in by_topic.items():
        rs_sorted = sorted(rs, key=lambda x: str(x.get("ts", "")), reverse=True)
        # 正答率只统计知识轨（2026-08-30，与 mastery_signal 同口径）：
        # 实践轨没有对错，留在分母里会凭空拉低正确率——每多一条实践记录就多一次误判。
        kr = _knowledge_records(rs)
        kr_sorted = sorted(kr, key=lambda x: str(x.get("ts", "")), reverse=True)
        practice_total += len(rs) - len(kr)
        ok = sum(1 for r in kr if _is_correct(r))
        recent = kr_sorted[:5]
        recent_ok = sum(1 for r in recent if _is_correct(r))
        items.append(
            MasteryItem(
                topic=topic,
                total=len(kr),
                ok=ok,
                # 与 mastery_signal 同口径（R1 + R1b）：既统一判定，也统一样本量封顶——
                # 否则 API 报 100% 而工具报 50%，前端与模型看到两个真相
                rate=round(_capped_rate(ok, len(kr)), 2),
                # 最近活动按全轨算：实践也算这个主题的一次活动
                last_ts=str(rs_sorted[0].get("ts", "")),
                # trend 同样封顶（否则「最近 1 次正答 100%」与工具层 50% 又是一对矛盾数据）
                trend=f"最近 {len(recent)} 次正答 {round(_capped_rate(recent_ok, len(recent)) * 100)}%",
                practice=len(rs) - len(kr),
            )
        )
    items.sort(key=lambda x: x.last_ts, reverse=True)

    judge_dist: dict[str, int] = {}
    for r in recs:
        j = str(r.get("judge", "未判定"))
        judge_dist[j] = judge_dist.get(j, 0) + 1

    return MasterySummary(
        total_records=len(recs),
        topics=len(items),
        items=items,
        judge_dist=judge_dist,
        practice_records=practice_total,
    )
