"""真实使用摩擦探测：模拟学生学"交叉熵损失"完整旅程，每步记录正常/摩擦点
纪律：走 HTTP（curl 子进程）让服务端处理，工具进程不直连数据文件。
每场景输出：耗时 / 工具调用 / 回答长度 / 摩擦观察（脚本自动标记异常，质量人工判断）
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


BASE = "http://127.0.0.1:8000/api/chat"
OUT = Path(__file__).resolve().parent.parent.parent / "data" / "friction_runs"
OUT.mkdir(exist_ok=True)


def chat(msg: str, sid: str | None, tag: str) -> dict:
    body = {"message": msg}
    if sid:
        body["session_id"] = sid
    t0 = time.time()
    r = subprocess.run(
        ["curl", "-s", "-N", "-X", "POST", BASE]
        + headers_json()
        + ["-d", json.dumps(body, ensure_ascii=False), "--max-time", "300"],
        capture_output=True, text=True, encoding="utf-8", errors="ignore",
    )
    dt = time.time() - t0
    out = r.stdout
    has_done = '"type": "done"' in out
    tools = {}
    for m in re.findall(r'"name": "([a-z_]+)"', out):
        tools[m] = tools.get(m, 0) + 1
    text = "".join(
        json.loads(line[5:])["text"]
        for line in out.splitlines()
        if line.startswith("data:") and '"type": "delta"' in line
        for _ in [0]
    )
    # 兜底解析
    if not text:
        for line in out.splitlines():
            if line.startswith("data:") and '"type": "delta"' in line:
                try:
                    text += json.loads(line[5:])["text"]
                except Exception:
                    pass
    sid_out = None
    m = re.search(r'"session_id": "([a-z0-9]+)"', out)
    if m:
        sid_out = m.group(1)
    # 落盘供人工检查
    (OUT / f"{tag}.txt").write_text(out[:20000], encoding="utf-8", errors="ignore")
    return {"sid": sid_out, "text": text, "tools": tools, "has_done": has_done, "sec": dt, "bytes": len(out)}


def mark(name: str, r: dict, notes: str):
    """打印结果 + 自动标记异常"""
    flags = []
    if not r["has_done"]:
        flags.append("⚠️ 流中断/无 done")
    if r["sec"] > 120:
        flags.append("⚠️ 慢(>120s)")
    if not r["text"].strip():
        flags.append("⚠️ 空回答")
    print(f"\n■ {name}  [{r['sec']:.0f}s] {flags and ' '.join(flags) or 'OK'}")
    if r["tools"]:
        print(f"   工具: {', '.join(f'{k}×{v}' for k, v in r['tools'].items())}")
    else:
        print("   工具: —")
    print(f"   回答({len(r['text'])}字): {r['text'][:120].strip()}")
    if notes:
        print(f"   观察: {notes}")


def main():
    sid = None
    print("=" * 60)
    print("真实使用摩擦探测：学「交叉熵损失」（全新概念，无先验）")
    print("=" * 60)

    scenes = [
        ("S1 开场", "我想学一个新的东西：交叉熵损失函数。完全没接触过，开始吧",
         "开场引导？是否查记忆找基础？是否先直觉后公式？"),
        ("S2 深入", "继续讲，它和均方误差有什么区别？什么时候该用哪个？",
         "对比讲解质量？是否用类比？Markdown 标记是否自然？"),
        ("S3 卡壳", "你讲得太抽象了！交叉熵那个 log 和负号我完全理解不了，换个人话说法重新讲",
         "是否重讲？是否调 reflect_teaching 沉淀（M8 引导）？"),
        ("S4 追问", "那 softmax 和交叉熵为什么总是搭配出现？我知识库里有相关内容吗？",
         "是否调 kb_search/search_memory？回答深度？"),
        ("S5 记笔记", "把交叉熵的直觉帮我记到记忆里，我怕忘了",
         "是否调 remember？内容质量？"),
        ("S6 出题", "出两道题考考我，检验我是不是真懂了",
         "题目质量？是否给检查点/答案？"),
        ("S7 收尾", "今天先学到这，帮我记一下学习进度",
         "是否调 log_learning？是否主动总结/streak？"),
    ]

    for tag, msg, notes in scenes:
        r = chat(msg, sid, tag)
        sid = r["sid"] or sid
        mark(tag, r, notes)
        time.sleep(1)

    print("\n" + "=" * 60)
    print(f"完成。sid={sid}，原始输出在 data/friction_runs/")
    print("下一步：人工分析 → docs/FRICTION-LOG.md")


if __name__ == "__main__":
    main()
