"""M1 FastAPI 入口：POST /api/chat（SSE 流式）—— 学习搭子对话循环
SSE 协议（自定义 JSON 事件，M4 前端直接消费）：
  data: {"type":"delta","text":"..."}   文本增量
  data: {"type":"thinking","text":"..."} 思考增量（前端可选展示）
  data: {"type":"done","session_id":"..."}
"""
import asyncio
import base64
import json
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from pydantic_ai.messages import ModelMessagesTypeAdapter, ModelRequest, SystemPromptPart

from app import scheduler
from app.agent.delegation import ProgressTracker
from app.agent.tutor import build_tutor_agent
from app.db import sessions, wakeups
from app.memory.store import recall_profile

UPLOAD_DIR = Path(__file__).resolve().parent.parent / "data" / "uploads"

# ---------- 长程 compaction（Pi 机制轻量版：摘要 + 尾部保留）----------
# 触发阈值 90K 字符：50 轮探测=66.5K，约 75 轮触发一次；压缩后腾出空间再撑 30-40 轮 → 覆盖 2 小时
COMPACT_THRESHOLD_CHARS = 90_000
COMPACT_TAIL_CHARS = 20_000  # 压缩后保留最近 ~20K 字符（≈15 轮细节，Pi keepRecentTokens 精神）


@asynccontextmanager
async def lifespan(_: FastAPI):
    """启动：会话库 + 唤醒库建表 + 记忆/知识库恢复（服务端创建=可写）+ 调度器常驻；关闭：停调度器"""
    from app.config import SHIGUANG_TOKEN

    if not SHIGUANG_TOKEN:
        print("[auth] ⚠️ 未配置 SHIGUANG_TOKEN——/api/* 鉴权关闭（仅适合 127.0.0.1 本地；局域网/公网必须配置）", flush=True)
    # #5 存储：启动时 VACUUM 收缩文件（清空旧链后空间释放；启动无并发，锁库安全；失败跳过）
    try:
        sessions.vacuum()
    except Exception as e:
        print(f"[db] VACUUM 失败（跳过）: {e}", flush=True)
    sessions.init_db()
    wakeups.init_db()
    from app.memory.recovery import restore_from_backup, restore_kb_index, restore_evolution_index

    restored = restore_from_backup()
    if restored:
        print(f"[recovery] 已从备份恢复: {', '.join(restored)}")
    kb_state = restore_kb_index()
    if not kb_state.startswith("kb: 索引正常"):
        print(f"[recovery] {kb_state}")
    evo_state = await restore_evolution_index()
    if not evo_state.startswith("evo: 索引正常"):
        print(f"[recovery] {evo_state}")
    scheduler.start()
    yield
    scheduler.stop()


app = FastAPI(title="personal-agent 学习搭子", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)

# 前端产物单一目录（#B 拆双目录 2026-08-13）：后端直接读 frontend/dist——构建产物只此一份，
# 消除"app/static 与 dist 两版漂移"根因（旧版 static/index.html 是 8/11 残留，已 git rm）。
# 部署/更新流程：cd frontend && npm run build → dist 即服务目录（dist 不进 git，构建是部署步骤）
STATIC_DIR = Path(__file__).resolve().parent.parent / "frontend" / "dist"
app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")


@app.get("/favicon.svg", include_in_schema=False)
def favicon():
    return FileResponse(STATIC_DIR / "favicon.svg")


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """P0 门锁（2026-08-12 体检 #11）：/api/* 校验 Authorization: Bearer <SHIGUANG_TOKEN>。
    静态资源（index/assets）放行；未配置 token = 鉴权关闭（本地 127.0.0.1 免鉴权是特性）。"""
    from app.config import SHIGUANG_TOKEN

    if SHIGUANG_TOKEN and request.url.path.startswith("/api/"):
        auth = request.headers.get("authorization", "")
        if auth != f"Bearer {SHIGUANG_TOKEN}":
            return JSONResponse(status_code=401, content={"detail": "unauthorized"})
    return await call_next(request)


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


