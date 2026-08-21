"""长会话退化探测：同会话连续 50 轮问答（模拟面试节奏），记录每轮
上下文增长（全量重放的实际量）/ 回答质量信号（长度/重复/漂移）→ 定位退化点。
纪律：走 HTTP（curl 子进程），工具进程不直连任何既有数据文件；只写新输出文件。
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
OUT = Path(__file__).resolve().parent.parent.parent / "data" / "longhorizon_runs"
OUT.mkdir(exist_ok=True)

# 模拟面试节奏的 50 个问题（ML基础 → DL → LLM/Agent，由浅入深）
QUESTIONS = [
    "什么是过拟合？怎么解决？",
    "L1 和 L2 正则化的区别？",
    "什么是交叉熵损失？",
    "梯度下降和随机梯度下降的区别？",
    "什么是学习率？怎么调？",
    "讲讲反向传播的原理",
    "什么是批量归一化？有什么用？",
    "激活函数为什么用 ReLU？",
    "什么是 dropout？为什么有效？",
    "如何判断模型欠拟合还是过拟合？",
    "什么是验证集？和测试集的区别？",
    "讲讲交叉验证",
    "什么是偏差和方差？",
    "什么是特征工程？常见做法？",
    "类别不平衡怎么处理？",
    "讲讲 CNN 的基本结构",
    "卷积层和全连接层的区别？",
    "什么是池化？为什么用？",
    "讲讲 RNN 的原理和缺点",
    "什么是 LSTM？解决了什么问题？",
    "什么是注意力机制？",
    "讲讲 Transformer 的整体架构",
    "什么是自注意力？QKV 是什么？",
    "什么是位置编码？为什么需要？",
    "Transformer 和 RNN 的对比？",
    "什么是 BERT？预训练任务是什么？",
    "什么是 GPT？和 BERT 的区别？",
    "什么是 tokenizer？常见类型？",
    "什么是 embedding？和 one-hot 的区别？",
    "讲讲 softmax 和 temperature 的关系",
    "什么是 RLHF？",
    "什么是 PPO？核心思想？",
    "什么是 DPO？和 RLHF 的区别？",
    "什么是上下文窗口？超了怎么办？",
    "什么是 RAG？解决什么问题？",
    "什么是 agent？和普通 LLM 的区别？",
    "什么是工具调用 function calling？",
    "什么是记忆机制？常见类型？",
    "什么是向量数据库？",
    "什么是 RAG 的 chunking？怎么选大小？",
    "什么是 embedding 模型？怎么选？",
    "什么是 rerank？什么时候需要？",
    "讲讲微调（fine-tuning）和全参微调的区别",
    "什么是 LoRA？为什么省显存？",
    "什么是量化？常见方案？",
    "什么是蒸馏？有什么用？",
    "什么是思维链 CoT？",
    "什么是多模态？架构怎么设计？",
    "什么是 agent 的规划能力？怎么实现？",
    "最后总结一下：从 ML 到 LLM，你认为最重要的 5 个概念是？",
]


def chat_round(sid: str, question: str, tag: str) -> dict:
    body = {"message": question, "session_id": sid}
    t0 = time.time()
    r = subprocess.run(
        ["curl", "-s", "-N", "-X", "POST", f"{BASE}/api/chat"]
        + headers_json()
        + ["-d", json.dumps(body, ensure_ascii=False), "--max-time", "120"],
        capture_output=True, text=True, encoding="utf-8", errors="ignore",
    )
    dt = time.time() - t0
    out = r.stdout

    text = ""
    tools = {}
    for line in out.splitlines():
        if not line.startswith("data:"):
            continue
        try:
            ev = json.loads(line[5:].strip())
        except Exception:
            continue
        if ev.get("type") == "delta":
            text += ev.get("text") or ""
        elif ev.get("type") == "tool":
            name = ev.get("name") or ""
            tools[name] = tools.get(name, 0) + 1

    has_done = '"type": "done"' in out
    # 质量信号
    signals = []
    if not has_done:
        signals.append("NO_DONE")
    if len(text) < 50:
        signals.append("回答过短")
    if re.search(r"上面|刚才|之前说过|正如前面|如前所述", text):
        signals.append("引用前文(可能重复)")
    if re.search(r"抱歉|对不起|我不太确定|我不了解|这个我不", text):
        signals.append("能力不足/道歉")
    # 漂移粗检：问题关键词在回答里是否完全消失
    kw = [w for w in re.findall(r"[\u4e00-\u9fff]{2,6}", question) if w not in ("什么是", "怎么", "什么", "为什么", "最后", "总结", "一下", "你觉得", "你认为")]
    if kw and not any(w in text for w in kw[:2]):
        signals.append("可能跑题(关键词缺失)")

    return {"sec": round(dt, 1), "len": len(text), "tools": tools, "signals": signals, "has_done": has_done}


def session_ctx_size(sid: str) -> int:
    """全量重放的实际量：GET /api/session/{sid} 的 messages 内容总字符数"""
    r = subprocess.run(
        ["curl", "-s", f"{BASE}/api/session/{sid}", "--max-time", "10"],
        capture_output=True, text=True, encoding="utf-8", errors="ignore",
    )
    try:
        d = json.loads(r.stdout)
        msgs = d.get("messages", [])
        return sum(len((m.get("content") or "")) for m in msgs)
    except Exception:
        return -1


def run(tag: str):
    # 新会话
    r = subprocess.run(
        ["curl", "-s", "-X", "POST", f"{BASE}/api/session/new", "--max-time", "10"],
        capture_output=True, text=True, encoding="utf-8", errors="ignore",
    )
    sid = json.loads(r.stdout)["session_id"]
    rows = []
    for i, q in enumerate(QUESTIONS, 1):
        res = chat_round(sid, q, tag)
        ctx = session_ctx_size(sid)
        row = {"round": i, "q_len": len(q), **res, "ctx_chars": ctx}
        rows.append(row)
        print(f"[{i:>2}/50] {res['sec']}s len={res['len']:>4} ctx={ctx:>6} tools={res['tools']} signals={res['signals']} {q[:16]}")
        sys.stdout.flush()

    # 摘要落盘
    summary = {
        "session_id": sid,
        "total_sec": round(sum(r["sec"] for r in rows), 1),
        "ctx_growth": [{"round": r["round"], "ctx_chars": r["ctx_chars"]} for r in rows],
        "degradation": [
            {"round": r["round"], "len": r["len"], "signals": r["signals"]}
            for r in rows if r["signals"]
        ],
        "all_signals_count": sum(len(r["signals"]) for r in rows),
    }
    (OUT / f"{tag}_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n=== 退化信号汇总 ===")
    for d in summary["degradation"]:
        print(f"  round {d['round']}: len={d['len']} {d['signals']}")
    print(f"=== 总耗时 {summary['total_sec']}s | 有信号轮数 {len(summary['degradation'])} ===")


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "LH50")
