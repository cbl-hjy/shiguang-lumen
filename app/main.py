"""M1 FastAPI 入口：POST /api/chat（SSE 流式）—— 学习搭子对话循环
SSE 协议（自定义 JSON 事件，M4 前端直接消费）：
  data: {"type":"delta","text":"..."}   文本增量
  data: {"type":"thinking","text":"..."} 思考增量（前端可选展示）
  data: {"type":"done","session_id":"..."}
"""

import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import scheduler
from app.council.api import router as council_router
from app.config import DATA_DIR
from app.db import sessions, wakeups
from app.routers.kb import router as kb_router
from app.routers.panels import router as panels_router

# 上传目录（2026-08-25 打包适配）：原 PROJECT_ROOT/data/uploads——打包后 PROJECT_ROOT=_internal
# 只读目录，必须走 DATA_DIR（启动器设用户数据目录；非打包 DATA_DIR=项目根，行为不变）
UPLOAD_DIR = DATA_DIR / "data" / "uploads"

# ---------- 长程 compaction（Pi 机制轻量版：摘要 + 尾部保留）----------
# 触发阈值 90K 字符：50 轮探测=66.5K，约 75 轮触发一次；压缩后腾出空间再撑 30-40 轮 → 覆盖 2 小时
COMPACT_THRESHOLD_CHARS = 90_000
COMPACT_TAIL_CHARS = 20_000  # 压缩后保留最近 ~20K 字符（≈15 轮细节，Pi keepRecentTokens 精神）


@asynccontextmanager
async def lifespan(_: FastAPI):
    """启动：会话库 + 唤醒库建表 + 记忆/知识库恢复（服务端创建=可写）+ 调度器常驻；关闭：停调度器"""
    from app.config import SHIGUANG_TOKEN

    if not SHIGUANG_TOKEN:
        print(
            "[auth] ⚠️ 未配置 SHIGUANG_TOKEN——/api/* 鉴权关闭（仅适合 127.0.0.1 本地；局域网/公网必须配置）",
            flush=True,
        )
    # #5 存储：启动时 VACUUM 收缩文件（清空旧链后空间释放；启动无并发，锁库安全；失败跳过）
    try:
        sessions.vacuum()
    except Exception as e:
        print(f"[db] VACUUM 失败（跳过）: {e}", flush=True)
    sessions.init_db()
    wakeups.init_db()
    # 多用户账号表（2026-08-28 P0）
    from app.db.users import init_db as users_init_db

    users_init_db()
    # 首用户引导码（P3 公网加固）：users 空时生成一次性引导码 → data/bootstrap_invite.txt，
    # 管理员用它注册首个账号（防公网陌生人抢占管理员）；已有用户则不再生成
    try:
        from app.db.users import user_count

        if user_count() == 0:
            import secrets as _secrets

            code = "SG-" + _secrets.token_hex(6).upper()
            _bootstrap_f = DATA_DIR / "data" / "bootstrap_invite.txt"
            _bootstrap_f.parent.mkdir(parents=True, exist_ok=True)
            _bootstrap_f.write_text(code, encoding="utf-8")
            print(f"[auth] 首用户引导码（注册首个账号用，仅显示这一次）: {code}", flush=True)
            print(f"[auth] 引导码已保存: {_bootstrap_f}", flush=True)
    except Exception as e:
        print(f"[auth] 引导码生成失败（不影响启动）: {e}", flush=True)
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
    # Phase1 M-3（2026-08-28）：启动时冷记忆降级扫描——从未命中+超龄条目退出向量索引
    # （文件保留可找回）。个人应用条目量小，毫秒级；失败不阻塞启动。
    try:
        from app.memory.lifecycle import demote_cold_memories

        demote_cold_memories()
    except Exception as e:
        print(f"[lifecycle] 启动降级扫描失败（跳过）: {e}", flush=True)
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


# OpenTelemetry 全局配置（2026-08-27 P1-6）：pydantic-ai OTel-native，设 provider 即自动出 spans
from app.telemetry import init_telemetry

init_telemetry()

# OpenTelemetry 全局配置（2026-08-27 P1-6）：pydantic-ai OTel-native，设 provider 即自动出 spans
from app.telemetry import init_telemetry

init_telemetry()