def _load_history(session_id: str | None):
    """恢复历史：DB 里存的完整对话链 JSON → pydantic-ai ModelMessage"""
    if not session_id:
        return None
    messages_json = sessions.load_messages_json(session_id)
    if not messages_json:
        return None
    try:
        return ModelMessagesTypeAdapter.validate_json(messages_json)
    except Exception:
        return None


# ---------- 长程 compaction：摘要生成 / 触发 / 注入 ----------

def _history_to_text(history) -> str:
    """ModelMessage 列表 → 可读对话文本（供摘要 LLM 输入）"""
    lines = []
    for m in history:
        for p in getattr(m, "parts", []):
            pn = type(p).__name__
            if pn == "UserPromptPart":
                lines.append(f"用户：{p.content}")
            elif pn == "SystemPromptPart":
                lines.append(f"系统：{p.content}")
            elif pn == "TextPart":
                lines.append(f"AI：{p.content}")
            elif pn == "ToolCallPart":
                lines.append(f"[工具调用：{p.tool_name}]")
            elif pn == "ToolReturnPart":
                lines.append(f"[工具返回：{str(p.content)[:80]}]")
    return "\n".join(lines)


def _summarize(conversation_text: str) -> str | None:
    """独立 LLM 调用生成学习向摘要（Pi compaction 的摘要步骤）；失败返回 None（幂等，下次重试）"""
    try:
        from openai import OpenAI

        from app.config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL

        client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
        resp = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[
                {"role": "system", "content": "你是学习搭子的会话摘要器。把用户与 AI 的对话压缩成结构化摘要，必须保留：①学习主题与进度 ②讲过的关键概念（每个一行）③用户暴露的偏好/水平/卡点 ④未解决的问题或待办。用中文，300 字以内，短句。"},
                {"role": "user", "content": conversation_text[-40000:]},
            ],
            max_tokens=800,
            temperature=0.3,
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception:
        return None


def _msg_len(m) -> int:
    """单条消息文本字符粗估（尾部保留预算用）"""
    total = 0
    for p in getattr(m, "parts", []):
        pn = type(p).__name__
        if pn in ("UserPromptPart", "SystemPromptPart", "TextPart"):
            total += len(getattr(p, "content", "") or "")
        elif pn == "ThinkingPart":
            total += len(getattr(p, "content", "") or "")
        elif pn == "ToolCallPart":
            total += len(getattr(p, "tool_name", "") or "") + 40
        elif pn == "ToolReturnPart":
            total += len(str(getattr(p, "content", "") or "")) // 2
    return total


def _apply_compaction(sid: str, history):
    """长程 compaction（Pi 机制：摘要消息 + 截断 + 尾部保留）：
    - 已压缩 → [摘要 system 消息, ...尾部保留消息]
    - 未压缩且超阈值 → 生成摘要并存储，同样构建
    - 失败幂等（摘要生成失败返回原 history，下次重试）；未超阈值原样返回
    返回 (history, est)——est 供预算感知分级注入
    """
    if not history:
        return history, 0
    summary = sessions.get_summary(sid)
    bad_summary = summary is not None and len(summary) < 30
    if bad_summary:
        # 读取端兜底：坏摘要（如 '🌙' 1 字）视为无摘要 → 走生成路径（写入端校验拦不住已落库的坏数据）
        print(f"[compaction] 会话 {sid[:8]} 检测到坏摘要({len(summary)}字)，重新生成", flush=True)
        summary = None
    est = 0
    if not summary:
        # 触发判定：用反序列化后的 history 真实估算（含工具 part/thinking）——
        # 不能用 DB content 列（assistant 存的是占位符 "(streamed)"，会永久低估导致永不到阈值）
        est = sum(_msg_len(m) for m in history)
        from collections import Counter
        _pt = Counter(type(p).__name__ for m in history for p in getattr(m, "parts", []))
        print(f"[compaction-debug] 会话 {sid[:8]} est={est} 阈值={COMPACT_THRESHOLD_CHARS} parts={dict(_pt)}", flush=True)
        if est < COMPACT_THRESHOLD_CHARS and not bad_summary:
            # 正常未压缩才跳过；坏摘要必须重生成（否则摘要永久缺失，早期信息不可恢复）
            return history, est
        summary = _summarize(_history_to_text(history))
        if not summary or len(summary) < 30:
            # 摘要过短视为失败（API 偶发截断/异常）——幂等，下次请求重试
            return history, est
        sessions.set_summary(sid, summary)
        # #5 存储 O(n²)→O(n)：压缩成功即清空旧 messages_json（保留 MAX(id) 行=重放源；归档失败不阻塞）
        sessions.clear_old_chains(sid)
        print(f"[compaction] 会话 {sid[:8]} 已压缩，摘要 {len(summary)} 字，保留尾部 {COMPACT_TAIL_CHARS} 字符", flush=True)
    else:
        est = sum(_msg_len(m) for m in history)
    # 尾部保留：从尾部往前取到字符预算，并保证以用户回合开头（避免截断在 assistant 回复中间）
    tail, used = [], 0
    for m in reversed(history):
        ml = _msg_len(m)
        if tail and used + ml > COMPACT_TAIL_CHARS:
            break
        tail.append(m)
        used += ml
    tail.reverse()
    while tail and type(tail[0]).__name__ == "ModelResponse":
        tail.pop(0)
    prefix = ModelRequest(
        parts=[SystemPromptPart(content=f"（以下是与你的更早对话摘要，继续本轮：）\n{summary}\n\n（摘要可能不完整，涉及早期细节拿不准时可以直接问用户）")]
    )
    return [prefix] + tail, est


