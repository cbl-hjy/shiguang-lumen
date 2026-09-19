"""拾光 MCP Server（2026-09-01，设计 docs/2026-09-01-MCP-SERVER-DESIGN.md）。

薄壳纪律：本文件只做协议适配，工具逻辑一行不写——全部复用 app/tools/* 与 app/memory/*。
红线对齐：
- stdio 子进程（spec 豁免 OAuth；不监听网络——本地威胁模型官方立场）
- 只读 5 件：写入路径在本进程物理不存在（比权限声明更硬）
- search_memory 必须 _bump=False（A2-2 既有只读开关，命中不 S+1——声明与行为一致）
- 不发 Registry；uid 不暴露参数（N=1 本地单视角，防伪造他人视角）

运行：.venv/Scripts/python.exe -m app.mcp_server   （或 mcp run app/mcp_server.py）
验收：scripts/mcp_smoke.py（stdio 客户端冒烟）+ 官方 Inspector（mcp dev）
"""

from __future__ import annotations

import json

from mcp.server import MCPServer

_MAX_QUERY = 2000  # 输入校验：查询长度上限
_MAX_OUTPUT = 6000  # 输出消毒：单条结果截断上限（防单条记忆爆 token）

mcp = MCPServer(
    "shiguang",
    instructions=(
        "拾光（Shiguang）个人学习搭子的只读数据面：检索用户记忆/知识库/技能沉淀、"
        "查看学习状态与能力仪表盘。全部工具只读，不产生任何写入。"
    ),
)


def _ok(text: str) -> str:
    """输出消毒：统一截断。"""
    text = text or "(空结果)"
    return text[:_MAX_OUTPUT]


def _err(where: str, e: BaseException) -> str:
    """诚实报错（不静默、不吞类型）。"""
    return f"({where} 失败：{type(e).__name__}: {e})"


def _check_query(q: str) -> str | None:
    if not (q or "").strip():
        return "(查询不能为空)"
    return None


@mcp.tool()
async def search_memory(query: str, top_k: int = 3, category: str = "") -> str:
    """检索拾光记忆库：用户的偏好/历史/学习进度/困惑/目标等个人状态。
    只在问题涉及用户本人时调用；通用知识问题不要调。category 可限定：
    学习记录/进度/偏好/目标/困惑/关系/笔记，留空=全量。只读（命中不强化）。"""
    if (e := _check_query(query)) :
        return e
    try:
        from app.memory import store

        return _ok(
            await store.search_memory(
                query[:_MAX_QUERY],
                top_k=max(1, min(top_k, 10)),
                category=category,
                _bump=False,  # 只读承诺的物理落实
            )
        )
    except BaseException as ex:  # noqa: BLE001
        return _err("记忆检索", ex)


@mcp.tool()
async def kb_search(query: str, deep: bool = False) -> str:
    """检索拾光个人知识库（外部资料/笔记），带出处引用。deep=True 附原文段落。"""
    if (e := _check_query(query)):
        return e
    try:
        from app.tools.kb import kb_search as _impl

        return _ok(await _impl(query[:_MAX_QUERY], deep=deep))
    except BaseException as ex:  # noqa: BLE001
        return _err("知识库检索", ex)


@mcp.tool()
async def search_skills(query: str, top_k: int = 3) -> str:
    """查拾光技能库：类似情境下沉淀的讲法/做法。返回名称+摘要。只读。"""
    if (e := _check_query(query)):
        return e
    try:
        from app.agent.evolution import search_skills as _impl

        return _ok(await _impl(query[:_MAX_QUERY], top_k=max(1, min(top_k, 5))))
    except BaseException as ex:  # noqa: BLE001
        return _err("技能检索", ex)


@mcp.tool()
def learning_status() -> str:
    """学习状态快照：校准（押把握 vs 实际）+ 保持率（延迟复测）聚合。无数据时如实说没有数据。"""
    try:
        from app.tools import learning

        recs = learning._ledger_read()  # 同项目薄壳复用私有读函数（非第二份实现）
        if not recs:
            return "(还没有学习台账数据)"
        return _ok(learning.calibration_summary(recs) + "\n\n" + learning.retention_summary(recs))
    except BaseException as ex:  # noqa: BLE001
        return _err("学习状态", ex)


@mcp.tool()
def capability_dashboard() -> str:
    """能力仪表盘 JSON：纠错循环/学习/ACE playbook/计划/预算五 section + 元指标新鲜度。
    全部描述性指标（N=1 趋势，非因果证据）；无数据的 section 如实标注。"""
    try:
        from app import capability_metrics

        return _ok(json.dumps(capability_metrics.scoreboard(), ensure_ascii=False, indent=1))
    except BaseException as ex:  # noqa: BLE001
        return _err("能力仪表盘", ex)


if __name__ == "__main__":
    mcp.run(transport="stdio")
