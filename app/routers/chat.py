"""Chat SSE 流式主流程（P2-1 2026-08-27 从 main.py 拆分：路由收编 + 业务模块化）。

原 main.py 1330 行单体拆出：chat 主流程 + 压缩/摘要/回滚/续写辅助 + post hooks。
main.py 只留 FastAPI 装配（lifespan/静态/鉴权/setup/update + router 挂载）。
"""
import asyncio
import base64
import json
import time
import uuid
from typing import AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from pydantic_ai import UsageLimits
from pydantic_ai.messages import (
    ModelMessagesTypeAdapter,
    ModelRequest,
    SystemPromptPart,
)

from app import observability as obs
from app.agent.delegation import ProgressTracker
from app.agent.context_strategy import prepare_history
from app.agent.session_compress import history_to_text, msg_len
from app.agent.tutor import build_dynamic_context, build_tutor_agent
from app.config import DATA_DIR
from app.db import sessions

UPLOAD_DIR = DATA_DIR / "data" / "uploads"  # 上传目录（拆分时从 main.py 带入）
COMPACT_THRESHOLD_CHARS = 90_000  # 长程压缩阈值（旧版字符口径，保留兼容外部引用）
COMPACT_TAIL_CHARS = 20_000  # 压缩后保留尾部（拆分时从 main.py 带入；≈14K token ≈ 10-15 轮）
COMPACT_TRIGGER_TOKENS_STR = "60K token"  # C-1 新触发口径（日志展示；真实阈值在 session_compress 锁死）

router = APIRouter(prefix="/api")


def tool_result_status(part) -> tuple[str, str]:
    """工具结果可观测性判定（2026-08-18 事故补，纯函数可测）：
    返回 (status, result)——status ∈ {"done", "error"}；result=工具返回文本摘要（≤100 字）。
    双判定失败：①pydantic-ai 原生 outcome（抛异常/拒绝/中断）②本项目 errors.py 标准格式 "(错误|" 前缀。
    事故背景：manage_wakeup 取消失败时模型谎报"已撤"——结果对用户可见是 harness 不变量。"""
    content = getattr(part, "content", None)
    if content is None:
        content = getattr(part, "return_value", None)  # OutputToolResultEvent 兼容
    result = str(content) if content is not None else ""
    outcome = getattr(part, "outcome", None)
    failed = outcome in ("failed", "denied", "interrupted") or result.startswith("(错误|")
    return ("error" if failed else "done"), result[:100] + ("…" if len(result) > 100 else "")


def _cache_eligible(tool_names: list[str]) -> bool:
    """LLM 缓存资格判定（2026-09-17 A2 对话层审计·发现 3 修复）：
    仅"本轮无任何工具调用"的纯问答轮可缓存——与 llm_cache 模块设计原文一致
    （"只缓存纯问答轮（无工具调用、无上传文件）"）。

    背景（实证）：原实现按"外部工具黑名单"判定（仅 web_search 等 5 个外部/易变工具
    不缓存），导致写操作工具轮次被缓存。A2-08 实测：提醒注册请求命中上一场景缓存
    （相似度 0.9437），用户收到"没设上"的错误回复、且目标提醒未注册。
    修复方向为 fail-safe：本函数按"有无工具调用"收紧——未来新增工具默认不可缓存，
    不会重演黑名单漏项（本次漏洞面含 manage_wakeup/forget/update_state/plan_* 等 ≥15 个写操作工具）。
    """
    return not tool_names


def _error_hint(msg: str) -> str:
    """异常收尾指令（2026-08-20，借鉴 DeepTutor"4 种故障各有指令"）：
    后端 error SSE 除了 message 还给用户可执行的下一步——错误不是终点，是引导。"""
    if "超限" in msg or "240s" in msg:
        return "会话超时：复杂问题可以拆成小问题逐个问；网络波动时稍等再试"
    if "request_limit" in msg or "exceed the request_limit" in msg:
        # 2026-08-21：工具轮次超限（模型反复调工具未收敛）——给用户"为什么停"的明确提示（曾静默断流无人知）
        return "本轮工具调用轮次超限已自动停止（常见于代码反复执行失败/问题太复杂）：简化需求或把问题拆小再问"
    if "空回复" in msg:
        return "模型没生成内容：直接说『重试』，或换个说法再问一次"
    if "fallback" in msg:
        return "服务暂时不稳定：稍后重试；若持续出现请检查网络"
    return "服务暂时不可用：稍后重试；若反复出现请检查网络与 API 配置"


