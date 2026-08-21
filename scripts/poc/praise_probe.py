"""连续好评探测（一号病菌：反思负向偏置）——用户连续好评，验证：
① save_skill 是否被自主调用（正向沉淀）
② 下一轮注入的 recent_reflections 是否只有失败反思（负向循环）
纪律：走 HTTP，零直连写数据；只读 reflections.md/skills.md 做对照。
"""
import json
import re
import subprocess
import sys
import time
from pathlib import Path

import sys as _sys
from pathlib import Path as _Path

_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))
from _auth import headers_json


BASE = "http://127.0.0.1:8000"
OUT = Path(__file__).resolve().parent.parent.parent / "data" / "ux_stress"
OUT.mkdir(exist_ok=True)
REFLECTIONS = Path(__file__).resolve().parent.parent.parent / "memory" / "reflections.md"
SKILLS = Path(__file__).resolve().parent.parent.parent / "memory" / "skills.md"

# 5 个教学回合：概念问题 + 强烈好评
ROUNDS = [
    ("讲一下什么是梯度下降，要通俗一点", "这个讲法太棒了，我一下就懂了！"),
    ("讲讲什么是交叉验证", "真懂我，这个类比太贴切了，讲得好！"),
    ("softmax 到底是干嘛的？", "这次终于听明白了，讲得太好了！"),
    ("什么是 RAG？", "你讲得比网上所有教程都好，我给你点个赞！"),
    ("讲讲 attention", "讲得真好，我以后就按你这个思路复习！"),
]


def chat(msg: str, sid: str, tag: str) -> dict:
    body = {"message": msg, "session_id": sid}
    r = subprocess.run(
        ["curl", "-s", "-N", "-X", "POST", f"{BASE}/api/chat"]
        + headers_json()
        + ["-d", json.dumps(body, ensure_ascii=False), "--max-time", "120"],
        capture_output=True, text=True, encoding="utf-8", errors="ignore",
    )
    out = r.stdout
    tools = {}
    for m in re.findall(r'"name": "([a-z_]+)"', out):
        tools[m] = tools.get(m, 0) + 1
    text = "".join(
        json.loads(line[5:])["text"]
        for line in out.splitlines()
        if line.startswith("data:") and '"type": "delta"' in line
        for _ in [0]
    )
    if not text:
        for line in out.splitlines():
            if line.startswith("data:") and '"type": "delta"' in line:
                try:
                    text += json.loads(line[5:])["text"]
                except Exception:
                    pass
    return {"tools": tools, "len": len(text), "done": '"type": "done"' in out}


def tail_of(path: Path, n: int = 3) -> str:
    if not path.exists():
        return "(文件不存在)"
    lines = path.read_text(encoding="utf-8", errors="ignore").strip().split("\n")
    return "\n".join(lines[-n:])


def main():
    # 记录跑前状态
    before_r = sum(1 for _ in open(REFLECTIONS, encoding="utf-8")) if REFLECTIONS.exists() else 0
    before_s = sum(1 for _ in open(SKILLS, encoding="utf-8")) if SKILLS.exists() else 0

    r = subprocess.run(["curl", "-s", "-X", "POST", f"{BASE}/api/session/new", "--max-time", "10"],
                       capture_output=True, text=True, encoding="utf-8")
    sid = json.loads(r.stdout)["session_id"]
    print(f"新会话: {sid}", flush=True)

    praise_tools = {}
    for i, (q, praise) in enumerate(ROUNDS, 1):
        r1 = chat(q, sid, f"p{i}q")
        r2 = chat(praise, sid, f"p{i}x")
        for t, c in r2["tools"].items():
            praise_tools[t] = praise_tools.get(t, 0) + c
        print(f"[回合{i}] 问题工具={r1['tools']} | 好评工具={r2['tools']} | 好评回应{r2['len']}字", flush=True)

    # 汇总
    after_r = sum(1 for _ in open(REFLECTIONS, encoding="utf-8")) if REFLECTIONS.exists() else 0
    after_s = sum(1 for _ in open(SKILLS, encoding="utf-8")) if SKILLS.exists() else 0
    print("\n=== 一号病菌验证 ===", flush=True)
    print(f"好评轮工具汇总: {praise_tools}", flush=True)
    print(f"save_skill 调用次数: {praise_tools.get('save_skill', 0)}", flush=True)
    print(f"reflections.md 行数: {before_r} → {after_r}（好评后{'增' if after_r > before_r else '未增'}）", flush=True)
    print(f"skills.md 行数: {before_s} → {after_s}（好评后{'增' if after_s > before_s else '未增'}）", flush=True)
    print(f"\n--- 当前 reflections.md 尾部（每轮注入的内容）---", flush=True)
    print(tail_of(REFLECTIONS, 4), flush=True)
    print(f"\n--- 当前 skills.md 尾部 ---", flush=True)
    print(tail_of(SKILLS, 4), flush=True)


if __name__ == "__main__":
    main()
