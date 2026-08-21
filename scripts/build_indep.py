"""独立进程构建：tsc -b && vite build（不经沙箱工具进程，避免写保护标记）"""
import subprocess
import sys

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

NODE = r"C:\Users\17680\.workbuddy\binaries\node\versions\22.22.2\node.exe"
WD = r"D:\work_buddy\personal-agent\frontend"


def run(args: list[str]) -> int:
    r = subprocess.run([NODE, *args], cwd=WD, capture_output=True, text=True, encoding="utf-8", errors="ignore")
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