app = FastAPI(title="personal-agent 学习搭子", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# 先贤会议（M3，2026-08-19）：/api/council/*（sages/debate/stop/distill/confirm）

app.include_router(council_router)
from app.routers.memory import router as memory_router

app.include_router(memory_router)
app.include_router(panels_router)
app.include_router(kb_router)
# 星图观测台（2026-08-21）：可观测性统一入口——/obs 页面 + /api/observability/* 聚合
from app.routers.observability import router as obs_router

app.include_router(obs_router)
from app.routers.chat import router as chat_router
from app.routers.learning import router as learning_router
app.include_router(learning_router)
app.include_router(chat_router)
# 多用户账号体系（2026-08-28 P0）：/api/auth/register|login|me
from app.routers.auth import router as auth_router

app.include_router(auth_router)
# 「它记得我」聚合档案（2026-08-28 前端重构：一次给全，抽屉内切换零等待）
from app.routers.me import router as me_router

app.include_router(me_router)

# 前端产物单一目录（#B 拆双目录 2026-08-13）：后端直接读 frontend/dist——构建产物只此一份，
# 消除"app/static 与 dist 两版漂移"根因（旧版 static/index.html 是 8/11 残留，已 git rm）。
# 部署/更新流程：cd frontend && npm run build → dist 即服务目录（dist 不进 git，构建是部署步骤）
# 打包感知（2026-08-25）：frozen 时前端随 PyInstaller datas 打进 _MEIPASS/frontend/dist
if getattr(sys, "frozen", False):
    STATIC_DIR = Path(sys._MEIPASS) / "frontend" / "dist"
else:
    STATIC_DIR = Path(__file__).resolve().parent.parent / "frontend" / "dist"
app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")
# 2026-08-29 图标/启动画面静态服务（此前只挂 /assets → icons/*.png、splash-mascot.png 全 404，
# 桌面版 favicon 都加载不出来）：把 dist 下这两个公开目录挂出来（只读，无鉴权需求）
app.mount("/icons", StaticFiles(directory=STATIC_DIR / "icons"), name="icons")
# 沙箱产出静态服务（2026-08-26）：/charts=SVG 图表（对话 markdown 图片直接显示，复用"点击放大"）、
# /outputs=分析结果下载（save_result 落盘）。只读，路径固定 D 盘缓存目录。
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SANDBOX_CHARTS = _PROJECT_ROOT / ".cache" / "sandbox_charts"
_SANDBOX_OUTPUTS = _PROJECT_ROOT / ".cache" / "sandbox_outputs"
_SANDBOX_CHARTS.mkdir(parents=True, exist_ok=True)
_SANDBOX_OUTPUTS.mkdir(parents=True, exist_ok=True)
app.mount("/charts", StaticFiles(directory=str(_SANDBOX_CHARTS)), name="sandbox_charts")
app.mount("/outputs", StaticFiles(directory=str(_SANDBOX_OUTPUTS)), name="sandbox_outputs")


@app.get("/favicon.svg", include_in_schema=False)
def favicon():
    return FileResponse(STATIC_DIR / "favicon.svg")


@app.get("/favicon.ico", include_in_schema=False)
def favicon_ico():
    """浏览器自动请求的 favicon.ico（index 声明 svg，但部分浏览器仍探测 ico）——返回精灵图标，消 404。"""
    return FileResponse(STATIC_DIR / "icons" / "favicon.ico")


@app.get("/splash-mascot.png", include_in_schema=False)
def splash_mascot():
    """启动画面精灵（dist 根文件——根目录未整体挂载，单独服务；与 favicon 同理）"""
    return FileResponse(STATIC_DIR / "splash-mascot.png")


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """多用户门锁（2026-08-28 P0 改造）：/api/* 校验 Authorization: Bearer <JWT> → user_id。
    - 豁免：OPTIONS（CORS 预检）、/api/auth/*（注册登录）、/api/observability（观测统计）、
      /api/setup（首次配置）、/api/update（版本信息）
    - JWT 校验成功 → request.state.user_id（数据层据此隔离）；失败 → 401（统一文案）
    - 静态资源（非 /api/）放行"""
    path = request.url.path
    if path.startswith("/api/") and request.method != "OPTIONS":
        exempt = (
            # 2026-08-28 修复：只豁免「未登录也必须能调」的两个端点（登录/注册）。
            # 此前 startswith("/api/auth/") 把 /api/auth/me 一并豁免 → 中间件不解析 token、
            # 不注入 user_id → me 端点永远 401 → 前端校验登录态失败（跳登录页/功能异常）。
            # 2026-09-02 TC-S01 移除 /api/observability 豁免：观测数据（trace 含对话内容）
            # 无 token 可读=隐私漏洞；前端 installAuthFetch 全局自动带头，观测视图登录后
            # 本就带 token——豁免是 08-21 /obs 独立页时代的过时设计（TC-S01 实证 7 端点 200）。
            path == "/api/auth/login"
            or path == "/api/auth/register"
            or path.startswith("/api/setup")
            or path.startswith("/api/update")
        )
        if not exempt:
            from app import auth_core

            auth = request.headers.get("authorization", "")
            uid = None
            if auth.startswith("Bearer "):
                uid = auth_core.verify_access_token(auth[7:])
            if not uid:
                return JSONResponse(status_code=401, content={"detail": "unauthorized"})
            request.state.user_id = uid
            # 2026-08-28 修复（学习路径读取失败根因）：sync 端点跑在线程池读不到中间件 contextvar，
            # 但 anyio run_in_threadpool 传播调用方 context → 中间件 set 一次，sync 端点线程即可读到
            auth_core.set_current_user_id(uid)
    resp = await call_next(request)
    return resp


@app.get("/healthz", include_in_schema=False)
def healthz():
    """生产级健康检查（2026-08-25 工程化补齐，对齐 K8s liveness/readiness + Docker HEALTHCHECK 思想）。

    探活三组件：
    - chromadb（本地向量索引）= 应用核心——挂 → HTTP 503（看门狗据此重启，治"进程活着应用坏了"）
    - ollama（embedding 服务）= 可降级依赖——挂 → status=degraded 但仍 200（看门狗 ensure_ollama 单独管拉起，不重启应用）
    - deepseek（外部 LLM API）= 可降级依赖——挂 → status=degraded 但仍 200（fallback 链+熔断兜底）
    语义：503 只代表"应用本体不可用"，不把可降级依赖升级为致命。"""
    checks: dict[str, str] = {}
    core_ok = True
    # 1. chromadb（核心）
    try:
        from app.memory import vector

        checks["chromadb"] = f"ok({vector.count()}条)"
    except Exception as e:
        checks["chromadb"] = f"fail: {str(e)[:80]}"
        core_ok = False
    # 2. Ollama（可降级，探 /api/version 轻量 ping，不做 embed）
    try:
        import urllib.request

        with urllib.request.urlopen("http://127.0.0.1:11434/api/version", timeout=3) as r:
            v = json.loads(r.read()).get("version", "?")
        checks["ollama"] = f"ok({v})"
    except Exception as e:
        checks["ollama"] = f"fail: {str(e)[:80]}"
    # 3. DeepSeek API（可降级，/models 轻量探活）
    try:
        from app.config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL
        from openai import OpenAI

        OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL).models.list()
        checks["deepseek"] = "ok"
    except Exception as e:
        checks["deepseek"] = f"fail: {str(e)[:80]}"
    status = (
        "ok"
        if (core_ok and all(v.startswith("ok") for v in checks.values()))
        else ("unhealthy" if not core_ok else "degraded")
    )
    return JSONResponse(
        status_code=200 if core_ok else 503, content={"status": status, "checks": checks}
    )


