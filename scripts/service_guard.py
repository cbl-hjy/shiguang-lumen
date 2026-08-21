# -*- coding: utf-8 -*-
"""#21 服务自愈看门狗（Windows，无第三方依赖）：
- 拉起 uvicorn 子进程（0.0.0.0 监听，手机局域网可用）
- 崩溃 3s 后自动重启，记录 data/service_guard.log（时间/次数）
- Ctrl+C 优雅退出（不重启）
- 安全护栏（用户补，关键）：0.0.0.0 监听必须 SHIGUANG_TOKEN 已配置——门锁没装不能开门。
  否则 .env 丢失/重装忘配 token 时，看门狗一拉起就是裸奔（RCE 面又开）。

注册开机自启（一次）：
  schtasks /Create /TN "ShiguangGuard" /TR "D:\\work_buddy\\personal-agent\\.venv\\Scripts\\python.exe D:\\work_buddy\\personal-agent\\scripts\\service_guard.py" /SC ONLOGON /F
验证：schtasks /Query /TN ShiguangGuard
注意：/TR 必须绝对路径（计划任务工作目录默认 system32，相对路径必炸——Windows 计划任务第一坑）。
"""
import os
import signal
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
LOG = ROOT / "data" / "service_guard.log"
LOCK_FILE = ROOT / "data" / "service_guard.pid"
HOST = "0.0.0.0"
PORT = 8000
RESTART_DELAY = 3
# Ollama 服务（方案 D，2026-08-21）：bge-m3 embedding 单一 GPU 实例——看门狗一并管理，
# 挂了自动拉起（embed 走 Ollama，挂了记忆检索降级"暂不可用"，拉起后自动恢复）
OLLAMA_PORT = 11434
_stop = False


def _find_ollama_exe() -> Path | None:
    """探测 Ollama 可执行文件（可移植，2026-08-21 发布版：不再硬编码 D 盘路径）：
    ① 环境变量 OLLAMA_EXE → ② PATH 中的 ollama → ③ 常见安装位置兜底"""
    import shutil

    env = os.environ.get("OLLAMA_EXE", "")
    if env and Path(env).exists():
        return Path(env)
    p = shutil.which("ollama")
    if p:
        return Path(p)
    candidates = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe",
        Path("C:/Program Files/Ollama/ollama.exe"),
        Path("D:/Ollama/ollama.exe"),
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def acquire_singleton() -> bool:
    """单例锁（2026-08-20 根治多代看门狗残留——反复出现的崩溃循环根因）：
    多个看门狗并存时会交替拉起 uvicorn 抢 8000 端口 → code=3 崩溃循环。
    已有存活看门狗则本实例退出；锁异常 fail-open（不因锁问题阻塞服务启动）。"""
    try:
        if LOCK_FILE.exists():
            old_pid = int((LOCK_FILE.read_text(encoding="utf-8").strip() or "0"))
            if old_pid > 0:
                r = subprocess.run(
                    ["tasklist", "/FI", f"PID eq {old_pid}"],
                    capture_output=True, text=True, timeout=10,
                )
                if f"{old_pid}" in r.stdout and "python" in r.stdout.lower():
                    print(f"已有看门狗 PID={old_pid} 存活——本实例退出（单例锁）", flush=True)
                    return False
        LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
        LOCK_FILE.write_text(str(os.getpid()), encoding="utf-8")
        return True
    except Exception:
        return True


def release_lock() -> None:
    try:
        LOCK_FILE.unlink(missing_ok=True)
    except Exception:
        pass


def log(msg: str):
    line = f"{datetime.now().isoformat(timespec='seconds')}  {msg}"
    print(line, flush=True)
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def load_token() -> str:
    env_path = ROOT / ".env"
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("SHIGUANG_TOKEN="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return ""


def port_in_use(port: int = PORT) -> bool:
    try:
        s = socket.create_connection(("127.0.0.1", port), timeout=1)
        s.close()
        return True
    except OSError:
        return False


def ollama_running() -> bool:
    return port_in_use(OLLAMA_PORT)


def start_ollama() -> None:
    """拉起 Ollama serve（分离子进程）。已有则跳过；找不到 Ollama → embed 走降级。"""
    if ollama_running():
        return
    ollama_exe = _find_ollama_exe()
    if ollama_exe is None:
        log("Ollama 未安装/未找到（设 OLLAMA_EXE 或装 Ollama）——embed 将走降级（检索暂不可用）")
        return
    env = dict(os.environ)
    # 模型目录：优先环境变量 OLLAMA_MODELS，未设置用 Ollama 默认（用户目录 .ollama）
    if not env.get("OLLAMA_MODELS"):
        env.pop("OLLAMA_MODELS", None)
    env["OLLAMA_MAX_LOADED_MODELS"] = "1"
    try:
        proc = subprocess.Popen(
            [str(ollama_exe), "serve"],
            cwd=str(ROOT),
            creationflags=subprocess.CREATE_NO_WINDOW,
            env=env,
        )
        log(f"Ollama 已拉起 PID={proc.pid}")
    except Exception as e:
        log(f"Ollama 拉起失败: {e}（embed 走降级）")


def ensure_ollama() -> None:
    """确保 Ollama 在跑（启动时 + uvicorn 循环内附带检测，挂了拉起）"""
    if ollama_running():
        return
    start_ollama()
    for _ in range(30):
        if ollama_running():
            return
        time.sleep(1)
    log("Ollama 30s 未就绪——uvicorn 照常拉起（embed 走降级，Ollama 恢复后自动切回）")


def on_stop(*_):
    global _stop
    _stop = True


def main():
    # 单例锁：已有存活看门狗则退出（根治多代残留——2026-08-20 用户批评反复出现）
    if not acquire_singleton():
        sys.exit(0)
    # 安全护栏：开门（0.0.0.0）必须门锁（token）在——start.bat 与看门狗各一道
    if not load_token():
        print(f"⚠️ 拒绝启动：host={HOST} 但 SHIGUANG_TOKEN 未配置（.env 缺失或为空）。", flush=True)
        print("  门锁没装不能开门——配置 SHIGUANG_TOKEN 后再启动，或改回 --host 127.0.0.1。", flush=True)
        release_lock()
        sys.exit(1)

    if port_in_use(PORT):
        log(f"检测到 {PORT} 端口已有服务（可能是手动启动）——本守护不接管，退出")
        sys.exit(0)

    signal.signal(signal.SIGINT, on_stop)
    signal.signal(signal.SIGTERM, on_stop)

    # 方案 D：启动时确保 Ollama 在跑（bge-m3 embedding 服务），挂了自动拉起
    ensure_ollama()

    restarts = 0
    log(f"看门狗启动（host={HOST} port={PORT} + Ollama {OLLAMA_PORT}）")
    while not _stop:
        # 附带检测：Ollama 挂了自动拉起（uvicorn 循环内，零额外线程）
        ensure_ollama()
        proc = subprocess.Popen(
            [str(PYTHON), "-m", "uvicorn", "app.main:app", "--host", HOST, "--port", str(PORT), "--log-level", "warning"],
            cwd=str(ROOT),
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        log(f"服务已拉起 PID={proc.pid}（累计重启 {restarts} 次）")
        while proc.poll() is None and not _stop:
            time.sleep(2)
        if _stop:
            proc.terminate()
            log("收到停止信号，优雅退出（不重启）")
            break
        restarts += 1
        log(f"服务异常退出 code={proc.returncode}——{RESTART_DELAY}s 后自动重启")
        time.sleep(RESTART_DELAY)
    release_lock()


if __name__ == "__main__":
    main()
