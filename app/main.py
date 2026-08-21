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
from pydantic_ai import UsageLimits
from pydantic_ai.messages import ModelMessagesTypeAdapter, ModelRequest, SystemPromptPart

from app import scheduler
from app import observability as obs
from app.agent.delegation import ProgressTracker
from app.agent.tutor import build_tutor_agent
from app.council.api import router as council_router
from app.db import sessions, wakeups
from app.routers.kb import router as kb_router
from app.routers.panels import router as panels_router

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
    # P3 种子初始化：topics.json 无主题时写入 6 个种子（幂等；parent 留空等模型演化）
    try:
        from app.memory.topics_store import seed_topics

        n = seed_topics()
        if n:
            print(f"[topics] 已初始化 {n} 个种子主题", flush=True)
    except Exception as e:
        print(f"[topics] 种子初始化失败（跳过）: {e}", flush=True)
    scheduler.start()
    # 先贤会议 RAPTOR 树检索预热（2026-08-21 方案 D）：Ollama bge-m3 首次调用 ~秒级加载——
    # 后台线程预热（不阻塞启动），首场辩论检索即就绪。Ollama 不可用时预热失败静默（检索时再降级）。
    try:
        import threading

        def _warm_raptor():
            try:
                from app.memory import vector

                vector.embed(["预热"])
                print("[raptor] Ollama bge-m3 预热完成——首场辩论检索零等待", flush=True)
            except Exception as e:
                print(f"[raptor] 预热失败（首场辩论首次检索仍会慢）: {e}", flush=True)

        threading.Thread(target=_warm_raptor, daemon=True, name="raptor-warm").start()
    except Exception as e:
        print(f"[raptor] 预热线程启动失败（跳过）: {e}", flush=True)
    yield
    scheduler.stop()


app = FastAPI(title="personal-agent 学习搭子", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)

# 先贤会议（M3，2026-08-19）：/api/council/*（sages/debate/stop/distill/confirm）
from app.council.api import router as council_router

app.include_router(council_router)
app.include_router(panels_router)
app.include_router(kb_router)
# 星图观测台（2026-08-21）：可观测性统一入口——/obs 页面 + /api/observability/* 聚合
from app.routers.observability import router as obs_router

app.include_router(obs_router)

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

    if SHIGUANG_TOKEN and request.url.path.startswith("/api/") and not request.url.path.startswith("/api/observability/"):
        # 星图观测台豁免（2026-08-21）：本地观测数据（统计非操作），浏览器直开 /obs 可见
        auth = request.headers.get("authorization", "")
        if auth != f"Bearer {SHIGUANG_TOKEN}":
            return JSONResponse(status_code=401, content={"detail": "unauthorized"})
    return await call_next(request)


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


def _error_hint(msg: str) -> str:
    """异常收尾指令（2026-08-20，借鉴 DeepTutor"4 种故障各有指令"）：
    后端 error SSE 除了 message 还给用户可执行的下一步——错误不是终点，是引导。"""
    if "超限" in msg or "240s" in msg:
        return "会话超时：复杂问题可以拆成小问题逐个问；网络波动时稍等再试"
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
    return content[:limit] + f"\n…(已截断，完整 {len(content)} 字符，可让用户提供更具体的查询缩小范围)"


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
        elif pn == "ThinkingPart":            total += len(getattr(p, "content", "") or "")
        elif pn == "ToolCallPart":
            total += len(getattr(p, "tool_name", "") or "") + 40
        elif pn == "ToolReturnPart":
            total += len(str(getattr(p, "content", "") or "")) // 2
    return total


def _record_token_usage(sid: str, usage, model: str = ""):
    """记录每轮 token 用量（A2-5 2026-08-20：已下沉 obs.token_usage——保留签名做兼容垫片，
    主流程调用点已换 obs.token_usage；本垫片防外部引用断裂）。"""
    obs.token_usage(sid, usage, model=model)


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


# ---------- A1 后台沉淀钩子（2026-08-20）----------
# 设计：6 路纯沉淀钩子（profile/confusion/relation/continuation/teaching/topics）done 后异步跑——
# done 立即发出（体验：不等数十秒提炼）；提炼后台跑（成本：不阻塞响应）。
# glint 留在流内（SSE glint 事件需 done 前推前端挂金光点）。
# 全局串行锁：防并发写 memory 文件竞态（relation/continuation 同写 state.json）+ 防 DeepSeek 429 堆积。
_POST_HOOK_LOCK = asyncio.Semaphore(1)
_POST_HOOK_TASKS: set = set()  # 持有引用防 GC（可观测：模块级可查）


