"""独立进程构建：tsc -b && vite build（不经沙箱工具进程，避免写保护标记）"""
import os
import shutil
import subprocess
import sys

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# 2026-09-16 脱敏 + 可移植化：原先硬编码本机用户目录下的 node 路径
# （既不可跨机运行，也把本机用户名写进了仓库）。
# 查找顺序：环境变量 SHIGUANG_NODE → PATH 上的 node → 明确报错。
NODE = os.environ.get("SHIGUANG_NODE") or shutil.which("node") or ""
if not NODE:
    sys.exit("未找到 node：请设置环境变量 SHIGUANG_NODE，或确保 node 在 PATH 中")
# 项目根由脚本位置推导（scripts/ 的上一级），不再硬编码盘符
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WD = os.path.join(ROOT, "frontend")


def run(args: list[str]) -> int:
    r = subprocess.run([NODE, *args], check=False, cwd=WD, capture_output=True, text=True, encoding="utf-8", errors="ignore")
    out = (r.stdout or "").strip()
    err = (r.stderr or "").strip()
    if out:
        print(out[-1200:])
    if err:
        print("STDERR:", err[-600:])
    return r.returncode


print("== tsc -b ==")
rc = run(["node_modules/typescript/bin/tsc", "-b"])
if rc != 0:
    print(f"tsc FAILED exit={rc}")
    sys.exit(rc)
print("tsc OK")

print("== vite build ==")
rc = run(["node_modules/vite/bin/vite.js", "build"])
if rc != 0:
    print(f"vite FAILED exit={rc}")
    sys.exit(rc)
print("vite OK")
sys.exit(0)
