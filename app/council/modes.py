# -*- coding: utf-8 -*-
"""先贤会议 · 模式预设（M3 修正——2026-08-19 用户纠偏：模式=完整配置包，用户只选模式）。

设计依据（COUNCIL-DESIGN §3）：模式 = 参会者构成 + 会议规则 + 收敛标准的三元组。
本表是"参会者构成"的真相源：选模式即定星宿组合，用户无需手动选。
自由定义（用户自选星宿）= 最高权限，模式跑稳后再开（本轮不做）。
"""
from __future__ import annotations

# 预设模式表（id → 配置包）。sage_ids 为空 = 该模式当前书库不支持（如实标注，不硬凑）
MODES: dict[str, dict] = {
    "cross": {
        "name": "跨领域圆桌",
        "desc": "不同领域各一位星宿，交叉视角",
        "sage_ids": ["influence", "poor", "descartes"],  # 行为 × 决策 × 哲学（领域正交，M4 验证过）
        "max_rounds": 2,
    },
    "spectrum": {
        "name": "观点光谱",
        "desc": "对同一问题立场差异最大的星宿铺开交锋",
        "sage_ids": ["influence", "poor", "descartes"],  # 当前书库退化为预设组合（立场差异最大化采样待书库扩充）
        "max_rounds": 3,
    },
    "review": {
        "name": "实战评审",
        "desc": "各领域星宿评审你的方案，产出改进建议",
        "sage_ids": ["influence", "poor", "descartes"],
        "max_rounds": 2,
    },
    "deep": {
        "name": "同源深挖",
        "desc": "同一领域内部分歧定位（哲学/方法：笛卡尔理性演绎 × 培根经验归纳）",
        "sage_ids": ["descartes", "bacon"],  # 同领域两本（2026-08-19 培根入库后解锁）
        "max_rounds": 3,
    },
}


def get_mode(mode_id: str) -> dict | None:
    return MODES.get(mode_id)


def resolve_sages(mode_id: str, requested: list[str] | None) -> list[str]:
    """模式预设优先；requested 仅当无模式/自定义时用（自由定义未上，留接口）。"""
    if requested:
        return requested
    mode = MODES.get(mode_id or "cross")
    return mode["sage_ids"] if mode else []
