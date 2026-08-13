"""状态轮（M9 打磨期第 3 步 MVP）：用户当前学习状态的快变分量。
四维：情绪（疑似标注）/ 卡点 / 节奏 / 意愿。
红线：状态=信息不是判断（注入"疑似"让模型自己权衡）；显式信号优先；
     变化触发（模型只在状态变化时调，防挖沙）；快照落盘=跨会话接续（第 2 步）的地基。
"""
import json
from datetime import datetime
from pathlib import Path
from app.config import DATA_DIR

STATE_FILE = DATA_DIR / "memory" / "state.json"

# 合法维度与取值（取值自由文本，不强校验——判断归模型）
DIMS = ("emotion", "blocker", "pace", "willingness")

DEFAULT_STATE = {
    "current": {},          # 当前会话状态 {dim: {value, confidence?, evidence?}}
    "last_session": {},     # 上次会话结束快照（第 2 步跨会话接续用）
    "updated_at": "",       # 最近一次更新（ISO）
}


def _load() -> dict:
    if not STATE_FILE.exists():
        return dict(DEFAULT_STATE)
    try:
        d = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return {**DEFAULT_STATE, **d}
    except Exception:
        return dict(DEFAULT_STATE)


def _save(state: dict):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def update_state(**kwargs) -> str:
    """更新用户当前状态（情绪/卡点/节奏/意愿），状态变化时调用（不要每轮调）。
    触发：用户明说情绪词→emotion；学不动/不想学→willingness；听不懂/卡住→blocker；纠正/缓解→覆盖。
    【参数名必须是维度名】emotion/blocker/pace/willingness 之一（如 update_state(blocker=...)）；
    参数值是 JSON 对象 {"value": "...", "confidence": "explicit|疑似", "evidence": "..."}——
    value 是值字段不是参数名，不要传 update_state(value=...)（那样会被忽略）。
    明说→confidence=explicit；推断→疑似（必须标）。会话结束自动快照 last_session。"""
    updates = {k: v for k, v in kwargs.items() if k in DIMS and v}
    if not updates:
        return "(状态更新为空——状态未变化就不用调，别每轮调)"
    state = _load()
    for dim, val in updates.items():
        # 模型可能把结构化参数传成 JSON 字符串（"{\"value\":...}"）——先解析
        if isinstance(val, str) and val.lstrip().startswith("{"):
            try:
                parsed = json.loads(val)
                if isinstance(parsed, dict):
                    val = parsed
            except Exception:
                pass
        if isinstance(val, dict):
            state["current"][dim] = val  # 支持 {value, confidence, evidence}
        else:
            state["current"][dim] = {"value": str(val), "confidence": "explicit"}
    state["updated_at"] = datetime.now().isoformat(timespec="minutes")
    _save(state)
    return f"已更新状态：{', '.join(updates)}"


def snapshot_to_last_session():
    """会话结束时调用：当前状态 → last_session 快照（第 2 步跨会话接续的地基）"""
    state = _load()
    if state["current"]:
        state["last_session"] = {
            **state["current"],
            "snap_at": datetime.now().isoformat(timespec="minutes"),
        }
        _save(state)


def clear_current():
    """新会话第一轮调用：清空 current（防跨会话残留——上次会话的状态不该冒充本次的）。
    last_session 保留（跨会话接续信息）。"""
    state = _load()
    if state["current"]:
        state["current"] = {}
        _save(state)


def inject_state() -> str:
    """注入用：拼接当前状态（轻量版，几百字内）。状态=信息不是判断，疑似标注让模型自己权衡。"""
    state = _load()
    cur, last = state.get("current", {}), state.get("last_session", {})
    # 去重：比较时排除 snap_at（否则 last != cur 恒真，"上次"每次都注入）
    last_cmp = {k: v for k, v in last.items() if k != "snap_at"}
    parts = []
    if last and last_cmp != cur:
        snap = last.get("snap_at", "")
        dims = []
        for dim in DIMS:
            v = last.get(dim)
            if v:
                dims.append(f"{_dim_cn(dim)}={_fmt(v)}")
        if dims:
            parts.append(f"上次会话结束状态（{snap}）：{'；'.join(dims)}")
    if cur:
        dims = []
        for dim in DIMS:
            v = cur.get(dim)
            if v:
                dims.append(f"{_dim_cn(dim)}={_fmt(v)}")
        if dims:
            parts.append(f"本次会话状态（更新于 {state.get('updated_at','?')}）：{'；'.join(dims)}")
    return "；".join(parts) if parts else ""


def _dim_cn(dim: str) -> str:
    return {"emotion": "情绪", "blocker": "卡点", "pace": "节奏", "willingness": "意愿"}.get(dim, dim)


def _fmt(v) -> str:
    if isinstance(v, dict):
        val = v.get("value", "")
        conf = v.get("confidence", "")
        ev = v.get("evidence", "")
        # 来源/置信走结构字段（发现一：value 只存内容，元信息不进数据）
        suffix = ""
        if conf in ("疑似", "suspect"):
            suffix = "（疑似）"
        elif conf == "explicit":
            suffix = "（明说）"
        # 防御：模型若已把字样写进 value，不重复加
        if suffix and suffix[1:-1] in val:
            suffix = ""
        s = val + suffix
        if ev:
            s += f"·依据:{ev[:40]}"
        return s
    return str(v)
