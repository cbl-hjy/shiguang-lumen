"""子进程受限执行器：由 sandbox.py 以 subprocess 调用（父进程负责超时）
不在沙箱内做超时（Windows 无 signal.alarm），隔离到子进程才能安全终止死循环
"""
import sys

from RestrictedPython import compile_restricted_exec, safe_globals
from RestrictedPython.Eval import default_guarded_getattr, default_guarded_getitem
from RestrictedPython.Guards import guarded_iter_unpack_sequence
from RestrictedPython.PrintCollector import PrintCollector


def main():
    code = open(sys.argv[1], encoding="utf-8").read()
    try:
        compiled = compile_restricted_exec(code)
    except SyntaxError as e:
        print(f"(语法错误: {e})", file=sys.stderr)
        return
    if getattr(compiled, "errors", None):
        print(f"(受限检查未通过: {'; '.join(compiled.errors)})", file=sys.stderr)
        return
    glb = safe_globals.copy()
    glb.update(
        {
            "_getattr_": default_guarded_getattr,
            "_getitem_": default_guarded_getitem,
            "_getiter_": iter,
            "_unpack_sequence_": guarded_iter_unpack_sequence,
            # 8.4 注入逻辑执行 _print_(_getattr_) → 传 PrintCollector 类（工厂）
            "_print_": PrintCollector,
        }
    )
    try:
        exec(compiled.code, glb)
    except Exception as e:
        print(f"(运行错误: {type(e).__name__}: {e})", file=sys.stderr)
        return
    printer = glb.get("_print")
    out = printer() if printer is not None else ""
    if out:
        print(out, end="")


if __name__ == "__main__":
    main()
