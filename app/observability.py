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
    """A2 修复（2026-08-27，对齐 OTel 业界共识）：关联键冗余全量打到事件上——
    事件自包含全量 session_id（此前只存 sid[:8] 截断前缀，78 个历史 sid 不可逆丢失 + 前缀碰撞隐患）；
    sid8 保留兼容旧查询（observability 端点 startswith(sid[:8]) 匹配）。"""
    _write({
        "type": "run_start",
        "run_id": run_id,
        "sid": sid[:8],
        "sid_full": sid,  # 全量 UUID（A2）
        "text": (text or "")[:80],
    })


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
    _write(
        {
            "type": "tool_start",
            "run_id": run_id,
            "name": name,
            "args": (args or "")[:80],
            "id": call_id,
        }
    )


def tool_end(
    run_id: str, name: str, status: str, call_id: str | None = None, result: str = ""
) -> None:
    _write(
        {
            "type": "tool_end",
            "run_id": run_id,
            "name": name,
            "status": status,
            "id": call_id,
            "result": (result or "")[:80],
        }
    )


def token_usage(sid: str, usage, model: str = "") -> None:
    """记录 token 用量（成本统计，A2-5 2026-08-20 下沉：main 主流程与 delegation 子任务共用——
    天下大同：一个成本台账，谁调用都记同一文件。失败静默（成本觉察非主流程）。
    2026-08-26 P0-2 缓存观测：追加 cache_read/cache_write 两列（pydantic-ai 2.27 RunUsage
    原生透传 DeepSeek prompt_cache_hit_tokens——命中率=read/input，观测缓存优化效果）。"""
    from datetime import datetime

    try:
        # 兼容两种 usage 结构（pydantic-ai 2.27）：stream.usage 与 AgentRunResult.usage 均为属性
        # （RunUsage：input_tokens/output_tokens/cache_read_tokens/cache_write_tokens）
        u = (
            getattr(usage, "request_tokens", None)
            or getattr(usage, "prompt_tokens", None)
            or getattr(usage, "input_tokens", 0)
        )
        o = getattr(usage, "response_tokens", None) or getattr(usage, "output_tokens", None) or 0
        t = getattr(usage, "total_tokens", (u or 0) + (o or 0))
        cr = getattr(usage, "cache_read_tokens", None) or 0  # 前缀缓存命中 token
        cw = getattr(usage, "cache_write_tokens", None) or 0  # 缓存写入 token
        # 模型名可读化（2026-08-26 P0-2：OpenAIChatModel 对象 str 无信息，用 model_name 字段）
        model_name = getattr(model, "model_name", None) or str(model)
        line = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')},{sid[:8]},{u or 0},{o or 0},{t or 0},{model_name},{cr},{cw}"
        f = DATA_DIR / "data" / "token_usage.csv"
        f.parent.mkdir(parents=True, exist_ok=True)
        _migrate_token_ledger(f)  # 老台账（无 cache 列）归档，幂等（已迁移/不存在则跳过）
        if not f.exists():  # 迁移后或首次：重建表头（迁移 rename 走的是 else 分支，需在此补表头）
            f.write_text(
                "time,session,prompt_tokens,output_tokens,total_tokens,model,cache_read,cache_write\n",
                encoding="utf-8",
            )
        with open(f, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        # 缓存命中率告警（2026-08-26 P1，业界标准：cached/input <50% 报警=前缀结构问题信号）：
        # 正常多轮会话 88-97%（静态前缀跨会话命中 94%+），<50% 意味着前缀被破坏
        # （工具定义变化/动态注入进 system）或工具循环极端密集——信息给觉察，不阻断。
        if (u or 0) > 0:
            hit_ratio = cr / u
            if hit_ratio < 0.5:
                print(
                    f"[cache] ⚠️ 低缓存命中率 {hit_ratio:.0%}（sid={sid[:8]}，prompt={u}，"
                    f"hit={cr}）——检查：①工具定义是否被改动（跑 scripts/probe_tool_schema.py）"
                    f"②是否有动态内容混入 system 前缀 ③工具循环是否过密",
                    flush=True,
                )
    except Exception as _e:
        print(f"[app/observability] 静默异常已可见化: {_e}", flush=True)


def _migrate_token_ledger(f) -> None:
    """老台账迁移（2026-08-26 P0-2）：06 列旧格式 → 归档为 *_legacy.csv，新格式从新表头开始。
    历史成本数据保留可查（观测资产），新观测从今天起结构统一。幂等：已迁移（表头含 cache_read）则跳过。"""
    try:
        head = f.read_text(encoding="utf-8").splitlines()[0] if f.exists() else ""
        if "cache_read" in head:
            return
        legacy = f.with_name("token_usage_legacy.csv")
        if not legacy.exists():
            f.rename(legacy)
    except Exception as _e:
        print(f"[app/observability] 静默异常已可见化: {_e}", flush=True)


def hook(run_id: str, name: str, ok: bool = True, result: str = "") -> None:
    """收尾钩子事件：profile/confusion/relation/continuation/teaching/topics 六路。"""
    _write(
        {"type": "hook", "run_id": run_id, "name": name, "ok": ok, "result": (result or "")[:80]}
    )


def error(run_id: str, where: str, msg: str) -> None:
    """错误集中落盘（应用级）：LLM 异常/超时/空回复/钩子失败，带环节定位。"""
    _write({"type": "error", "run_id": run_id, "where": where, "msg": (msg or "")[:200]})


def run_end(run_id: str, status: str, dur_ms: int, detail: str = "") -> None:
    _write(
        {
            "type": "run_end",
            "run_id": run_id,
            "status": status,
            "dur_ms": dur_ms,
            "detail": (detail or "")[:120],
        }
    )