# 预算感知：上下文预算分级注入（护栏=提供信息，模型自己决定怎么收着点）
BUDGET_MAX_CHARS = 90_000  # 与 compaction 阈值同口径（est 字符估算）
BUDGET_WARN_PCT = 0.7      # >70% 提示精简
BUDGET_URGENT_PCT = 0.88   # >88% 强提示（接近压缩点）

def _budget_hint(est: int) -> str | None:
    if est <= 0:
        return None
    pct = est / BUDGET_MAX_CHARS
    if pct >= BUDGET_URGENT_PCT:
        return f"（上下文预算已用 {pct:.0%}，接近上限：请优先讲核心结论，工具调用从简）"
    if pct >= BUDGET_WARN_PCT:
        return f"（上下文预算已用 {pct:.0%}：回复请酌情精简，聚焦用户当前问题）"
    return None


@app.post("/api/chat")
async def chat(req: ChatRequest, request: Request) -> StreamingResponse:
    agent = build_tutor_agent()
    # #6 去重标志：前端手动重试带 X-Retry: 1（优先认标志，比内容匹配可靠；内容匹配仅作无标志回退）
    is_retry = request.headers.get("x-retry") == "1"
    sid = req.session_id if (req.session_id and sessions.session_exists(req.session_id)) else sessions.new_session()
    history = _load_history(sid)
    if not history:
        # 新会话第一轮：清空 current（防跨会话残留——上次的状态不该冒充本次的），last_session 保留
        from app.memory.state import clear_current

        clear_current()
    history, _est = _apply_compaction(sid, history)  # 长程 compaction：超阈值压旧保新
    # 预算感知：基于最终返回链重算（压缩后 est 归零/变小——不能用压缩前的值，否则已压缩会话每轮误报 287%）
    hint = _budget_hint(sum(_msg_len(m) for m in history)) if history else None
    if hint and history:
        history = [ModelRequest(parts=[SystemPromptPart(content=hint)])] + history
    file_path = _save_upload(req)
    user_text = req.message
    if file_path:
        hint = f"（用户上传了文件：{file_path}，请用 ocr_image 或 read_document 读取内容后回答）\n"
        user_text = hint + user_text

    async def gen() -> AsyncIterator[str]:
        full_text = ""
        # M7：每个 run 一个 run_id + 进度 tracker（deps 注入，进度卡唯一通道）
        run_id = uuid.uuid4().hex[:10]
        tracker = ProgressTracker(run_id)
        yield _sse({"type": "run", "run_id": run_id})
        turn_started = False
        error_msg = ""
        messages = []
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
        t0 = time.monotonic()
        for i, m in enumerate(attempts):
            tag = "primary" if i == 0 else "fallback"
            remaining = TOTAL_BUDGET - (time.monotonic() - t0)
            if remaining <= 0:
                error_msg = "请求总时长超限（240s）"
                print(f"[chat-timeout] 会话 {sid[:8]} 总预算耗尽（{tag} 未尝试）", flush=True)
                messages = []
                break
            try:
                full_text = ""
                used_tool = False
                # model= 请求级切换（fallback 用）；model_settings.timeout=单次模型调用超时；
                # asyncio.timeout=整轮流总护栏（#6，两层级勿合并）
                async with asyncio.timeout(remaining):
                    async with agent.run_stream_events(
                        user_text, message_history=history, deps={"progress": tracker},
                        model=m, model_settings={"timeout": MODEL_TIMEOUT_SECONDS},
                    ) as stream:
                        async for ev in stream:
                            # 注意：事件没有 .type 属性，用类名分发（字段是 event_kind）
                            et = type(ev).__name__
                            if et == "PartEndEvent":
                                # 事件时序：PartEnd（模型输出工具调用完毕，args 已就绪）→ 执行 → ToolResultEvent
                                part = getattr(ev, "part", None)
                                tool_name = getattr(part, "tool_name", None)
                                if tool_name:
                                    used_tool = True
                                    if not turn_started:
                                        yield _sse({"type": "turn_start"})
                                        turn_started = True
                                    args = str(getattr(part, "args", "") or "")[:80]
                                    yield _sse({
                                        "type": "tool",
                                        "name": tool_name,
                                        "status": "start",
                                        "args": args,
                                        "id": getattr(part, "tool_call_id", None),
                                    })
                            elif et.endswith("ToolResultEvent"):
                                # 工具执行完成（FunctionToolResultEvent / OutputToolResultEvent）
                                part = getattr(ev, "part", None)
                                tool_name = getattr(part, "tool_name", None)
                                if tool_name:
                                    yield _sse({
                                        "type": "tool",
                                        "name": tool_name,
                                        "status": "done",
                                        "id": getattr(part, "tool_call_id", None),
                                    })
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
                if full_text or used_tool:
                    # 成功（有文本或有工具调用）——注意：有工具调用的 run 不重试（规避副作用重复，用户拍板 A）
                    messages = msgs
                    circuit_record(True)
                    break
                # 空 content（166 轮 0 字场景的正主）：无文本且无工具调用 → 确定性判定（有没有字/有没有调工具）
                if i < len(attempts) - 1:
                    print(f"[fallback] 会话 {sid[:8]} {tag} 空content(0字无工具) → fallback", flush=True)
                    circuit_record(False)
                    continue
                error_msg = "模型返回空回复（已重试）"
                circuit_record(False)
                break
            except asyncio.TimeoutError:
                # #6 整轮流超时（asyncio.timeout 总护栏 240s 触发）——剩余预算耗尽，直接 error，不再重试
                error_msg = "请求总时长超限（240s）"
                print(f"[chat-timeout] 会话 {sid[:8]} {tag} 触发总护栏 240s", flush=True)
                circuit_record(False)
                messages = []
                break
            except Exception as e:
                if i < len(attempts) - 1 and should_fallback(e):
                    print(f"[fallback] 会话 {sid[:8]} {tag} 异常→fallback: {str(e)[:120]}", flush=True)
                    circuit_record(False)
                    continue
                # #4 异常路径：API 失败/超时/断流 → 用户消息必须落库（否则消息丢失）+ 前端收到 error 事件
                error_msg = str(e)[:200]
                print(f"[chat-error] 会话 {sid[:8]} {tag} 异常: {error_msg}", flush=True)
                circuit_record(False)
                messages = []
                break
        if error_msg:
            yield _sse({"type": "error", "message": error_msg})  # 前端显示错误而非干等
        # 持久化：完整对话链（供下次重放）+ 用户消息（异常时也要落用户消息，避免丢消息）
        try:
            messages_json = ModelMessagesTypeAdapter.dump_json(messages).decode() if messages else ""
            sessions.save_run(sid, user_text, messages_json, is_retry=is_retry)
        except Exception as e2:
            print(f"[chat-save-error] 会话 {sid[:8]} 落库失败: {e2}", flush=True)
        # 状态轮：会话结束快照 current → last_session（跨会话接续地基）
        from app.memory.state import snapshot_to_last_session

        snapshot_to_last_session()
        # D1 事件兜底（v0.2）：本请求轮末若有记忆变化 → 机器触发画像重提炼（触发归机器，提炼归模型）
        # 口径：turn-end 粒度（每轮 POST 末尾）——单用户频率低、画像更及时；频率受 remember 去重天然制约
        from app.memory.store import consume_memory_changed, update_profile

        if consume_memory_changed():
            try:
                rp = await update_profile()
                print(f"[profile] 会话 {sid[:8]} 记忆变化 → {rp}", flush=True)
            except Exception as e3:
                print(f"[profile] 会话 {sid[:8]} 画像刷新失败: {e3}", flush=True)
        if turn_started:
            yield _sse({"type": "turn_end"})
        yield _sse({"type": "done", "session_id": sid})

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.get("/", include_in_schema=False)
def index():
    """前端首页。产物新鲜度哨兵（防"以为是新的其实是旧的"复发）：build.json 时间戳放响应头 + 启动日志。
    build 产物由 npm run build 写 dist/build.json（见 frontend/package.json），start.bat 启动前必 build。"""
    resp = FileResponse(STATIC_DIR / "index.html")
    try:
        bi = json.loads((STATIC_DIR / "build.json").read_text(encoding="utf-8"))
        resp.headers["X-Built-At"] = bi.get("built_at", "")
    except Exception:
        pass
    return resp


