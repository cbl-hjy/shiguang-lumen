"""接地纠错循环（2026-08-30，设计 docs/2026-08-30-ERROR-LOOP-DESIGN.md）：

运行时错误循环管理：台账 → 循环检测 → 预算升级 → 硬停止 → 回灌。
与四件套边界（红线：不重复造）：
- tools/errors.py 管「长什么样」（错误格式化）——本模块是它的消费者（解析 "(错误|" 前缀串）
- agent/verifier.py 管「对不对」（输出把关，模型自主调用）
- agent/evolution.py 管「记住了吗」（collect_failure 回灌目的地，直接调用不另写）
- 本模块管「卡住了怎么办」（唯一新增件）

分工铁律（设计 §4）：台账/检测/计数/触发/回灌压缩归代码；失败后怎么办/怎么表达归模型。
harness 不替模型写道歉/修复文案（n=3 只给事实信号）；n=5 系统消息是唯一例外且系统标识。
"""
from __future__ import annotations

import json
import re
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.auth_core import get_current_user_id
from app.config import DATA_DIR
from app.user_data import get_user_data_dir

# ---------- 阈值（设计 §3.2/§3.3，确定性不变量） ----------
LOOP_MIN = 3  # 同 tool+code ≥3 次 → 错误循环
SIGNAL_N = 2  # 连续 2 次失败 → 注入信息信号（不干预）
ESCALATE_N = 3  # 连续 3 次失败 → 升级信号 + obs 事件 error_escalation
HARD_STOP_N = 5  # 连续 5 次失败 → SSE 系统消息 + 冻结工具调用一轮

# n=5 硬停止消息（设计 §3.3 原文）——harness 的消息，必须系统标识，不是模型口吻
HARD_STOP_MESSAGE = "系统：agent 已连续 5 次工具失败，已暂停自动重试。请直接描述你的问题或稍后再试。"

# ---------- session 识别（contextvar，与 auth_core._current_user_id 同模式） ----------
# 工具在请求上下文中运行（anyio 传播 context），contextvar 天然 per-request 隔离；
# 全局变量会串 session（多请求并发时互相污染台账）——这是本模块最关键的隔离决策。
_current_session_id: ContextVar[Optional[str]] = ContextVar("shiguang_error_loop_session", default=None)


def set_current_session_id(sid: Optional[str]) -> None:
    _current_session_id.set(sid)


def get_current_session_id() -> Optional[str]:
    return _current_session_id.get()


# ---------- per-session 内存台账 ----------
# {sid: {"consecutive": int, "seq": [{tool, code, domain}], "frozen": bool,
#        "hard_stop_pending": bool, "last_tool": str, "last_code": str}}
_sessions: dict[str, dict] = {}


def _state(sid: str) -> dict:
    st = _sessions.get(sid)
    if st is None:
        st = {
            "consecutive": 0,
            "seq": [],
            "frozen": False,
            "hard_stop_pending": False,
            "last_tool": "",
            "last_code": "",
        }
        _sessions[sid] = st
    return st


# ---------- 落盘（per-user jsonl，度量用；写失败静默打印不炸） ----------
# 测试覆盖钩子（同 evolution._EVO_*_OVERRIDE 模式：钩子优先于 uid 解析，测试零侵入生产路径）
_LEDGER_OVERRIDE: Path | None = None


def _ledger_path() -> Path:
    """per-user 数据目录下 data/error_ledger.jsonl（参照 evolution._evo_dir 模式；legacy 回退全局）"""
    if _LEDGER_OVERRIDE is not None:
        return _LEDGER_OVERRIDE
    uid = get_current_user_id()
    base = get_user_data_dir(uid) if uid else DATA_DIR
    return base / "data" / "error_ledger.jsonl"


def _append_ledger(rec: dict) -> None:
    try:
        f = _ledger_path()
        f.parent.mkdir(parents=True, exist_ok=True)
        with f.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"[agent/error_loop] 台账落盘失败（静默，不影响对话）: {e}", flush=True)


