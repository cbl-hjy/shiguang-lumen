"""memory_audit.py —— 记忆复查工具（ver=unverified 闭环）

依据：docs/DATA-GOVERNANCE-PLAN.md（对齐 Generative Agents 证据指针 + Foundry 记忆可审原则）
定位：doc_health 报"imp>=6 未复查"时跑；列出候选 → 人工/模型逐条确认 → 改 verified。
原则：复查是"人可审"不是"系统评级"——确认后的记忆仍是用户可改的真相源，不是考核。

用法：
  python scripts/memory_audit.py list            # 列出 imp>=6 且未复查的记忆
  python scripts/memory_audit.py verify <关键词>  # 把含关键词的条目标记 verified
  python scripts/memory_audit.py verify --all    # 全部标记 verified（只在逐条确认后）
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MEM_FILE = ROOT / "memory" / "user_memory.md"
IMP_THRESHOLD = 6


def _entries():
    lines = MEM_FILE.read_text(encoding="utf-8").splitlines()
    for i, ln in enumerate(lines, 1):
        if not ln.startswith("- ") or "imp=" not in ln:
            continue
        try:
            imp = int(ln.split("imp=")[1].split("|")[0].strip())
        except (IndexError, ValueError):
            continue
        yield i, ln, imp


def list_unverified():
    items = [(i, ln, imp) for i, ln, imp in _entries() if imp >= IMP_THRESHOLD and "ver=verified" not in ln]
    if not items:
        print(f"(无 imp>={IMP_THRESHOLD} 未复查记忆，全绿)")
        return
    print(f"imp>={IMP_THRESHOLD} 未复查记忆 {len(items)} 条：\n")
    for i, ln, imp in items:
        content = ln.split("|")[-1].strip()[:80]
        print(f"  [{i}] imp={imp} {content}")


def verify(keyword=None, all_flag=False):
    lines = MEM_FILE.read_text(encoding="utf-8").splitlines()
    changed = 0
    for i, ln in enumerate(lines):
        if not ln.startswith("- ") or "imp=" not in ln or "ver=verified" in ln:
            continue
        try:
            imp = int(ln.split("imp=")[1].split("|")[0].strip())
        except (IndexError, ValueError):
            continue
        if imp < IMP_THRESHOLD:
            continue
        if not all_flag and keyword and keyword not in ln:
            continue
        # 在 imp= 后追加 ver=verified（保留原字段；格式: | imp=7 | cat=.. ）
        if "ver=" in ln:
            lines[i] = ln.replace("ver=unverified", "ver=verified", 1)
        else:
            # 插到 cat 前：| imp=7 | cat=x | ... → | imp=7 | ver=verified | cat=x | ...
            parts = ln.split("|")
            for j, p in enumerate(parts):
                if "cat=" in p:
                    parts.insert(j, " ver=verified ")
                    break
            lines[i] = "|".join(parts)
        changed += 1
    if changed:
        MEM_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"已标记 {changed} 条为 verified")
    else:
        print("无匹配条目（或已全部 verified）")


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0] == "list":
        list_unverified()
    elif args[0] == "verify":
        if "--all" in args:
            verify(all_flag=True)
        elif len(args) >= 2:
            verify(keyword=args[1])
        else:
            print("用法: memory_audit.py verify <关键词> | --all")
    else:
        print("用法: list | verify <关键词> | verify --all")