@app.get("/api/memory")
def get_memory():
    from app.agent.evolution import list_reflections, list_skills
    from app.memory.store import read_entries

    return {
        "profile": recall_profile(),
        "entries": [
            {
                "content": e.content,
                "category": e.category,
                "importance": e.importance,
                "date": e.created_at,
                "source": e.source,
            }
            for e in read_entries()
        ],
        "reflections": list_reflections(),
        "skills": list_skills(),
    }


class MemoryEditRequest(BaseModel):
    old: str
    new: str


class MemoryDeleteRequest(BaseModel):
    content: str


@app.post("/api/memory/edit")
async def memory_edit(req: MemoryEditRequest):
    from app.memory.store import edit_memory

    return {"ok": True, "msg": await edit_memory(req.old, req.new)}


@app.post("/api/memory/delete")
def memory_delete(req: MemoryDeleteRequest):
    from app.memory.store import forget

    return {"ok": True, "msg": forget(req.content)}


class EvolutionDeleteRequest(BaseModel):
    kind: str  # reflection | skill
    content: str


@app.post("/api/evolution/delete")
def evolution_delete(req: EvolutionDeleteRequest):
    """M5 人可删：删除反思/技能条目（文件 + 向量）"""
    from app.agent.evolution import delete_item

    return {"ok": True, "msg": delete_item(req.kind, req.content)}