# ===== 首次运行引导（阶段③，2026-08-25）：无 DeepSeek key 时前端显示配置页 =====
# 设计：GET status 供前端检测；POST 校验 key → 写 SHIGUANG_ENV_FILE（.env）→ 1s 后进程退出
# （响应先送达）→ launcher while 循环 3s 自动重启 → 新进程读到新 key。端点走鉴权中间件
# （引导期 token 空=本地免鉴权特性；已配 token 时前端 fetch 自动带）。


def _read_env_key(key_name: str) -> str:
    """读 SHIGUANG_ENV_FILE（config.ENV_FILE）中指定键的值，失败返回空串"""
    try:
        from app.config import ENV_FILE

        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith(f"{key_name}="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception as e:
        print(f"[env] 读取 {key_name} 失败: {e}", flush=True)
    return ""


def _write_env_key(key_name: str, value: str) -> bool:
    """写入/替换 .env 中指定键（存在则替换，否则追加）。成功返回 True"""
    try:
        from app.config import ENV_FILE

        ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
        lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
        prefix = f"{key_name}="
        out = []
        hit = False
        for ln in lines:
            if ln.strip().startswith(prefix):
                out.append(f"{prefix}{value}")
                hit = True
            else:
                out.append(ln)
        if not hit:
            out.append(f"{prefix}{value}")
        ENV_FILE.write_text("\n".join(out) + "\n", encoding="utf-8")
        return True
    except Exception:
        return False


@app.get("/api/setup/status", include_in_schema=False)
def setup_status():
    """引导状态：needs_setup（无 key）+ 依赖健康（ollama/model）供引导页展示"""
    from app.config import DEEPSEEK_API_KEY, DATA_DIR

    needs = not DEEPSEEK_API_KEY.strip()
    ollama_ok = False
    model_ok = False
    ollama_error = ""
    try:
        import urllib.request

        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=3) as r:
            tags = json.loads(r.read()).get("models", [])
        ollama_ok = True
        model_ok = any(m.get("name", "").startswith("bge-m3") for m in tags)
    except Exception as e:
        ollama_error = str(e)[:120]
    # 2026-08-26 P1：launcher 配置失败原因（安装版无控制台，用户不可见）→ 引导页展示
    st = DATA_DIR / "ollama_status.json"
    if st.exists():
        try:
            st_data = json.loads(st.read_text(encoding="utf-8"))
            if not st_data.get("ok") and st_data.get("error"):
                ollama_error = st_data["error"]
        except Exception as e:
            print(f"[setup] ollama_status.json 解析失败（降级为在线探测结果）: {e}", flush=True)
    return JSONResponse(
        content={
            "needs_setup": needs,
            "deepseek_configured": not needs,
            "ollama_ok": ollama_ok,
            "model_ok": model_ok,
            "ollama_error": ollama_error,
        }
    )


