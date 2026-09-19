# -*- coding: utf-8 -*-
"""#21 服务自愈看门狗（Windows，无第三方依赖）：
- 拉起 uvicorn 子进程（0.0.0.0 监听，手机局域网可用）
- 崩溃 3s 后自动重启，记录 data/service_guard.log（时间/次数）
- Ctrl+C 优雅退出（不重启）
- 安全护栏（用户补，关键）：0.0.0.0 监听必须 SHIGUANG_TOKEN 已配置——门锁没装不能开门。
  否则 .env 丢失/重装忘配 token 时，看门狗一拉起就是裸奔（RCE 面又开）。

注册开机自启（一次）：
  schtasks /Create /TN "ShiguangGuard" /TR "<project-root>\\.venv\\Scripts\\python.exe <project-root>\\scripts\\service_guard.py" /SC ONLOGON /F
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
# 2026-08-26 安全加固：开发服务也绑定 127.0.0.1——0.0.0.0 使局域网可达，
# 配合 /api/observability 豁免 + /api/setup 无鉴权 = 真实暴露面（威胁模型审计发现）
# 2026-08-27 改回 0.0.0.0：移动端需求（手机局域网访问拾光），门锁已就位——
# 下方 192 行护栏：HOST=0.0.0.0 但 SHIGUANG_TOKEN 缺失 → 拒绝启动（安全不降级）；
# start.bat 提示文本本就宣称"0.0.0.0 局域网可访问"，此前提示与实际不一致，本次对齐
HOST = "0.0.0.0"
PORT = 8000
RESTART_DELAY = 3
# Ollama 服务（方案 D，2026-08-21）：bge-m3 embedding 单一 GPU 实例——看门狗一并管理，
# 挂了自动拉起（embed 走 Ollama，挂了记忆检索降级"暂不可用"，拉起后自动恢复）
OLLAMA_EXE = None  # 由 _find_ollama_exe() 运行时探测（可移植，2026-09-19 发布版）
OLLAMA_PORT = 11434
OLLAMA_MODELS = "<ollama-models-dir>"
# 应用级健康检查（2026-08-25 工程化补齐，对齐 K8s liveness：进程活着但应用坏了 → 重启）：
# 每 HEALTH_INTERVAL 秒探 /healthz，连续 HEALTH_FAIL_THRESHOLD 次非 200 → 杀掉 uvicorn 走自动重启
HEALTH_URL = "http://127.0.0.1:8000/healthz"
HEALTH_INTERVAL = 15
HEALTH_FAIL_THRESHOLD = 3
# 每日备份（2026-08-25 工程化补齐，scripts/backup.py）：跨天后检查一次，未备份则分离进程跑
BACKUP_SCRIPT = ROOT / "scripts" / "backup.py"
BACKUP_DATE_DIR = ROOT / "backups"
_stop = False


# 单例锁专用端口（2026-08-28 P0-4 根治看门狗繁殖）：
# 原 pidfile+tasklist 检查存在 TOCTOU 竞态——两个实例同时读锁文件都会认为"无锁"，
# 同时拉起 uvicorn 抢 8000 端口 → code=3 崩溃循环（历史复发 3 次）。
# 改用 TCP bind 独占端口：OS 层原子，双开必有一个 bind 失败，竞态从根上消除。
SINGLETON_PORT = 8901
_singleton_sock = None


def acquire_singleton() -> bool:
    """单例锁：bind 独占端口（OS 原子，无竞态）。
    已有看门狗持有锁则本实例退出；锁异常 fail-open（不因锁问题阻塞服务启动）。"""
    global _singleton_sock
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", SINGLETON_PORT))
        s.listen(1)
        _singleton_sock = s  # 持有到进程退出（OS 自动回收）
        LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
        LOCK_FILE.write_text(str(os.getpid()), encoding="utf-8")
        return True
    except OSError:
        print(
            f"已有看门狗持有单例锁（127.0.0.1:{SINGLETON_PORT}）——本实例退出（单例锁）",
            flush=True,
        )
        return False
    except Exception:
        # 锁异常 fail-open：不因锁问题阻塞服务启动
        return True


def release_lock() -> None:
    try:
        LOCK_FILE.unlink(missing_ok=True)
    except Exception as e:
        print(f"[guard] 锁文件清理失败: {e}", flush=True)
    try:
        if _singleton_sock is not None:
            _singleton_sock.close()
    except Exception as e:
        print(f"[guard] 单例 socket 关闭失败: {e}", flush=True)


def log(msg: str):
    line = f"{datetime.now().isoformat(timespec='seconds')}  {msg}"
    print(line, flush=True)
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception as e:
        print(f"[guard] 日志写入失败: {e}", flush=True)  # 守卫丢日志=失效起点，必须可见


def load_token() -> str:
    env_path = ROOT / ".env"
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("SHIGUANG_TOKEN="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception as e:
        print(f"[guard] 读 .env 失败: {e}", flush=True)
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
    """拉起 Ollama serve（分离子进程，OLLAMA_MODELS 指 D 盘）。已有则跳过。"""
    if ollama_running():
        return
    if not OLLAMA_EXE.exists():
        log(f"Ollama 未安装（{OLLAMA_EXE} 不存在）——embed 将走降级（检索暂不可用）")
        return
    env = dict(os.environ)
    env["OLLAMA_MODELS"] = OLLAMA_MODELS
    env["OLLAMA_MAX_LOADED_MODELS"] = "1"
    # 服务级 keep_alive（2026-08-25）：模型驻留 30m，消 4.15s 冷启动（vector.py/kb.py 请求级双保险）
    env["OLLAMA_KEEP_ALIVE"] = "30m"
    try:
        proc = subprocess.Popen(
            [str(OLLAMA_EXE), "serve"],
            cwd=str(ROOT),
            creationflags=subprocess.CREATE_NO_WINDOW,
            env=env,
        )
        log(f"Ollama 已拉起 PID={proc.pid}（models={OLLAMA_MODELS}）")
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


def health_check() -> bool:
    """探 /healthz：200 = 应用本体健康（chromadb 可查）；非 200/异常 = 应用坏了（进程可能还活着）"""
    try:
        with socket.create_connection(("127.0.0.1", PORT), timeout=3):
            pass
        import urllib.request

        with urllib.request.urlopen(HEALTH_URL, timeout=5) as r:
            return r.status == 200
    except Exception:
        return False


def daily_backup_if_due() -> None:
    """每日一次备份：跨天且今日未备份 → 分离进程跑 scripts/backup.py（不阻塞看门狗主循环）。
    失败不阻断服务（备份失败只记日志，明日重试）"""
    today = time.strftime("%Y%m%d")
    if (BACKUP_DATE_DIR / today).exists():
        return
    if not BACKUP_SCRIPT.exists():
        return
    try:
        with open(ROOT / "data" / "backup.log", "a", encoding="utf-8") as logf:
            subprocess.Popen(
                [str(PYTHON), str(BACKUP_SCRIPT)],
                cwd=str(ROOT),
                creationflags=subprocess.CREATE_NO_WINDOW,
                stdout=logf,  # 子进程继承句柄；with 退出只关父进程副本
                stderr=subprocess.STDOUT,
            )
        log(f"每日备份已触发（{today}）")
    except Exception as e:
        log(f"备份触发失败: {e}")


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
    last_backup_day = ""
    log(f"看门狗启动（host={HOST} port={PORT} + Ollama {OLLAMA_PORT}）")
    while not _stop:
        # 附带检测：Ollama 挂了自动拉起（uvicorn 循环内，零额外线程）
        ensure_ollama()
        # 每日备份：跨天触发一次（2026-08-25 工程化补齐）
        day = time.strftime("%Y%m%d")
        if day != last_backup_day:
            last_backup_day = day
            daily_backup_if_due()
        # 2026-08-26 根治 code=3 崩溃循环：拉起前端口预检——端口被外部进程占用时
        # 盲目拉起 uvicorn 必然 bind 失败（Errno 10048 → code=3 → 重启循环，历史 5473 次）。
        # 被占则等待释放（不做无意义拉起），最多等 30s 后仍被占则继续循环等待。
        for _ in range(6):
            if _stop:
                break
            if not port_in_use(PORT):
                break
            log(f"端口 {PORT} 被外部进程占用——等待释放后再拉起（预检，防 bind 失败循环）")
            time.sleep(5)
        if _stop:
            break
        if port_in_use(PORT):
            log(f"端口 {PORT} 持续被占（30s）——本轮跳过拉起，继续等待")
            time.sleep(5)
            continue
        # 2026-08-26 根治 code=3 崩溃循环（残留 uvicorn 占端口导致 bind 失败）：
        # stderr 落盘——崩溃真实原因可查（此前 5473 次崩溃零可见性）。
        # with 包 Popen：子进程继承句柄，父进程关闭副本不影响其写日志。
        with open(ROOT / "data" / "service_uvicorn.log", "a", encoding="utf-8", errors="replace") as logf:
            proc = subprocess.Popen(
                [str(PYTHON), "-m", "uvicorn", "app.main:app", "--host", HOST, "--port", str(PORT), "--log-level", "warning"],
                cwd=str(ROOT),
                creationflags=subprocess.CREATE_NO_WINDOW,
                stderr=logf,
            )
        log(f"服务已拉起 PID={proc.pid}（累计重启 {restarts} 次）")
        health_fails = 0
        last_health_t = 0.0
        while proc.poll() is None and not _stop:
            time.sleep(2)
            # 应用级健康检查（15s 一次）：连续 3 次失败 = 应用坏了（进程还活着）→ 杀进程走重启
            if time.time() - last_health_t >= HEALTH_INTERVAL:
                last_health_t = time.time()
                if health_check():
                    if health_fails:
                        log(f"健康检查恢复（连续失败 {health_fails} 次后）")
                    health_fails = 0
                else:
                    health_fails += 1
                    log(f"健康检查失败 {health_fails}/{HEALTH_FAIL_THRESHOLD}（/healthz 非 200）")
                    if health_fails >= HEALTH_FAIL_THRESHOLD:
                        log("健康检查连续失败达阈值——判定应用不可用，强制重启（治进程活着应用坏了）")
                        try:
                            proc.terminate()
                        except Exception as e:
                            log(f"terminate 失败（将尝试自然超时兜底）: {e}")
                        break
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
