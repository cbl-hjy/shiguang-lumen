"""bge-m3 FP16 精度漂移验证 v4（顺序双实例，不碰 chromadb——主服务占用会锁冲突）。

v3 教训：脚本读 chromadb 存量向量，但主服务进程同开一个库 → SQLite/HNSW 锁冲突卡死。
v4 设计：顺序加载 FP32（encode 后释放）→ FP16（encode），不读 chromadb。
显存峰值 = max(FP32~2.3, FP16~1.2) + 主服务 ~1.2 ≈ 3.5GB，8GB 安全。

用法：GPU 空闲时 python scripts/exp_embed_precision.py
"""
import os
import random
import sys

os.environ["TOKENIZERS_PARALLELISM"] = "false"
sys.path.insert(0, ".")

import torch
from sentence_transformers import SentenceTransformer

import numpy as np


def _cos(a, b) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def _load(half: bool, max_seq: int = 512):
    path = os.environ.get("BGE_M3_PATH") or "BAAI/bge-m3"
    m = SentenceTransformer(path, device="cuda")
    m.max_seq_length = max_seq
    if half:
        m = m.half()
    return m


def main():
    from app.memory.schema import MEMORY_FILE

    lines = MEMORY_FILE.read_text(encoding="utf-8").splitlines()
    texts = [l[2:].split("|")[-1].strip() for l in lines if l.startswith("- ")]
    texts = texts[:24]
    n = len(texts)
    print(f"取 {n} 条代表性记忆", flush=True)

    print("加载 FP32 → encode → 释放（峰值显存控制）...", flush=True)
    m32 = _load(half=False)
    v32 = m32.encode(texts, normalize_embeddings=True, batch_size=8)
    del m32
    torch.cuda.empty_cache()

    print("加载 FP16 → encode...", flush=True)
    m16 = _load(half=True)
    v16 = m16.encode(texts, normalize_embeddings=True, batch_size=8)

    self_sims = [_cos(a, b) for a, b in zip(v32, v16)]
    print(f"\n=== ① 同文本 FP32 vs FP16 向量相似度 ===")
    print(f"最小 {min(self_sims):.6f} | 平均 {sum(self_sims) / len(self_sims):.6f}", flush=True)

    print("\n=== ② 两两相似度差异 + 去重阈值边界 ===")
    max_diff = 0.0
    flips = []
    for i in range(n):
        for j in range(i + 1, n):
            s32 = _cos(v32[i], v32[j])
            s16 = _cos(v16[i], v16[j])
            max_diff = max(max_diff, abs(s32 - s16))
            for th in (0.85, 0.97):
                if (s32 >= th) != (s16 >= th):
                    flips.append((i, j, th, round(s32, 4), round(s16, 4)))
    print(f"最大绝对差异: {max_diff:.6f}（<0.01 视为无漂移）")
    print(f"去重阈值边界翻转对数: {len(flips)}")
    for f in flips[:5]:
        print(f"  ⚠ {texts[f[0]][:22]} vs {texts[f[1]][:22]} | 阈值{f[2]} | FP32={f[3]} FP16={f[4]}", flush=True)

    print("\n=== ③ 检索 top-5 排序一致性 ===")
    random.seed(42)
    queries = random.sample(texts, 3)
    agree = 0
    for q in queries:
        qi = texts.index(q)
        r32 = sorted(range(n), key=lambda k: -_cos(v32[qi], v32[k]))[:5]
        r16 = sorted(range(n), key=lambda k: -_cos(v16[qi], v16[k]))[:5]
        ok = r32 == r16
        agree += ok
        print(f"查询「{q[:24]}...」: {'一致 ✓' if ok else '不一致 ✗'}")
        if not ok:
            print(f"  FP32: {r32}\n  FP16: {r16}")
    print(f"\n排序一致 {agree}/3")

    verdict = "✅ 通过" if max_diff < 0.01 and not flips else "⚠️ 需检查"
    print(f"\n结论: {verdict}（最大差异 {max_diff:.6f}，翻转 {len(flips)} 对）")


if __name__ == "__main__":
    main()
