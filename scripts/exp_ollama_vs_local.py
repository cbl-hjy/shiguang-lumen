"""R2 验证门 v2：Ollama bge-m3 (Q8_0) vs 本地 bge-m3 (PyTorch FP16) 一致性。

官方 API 用法（docs.ollama.com/api/embed）：input 支持 string[] 批量，一次调用传全部文本。
日志落盘（log 参数），前台跑完才有结论，避免 tail 缓冲误判卡住。

判定：
- cosine > 0.99 → 一致，存量向量可复用，去重阈值不翻转
- 0.95~0.99 → 有差异，建议重建索引
- < 0.95 → 严重不一致，方案需重评

用法：python scripts/exp_ollama_vs_local.py > logs/exp_ollama_v2.log 2>&1
"""
import json
import math
import os
import sys
import urllib.request

os.environ["TOKENIZERS_PARALLELISM"] = "false"
sys.path.insert(0, ".")

import numpy as np

OLLAMA_URL = "http://127.0.0.1:11434/api/embed"


def ollama_embed_batch(texts: list[str]) -> list[list[float]]:
    """官方批量用法：input 传 string[]"""
    req = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps({"model": "bge-m3", "input": texts}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        d = json.loads(r.read())
    return d["embeddings"]


def cos(a, b) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def main():
    from app.memory.schema import MEMORY_FILE
    from sentence_transformers import SentenceTransformer

    lines = MEMORY_FILE.read_text(encoding="utf-8").splitlines()
    texts = [l[2:].split("|")[-1].strip() for l in lines if l.startswith("- ")]
    texts = texts[:5]
    print(f"[1/4] 取 {len(texts)} 条记忆文本", flush=True)

    print("[2/4] 加载本地 bge-m3（GPU FP16）...", flush=True)
    m = SentenceTransformer(os.environ.get("BGE_M3_PATH") or "BAAI/bge-m3", device="cuda")
    m.max_seq_length = 512
    m = m.half()
    v_local = m.encode(texts, normalize_embeddings=True, batch_size=5)
    print(f"[2/4] 本地编码完成 {len(v_local)} 条", flush=True)

    print("[3/4] Ollama 批量 /api/embed...", flush=True)
    v_ollama = ollama_embed_batch(texts)
    print(f"[3/4] Ollama 返回 {len(v_ollama)} 条", flush=True)

    print("\n=== [4/4] 逐条对比 ===")
    sims = []
    for i, t in enumerate(texts):
        lo, ol = v_local[i], v_ollama[i]
        norm_ol = math.sqrt(sum(x * x for x in ol))
        s = cos(lo, ol)
        sims.append(s)
        flag = "✅" if s > 0.99 else ("⚠️" if s > 0.95 else "❌")
        print(f"  {flag} [{s:.4f}] 本地{len(lo)}维 Ollama{len(ol)}维 范数{norm_ol:.4f} | {t[:30]}", flush=True)

    avg = sum(sims) / len(sims)
    mn = min(sims)
    print(f"\n=== 结论 ===")
    print(f"平均 cosine: {avg:.4f} | 最小: {mn:.4f}", flush=True)
    if mn > 0.99:
        print("✅ R2 通过：高度一致，去重阈值不翻转，存量向量可复用", flush=True)
    elif mn > 0.95:
        print("⚠️ R2 部分通过：有差异但可控，建议重建索引", flush=True)
    else:
        print("❌ R2 不通过：严重不一致，方案需重评", flush=True)


if __name__ == "__main__":
    main()