async def _run_post_hooks(sid: str, run_id: str, dialogue: str, need_profile: bool) -> None:
    """done 后异步执行的收尾沉淀（A1，2026-08-20）。
    与流内 glint 分工：glint 需 SSE 推送留流内；其余纯沉淀全后台。"""
    async with _POST_HOOK_LOCK:
        # profile（记忆变化门——consume 已提前到流内，这里只执行）
        if need_profile:
            try:
                from app.memory.store import update_profile

                rp = await update_profile()
                obs.hook(run_id, "profile", True, rp)
                print(f"[profile] 会话 {sid[:8]} 记忆变化 → {rp}", flush=True)
            except Exception as e3:
                try:
                    from app.memory.store import log_change

                    log_change("extractor_failed", "profile 画像刷新失败")
                except Exception:
                    pass
                obs.hook(run_id, "profile", False, str(e3))
                obs.error(run_id, "hook_profile", str(e3))
                print(f"[profile] 会话 {sid[:8]} 画像刷新失败: {e3}", flush=True)
        if not dialogue:
            return
        # 困惑（P0-2 方案B：每会话末必跑——"聊了困惑但没 remember"是最该提炼的场景）
        try:
            from app.agent.tutor import build_tutor_agent

            build_tutor_agent()  # 确保提炼回调已注册（主对话已调过，这里兜底）
            from app.memory.store import extract_session_confusion, remember

            confusion = await extract_session_confusion(dialogue)
            if confusion:
                r = await remember(confusion, source="agent", importance=7, category="困惑")
                obs.hook(run_id, "confusion", True, r)
                print(f"[confusion] 会话 {sid[:8]} 提炼困惑 → {r}", flush=True)
        except Exception as e4:
            try:
                from app.memory.store import log_change

                log_change("extractor_failed", "confusion 提炼失败")
            except Exception:
                pass
            obs.hook(run_id, "confusion", False, str(e4))
            obs.error(run_id, "hook_confusion", str(e4))
            print(f"[confusion] 会话 {sid[:8]} 困惑提炼失败: {e4}", flush=True)
        # 关系轨（阶段1）：提炼"我们之间"→ 写 state.json（慢变状态）
        try:
            from app.memory.store import extract_session_relation
            from app.memory.state import update_relation

            rel = await extract_session_relation(dialogue)
            if rel:
                rr = update_relation(
                    depth=rel.get("depth", ""),
                    last_topic=rel.get("last_topic", ""),
                    tone=rel.get("tone", ""),
                    evidence=dialogue[:120],
                )
                obs.hook(run_id, "relation", True, rr)
                print(f"[relation] 会话 {sid[:8]} 关系轨 → {rr}", flush=True)
        except Exception as e5:
            try:
                from app.memory.store import log_change

                log_change("extractor_failed", "relation 提炼失败")
            except Exception:
                pass
            obs.hook(run_id, "relation", False, str(e5))
            obs.error(run_id, "hook_relation", str(e5))
            print(f"[relation] 会话 {sid[:8]} 关系轨提炼失败: {e5}", flush=True)
        # 任务轨续接点（阶段2）：提炼"下次从哪继续"→ 写 state.json
        try:
            from app.memory.store import extract_session_continuation
            from app.memory.state import update_continuation

            cont = await extract_session_continuation(dialogue)
            if cont:
                cr = update_continuation(next_step=cont, evidence=dialogue[:120])
                obs.hook(run_id, "continuation", True, cr)
                print(f"[continuation] 会话 {sid[:8]} 续接点 → {cr}", flush=True)
        except Exception as e6:
            try:
                from app.memory.store import log_change

                log_change("extractor_failed", "continuation 提炼失败")
            except Exception:
                pass
            obs.hook(run_id, "continuation", False, str(e6))
            obs.error(run_id, "hook_continuation", str(e6))
            print(f"[continuation] 会话 {sid[:8]} 续接点提炼失败: {e6}", flush=True)
        # 教学经验（自主反思）：反思/技能不再"等用户喂"（机器触发，判断归模型）
        try:
            from app.memory.store import extract_session_teaching
            from app.agent.evolution import reflect_teaching, save_skill

            teaching = await extract_session_teaching(dialogue)
            if teaching:
                if teaching.get("reflection"):
                    rr_ = await reflect_teaching(f"会话复盘：{teaching['reflection']}")
                    obs.hook(run_id, "teaching", True, f"反思 {rr_}")
                    print(f"[teaching] 会话 {sid[:8]} 反思 → {rr_}", flush=True)
                if teaching.get("skill_method"):
                    sk_ = await save_skill(
                        description=teaching.get("skill_desc") or teaching.get("skill_method")[:60],
                        method=teaching["skill_method"],
                    )
                    obs.hook(run_id, "teaching", True, f"技能 {sk_}")
                    print(f"[teaching] 会话 {sid[:8]} 技能 → {sk_}", flush=True)
        except Exception as e7:
            try:
                from app.memory.store import log_change

                log_change("extractor_failed", "teaching 提炼失败")
            except Exception:
                pass
            obs.hook(run_id, "teaching", False, str(e7))
            obs.error(run_id, "hook_teaching", str(e7))
            print(f"[teaching] 会话 {sid[:8]} 教学经验提炼失败: {e7}", flush=True)
        # 主题提炼（意图驱动）：模型识别主题+归并，harness 只做意图分流 + 确定性验证
        try:
            from app.memory.store import extract_session_topics
            from app.memory.topics_store import find_topic, mark_farewell, register_candidate, touch_topic

            tps = await extract_session_topics(dialogue)
            if tps and tps.get("topics"):
                for tp in tps["topics"]:
                    # 2026-08-20 trace 抓出：模型输出可能含非 dict 元素 → harness 过滤
                    if not isinstance(tp, dict):
                        continue
                    name, intent, conf = tp["name"], tp["intent"], tp.get("confidence", "high")
                    if intent == "learning":
                        if find_topic(name):
                            touch_topic(name)
                            print(f"[topics] 会话 {sid[:8]} learning → {name}", flush=True)
                        else:
                            r = register_candidate(name)
                            print(f"[topics] 会话 {sid[:8]} learning未命中→候选 {name} count={r.get('count')} created={r.get('created')}", flush=True)
                    elif intent == "new":
                        r = register_candidate(name)
                        print(f"[topics] 会话 {sid[:8]} new → {name} count={r.get('count')} created={r.get('created')}", flush=True)
                    elif intent == "farewell":
                        if mark_farewell(name):
                            print(f"[topics] 会话 {sid[:8]} farewell → {name}", flush=True)
                    # mention → 完全不动（提到≠想学，防误激活，体验关键）
                obs.hook(run_id, "topics", True, f"{len(tps['topics'])} 个主题")
        except Exception as e8:
            import traceback

            traceback.print_exc()  # 错误详情落 stderr（配合 trace 定位）
            try:
                from app.memory.store import log_change

                log_change("extractor_failed", "topics 提炼失败")
            except Exception:
                pass
            obs.hook(run_id, "topics", False, str(e8))
            obs.error(run_id, "hook_topics", str(e8))
            print(f"[topics] 会话 {sid[:8]} 主题提炼失败: {e8}", flush=True)


