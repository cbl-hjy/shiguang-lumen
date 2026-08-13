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
HOST = "0.0.0.0"
PORT = 8000
RESTART_DELAY = 3
_stop = False


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


def port_in_use() -> bool:
    try:
        s = socket.create_connection(("127.0.0.1", PORT), timeout=1)
        s.close()
        return True
    except OSError:
        return False


def on_stop(*_):
    global _stop
    _stop = True


def main():
    # 安全护栏：开门（0.0.0.0）必须门锁（token）在——start.bat 与看门狗各一道
    if not load_token():
        print(f"⚠️ 拒绝启动：host={HOST} 但 SHIGUANG_TOKEN 未配置（.env 缺失或为空）。", flush=True)
        print("  门锁没装不能开门——配置 SHIGUANG_TOKEN 后再启动，或改回 --host 127.0.0.1。", flush=True)
        sys.exit(1)

    if port_in_use():
        log(f"检测到 {PORT} 端口已有服务（可能是手动启动）——本守护不接管，退出")
        sys.exit(0)

    signal.signal(signal.SIGINT, on_stop)
    signal.signal(signal.SIGTERM, on_stop)

    restarts = 0
    log(f"看门狗启动（host={HOST} port={PORT}）")
    while not _stop:
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


if __name__ == "__main__":
    main()