@app.get("/api/update/status", include_in_schema=False)
def update_status():
    """更新检查结果（2026-08-26 P1：轻量更新源 update.json，Inno 版无 velopack 更新）：
    launcher 启动时后台检查写入 update_status.json；前端据此显示"发现新版"横幅。"""
    from app.config import DATA_DIR

    f = DATA_DIR / "update_status.json"
    if f.exists():
        try:
            return JSONResponse(json.loads(f.read_text(encoding="utf-8")))
        except Exception as e:
            print(f"[update] update_status.json 解析失败: {e}", flush=True)
    return JSONResponse({"update_available": False})


class SetupRequest(BaseModel):
    api_key: str


@app.post("/api/setup", include_in_schema=False)
def setup_save(req: SetupRequest):
    """保存 DeepSeek key：校验（models.list 轻量调用）→ 写 .env → 1s 后退出触发 launcher 重启。
    校验失败 400 不写盘；写盘失败 500。"""
    from app.config import DEEPSEEK_BASE_URL

    key = (req.api_key or "").strip()
    if not key:
        return JSONResponse(status_code=400, content={"ok": False, "error": "key 不能为空"})
    # 校验：OpenAI 兼容 /models 轻量调用（超时 10s）
    try:
        from openai import OpenAI

        OpenAI(api_key=key, base_url=DEEPSEEK_BASE_URL, timeout=10).models.list()
    except Exception as e:
        return JSONResponse(
            status_code=400, content={"ok": False, "error": f"key 校验失败: {str(e)[:120]}"}
        )
    if not _write_env_key("DEEPSEEK_API_KEY", key):
        return JSONResponse(status_code=500, content={"ok": False, "error": "写入配置失败"})
    # 响应先送达，1s 后退出（launcher 捕获后 3s 自动重启读新 key）
    import os as _os
    import threading as _threading

    # 2026-08-26 随机 token 加固：把当前鉴权 token 交给前端（引导期唯一拿 token 的时机，
    # 重启后前端 localStorage 自动带 Bearer——Open WebUI 首次密钥模式）
    from app.config import SHIGUANG_TOKEN as _TOKEN

    _threading.Timer(1.0, _os._exit, args=(42,)).start()
    return JSONResponse(content={"ok": True, "restarting": True, "token": _TOKEN})


@app.get("/", include_in_schema=False)
def index():
    """前端首页。产物新鲜度哨兵（防"以为是新的其实是旧的"复发）：build.json 时间戳放响应头 + 启动日志。
    build 产物由 npm run build 写 dist/build.json（见 frontend/package.json），start.bat 启动前必 build。
    2026-08-26：Cache-Control no-cache——index.html 必须每次重新校验（用户预览缓存旧 index.html 加载旧 JS
    ="背景还是旧的"反复出现的根因；assets 有 hash 可长缓存，index 必须 no-cache）"""
    resp = FileResponse(STATIC_DIR / "index.html")
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    try:
        bi = json.loads((STATIC_DIR / "build.json").read_text(encoding="utf-8"))
        resp.headers["X-Built-At"] = bi.get("built_at", "")
    except Exception as e:
        print(f"[index] build.json 缺失或解析失败（开发模式正常现象）: {e}", flush=True)
    return resp


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