@app.get("/api/sessions")
def sessions_list():
    """历史会话列表（B，DeepSeek 式）：标题 + 时间 + 消息数"""
    from app.db.sessions import list_sessions

    return {"sessions": list_sessions()}


@app.post("/api/session/new")
def session_new():
    """新建会话：返回新 session_id（前端切到新会话）"""
    from app.db.sessions import new_session

    return {"session_id": new_session()}


@app.get("/api/session/{sid}")
def get_session(sid: str):
    """恢复会话：把持久化的对话链转成前端格式返回（刷新后恢复消息列表）"""
    from app.db.sessions import load_messages_json
    from pydantic_ai.messages import ModelMessagesTypeAdapter

    raw = load_messages_json(sid)
    if not raw:
        return {"messages": []}
    try:
        msgs = ModelMessagesTypeAdapter.validate_json(raw)
    except Exception as e:
        return {"messages": [], "error": str(e)}
    out = []
    for m in msgs:
        parts = getattr(m, "parts", []) or []
        content, thinking = "", ""
        tool_calls = []
        is_user = any(getattr(p, "part_kind", "") == "user-prompt" for p in parts)
        for p in parts:
            kind = getattr(p, "part_kind", "")
            if kind == "user-prompt":
                content += getattr(p, "content", "")
            elif kind == "text":
                content += getattr(p, "content", "")
            elif kind == "thinking":
                thinking += getattr(p, "content", "")
            elif kind == "tool-call":
                args = str(getattr(p, "args", "") or "")[:80]
                tool_calls.append(
                    {
                        "id": getattr(p, "tool_call_id", None),
                        "name": getattr(p, "tool_name", ""),
                        "status": "done",
                        "args": args or None,
                    }
                )
        # 跳过 system-prompt / tool-return 专用消息（无用户内容也无模型内容）
        if not content and not thinking and not tool_calls and not is_user:
            continue
        out.append(
            {
                "role": "user" if is_user else "assistant",
                "content": content or ("(调用了工具)" if tool_calls else ""),
                "thinking": thinking,
                "toolCalls": tool_calls,
                "done": True,
            }
        )
    return {"messages": out}


