# -*- coding: utf-8 -*-
"""运行 trace 日志（2026-08-20，harness 可观测性补强——用户纲领"harness 做厚 + 更透明"）：

事件流 append-only jsonl：每次对话 run 的完整轨迹（LLM 调用 / 工具调用 / 收尾钩子 / 错误），
按 run_id 过滤即一轮对话的完整时间线。纯 harness 层：不进 prompt/上下文、零模型负担、
写入失败静默（观测非主流程，08-18 变更日志同款纪律）。

与既有数据文件的分工（各管一段 vs 完整轨迹）：
- injection_log.jsonl = 注入审计（每轮各块长度）
- change_log.jsonl    = 记忆变更审计
- token_usage.csv     = 成本统计
- service_guard.log   = 服务级事件（拉起/崩溃/重启）
- trace_log.jsonl     = 本轮 run 完整事件流（本模块）
"""
import json
import time
import uuid
from pathlib import Path

from app.config import DATA_DIR

TRACE_FILE = DATA_DIR / "data" / "trace_log.jsonl"

# 完整性校验（2026-08-21 补洞：_write 失败不再静默——计数暴露给星图，数据缺失可见）
_write_fails = 0


def _write(ev: dict) -> None:
    global _write_fails
    ev.setdefault("ts", time.strftime("%Y-%m-%d %H:%M:%S"))
    try:
        TRACE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with TRACE_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")
    except Exception:
        _write_fails += 1


def write_fail_count() -> int:
    """观测台完整性校验：trace 写入失败次数（>0 = 数据有缺失，需排查磁盘/权限）"""
    return _write_fails


def new_run_id() -> str:
    """每轮对话一个 run_id（12 位 hex），贯穿整轮事件流。"""
    return uuid.uuid4().hex[:12]


def run_start(run_id: str, sid: str, text: str) -> None:
    _write({"type": "run_start", "run_id": run_id, "sid": sid[:8], "text": (text or "")[:80]})


def llm_start(run_id: str, tag: str, model: str) -> None:
    _write({"type": "llm_start", "run_id": run_id, "tag": tag, "model": str(model)})


def llm_end(run_id: str, tag: str, ok: bool = True) -> None:
    """LLM 调用结束（2026-08-21 补：与 llm_start 配对算单次 LLM 耗时——对齐 GenAI operation.duration）。
    ok=False 表示该次调用失败（异常/超时），聚合时计入失败率。"""
    _write({"type": "llm_end", "run_id": run_id, "tag": tag, "status": "ok" if ok else "error"})


def llm_output(run_id: str, tag: str, text: str) -> None:
    """LLM 回复全文进 trace（2026-08-21 补：会话重放可见模型回复——Langfuse generation output）。
    截断 1000 字防 trace 膨胀；本地存储（data/ git 忽略，隐私安全）。"""
    _write({"type": "llm_output", "run_id": run_id, "tag": tag, "text": (text or "")[:1000]})


def tool_start(run_id: str, name: str, args: str, call_id: str | None = None) -> None:
    _write({"type": "tool_start", "run_id": run_id, "name": name, "args": (args or "")[:80], "id": call_id})


def tool_end(run_id: str, name: str, status: str, call_id: str | None = None, result: str = "") -> None:
    _write({"type": "tool_end", "run_id": run_id, "name": name, "status": status,
            "id": call_id, "result": (result or "")[:80]})


def token_usage(sid: str, usage, model: str = "") -> None:
    """记录 token 用量（成本统计，A2-5 2026-08-20 下沉：main 主流程与 delegation 子任务共用——
    天下大同：一个成本台账，谁调用都记同一文件。失败静默（成本觉察非主流程）。"""
    from datetime import datetime

    try:
        # 兼容两种 usage 结构（pydantic-ai 2.27）：stream.usage()=request_tokens/response_tokens；
        # AgentRunResult.usage=RunUsage(input_tokens/output_tokens)——A2-5 实测抓出
        u = (
            getattr(usage, "request_tokens", None)
            or getattr(usage, "prompt_tokens", None)
            or getattr(usage, "input_tokens", 0)
        )
        o = (
            getattr(usage, "response_tokens", None)
            or getattr(usage, "output_tokens", None)
            or 0
        )
        t = getattr(usage, "total_tokens", (u or 0) + (o or 0))
        line = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')},{sid[:8]},{u or 0},{o or 0},{t or 0},{model}"
        f = DATA_DIR / "data" / "token_usage.csv"
        if not f.exists():
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text("time,session,prompt_tokens,output_tokens,total_tokens,model\n", encoding="utf-8")
        with open(f, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:
        pass


def hook(run_id: str, name: str, ok: bool = True, result: str = "") -> None:
    """收尾钩子事件：profile/confusion/relation/continuation/teaching/topics 六路。"""
    _write({"type": "hook", "run_id": run_id, "name": name, "ok": ok, "result": (result or "")[:80]})


def error(run_id: str, where: str, msg: str) -> None:
    """错误集中落盘（应用级）：LLM 异常/超时/空回复/钩子失败，带环节定位。"""
    _write({"type": "error", "run_id": run_id, "where": where, "msg": (msg or "")[:200]})


def run_end(run_id: str, status: str, dur_ms: int, detail: str = "") -> None:
    _write({"type": "run_end", "run_id": run_id, "status": status, "dur_ms": dur_ms,
            "detail": (detail or "")[:120]})
