"""Python 沙箱：子进程隔离 + 超时终止 + 内存墙（2026-08-20 补 A6）
安全：受限执行（RestrictedPython 8.4 装配，见 _sandbox_runner.py）+ 进程超时杀死死循环
     + 内存上限（防无限分配拖垮服务——沙箱失控=事故，能力墙做厚）
关键坑（2026-08-20 踩透）：.venv 的 python.exe 是 venvlauncher（~8MB 启动器），它 spawn 真正的
解释器——Popen 的 proc.pid 是 launcher，监控它的内存永远读不到真实占用。必须用 base python
（sys.base_prefix）直跑 + PYTHONPATH 注入 venv site-packages，proc.pid 才是真实解释器。
临时文件走 D 盘（用户铁律：数据不碰 C 盘）
"""
import ctypes
import os
import pathlib
import subprocess
import sys
import tempfile
import time
from ctypes import wintypes

TIMEOUT = 10
MAX_OUT = 2000  # stdout 截断上限（工具结果进上下文前的预算控制——160K 工具文本大头）
MEM_LIMIT_MB = 200  # 内存墙（A6，2026-08-20）：沙箱子进程工作集上限——正常学习代码 <100MB，
# 无限分配（x=[]; while True: x.append(...)）几秒即超——200MB 给足余量同时拦死失控
RUNNER = pathlib.Path(__file__).parent / "_sandbox_runner.py"
_TMP_DIR = pathlib.Path("D:/work_buddy/.caches/tmp")
# venvlauncher 坑（见模块 docstring）：base python 直跑 + PYTHONPATH 注入 venv 包
_BASE_PY = os.path.join(sys.base_prefix, "python.exe")
_VENV_SITE = os.path.join(sys.prefix, "Lib", "site-packages")


def _sandbox_env() -> dict:
    env = dict(os.environ)
    env["PYTHONPATH"] = _VENV_SITE + os.pathsep + env.get("PYTHONPATH", "")
    return env


def _process_mem_mb(pid: int) -> float:
    """Windows: GetProcessMemoryInfo 取工作集（MB）——零依赖（不引 psutil，C 盘压力）。
    进程已退出/权限不足返回 0.0（不误杀）。"""
    try:
        # WinDLL=stdcall（Win32 API 调用约定）——windll(cdecl) 调用会栈损坏不稳定（踩过：第 0 次碰巧成功之后全 0）
        kernel32 = ctypes.WinDLL("kernel32")
        psapi = ctypes.WinDLL("psapi")
        # 句柄是 64 位——restype 必须 c_void_p，默认 c_int 截断高位 → 句柄无效返回 0
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        h = kernel32.OpenProcess(0x0400 | 0x0010, False, pid)  # QUERY_INFORMATION | VM_READ
        if not h:
            return 0.0
        try:

            class _PMC(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD),
                    ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            pmc = _PMC()
            pmc.cb = ctypes.sizeof(_PMC)
            if psapi.GetProcessMemoryInfo(h, ctypes.byref(pmc), pmc.cb):
                return pmc.WorkingSetSize / (1024 * 1024)
            return 0.0
        finally:
            kernel32.CloseHandle(h)
    except Exception:
        return 0.0


def _run_with_limits(args: list, timeout: int = TIMEOUT, mem_limit_mb: int = MEM_LIMIT_MB, env: dict | None = None) -> tuple:
    """Popen + 轮询（内存墙 + 超时）。输出重定向到临时文件——Popen 不 communicate 会因管道满
    死锁（子进程输出 >64KB 时阻塞），文件句柄规避。返回 (stdout, stderr, 终止原因|None)。"""
    out_f = tempfile.TemporaryFile(mode="w+", encoding="utf-8")
    err_f = tempfile.TemporaryFile(mode="w+", encoding="utf-8")
    # 子进程编码修复（2026-08-21 沙箱事故）：Windows 下 Python 子进程 stdout 默认 GBK（cp936），
    # 中文输出（print/字符串）被父进程按 UTF-8 读 → 'utf-8' codec can't decode 崩溃。
    # PYTHONUTF8=1 强制子进程 UTF-8 模式（PEP 540），与父进程读写一致。
    env = {**(env or {}), "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    try:
        proc = subprocess.Popen(
            args, stdout=out_f, stderr=err_f, env=env,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        deadline = time.monotonic() + timeout
        reason = None
        while proc.poll() is None:
            if time.monotonic() > deadline:
                reason = f"运行超时 {timeout} 秒（可能存在死循环，已终止）"
                break
            if _process_mem_mb(proc.pid) > mem_limit_mb:
                reason = f"内存超限 {mem_limit_mb}MB（疑似无限分配，已终止）"
                break
            time.sleep(0.2)
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        out_f.seek(0)
        err_f.seek(0)
        return out_f.read(), err_f.read(), reason
    finally:
        out_f.close()
        err_f.close()


def python_sandbox(code: str) -> str:
    """运行一段 Python 代码（学编程/算题/实验；不支持 import；超时 10s + 内存墙 200MB）"""
    from app.tools.errors import arg_error, timeout_error, tool_err

    code = code.strip()
    if not code:
        return arg_error("沙箱", "代码为空")
    _TMP_DIR.mkdir(parents=True, exist_ok=True)
    tmp = tempfile.NamedTemporaryFile(
        "w", suffix=".py", encoding="utf-8", delete=False, dir=str(_TMP_DIR)
    )
    code_path = tmp.name
    try:
        tmp.write(code)
        tmp.close()
        # base python 直跑（venvlauncher 坑见模块 docstring）+ PYTHONPATH 注入 venv 包
        out, err, reason = _run_with_limits([_BASE_PY, str(RUNNER), code_path], env=_sandbox_env())
        if reason:
            if "内存" in reason:
                return tool_err("沙箱", reason, "代码疑似无限分配，缩小数据规模后重试")
            return timeout_error("沙箱", reason)
    except Exception as e:
        return tool_err("沙箱", str(e))
    finally:
        try:
            pathlib.Path(code_path).unlink()
        except Exception:
            pass
    if len(out) > MAX_OUT:
        out = out[:MAX_OUT] + f"\n…(输出已截断，共 {len(out)} 字符，需要更多请缩小范围重跑)"
    err = (err or "").strip()
    if err:
        last = err.splitlines()[-1]
        if out:
            return out + "\n" + last
        return f"({last})"
    return out if out else "(执行成功，无输出)"
