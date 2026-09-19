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

TIMEOUT = 30  # 基础超时（2026-08-26 增强：10→30s）；数据分析（pandas/numpy）60s（P1b 分级）
MAX_OUT = 4000  # stdout 截断上限（2026-08-26：2000→4000——分析结果/图表引用需要更宽裕）
MEM_LIMIT_MB = 200  # 内存墙（A6，2026-08-20）：沙箱子进程工作集上限——正常学习代码 <100MB，
# 无限分配（x=[]; while True: x.append(...)）几秒即超——200MB 给足余量同时拦死失控
RUNNER = pathlib.Path(__file__).parent / "_sandbox_runner.py"
_PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
_TMP_DIR = _PROJECT_ROOT / ".cache" / "tmp"
# venvlauncher 坑（见模块 docstring）：base python 直跑 + PYTHONPATH 注入 venv 包
_BASE_PY = os.path.join(sys.base_prefix, "python.exe")
_VENV_SITE = os.path.join(sys.prefix, "Lib", "site-packages")


# 项目根：runner 以脚本方式起，sys.path[0] 是 app/tools/ 而不是项目根，
# 所以 runner 里 import app.* 需要显式把根也带上（2026-08-30）
_PROJECT_ROOT = str(pathlib.Path(__file__).resolve().parent.parent.parent)


def _sandbox_env() -> dict:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [_VENV_SITE, _PROJECT_ROOT, env.get("PYTHONPATH", "")]
    ).strip(os.pathsep)
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


def _run_with_limits(
    args: list, timeout: int = TIMEOUT, mem_limit_mb: int = MEM_LIMIT_MB, env: dict | None = None
) -> tuple:
    """Popen + 轮询（内存墙 + 超时）。输出重定向到临时文件——Popen 不 communicate 会因管道满
    死锁（子进程输出 >64KB 时阻塞），文件句柄规避。返回 (stdout, stderr, 终止原因|None)。"""
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as out_f, tempfile.TemporaryFile(mode="w+", encoding="utf-8") as err_f:
        # 子进程编码修复（2026-08-21 沙箱事故）：Windows 下 Python 子进程 stdout 默认 GBK（cp936），
        # 中文输出（print/字符串）被父进程按 UTF-8 读 → 'utf-8' codec can't decode 崩溃。
        # PYTHONUTF8=1 强制子进程 UTF-8 模式（PEP 540），与父进程读写一致。
        env = {**(env or {}), "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
        try:
            proc = subprocess.Popen(
                args, stdout=out_f, stderr=err_f, env=env, creationflags=subprocess.CREATE_NO_WINDOW
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
        except Exception as _se:
            print(f"[sandbox] 运行异常: {_se}", file=__import__('sys').stderr)
            raise


def python_sandbox(code: str) -> str:
    """运行一段 Python 代码（学编程/算题/实验/数据分析；超时 30s + 内存墙 200MB）。
    ⚡ 沙箱内置函数（可直接调用，无需 import，签名如下）：
    chart(data, kind="line", title="", xlabel="", ylabel="") → 画 SVG 图并返回图片引用；
      data 支持 [1,2,3] / [{'x','y'}] / [[x,y]] / {标签:值}，kind: line/bar/scatter/pie
    read_file(path) → 读取用户资料文件内容（仅限 memory/ data/ research/ 目录）
    save_result(content, name="result.txt") → 保存结果并返回下载链接；
      第一个参数是内容，第二个是文件名（如 save_result("a,b", "data.csv")）；
      成果归档：用 read_file 读回内容 → 调 kb_ingest 入个人知识库（长期留存可检索）
    画图首选 chart()，不要用字符画。
    能力边界（2026-08-26 增强，完整装配见 _sandbox_runner.py）：
    - import 白名单：纯计算标准库 + numpy/pandas（实测 RestrictedPython 兼容）；文件/网络/系统模块禁止
    - 内置补全：set/dict/list/enumerate/min/max/sum/any/all/map/filter（RestrictedPython 默认太保守）
    - 受控注入：chart() 画图（返回 markdown 图片引用，对话直接显示 SVG）/ read_file() 读 data/ 资料
      （白名单路径）/ save_result() 存分析结果到 /outputs（可下载）
    - 类/属性赋值/局部 +=/解包/列表推导 均可用
    - 限制：类属性增强赋值 self.x += 1 被 RestrictedPython 静态拒绝——用 self.x = self.x + 1 替代"""
    from app.tools.errors import arg_error, timeout_error, tool_err

    code = code.strip()
    if not code:
        return arg_error("沙箱", "代码为空")
    # 临时文件固定路径覆盖写（2026-08-26：safe-delete fail-closed 拦 unlink → 每跑一次留一个
    # tmp 文件（实测堆积 565 个）。固定文件名每次覆盖 = 目录永远只有 1 个文件，零堆积绕开删除）
    # 分级超时（2026-08-26 调研 P1b）：数据分析（pandas/numpy）给 60s，学习代码 30s——
    # 对齐 Azure 220s 的"长任务能力"，但不全局放松（学习代码死循环 30s 内照样拦）
    timeout = 60 if ("pandas" in code or "numpy" in code) else TIMEOUT
    _TMP_DIR.mkdir(parents=True, exist_ok=True)
    code_path = str(_TMP_DIR / "sandbox_code.py")  # 固定路径覆盖（零堆积，safe-delete 兼容）
    try:
        with open(code_path, "w", encoding="utf-8") as fh:
            fh.write(code)
        # base python 直跑（venvlauncher 坑见模块 docstring）+ PYTHONPATH 注入 venv 包
        out, err, reason = _run_with_limits(
            [_BASE_PY, str(RUNNER), code_path], timeout=timeout, env=_sandbox_env()
        )
        if reason:
            if "内存" in reason:
                return tool_err("沙箱", reason, "代码疑似无限分配，缩小数据规模后重试")
            return timeout_error("沙箱", reason)
    except Exception as e:
        return tool_err("沙箱", str(e))
    # 不删临时文件（2026-08-30）：固定路径每次覆盖写，目录永远只有 1 个文件，
    # 本来就没有堆积问题——所以这里的 unlink 是纯负担。
    # 它曾是全量回归里 5 个用例变红的真凶：外部删除守卫按轮次累计 50 次后抛
    # SystemExit（BaseException），`except Exception` 接不住，直接从 finally 打穿调用栈，
    # 把一次**已经成功**的沙箱执行变成进程级失败。单独跑该文件时删除预算充足，8 passed。
    # 教训：清理动作如果对整个功能不是必需的，最稳的实现是**不做**，而不是"做了但兜住异常"。
    if len(out) > MAX_OUT:
        out = out[:MAX_OUT] + f"\n…(输出已截断，共 {len(out)} 字符，需要更多请缩小范围重跑)"
    err = (err or "").strip()
    if err:
        last = err.splitlines()[-1]
        if out:
            return out + "\n" + last
        return f"({last})"
    return out if out else "(执行成功，无输出)"
