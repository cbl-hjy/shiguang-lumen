# -*- coding: utf-8 -*-
"""harness 层上下文策略接口（2026-09-02，设计 §4.0 docs/2026-09-01-STATEFRESH-V2-EXPERIMENT-DESIGN.md）。

对齐 Anthropic Managed Agents（2026-04-08 一手）：session = append-only 事件日志（durable + 可查询），
harness = 对上下文做任意变换（compaction/trimming/cache 全是这一层）——
"opinionated about the shape of these interfaces, not about what runs behind them"。

本模块是这个抽象的落地：
- 形状定死：**一个方法** `prepare_history(events, sid, uid) -> (messages, est)`
- 实现可换：`SummaryCompaction`（现有压缩，零逻辑改动的纯包装）/ 未来 `StateExternalization`（V2 实验臂 B）
- 换实现 = 注册一行 + 环境变量切换（度量"换实现成本"的仪器本身）

纪律：
- 本文件**不写任何压缩逻辑**（同一仪器禁止第二份实现——只调 session_compress）
- 触发阈值/防抖仍在 session_compress 里由代码锁死（触发归代码，内容归模型）
- 接口面只允许一个方法，多一个方法都算过度工程（N=1 单人产品的复杂度纪律）
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from app.agent.session_compress import apply_compaction

DEFAULT_STRATEGY = "summary"  # 现状实现（对照组基线：行为必须与改造前逐字节一致）


@runtime_checkable
class ContextStrategy(Protocol):
    """上下文策略接口：session 原始事件 → 本轮注入的消息列表。"""

    name: str

    def prepare_history(self, history: list[Any], sid: str, uid: str | None = None) -> tuple[list[Any], int]:
        """返回 (注入消息列表, 预算估算)。失败必须返回原 history（幂等，不阻断主流程）。"""
        ...


class SummaryCompaction:
    """臂 A：现有温和摘要压缩的零改动包装（V2 实验对照组基线）。

    包装而非重写：保证对照组行为 == 改造前行为（实验结论才有意义）。
    已知偏离接口哲学：现有实现压缩后会 clear_old_chains（清旧消息），与"session=append-only"
    抽象冲突——**按 2026-09-02 grill-me 拍板保留为观测点**，不在对照组里偷偷抹平。
    """

    name = "summary"

    def prepare_history(self, history: list[Any], sid: str, uid: str | None = None) -> tuple[list[Any], int]:
        from app.agent.session_compress import apply_compaction as _impl

        return _impl(sid, history, uid)


_REGISTRY: dict[str, ContextStrategy] = {SummaryCompaction.name: SummaryCompaction()}


def register_strategy(strategy: ContextStrategy) -> None:
    """注册一个策略实现（换实现的成本 = 这一行）。"""
    if not isinstance(strategy, ContextStrategy):  # runtime_checkable Protocol：只验形状不验继承
        raise TypeError(f"策略不符合 ContextStrategy 接口形状：{type(strategy)}")
    _REGISTRY[strategy.name] = strategy


def get_strategy(name: str | None = None) -> ContextStrategy:
    """取策略实现（默认现状压缩）。name 未注册 → 回退默认（绝不因配置错而阻断对话）。"""
    if name and name in _REGISTRY:
        return _REGISTRY[name]
    return _REGISTRY[DEFAULT_STRATEGY]


def prepare_history(history: list[Any], sid: str, uid: str | None = None, name: str | None = None):
    """生产入口：chat.py 只调这一个函数，不直接依赖任何具体策略。"""
    return get_strategy(name).prepare_history(history, sid, uid)


__all__ = [
    "ContextStrategy",
    "DEFAULT_STRATEGY",
    "SummaryCompaction",
    "apply_compaction",  # 兼容：旧 import 路径不破坏（chat.py 迁移后此处仅为 re-export）
    "get_strategy",
    "prepare_history",
    "register_strategy",
]
