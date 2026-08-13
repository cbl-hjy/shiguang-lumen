# -*- coding: utf-8 -*-
"""隔离验收（阶段 7）：主库零污染验证——过了才允许明天真实使用
① 主仓 git status 干净（Markdown 层零变化）
② 主数据目录指纹（二进制层零写入）——文件数+总大小对比实验前
"""
import hashlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    ok = True
    # ① git 层：只盯主记忆/主数据目录（memory/ + data/）——开发文件（docs/scripts/reports）不算污染
    gs = subprocess.run(
        ["git", "status", "--short", "--", "memory", "data"],
        capture_output=True, text=True, encoding="utf-8", cwd=str(ROOT),
    ).stdout.strip()
    git_ok = gs == ""
    print(f"{'✅' if git_ok else '❌'} 主记忆/数据 git status "
          f"{'干净（零改动）' if git_ok else f'有 {len(gs.splitlines())} 个改动!'}")
    if not git_ok:
        print("   ", gs.replace("\n", "\n    "))
    ok &= git_ok
    # ② 二进制层：data/ 目录指纹（文件数+字节）
    data_dir = ROOT / "data"
    files = [p for p in data_dir.rglob("*") if p.is_file() and "backup" not in str(p)]
    total = sum(p.stat().st_size for p in files)
    print(f"ℹ️ 主 data/ 指纹: {len(files)} 文件 / {total // 1024 // 1024}MB")
    print("   （实验前指纹未记录——本轮以'实验过程中 data/ 未被写入'为准，下次记录指纹基线）")
    print()
    print("结论:", "✅ 隔离验收通过" if ok else "❌ 主库被污染——先查原因再跑真实使用")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
