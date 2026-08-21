# -*- coding: utf-8 -*-
"""先贤会议 · 数据模型（M1 骨架）

设计依据：docs/COUNCIL-DESIGN.md（设计共识）+ research/2026-08-19-council-framework-research.md（选型）
- SageCard：星笺（data/sages/*.json 的 Pydantic 视图，供发言注入）
- DebateTurn / ModeratorVerdict / DebateReport：会议记录与判定 schema
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from pydantic import BaseModel, Field


# ---------- 星笺 ----------
class Claim(BaseModel):
    slug: str = ""
    title: str = ""
    quote: str = ""
    evidence: str = ""  # V1 跨域佐证（2026-08-20 对齐：蒸馏产出叙述性字符串；list 旧数据容错）
    novel_question: str = ""
    derived_answer: str = ""
    novelty: str = ""
    cases: list[str] = []
    source: str = ""

    @field_validator("evidence", mode="before")
    @classmethod
    def _evidence_to_str(cls, v):
        """容错：旧蒸馏产物 evidence 可能是 list（空列表或数组）——统一转字符串"""
        if isinstance(v, list):
            return "；".join(str(x) for x in v) if v else ""
        return v or ""


class Boundaries(BaseModel):
    limits: list[str] = []
    blindspots: list[str] = []
    unproven: list[str] = []
    strongest_opposition: str = ""


class SageCard(BaseModel):
    """星笺——星宿 agent 的立场来源（M1 无 RAPTOR 树，立场卡即全部知识）"""

    id: str
    name: str
    book: str = ""
    author: str = ""
    year: str = ""
    stance: str
    core_claims: list[Claim] = []
    skeleton: list[str] = []
    boundaries: Boundaries = Boundaries()

    def stance_block(self, budget: int = 700) -> str:
        """压缩为星宿 agent 的立场注入块（token 可控）"""
        parts = [f"立场：{self.stance}", "核心观点："]
        for c in self.core_claims:
            line = f"- {c.title}"
            if c.quote:
                line += f"（原文：{c.quote[:50]}）"
            parts.append(line)
        b = self.boundaries
        limits = "；".join(b.limits[:2]) or "无"
        parts.append(f"边界（此书不覆盖/盲点）：{limits}")
        text = "\n".join(parts)
        if len(text) > budget:
            cut = text[:budget]
            return cut.rsplit("\n", 1)[0]
        return text


# ---------- 会议记录 ----------
class DebateTurn(BaseModel):
    round: int
    sage_id: str
    sage_name: str
    speech: str
    words: int = 0
    tool_calls: int = 0  # 本轮工具调用次数（2026-08-20 观察机制：工具调用率数据源；旧数据默认 0 兼容）


class ModeratorVerdict(BaseModel):
    """主持人判定（单调用 LLM-as-judge，不投票——[R8] 实测最稳）"""

    repeated: bool = False
    off_topic: bool = False
    new_claims: int = 0
    marginal_gain: bool = True
    should_converge: bool = False
    notes: str = ""


class DebateReport(BaseModel):
    """综合报告——第一节必为"对你有用的结论"（收益判定铁律）"""

    actionable: list[str] = Field(default_factory=list)
    consensus: list[str] = Field(default_factory=list)
    divergences: list[str] = Field(default_factory=list)
    complementarities: list[str] = Field(default_factory=list)
    unanswered: list[str] = Field(default_factory=list)


class DebateRecord(BaseModel):
    """一场研讨会的完整记录（落盘 data/debates/<id>.jsonl 的结构）"""

    id: str
    question: str
    mode: str = "跨领域圆桌"
    sages: list[str] = []
    max_rounds: int = 4
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    turns: list[DebateTurn] = []
    verdicts: list[ModeratorVerdict] = []
    report: DebateReport | None = None
    ended_reason: Literal["converged", "stall", "max_rounds", "user_stop"] = "max_rounds"