@app.get("/api/kb/reindex")
def kb_reindex_api():
    """手动重建知识库索引（源文件权威；删库/索引损坏/检索引空时用）"""
    from app.tools.kb import kb_reindex

    return {"ok": True, "msg": kb_reindex()}


@app.get("/api/progress")
def get_progress():
    """学习进度（可视化左栏）：从记忆条目推导客观事实；无数据则诚实空态
    - 主题节点：goal/进度/学习记录 类条目
    - streak：需要每日学习日志（M6 接入），当前无则不虚构
    """
    from app.memory.store import read_entries

    entries = read_entries()
    goal_cats = {"goal", "目标", "progress", "进度", "learning", "学习记录"}
    topics = []
    for e in entries:
        if e.category in goal_cats and e.content.strip():
            title = e.content.strip()
            topics.append(
                {
                    "title": title[:40] + ("…" if len(title) > 40 else ""),
                    "status": "active",
                    "date": e.created_at,
                }
            )
    # streak：连续学习天数来自 daily_activity（M6 学习日志真数据，不虚构）
    return {
        "topics": topics[:6],
        "streak": wakeups.streak_days(),
        "hasLearningLog": wakeups.has_learning_log(),
        "memoryCount": len(entries),
        "recentActivity": [
            {"date": a["date"], "topics": json.loads(a.get("topics") or "[]")}
            for a in wakeups.recent_activity(7)
        ],
    }


# ---------- M6 通知 API（前端轮询投递）----------

@app.get("/api/notifications")
def get_notifications():
    return {"notifications": wakeups.notifications(20)}


# ---------- M7 多 agent 任务进度（前端进度卡轮询）----------

@app.get("/api/tasks/{run_id}")
async def get_task_progress(run_id: str):
    snap = await ProgressTracker(run_id).snapshot()
    return {"run_id": run_id, "progress": snap}


# ---------- M8 进化层反馈（前端 👎/👍 按钮 → 反思/技能）----------

class FeedbackRequest(BaseModel):
    rating: int  # -1=不满意（触发反思）, 1=满意（提示可存技能）
    message: str  # 用户当时说的话
    response: str | None = None  # 模型的回复（上下文）


@app.post("/api/feedback")
async def feedback(req: FeedbackRequest):
    """响应显式用户动作：👎 → 触发反思入库；👍 → 返回提示信息（由模型自主决定是否存技能）"""
    from app.agent.evolution import reflect_teaching

    if req.rating < 0:
        ctx = f"用户说：{req.message}"
        if req.response:
            ctx += f"\n我当时的讲解：{req.response[:500]}"
        result = await reflect_teaching(ctx)
        return {"ok": True, "handled": "reflection", "msg": result}
    return {"ok": True, "handled": "ack", "msg": "已收到 👍，觉得这套讲法好可以直接告诉我存进技能库"}


class NotificationReadRequest(BaseModel):
    id: int


@app.post("/api/notifications/read")
def notification_read(req: NotificationReadRequest):
    wakeups.mark_read(req.id)
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