# ---------- 错误解析（消费 errors.py 统一格式，不另造分类） ----------
_ERROR_RE = re.compile(r"^\(错误\|([^|)]*)\|([^|)]*)\|")


def parse_error(result: str) -> tuple[str, str]:
    """解析 "(错误|domain|code|...)" → (domain, code)；非标准格式 → ("", "UNKNOWN")"""
    m = _ERROR_RE.match(result or "")
    if not m:
        return ("", "UNKNOWN")
    return (m.group(1), m.group(2))


def is_error_result(r) -> bool:
    return isinstance(r, str) and r.startswith("(错误|")


# ---------- 回灌（接地证据 → evolution.collect_failure，同一仪器禁第二份实现） ----------
def _feedback(st: dict, outcome: str, recovered_with: str = "") -> None:
    """错误序列收尾回灌：压缩证据（≤300 字，压缩归代码）→ collect_failure 进待审区。
    幂等复用 collect_failure 既有机制（同证据 24h 不重复采集）；失败静默。"""
    try:
        from app.agent.evolution import collect_failure

        seq = st["seq"]
        if not seq:
            return
        tools = [f"{e['tool']}({e['code']})" for e in seq[-6:]]
        loop = _loop_tool(seq)
        if outcome == "recovered":
            head = f"工具错误序列自我恢复（{len(seq)} 次失败后由 {recovered_with} 成功收尾）"
        else:
            head = f"工具错误序列硬停止（连续 {HARD_STOP_N} 次失败，已冻结一轮）"
        evidence = f"{head}：{' → '.join(tools)}"
        if loop:
            evidence += f"；循环标记：{loop} 同错误码 ≥{LOOP_MIN} 次"
        collect_failure(evidence[:300], target=f"tool:{loop or seq[-1]['tool']}")
        # ACE playbook 接地计数（2026-08-30，设计 docs/2026-08-30-ACE-PLAYBOOK-DESIGN.md §2）：
        # 失败序列收尾 = 接地信号 → 本会话被检索技能 harmful+1（计数推进归 evolution，同一仪器）
        from app.agent.evolution import on_failure_sequence

        on_failure_sequence(get_current_session_id())
    except Exception as e:
        print(f"[agent/error_loop] 回灌失败（静默）: {e}", flush=True)


def _loop_tool(seq: list[dict]) -> str:
    """循环检测（设计 §3.2）：序列内同 tool+code ≥LOOP_MIN → 返回该 tool，否则 ""。
    参数相似性不做向量计算（设计 §8 明确不做）——code 已是归一化分类，够用。"""
    counts: dict[tuple[str, str], int] = {}
    for e in seq:
        k = (e["tool"], e["code"])
        counts[k] = counts.get(k, 0) + 1
        if counts[k] >= LOOP_MIN:
            return k[0]
    return ""


def _reset_seq(st: dict) -> None:
    st["consecutive"] = 0
    st["seq"] = []
    st["last_tool"] = ""
    st["last_code"] = ""