# 工具结果压缩（2026-08-20，context 卫生，用户纲领"harness 做厚"）：
# 统一硬上限兜底——防大工具结果（读文档/检索/沙箱输出）全量进上下文（context rot 来源）。
# 与工具内部语义压缩（read_document 4000 截断/Tavily 摘要等）互补：语义压缩管"精"，这里管"底线"。
# 不约束模型：截断后保留"…(已截断)"标记，模型知道信息不全（信息给觉察）。
TOOL_RESULT_LIMIT = 4000


def _compress_tool_content(content: str, limit: int = TOOL_RESULT_LIMIT) -> str:
    """纯函数（可单测）：超限截断 + 标记；空/短内容原样返回。"""
    if not isinstance(content, str) or len(content) <= limit:
        return content
    return (
        content[:limit] + f"\n…(已截断，完整 {len(content)} 字符，可让用户提供更具体的查询缩小范围)"
    )


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None
    # 上传的文件（base64，图片/PDF/文档），保存后交给模型用工具读取
    file_b64: str | None = None
    file_name: str | None = None


def _save_upload(req: ChatRequest) -> str | None:
    """保存上传文件到 data/uploads，返回路径（模型用 ocr_image/read_document 读取）"""
    if not req.file_b64:
        return None
    try:
        raw = base64.b64decode(req.file_b64.split(",", 1)[-1])
    except Exception:
        return None
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    name = req.file_name or f"upload_{uuid.uuid4().hex[:8]}"
    safe = "".join(c for c in name if c.isalnum() or c in ".-_")[:60]
    path = UPLOAD_DIR / f"{uuid.uuid4().hex[:6]}_{safe}"
    path.write_bytes(raw)
    return str(path)


def _sse(obj: dict) -> str:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


def _memory_file_digest(uid: str | None = None) -> str:
    """记忆文件内容摘要（2026-08-26 画像断档修复）：user_memory.md 内容变化 = 记忆变化。
    与 contextvars 无关——绕开 remember 在 agent tool context 置位、流尾读不到的跨 context 问题。"""
    import hashlib

    try:
        p = DATA_DIR / "memory" / "user_memory.md"
        return hashlib.md5(p.read_bytes()).hexdigest() if p.exists() else ""
    except Exception:
        return ""


def _load_history(session_id: str | None, uid: str | None = None):
    """恢复历史：DB 里存的完整对话链 JSON → pydantic-ai ModelMessage"""
    if not session_id:
        return None
    messages_json = sessions.load_messages_json(session_id, uid)
    if not messages_json:
        return None
    try:
        return ModelMessagesTypeAdapter.validate_json(messages_json)
    except Exception:
        return None


# 预算感知：上下文预算分级注入（护栏=提供信息，模型自己决定怎么收着点）
BUDGET_MAX_CHARS = 90_000  # 与 compaction 阈值同口径（est 字符估算）
BUDGET_WARN_PCT = 0.7  # >70% 提示精简
BUDGET_URGENT_PCT = 0.88  # >88% 强提示（接近压缩点）


def _budget_hint(est: int) -> str | None:
    if est <= 0:
        return None
    pct = est / BUDGET_MAX_CHARS
    if pct >= BUDGET_URGENT_PCT:
        return f"（上下文预算已用 {pct:.0%}，接近上限：请优先讲核心结论，工具调用从简）"
    if pct >= BUDGET_WARN_PCT:
        return f"（上下文预算已用 {pct:.0%}：回复请酌情精简，聚焦用户当前问题）"
    return None


# A1 后台沉淀钩子（2026-08-29 Phase4 A-2：已独立为 chat_hooks.py——纯移动，逻辑零改动）
from app.routers.chat_hooks import _POST_HOOK_TASKS, _run_post_hooks

