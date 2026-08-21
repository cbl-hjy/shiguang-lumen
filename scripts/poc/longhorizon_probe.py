"""长程任务现状探测：真实模型自主跑"系统研究专题"任务，不干预。
记录：工具调用时间线 / 上下文增长估算 / 质量信号（迷失/重复/收尾）。
纪律：走 HTTP（curl 子进程），工具进程不直连任何既有数据文件；只写新的输出文件。
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
OUT = Path(__file__).resolve().parent.parent.parent / "data" / "longhorizon_runs"
OUT.mkdir(exist_ok=True)

TASK = (
    "帮我做一个系统研究：对比学习和强化学习这两个方向，从核心思想、典型算法、"
    "适用场景、学习路线、面试高频考点五个维度整理成一份面试可用的笔记。"
    "这是个比较大的任务，你可以自主决定怎么做（拆解、检索、组织都可以），"
    "做完给我一份结构化的总结。"
)


def run_probe(tag: str) -> dict:
    body = {"message": TASK}
    t0 = time.time()
    r = subprocess.run(
        ["curl", "-s", "-N", "-X", "POST", BASE]
        + headers_json()
        + ["-d", json.dumps(body, ensure_ascii=False), "--max-time", "600"],
        capture_output=True, text=True, encoding="utf-8", errors="ignore",
    )
    dt = time.time() - t0
    out = r.stdout
    (OUT / f"{tag}.txt").write_text(out[:200000], encoding="utf-8", errors="ignore")

    # 逐行解析 SSE，构建事件时间线
    events = []  # {t, type, name?, args_len?, text_len?}
    text_total = 0
    for line in out.splitlines():
        if not line.startswith("data:"):
            continue
        try:
            ev = json.loads(line[5:].strip())
        except Exception:
            continue
        et = ev.get("type")
        if et == "tool":
            name = ev.get("name") or ""
            args = ev.get("args") or ev.get("arguments") or ""
            if isinstance(args, dict):
                args_len = len(json.dumps(args, ensure_ascii=False))
            else:
                args_len = len(str(args))
            events.append({"t": time.time() - t0, "type": "tool", "name": name, "args_len": args_len})
        elif et == "delta":
            text = ev.get("text") or ""
            text_total += len(text)
            events.append({"t": time.time() - t0, "type": "delta", "text_len": len(text)})
        elif et in ("run", "turn_end", "done"):
            events.append({"t": time.time() - t0, "type": et})

    # 工具时间线（去 delta）：名字 + 参数长度
    tool_chain = [{"t": round(e["t"], 1), "name": e["name"], "args_len": e["args_len"]}
                  for e in events if e["type"] == "tool"]
    tool_names = [tc["name"] for tc in tool_chain]
    deltas = [e for e in events if e["type"] == "delta"]
    has_done = any(e["type"] == "done" for e in events)
    turn_count = sum(1 for e in events if e["type"] == "turn_end")

    # 质量信号
    signals = []
    if not has_done:
        signals.append("流中断/无 done")
    if tool_names.count(tool_names[-1]) > 3 if tool_names else False:
        signals.append("疑似重复调用同一工具")
    if re.search(r"抱歉|对不起|我搞错了|重来", out, re.I):
        signals.append("出现道歉/自我否定")
    if "deleg_study" in tool_names:
        signals.append("deleg_study 被调用")
    if text_total > 3000:
        signals.append(f"输出量大({text_total}字)——长回答")

    summary = {
        "sec": round(dt, 1),
        "has_done": has_done,
        "turn_count": turn_count,
        "tool_chain": tool_chain,
        "tool_stats": {n: tool_names.count(n) for n in set(tool_names)},
        "text_total": text_total,
        "signals": signals,
        "bytes": len(out),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return summary


if __name__ == "__main__":
    tag = sys.argv[1] if len(sys.argv) > 1 else "LH1"
    run_probe(tag)
