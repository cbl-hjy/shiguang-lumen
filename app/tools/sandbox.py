"""Python 沙箱：子进程隔离 + 超时终止（Windows 无 signal.alarm，靠 subprocess timeout）
安全：受限执行（RestrictedPython 8.4 装配，见 _sandbox_runner.py）+ 进程超时杀死死循环
临时文件走 D 盘（用户铁律：数据不碰 C 盘）
"""
import pathlib
import subprocess
import sys
import tempfile

TIMEOUT = 10
MAX_OUT = 2000  # stdout 截断上限（工具结果进上下文前的预算控制——160K 工具文本大头）
RUNNER = pathlib.Path(__file__).parent / "_sandbox_runner.py"
_TMP_DIR = pathlib.Path(__file__).resolve().parent.parent.parent / ".cache" / "tmp"


def python_sandbox(code: str) -> str:
    """运行一段 Python 代码（学编程/算题/实验；不支持 import；超时 10s）"""
    code = code.strip()
    if not code:
        return "(代码为空)"
    _TMP_DIR.mkdir(parents=True, exist_ok=True)
    tmp = tempfile.NamedTemporaryFile(
        "w", suffix=".py", encoding="utf-8", delete=False, dir=str(_TMP_DIR)
    )
    code_path = tmp.name
    try:
        tmp.write(code)
        tmp.close()
        r = subprocess.run(
            [sys.executable, str(RUNNER), code_path],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return f"(运行超时 {TIMEOUT} 秒——可能存在死循环，已终止)"
    except Exception as e:
        return f"(沙箱异常: {e})"
    finally:
        try:
            pathlib.Path(code_path).unlink()
        except Exception:
            pass
    out = r.stdout or ""
    if len(out) > MAX_OUT:
        out = out[:MAX_OUT] + f"\n…(输出已截断，共 {len(r.stdout)} 字符，需要更多请缩小范围重跑)"
    err = (r.stderr or "").strip()
    if err:
        last = err.splitlines()[-1]
        if out:
            return out + "\n" + last
        return f"({last})"
    return out if out else "(执行成功，无输出)"
