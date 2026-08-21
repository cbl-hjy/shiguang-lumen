"""历史记忆类别归一（2026-08-17，写入侧类别统一工程）
只改 cat= 段为词汇表内值（normalize_category），其他字段（日期/src/imp/ver/内容）原样保留。
安全：执行前备份到 backups/；git 可回滚。ver= 是有效治理字段，绝不触碰。
"""
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, ".")

ROOT = Path(".")
MEM = ROOT / "memory" / "user_memory.md"
BACKUP = Path("D:/work_buddy/backups") / f"user_memory_pre_normalize_{datetime.now():%Y%m%d_%H%M}.md"

from app.memory.schema import normalize_category  # noqa: E402

PAT = re.compile(r"cat=([^|]+)")


def main():
    if not MEM.exists():
        print("记忆文件不存在")
        return
    text = MEM.read_text(encoding="utf-8")
    lines = text.splitlines()
    changed = 0
    out = []
    for ln in lines:
        if not ln.startswith("- "):
            out.append(ln)
            continue
        m = PAT.search(ln)
        if not m:
            out.append(ln)
            continue
        old = m.group(1).strip()
        new = normalize_category(old)
        if old == new:
            out.append(ln)
            continue
        out.append(PAT.sub(f"cat={new}", ln, count=1))
        changed += 1
        print(f"  {old} → {new} | {ln.split('|')[-1].strip()[:40]}")
    if changed == 0:
        print("无需归一（全部已是词汇表内值）")
        return
    # 备份后写入
    shutil.copy2(MEM, BACKUP)
    MEM.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"\n归一 {changed} 条 → {MEM}")
    print(f"备份: {BACKUP}")
    # 验证
    from collections import Counter
    cats = Counter(PAT.search(l).group(1).strip() for l in MEM.read_text(encoding="utf-8").splitlines() if l.startswith("- ") and PAT.search(l))
    print("归一后 cat 分布:", dict(cats))
    bad = [c for c in cats if c not in ("学习记录", "进度", "目标", "偏好", "困惑", "关系", "错误记录", "反思", "笔记")]
    print("非词汇表残留:", bad if bad else "无 ✓")


if __name__ == "__main__":
    main()