@router.post("/chat")
async def chat(req: ChatRequest, request: Request) -> StreamingResponse:
    uid = getattr(request.state, "user_id", None)
    # P0 多用户：注入当前用户上下文（contextvar——记忆/画像/状态/向量 per-user 路径据此解析；
    # anyio 的 to_thread 会传播 context，agent 工具线程内可读）
    from app.auth_core import set_current_user_id

    set_current_user_id(uid)
    agent = build_tutor_agent(uid)
    # #6 去重标志：前端手动重试带 X-Retry: 1（优先认标志，比内容匹配可靠；内容匹配仅作无标志回退）
    is_retry = request.headers.get("x-retry") == "1"
    sid = (
        req.session_id
        if (req.session_id and sessions.session_exists(req.session_id, uid))
        else sessions.new_session(uid)
    )
    # 接地纠错循环（2026-08-30）：session 经 contextvar 传给工具包装器（与 set_current_user_id
    # 同模式——工具在请求上下文中运行，全局变量会串 session）；begin_turn 解除上一轮 n=5 冻结
    from app.agent import error_loop

    error_loop.set_current_session_id(sid)
    error_loop.begin_turn(sid)
    # 运行 trace（2026-08-20）：本轮 run 唯一 id + 起点事件（完整轨迹见 app/observability.py）
    run_id = obs.new_run_id()
    obs.run_start(run_id, sid, req.message)
    history = _load_history(sid, uid)
    # B2 摘要兜底（2026-08-20）：链全丢（异常/清空）但摘要存在时——用摘要构建最小历史，
    # 保证压缩前的早期上下文不丢（摘要=早期信息的唯一载体）；有摘要=会话延续，不清 current
    if not history:
        summary = sessions.get_summary(sid, uid)
        if summary and len(summary) >= 30:
            # C-1 兼容（2026-08-29）：新版存 JSON 四字段 → 渲染成可读纪要；旧版自由文本 → 原样
            try:
                from app.agent.session_compress import parse_stored, render_summary

                meta = parse_stored(summary)
                body = render_summary(meta) if meta else summary
            except Exception:
                body = summary
            history = [
                ModelRequest(
                    parts=[
                        SystemPromptPart(
                            content=f"（以下是与你的更早对话纪要，继续本轮：）\n{body}\n\n（纪要可能不完整，涉及早期细节拿不准时可以直接问用户）"
                        )
                    ]
                )
            ]
    if not history:
        # 新会话第一轮：清空 current（防跨会话残留——上次的状态不该冒充本次的），last_session 保留
        from app.memory.state import clear_current

        clear_current()
    # 2026-09-02：改走 harness 层上下文策略接口（ContextStrategy）——生产路径不再直接依赖具体压缩实现，
    # 换策略 = 注册一行（V2 实验臂 B 接入时这里零改动）。
    history, _est = prepare_history(history, sid, uid)  # 默认 = 现有摘要压缩（行为不变）
    # 预算感知（2026-08-26 P0-1）：hint 不再插 history 前缀（任何每轮变化的字节都会切断
    # DeepSeek 前缀缓存命中）——改为拼进本轮 user 消息尾部（与动态上下文一起，见下方拼接）
    hint = _budget_hint(sum(msg_len(m) for m in history)) if history else None
    file_path = _save_upload(req)
    user_text = req.message
    if file_path:
        hint = (
            f"（用户上传了文件：{file_path}，请用 ocr_image 或 read_document 读取内容后回答）\n"
            + (hint or "")
        )
    # P0-1 缓存优化（2026-08-26）：动态上下文（时间戳/状态/经验）+ 预算/上传提示拼进本轮
    # user 消息尾部——system 纯静态 + history 完全稳定 → 第二轮起全部历史轮次前缀命中。
    # 纯用户文本保留给语义缓存键（llm_cache 键=用户真正的问题，不含每轮变化的 ctx）
    _pure_user = user_text.strip()
    _ctx = build_dynamic_context()
    if _ctx:
        user_text = f"{_ctx}\n\n{user_text}"
    if hint:
        user_text = f"{hint}\n{user_text}"

    async def gen() -> AsyncIterator[str]:
        # B1 消息级持久化（2026-08-20，行业标准：用户输入无条件先落库，不依赖流完成）：
        # 壳层 = 前置落用户消息 + try/finally 兜底（断流/异常/正常都执行 _finalize，同步函数不被打断）
        state = {"messages": [], "error_msg": [""], "t0": time.monotonic()}
        state["history"] = history  # 缓存提取用（模型实际输入是 history——2026-08-21 修复）
        task_run_id = uuid.uuid4().hex[:10]
        tracker = ProgressTracker(task_run_id)
        try:
            sessions.save_user_message(sid, user_text, uid)
        except Exception as e:
            print(f"[chat-save-user] 会话 {sid[:8]} 用户消息落库失败: {e}", flush=True)
        yield _sse({"type": "run", "run_id": task_run_id})

        def _finalize() -> None:
            """finally 兜底（同步——CancelledError 只注入 await 点，同步段可靠执行）：
            落 assistant 链（断流也留底）+ 运行 trace 收尾。"""
            try:
                messages_json = (
                    ModelMessagesTypeAdapter.dump_json(state["messages"]).decode()
                    if state["messages"]
                    else ""
                )
                sessions.save_assistant_message(sid, user_text, messages_json, is_retry=is_retry, uid=uid)
            except Exception as e2:
                print(f"[chat-save-error] 会话 {sid[:8]} 落库失败: {e2}", flush=True)
            obs.run_end(
                run_id,
                "error" if state["error_msg"][0] else "ok",
                int((time.monotonic() - state["t0"]) * 1000),
                state["error_msg"][0] or "",
            )

        try:
            async for ev in _chat_stream(state, request, tracker):
                yield ev
        except asyncio.CancelledError:
            # 断流（GeneratorExit/ClientDisconnect 隐式取消）：兜底落库后重抛
            _finalize()
            raise
        except Exception:
            _finalize()
            raise
        else:
            _finalize()

    async def _chat_stream(
        state: dict, request: Request, tracker: ProgressTracker
    ) -> AsyncIterator[str]:
        full_text = ""
        turn_started = False
        error_msg = ""
        messages = state["messages"]
        _tool_names: list[str] = []  # 本轮用到的工具（缓存安全分类用，2026-08-21）
        _tool_fails = 0  # P1-3 双信号：本轮工具失败数（反思/教学优先级信号，2026-08-27）
        # 记忆变化门基线（2026-08-26 修复：ContextVar 跨 context 不共享——remember 在 agent tool
        # context 置位，流尾 consume 读不到 → 画像永不更新。改用记忆文件内容 hash 对比：
        # 覆盖 ADD/DELETE/EDIT 全部变化，与 contextvars 无关，双保险保留原 consume）
        _mem_hash_start = _memory_file_digest(uid)
        # 缓存资格判定：见模块级 _cache_eligible（2026-09-17 审计修复：黑名单近似 → 无工具调用才缓存，
        # 原黑名单只列 5 个外部工具，manage_wakeup 等写操作工具轮次被误缓存——A2-08 实证）
        # LLM 响应缓存（2026-08-21 harness 加厚：重复提问短路省成本；不做死约束——不命中照常调用）
        from app.agent.llm_cache import lookup as _cache_lookup

        _last_user = _pure_user[
            :200
        ]  # 缓存键 = 纯用户消息（2026-08-26 P0-1：user_text 已含动态 ctx，键必须是纯问题）
        if _last_user and len(_last_user) > 8:
            cached = _cache_lookup(_last_user)
            if cached:
                # 命中：直接作为回复流式输出（带"缓存回复"标记，信息给觉察）
                # 落链补洞（2026-08-21）：return 前构造 state["messages"]——否则 _finalize 落空链，
                # 恢复 API 读不到该轮（缓存命中轮刷新丢对话，实测 23:49 命中轮 json_len=0）
                try:
                    from pydantic_ai.messages import (
                        ModelRequest,
                        ModelResponse,
                        TextPart,
                        UserPromptPart,
                    )

                    state["messages"] = list(history or []) + [
                        ModelRequest(parts=[UserPromptPart(content=user_text)]),
                        ModelResponse(parts=[TextPart(content=cached)]),
                    ]
                except Exception as _e:
                    print(f"[routers/chat] 静默异常已可见化: {_e}", flush=True)
                yield _sse({"type": "turn_start"})
                yield _sse({"type": "text", "text": cached})
                yield _sse({"type": "done", "session_id": state.get("session_id", "")})
                return
        # #2 fallback 链（P0）：主模型 → 备用模型（错误分类/空 content 触发；熔断冷却期只试主）
        from app.agent.model import (
            get_fallback_model,
            get_model,
            should_fallback,
            circuit_open,
            circuit_record,
            MODEL_TIMEOUT_SECONDS,
        )

        fallback_model = get_fallback_model()
        attempts = [get_model()]
        if fallback_model and not circuit_open():
            attempts.append(fallback_model)
        # #6 整轮流总护栏（真 240s）：asyncio.timeout 包【每次尝试】，预算 = 240 - 已消耗——
        # 主吃满 180s 超时后，备用只剩 60s 预算 → 用户最坏等 240s，不是 360s（尝试前检查兑现不了这个数）
        TOTAL_BUDGET = 240
        t0 = state["t0"]
        for i, m in enumerate(attempts):
            tag = "primary" if i == 0 else "fallback"
            obs.llm_start(run_id, tag, str(m))
            remaining = TOTAL_BUDGET - (time.monotonic() - t0)
            if remaining <= 0:
                error_msg = "请求总时长超限（240s）"
                obs.error(run_id, "budget", error_msg)
                print(f"[chat-timeout] 会话 {sid[:8]} 总预算耗尽（{tag} 未尝试）", flush=True)
                # A1（2026-08-21 A3 双保险）：中断不清空——历史链 + 本轮用户消息追加进 state，
                # _finalize 落库的链含"用户说了什么"（刷新不丢对话；半截回复丢弃可接受）
                try:
                    from pydantic_ai.messages import ModelRequest, UserPromptPart

                    state["messages"] = list(history or []) + [
                        ModelRequest(parts=[UserPromptPart(content=user_text)])
                    ]
                except Exception as _e:
                    print(f"[routers/chat] 静默异常已可见化: {_e}", flush=True)
                messages = state["messages"]
                break
            try:
                truncated = False  # 2026-08-27：循环前初始化（异常路径兜底，避免 NameError）
                full_text = ""  # 每轮尝试重置（2026-08-27：提到外层可见，异常时保留半截回复）
                used_tool = False
                # model= 请求级切换（fallback 用）；model_settings.timeout=单次模型调用超时；
                # asyncio.timeout=整轮流总护栏（#6，两层级勿合并）
                async with asyncio.timeout(remaining):
                    async with agent.run_stream_events(
                        user_text,
                        message_history=history,
                        deps={"progress": tracker},
                        model=m,
                        model_settings={"timeout": MODEL_TIMEOUT_SECONDS},
                        # 轮次预算（2026-08-19，借鉴 DeepTutor 探索 8+settle 3=12 轮上界）：
                        # request_limit=模型请求轮次上限（每轮工具调用一次），防无限调工具空转；
                        # total_tokens_limit=整 run 累计 token 兜底（输入+输出+工具循环多轮累加）。
                        # ⚠️ 修正 2026-08-19：原 30000 拍低了——带工具循环的长对话累计即超
                        # （实测 30684 误伤"继续讲因果推断"正常对话，run 中断收尾钩子都没跑）。
                        # 按窗口比例：DeepSeek 128K × 70% ≈ 90000（留 30% 给模型输出余量）
                        usage_limits=UsageLimits(request_limit=8, total_tokens_limit=110000),
                    ) as stream:
                        async for ev in stream:
                            # B1 is_disconnected 检查（2026-08-20 行业标准）：客户端断开即停生成——
                            # 省"用户关页面还在烧 LLM 费"；raise CancelledError → gen 壳 _finalize 兜底落库
                            if await request.is_disconnected():
                                raise asyncio.CancelledError
                            # 注意：事件没有 .type 属性，用类名分发（字段是 event_kind）
                            et = type(ev).__name__
                            if et == "PartEndEvent":
                                # 事件时序：PartEnd（模型输出工具调用完毕，args 已就绪）→ 执行 → ToolResultEvent
                                part = getattr(ev, "part", None)
                                tool_name = getattr(part, "tool_name", None)
                                if tool_name:
                                    used_tool = True
                                    _tool_names.append(tool_name)
                                    if not turn_started:
                                        yield _sse({"type": "turn_start"})
                                        turn_started = True
                                    args = str(getattr(part, "args", "") or "")[:80]
                                    obs.tool_start(
                                        run_id, tool_name, args, getattr(part, "tool_call_id", None)
                                    )
                                    yield _sse(
                                        {
                                            "type": "tool",
                                            "name": tool_name,
                                            "status": "start",
                                            "args": args,
                                            "id": getattr(part, "tool_call_id", None),
                                        }
                                    )
                            elif et.endswith("ToolResultEvent"):
                                # 工具执行完成（FunctionToolResultEvent / OutputToolResultEvent）
                                part = getattr(ev, "part", None)
                                tool_name = getattr(part, "tool_name", None)
                                if tool_name:
                                    # 工具结果压缩（2026-08-20）：统一硬上限——改 part.content 影响
                                    # all_messages 里保存的内容（下一轮上下文），前端展示走 tool_result_status 不受影响
                                    pc = getattr(part, "content", None)
                                    if isinstance(pc, str):
                                        setattr(part, "content", _compress_tool_content(pc))
                                    # 可观测性（2026-08-18 事故补）：done 必须带结果与失败标记——
                                    # 工具返回失败时模型可能吞掉（谎报成功），harness 不变量：结果对用户可见
                                    status, result = tool_result_status(part)
                                    obs.tool_end(
                                        run_id,
                                        tool_name,
                                        status,
                                        getattr(part, "tool_call_id", None),
                                        result,
                                    )
                                    # 接地纠错循环（2026-08-30 设计 §3.3）：失败回灌已上收
                                    # error_loop（序列级接地证据，包装器记账时完成）——此处只负责
                                    # 升级事件的 obs 留痕（n=3）与硬停止系统消息（n=5，SSE 注入点）。
                                    # 选 SSE 注入而非包装器返回串：设计语义要求用户看到的一定是
                                    # 【系统标识】消息；包装器返回进的是模型上下文，说不说归模型，
                                    # 用户可能永远看不到——SSE type=system 由前端系统样式渲染，模型无法让失败看起来没发生过。
                                    if status == "error":
                                        _tool_fails += 1
                                        try:
                                            from app.agent import error_loop

                                            _n = error_loop.consecutive_errors()
                                            if _n == error_loop.ESCALATE_N:
                                                obs.hook(
                                                    run_id,
                                                    "error_escalation",
                                                    True,
                                                    f"连续 {_n} 次工具失败（session 内）",
                                                )
                                            if error_loop.consume_hard_stop():
                                                obs.hook(
                                                    run_id,
                                                    "error_hard_stop",
                                                    True,
                                                    f"连续 {error_loop.HARD_STOP_N} 次工具失败，冻结一轮",
                                                )
                                                yield _sse(
                                                    {
                                                        "type": "system",
                                                        "text": error_loop.HARD_STOP_MESSAGE,
                                                    }
                                                )
                                        except Exception as _e:
                                            print(f"[routers/chat] 静默异常已可见化: {_e}", flush=True)
                                    yield _sse(
                                        {
                                            "type": "tool",
                                            "name": tool_name,
                                            "status": status,
                                            "id": getattr(part, "tool_call_id", None),
                                            "result": result,
                                        }
                                    )
                            elif et == "PartDeltaEvent":
                                d = ev.delta
                                kind = getattr(d, "part_delta_kind", None)
                                text = getattr(d, "content_delta", None)
                                if not text:
                                    continue
                                if not turn_started:
                                    yield _sse({"type": "turn_start"})
                                    turn_started = True
                                if kind == "text":
                                    full_text += text
                                    yield _sse({"type": "delta", "text": text})
                                elif kind == "thinking":
                                    yield _sse({"type": "thinking", "text": text})
                msgs = stream.all_messages()
                # 截断检测（2026-08-27 根治"输出一半无提示"）：模型撞单次输出上限时流正常结束、
                # 无异常无 error——必须显式读 finish_reason 才能发现。length=被截断→前端提示可继续
                truncated = False
                try:
                    _fr = getattr(msgs[-1], "finish_reason", None)
                    if _fr is not None and str(_fr) == "length":
                        truncated = True
                except Exception as _e:
                    print(f"[routers/chat] 静默异常已可见化: {_e}", flush=True)
                if full_text or used_tool:
                    # 成功（有文本或有工具调用）——注意：有工具调用的 run 不重试（规避副作用重复，用户拍板 A）
                    # token 用量记录（A2-5 2026-08-20：逻辑下沉 obs.token_usage，主流程/子任务同一台账；
                    # 2026-08-26 P0-2 修复：stream.usage 是属性非方法（pydantic-ai 2.27）——
                    # 主流程 08-21 起静默断流 5 天（delegation 已修，main 漏网），异常打印可见防再断）
                    try:
                        obs.token_usage(sid, stream.usage, model=m)
                    except Exception as e:
                        print(f"[usage] token_usage 记录失败: {str(e)[:120]}", flush=True)
                    messages = msgs
                    state["messages"] = (
                        msgs  # B1 引用同步（_finalize 读 state——548 行重新赋值会断引用）
                    )
                    if truncated:
                        obs.hook(
                            run_id,
                            "truncated",
                            True,
                            f"finish_reason=length 输出截断 len={len(full_text)}",
                        )
                        print(
                            f"[truncated] 会话 {sid[:8]} 模型输出达单次上限被截断（len={len(full_text)}）",
                            flush=True,
                        )
                    obs.llm_end(run_id, tag, True)  # LLM 调用成功（2026-08-21 补：配对算耗时）
                    # 截断自动续写（2026-08-27，用户：不能截断就截断）：finish_reason=length →
                    # 自动续写最多 2 次，用户无感知拿到完整回复（Claude Code 同类行为）。
                    # 续写轮禁工具（纯文字续）；续写轮异常/调工具 → 放弃并保持截断提示可见
                    _cont = 0
                    while truncated and full_text and _cont < 2:
                        _cont += 1
                        obs.hook(run_id, "auto_continue", True, f"#{_cont} len={len(full_text)}")
                        print(
                            f"[auto-continue] 会话 {sid[:8]} 截断自动续写 #{_cont}（当前 {len(full_text)} 字）",
                            flush=True,
                        )
                        try:
                            async with asyncio.timeout(remaining):
                                async with agent.run_stream_events(
                                    "（系统自动续写指令）你刚才的回复因长度限制被截断了。请直接从你中断的地方继续写，"
                                    "不要重复已写内容，不要调用任何工具，只继续输出文字。",
                                    message_history=msgs,
                                    deps={"progress": tracker},
                                    model=m,
                                    model_settings={"timeout": MODEL_TIMEOUT_SECONDS},
                                    usage_limits=UsageLimits(
                                        request_limit=4, total_tokens_limit=110000
                                    ),
                                ) as st2:
                                    cont_text, cont_tool = "", False
                                    async for ev2 in st2:
                                        et2 = type(ev2).__name__
                                        if et2 == "PartDeltaEvent":
                                            d2 = ev2.delta
                                            if getattr(d2, "part_delta_kind", None) == "text":
                                                tx = getattr(d2, "content_delta", None)
                                                if tx:
                                                    cont_text += tx
                                                    full_text += tx
                                                    yield _sse({"type": "delta", "text": tx})
                                        elif et2.endswith("ToolResultEvent"):
                                            cont_tool = True
                                msgs = st2.all_messages()
                                state["messages"] = msgs
                                _fr2 = getattr(msgs[-1], "finish_reason", None)
                                truncated = _fr2 is not None and str(_fr2) == "length"
                                if cont_tool or not cont_text:
                                    truncated = (
                                        True  # 续写轮调工具/无输出 → 放弃续写（保持截断提示）
                                    )
                        except Exception as e_cont:
                            obs.hook(run_id, "auto_continue", False, str(e_cont)[:80])
                            print(f"[auto-continue] 续写失败: {e_cont}", flush=True)
                            truncated = True  # 续写失败 → 保持截断提示可见（不静默）
                    if full_text:
                        obs.llm_output(
                            run_id, tag, full_text
                        )  # 回复全文进 trace（重放可见，2026-08-21 补）
                    # 纯问答轮存缓存（无工具调用才存——2026-09-17 审计修复见 _cache_eligible；
                    # harness 兜底不做死约束）
                    if full_text and _cache_eligible(_tool_names):
                        try:
                            from app.agent.llm_cache import store as _cache_store

                            obs.hook(
                                run_id,
                                "cache_store",
                                True,
                                f"u={len(_last_user)} f={len(full_text)} tools={_tool_names}",
                            )
                            _cache_store(_last_user or "", full_text)
                        except Exception as e:
                            obs.hook(run_id, "cache_store", False, str(e)[:80])
                            pass
                    circuit_record(True)
                    break
                # 空 content（166 轮 0 字场景的正主）：无文本且无工具调用 → 确定性判定（有没有字/有没有调工具）
                if i < len(attempts) - 1:
                    obs.error(run_id, "empty", f"{tag} 空content(0字无工具) → fallback")
                    print(
                        f"[fallback] 会话 {sid[:8]} {tag} 空content(0字无工具) → fallback",
                        flush=True,
                    )
                    circuit_record(False)
                    continue
                error_msg = "模型返回空回复（已重试）"
                obs.error(run_id, "empty", error_msg)
                circuit_record(False)
                break
            except asyncio.TimeoutError:
                # #6 整轮流超时（asyncio.timeout 总护栏 240s 触发）——剩余预算耗尽，直接 error，不再重试
                error_msg = "请求总时长超限（240s）"
                obs.llm_end(run_id, tag, False)
                obs.error(run_id, "timeout", f"{tag} 触发总护栏 240s")
                print(f"[chat-timeout] 会话 {sid[:8]} {tag} 触发总护栏 240s", flush=True)
                circuit_record(False)
                # A1（2026-08-21 A3 双保险）：中断不清空——历史链 + 本轮用户消息追加进 state，
                # _finalize 落库的链含"用户说了什么"（刷新不丢对话；半截回复丢弃可接受）
                try:
                    from pydantic_ai.messages import ModelRequest, UserPromptPart

                    state["messages"] = list(history or []) + [
                        ModelRequest(parts=[UserPromptPart(content=user_text)])
                    ]
                except Exception as _e:
                    print(f"[routers/chat] 静默异常已可见化: {_e}", flush=True)
                messages = state["messages"]
                break
            except Exception as e:
                obs.llm_end(run_id, tag, False)  # LLM 调用异常（2026-08-21 补）
                if i < len(attempts) - 1 and should_fallback(e):
                    obs.error(run_id, "llm_fallback", f"{tag} 异常→fallback: {str(e)[:120]}")
                    print(
                        f"[fallback] 会话 {sid[:8]} {tag} 异常→fallback: {str(e)[:120]}", flush=True
                    )
                    circuit_record(False)
                    continue
                # #4 异常路径：API 失败/超时/断流 → 用户消息必须落库（否则消息丢失）+ 前端收到 error 事件
                error_msg = str(e)[:200]
                obs.error(run_id, "llm", error_msg)
                print(f"[chat-error] 会话 {sid[:8]} {tag} 异常: {error_msg}", flush=True)
                circuit_record(False)
                # A1（2026-08-21 A3 双保险）：中断不清空——历史链 + 本轮用户消息追加进 state，
                # _finalize 落库的链含"用户说了什么"（刷新不丢对话；半截回复丢弃可接受）
                try:
                    from pydantic_ai.messages import ModelRequest, UserPromptPart

                    state["messages"] = list(history or []) + [
                        ModelRequest(parts=[UserPromptPart(content=user_text)])
                    ]
                except Exception as _e:
                    print(f"[routers/chat] 静默异常已可见化: {_e}", flush=True)
                # 2026-08-27 用户明确不接受"半截回复丢弃"：异常时把已生成文本也落库
                # （前端已显示的部分刷新后不丢；full_text 可能未定义→外层 "" 兜底）
                if full_text:
                    try:
                        from pydantic_ai.messages import ModelResponse, TextPart

                        state["messages"] = list(history or []) + [
                            ModelRequest(parts=[UserPromptPart(content=user_text)]),
                            ModelResponse(parts=[TextPart(content=full_text)]),
                        ]
                    except Exception as _e:
                        print(f"[routers/chat] 静默异常已可见化: {_e}", flush=True)
                messages = state["messages"]
                break
        if error_msg:
            state["error_msg"][0] = error_msg
            yield _sse(
                {"type": "error", "message": error_msg, "hint": _error_hint(error_msg)}
            )  # 前端显示错误+下一步建议而非干等
        # B1 持久化移至 gen 壳的 _finalize（finally 兜底：断流/异常/正常都执行）——此处不再落库
        # 状态轮：会话结束快照 current → last_session（跨会话接续地基）
        from app.memory.state import snapshot_to_last_session

        snapshot_to_last_session()
        # A1（2026-08-20）：沉淀钩子 done 后异步——done 立即发出（体验：不等数十秒提炼），
        # 提炼后台跑（成本：不阻塞响应；串行防并发写 memory 文件竞态）。
        # 流内只保留：状态轮快照（上）+ 闪光提炼（SSE glint 事件需 done 前推送）。
        # 口径：profile 仍挂记忆变化门（consume 提前消费，值传后台任务）；
        # 其余五路（困惑/关系/续接点/教学/主题）每会话末必跑（不挂门——聊了困惑但没 remember 是最该提炼的场景）。
        from app.memory.store import consume_memory_changed

        # 2026-08-26 修复：双通道判定——文件 hash 变化（跨 context 可靠）或 ContextVar 置位
        need_profile = consume_memory_changed() or (_memory_file_digest() != _mem_hash_start)
        dialogue = history_to_text(messages[-8:]) if messages else ""
        if dialogue:
            # 闪光提炼（2026-08-20，拾光=拾到我们没发现的闪光）：提炼"用户没发现的自己"→
            # SSE glint 事件（done 前推前端，给最后一条 assistant 消息挂金光点）+ 写 cat=闪光
            # 与困惑同构：提炼归模型三判据，无闪光 None（零成本）；闪光≠夸奖≠困惑
            try:
                from app.memory.store import extract_session_glint, remember

                glint = await extract_session_glint(dialogue)
                if glint:
                    yield _sse({"type": "glint", "text": glint})
                    gr = await remember(glint, source="agent", importance=7, category="闪光")
                    obs.hook(run_id, "glint", True, gr)
                    print(f"[glint] 会话 {sid[:8]} 拾到闪光 → {gr}", flush=True)
                else:
                    # B4（2026-08-27）：None 也留痕——观测台可区分"在跑但无闪光"与"没跑"（绿了不算）
                    obs.hook(run_id, "glint", True, "none（模型三判据：本轮无闪光）")
            except Exception as e4b:
                obs.hook(run_id, "glint", False, str(e4b))
                print(f"[glint] 会话 {sid[:8]} 闪光提炼失败: {e4b}", flush=True)
        if turn_started:
            yield _sse({"type": "turn_end"})
        # 截断提示（2026-08-27 根治"静默半截"）：done 前推——前端琥珀色提示"可直接说继续"而非干等
        if truncated:
            yield _sse({"type": "truncated", "reason": "output_length", "len": len(full_text)})
        # 工具调用后无正文提示（2026-08-27 用户场景：工具跑完就停、没有文字解读——看起来像中断）。
        # 只提示不判定（判断无墙）：模型可能故意只调工具等用户看结果；harness 让"没输出"这件事可见
        if used_tool and not full_text and not truncated and not error_msg:
            yield _sse({"type": "tool_only", "tools": _tool_names[-3:]})
            obs.hook(run_id, "tool_only", True, "工具调用后无正文输出（模型选择停在这里）")
        # A1：沉淀钩子后台化（done 立即发出；任务持有引用防 GC，串行锁防并发写）
        task = asyncio.create_task(
            _run_post_hooks(sid, run_id, dialogue, need_profile, tool_fails=_tool_fails, uid=uid)
        )
        _POST_HOOK_TASKS.add(task)
        task.add_done_callback(_POST_HOOK_TASKS.discard)

        yield _sse({"type": "done", "session_id": sid})

    return StreamingResponse(gen(), media_type="text/event-stream")