# ---------- 记录入口（工具包装器调用） ----------
def record_error(tool: str, result: str) -> dict:
    """工具失败记账：台账 + 连续计数 + 循环检测 + n=5 硬停止判定。
    返回 {"consecutive": n, "loop": bool, "hard_stop": bool}。无 session 上下文 → 跳过（no-op）。"""
    sid = get_current_session_id()
    if not sid:
        return {"consecutive": 0, "loop": False, "hard_stop": False}
    st = _state(sid)
    domain, code = parse_error(result)
    st["consecutive"] += 1
    attempt_n = sum(1 for e in st["seq"] if e["tool"] == tool and e["code"] == code) + 1
    st["seq"].append({"tool": tool, "code": code, "domain": domain})
    st["last_tool"] = tool
    st["last_code"] = code
    loop = bool(_loop_tool(st["seq"]))
    hard_stop = st["consecutive"] >= HARD_STOP_N
    _append_ledger(
        {
            "event": "error",
            "ts": datetime.now().isoformat(timespec="seconds"),
            "session_id": sid,
            "tool": tool,
            "code": code,
            "domain": domain,
            "attempt_n": attempt_n,
            "consecutive": st["consecutive"],
            "loop": loop,
            "compressed": (result or "")[:300],
        }
    )
    if hard_stop:
        # 硬停止（设计 §3.3）：回灌（卡点证据）+ 冻结一轮 + SSE 系统消息挂起（chat.py 消费）。
        # 序列关闭：计数清零——失败必须可见已由系统消息保证，台账从下一轮重新计。
        _feedback(st, "hard_stop")
        _append_ledger(
            {
                "event": "seq_end",
                "ts": datetime.now().isoformat(timespec="seconds"),
                "session_id": sid,
                "seq_len": len(st["seq"]),
                "outcome": "hard_stop",
                "loop": loop,
                "loop_tool": _loop_tool(st["seq"]),
                "recovered_with": "",
            }
        )
        _reset_seq(st)
        st["frozen"] = True
        st["hard_stop_pending"] = True
    return {"consecutive": st["consecutive"], "loop": loop, "hard_stop": hard_stop}


def record_success(tool: str) -> None:
    """工具成功：连续计数清零（设计 §3.3 成功一次清零）。
    若有未收尾错误序列 → 以成功收尾（自我恢复），回灌接地证据。"""
    sid = get_current_session_id()
    if not sid:
        return
    st = _state(sid)
    if st["consecutive"] > 0 and st["seq"]:
        loop = bool(_loop_tool(st["seq"]))
        _feedback(st, "recovered", recovered_with=tool)
        _append_ledger(
            {
                "event": "seq_end",
                "ts": datetime.now().isoformat(timespec="seconds"),
                "session_id": sid,
                "seq_len": len(st["seq"]),
                "outcome": "recovered",
                "loop": loop,
                "loop_tool": _loop_tool(st["seq"]),
                "recovered_with": tool,
            }
        )
    _reset_seq(st)


# ---------- 状态查询（chat.py / 动态上下文用） ----------
def consecutive_errors() -> int:
    sid = get_current_session_id()
    return _state(sid)["consecutive"] if sid else 0


def is_frozen() -> bool:
    sid = get_current_session_id()
    return bool(sid and _state(sid)["frozen"])


def consume_hard_stop() -> bool:
    """n=5 系统消息待发送标记（一次性消费——chat.py SSE 注入后清零）"""
    sid = get_current_session_id()
    if not sid:
        return False
    st = _state(sid)
    pending = st["hard_stop_pending"]
    st["hard_stop_pending"] = False
    return pending


def begin_turn(sid: Optional[str]) -> None:
    """新用户轮开始（chat.py 设置 session 后调用）：解除上一轮冻结。
    连续计数跨轮保留（设计 §3.3：只有成功才清零）——n=2/3 信号靠下一轮动态上下文注入。"""
    if sid and sid in _sessions:
        _sessions[sid]["frozen"] = False


# ---------- 注入信号（设计 §3.4：≤2 行，给事实与选项不给指令） ----------
def health_signal() -> str:
    """工具健康信号（build_dynamic_context 调用）：连续失败 ≥2 才出现，成功清零后消失。
    n=2 信息信号；n≥3 升级信号（建议直接告诉用户卡在哪——harness 不代写文案，只给事实）。"""
    sid = get_current_session_id()
    if not sid:
        return ""
    st = _state(sid)
    n = st["consecutive"]
    if n < SIGNAL_N:
        return ""
    tool = st["last_tool"] or "工具"
    code = st["last_code"] or "UNKNOWN"
    if n >= ESCALATE_N:
        return f"⚠ 工具健康：{tool} 连续 {n} 次失败（{code}）——建议直接告诉我你卡在哪，不要独自反复重试。"
    return f"⚠ 工具健康：{tool} 连续 {n} 次失败（{code}）。可换工具/换参数，或告诉我你卡住了。"