@app.post("/api/chat")
async def chat(req: ChatRequest, request: Request) -> StreamingResponse:
    agent = build_tutor_agent()
    # #6 去重标志：前端手动重试带 X-Retry: 1（优先认标志，比内容匹配可靠；内容匹配仅作无标志回退）
    is_retry = request.headers.get("x-retry") == "1"
    sid = req.session_id if (req.session_id and sessions.session_exists(req.session_id)) else sessions.new_session()
    # 运行 trace（2026-08-20）：本轮 run 唯一 id + 起点事件（完整轨迹见 app/observability.py）
    run_id = obs.new_run_id()
    obs.run_start(run_id, sid, req.message)
    history = _load_history(sid)
    # B2 摘要兜底（2026-08-20）：链全丢（异常/清空）但摘要存在时——用摘要构建最小历史，
    # 保证压缩前的早期上下文不丢（摘要=早期信息的唯一载体）；有摘要=会话延续，不清 current
    if not history:
        summary = sessions.get_summary(sid)
        if summary and len(summary) >= 30:
            history = [
                ModelRequest(
                    parts=[
                        SystemPromptPart(
                            content=f"（以下是与你的更早对话摘要，继续本轮：）\n{summary}\n\n（摘要可能不完整，涉及早期细节拿不准时可以直接问用户）"
                        )
                    ]
                )
            ]
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
        # B1 消息级持久化（2026-08-20，行业标准：用户输入无条件先落库，不依赖流完成）：
        # 壳层 = 前置落用户消息 + try/finally 兜底（断流/异常/正常都执行 _finalize，同步函数不被打断）
        state = {"messages": [], "error_msg": [""], "t0": time.monotonic()}
        task_run_id = uuid.uuid4().hex[:10]
        tracker = ProgressTracker(task_run_id)
        try:
            sessions.save_user_message(sid, user_text)
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
                sessions.save_assistant_message(sid, user_text, messages_json, is_retry=is_retry)
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

    async def _chat_stream(state: dict, request: Request, tracker: ProgressTracker) -> AsyncIterator[str]:
        full_text = ""
        turn_started = False
        error_msg = ""
        messages = state["messages"]
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
                        # 轮次预算（2026-08-19，借鉴 DeepTutor 探索 8+settle 3=12 轮上界）：
                        # request_limit=模型请求轮次上限（每轮工具调用一次），防无限调工具空转；
                        # total_tokens_limit=整 run 累计 token 兜底（输入+输出+工具循环多轮累加）。
                        # ⚠️ 修正 2026-08-19：原 30000 拍低了——带工具循环的长对话累计即超
                        #（实测 30684 误伤"继续讲因果推断"正常对话，run 中断收尾钩子都没跑）。
                        # 按窗口比例：DeepSeek 128K × 70% ≈ 90000（留 30% 给模型输出余量）
                        usage_limits=UsageLimits(request_limit=8, total_tokens_limit=90000),
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
                                    if not turn_started:
                                        yield _sse({"type": "turn_start"})
                                        turn_started = True
                                    args = str(getattr(part, "args", "") or "")[:80]
                                    obs.tool_start(run_id, tool_name, args, getattr(part, "tool_call_id", None))
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
                                    # 工具结果压缩（2026-08-20）：统一硬上限——改 part.content 影响
                                    # all_messages 里保存的内容（下一轮上下文），前端展示走 tool_result_status 不受影响
                                    pc = getattr(part, "content", None)
                                    if isinstance(pc, str):
                                        setattr(part, "content", _compress_tool_content(pc))
                                    # 可观测性（2026-08-18 事故补）：done 必须带结果与失败标记——
                                    # 工具返回失败时模型可能吞掉（谎报成功），harness 不变量：结果对用户可见
                                    status, result = tool_result_status(part)
                                    obs.tool_end(run_id, tool_name, status, getattr(part, "tool_call_id", None), result)
                                    yield _sse({
                                        "type": "tool",
                                        "name": tool_name,
                                        "status": status,
                                        "id": getattr(part, "tool_call_id", None),
                                        "result": result,
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
                    # token 用量记录（A2-5 2026-08-20：逻辑下沉 obs.token_usage，主流程/子任务同一台账）
                    try:
                        obs.token_usage(sid, stream.usage(), model=m)
                    except Exception:
                        pass
                    messages = msgs
                    state["messages"] = msgs  # B1 引用同步（_finalize 读 state——548 行重新赋值会断引用）
                    obs.llm_end(run_id, tag, True)  # LLM 调用成功（2026-08-21 补：配对算耗时）
                    if full_text:
                        obs.llm_output(run_id, tag, full_text)  # 回复全文进 trace（重放可见，2026-08-21 补）
                    circuit_record(True)
                    break
                # 空 content（166 轮 0 字场景的正主）：无文本且无工具调用 → 确定性判定（有没有字/有没有调工具）
                if i < len(attempts) - 1:
                    obs.error(run_id, "empty", f"{tag} 空content(0字无工具) → fallback")
                    print(f"[fallback] 会话 {sid[:8]} {tag} 空content(0字无工具) → fallback", flush=True)
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
                messages = []
                break
            except Exception as e:
                obs.llm_end(run_id, tag, False)  # LLM 调用异常（2026-08-21 补）
                if i < len(attempts) - 1 and should_fallback(e):
                    obs.error(run_id, "llm_fallback", f"{tag} 异常→fallback: {str(e)[:120]}")
                    print(f"[fallback] 会话 {sid[:8]} {tag} 异常→fallback: {str(e)[:120]}", flush=True)
                    circuit_record(False)
                    continue
                # #4 异常路径：API 失败/超时/断流 → 用户消息必须落库（否则消息丢失）+ 前端收到 error 事件
                error_msg = str(e)[:200]
                obs.error(run_id, "llm", error_msg)
                print(f"[chat-error] 会话 {sid[:8]} {tag} 异常: {error_msg}", flush=True)
                circuit_record(False)
                messages = []
                break
        if error_msg:
            state["error_msg"][0] = error_msg
            yield _sse({"type": "error", "message": error_msg, "hint": _error_hint(error_msg)})  # 前端显示错误+下一步建议而非干等
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

        need_profile = consume_memory_changed()
        dialogue = _history_to_text(messages[-8:]) if messages else ""
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
            except Exception as e4b:
                obs.hook(run_id, "glint", False, str(e4b))
                print(f"[glint] 会话 {sid[:8]} 闪光提炼失败: {e4b}", flush=True)
        if turn_started:
            yield _sse({"type": "turn_end"})
        # A1：沉淀钩子后台化（done 立即发出；任务持有引用防 GC，串行锁防并发写）
        task = asyncio.create_task(_run_post_hooks(sid, run_id, dialogue, need_profile))
        _POST_HOOK_TASKS.add(task)
        task.add_done_callback(_POST_HOOK_TASKS.discard)

        yield _sse({"type": "done", "session_id": sid})

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.get("/obs", include_in_schema=False)
def obs_page():
    """星图观测台（可观测性统一入口，独立于前端构建）"""
    p = Path(__file__).resolve().parent / "obs.html"
    return FileResponse(p)


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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
