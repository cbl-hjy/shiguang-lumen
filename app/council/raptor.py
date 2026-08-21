# -*- coding: utf-8 -*-
"""RAPTOR 树（融合欠账补全——2026-08-19）：递归聚类摘要树，星宿"翻阅自己的书"的检索设施。

设计（不过度工程版，借 RAPTOR 论文 ICLR 2024 思想）：
- 叶子 = 原文块（复用 distill_core.chunk_text）
- 每层贪心聚类（余弦阈值，纯 numpy，不引 sklearn/GMM）→ 簇 LLM 摘要（保留原文关键句，可核查）
- 递归至单根；树 JSON 落盘 data/council_trees/<sage_id>.json
- 检索：全部摘要节点向量 vs 问题向量 top-k（节点数百级，O(n) 可行）→ 注入星宿发言作为"书中证据"
embedding 走 Ollama 服务（bge-m3 Q8_0，单一 GPU 实例）——2026-08-21 方案 D：
  原 08-19 定案"CPU 独立实例防 GPU 抢显存"已过时——Ollama 单 CUDA context 根治并发，
  建树从 CPU 1-2 分钟提速到 GPU 秒级（R2 验证：Ollama vs 本地 cosine 0.9997 一致）。
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
import uuid
from pathlib import Path

import numpy as np

from app.config import DATA_DIR

TREES_DIR = DATA_DIR / "data" / "council_trees"
CLUSTER_CHARS = 6000  # 簇文本拼接上限
MAX_LEVEL = 4
SIM_THRESHOLD = 0.70  # 贪心聚类余弦阈值（中位块间相似度 0.689 实测校准：0.70 分出话题簇，可调）
# LLM 摘要并发上限（2026-08-21 加速：官方 RAPTOR 并行摘要被注释掉是因 LLM API 限流；
# 我们 asyncio.gather 并行 + 信号量限并发 3，防 DeepSeek 429 堆积——A1 钩子同款教训）
MAX_LLM_CONCURRENCY = 3
_LLM_SEM: asyncio.Semaphore | None = None


async def _cpu_embed(texts: list[str]) -> list[list[float]]:
    """编码走 Ollama 服务（复用 vector.embed 的 HTTP + 熔断）。Ollama 挂 → 异常传播给调用方（建树挂账/检索降级纯立场卡）"""
    from app.memory import vector

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, vector.embed, texts)

CLUSTER_PROMPT = (
    "You are summarizing a cluster of text passages from a book. Output JSON only:\n"
    "{\"summary\": \"cluster's key claims in one paragraph (<=120 words, Chinese ok)\", "
    "\"quotes\": [\"2-3 exact verbatim quotes from the cluster text that best support the summary\"]}\n"
    "Rules: quotes MUST be verbatim substrings of the provided cluster text (used for verifiable citation)."
)


def _extract_json(text: str) -> dict | None:
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


async def _cluster_summary(cluster_text: str, label: str) -> dict:
    """簇摘要——复用 distill_core._llm_json（2026-08-19：原裸 Agent.run 无 fallback，
    卡死在 LLM 调用上（进程活着 0 输出）——统一走主→备/同模型重试 + 熔断链）"""
    from app.council.distill_core import _llm_json

    return await _llm_json(CLUSTER_PROMPT, cluster_text[:CLUSTER_CHARS], f"raptor-{label}")


def _greedy_cluster(embs: np.ndarray, sim_threshold: float = SIM_THRESHOLD) -> list[list[int]]:
    """贪心阈值聚类（2026-08-19 实验修正后采用）：
    官方 GMM+BIC 实测不适用——3500 字符块间余弦相似度中位 0.689（同一本书嵌得近），
    BIC 无拐点恒偏好 19+ 簇（37 块→36 簇，树不成形）。阈值聚类直接对应相似度语义，参数可调。
    参考：官方 RAPTOR 的 threshold=0.1 概率多标签（cluster_utils.py），本实现改单标签 argmax 保树结构。"""
    clusters: list[list[int]] = []
    centers: list[np.ndarray] = []
    for i, e in enumerate(embs):
        best_sim, best_ci = -1.0, -1
        for ci, c in enumerate(centers):
            s = float(np.dot(e, c))
            if s > best_sim:
                best_sim, best_ci = s, ci
        if best_ci >= 0 and best_sim >= sim_threshold:
            clusters[best_ci].append(i)
            centers[best_ci] = embs[clusters[best_ci]].mean(axis=0)
        else:
            clusters.append([i])
            centers.append(e.copy())
    return clusters


def _node(nid: str, level: int, text: str, emb: list[float], children: list | None = None) -> dict:
    return {"id": nid, "level": level, "text": text, "embedding": emb, "children": children or []}


async def _build_level(texts: list[str], embs: list[list[float]], level: int) -> list[dict]:
    """一层：聚类 → 簇生成摘要节点（并行，2026-08-21 加速）或叶子。返回该层节点列表。

    加速：同层簇摘要 asyncio.gather 并行（信号量限并发 3 防 429），子树递归也随簇并行——
    总时长从"所有簇串联×35s"降为"最深路径×35s"（86 块建树 15 分钟 → 预期 3-5 分钟）。
    单簇摘要失败降级原文透传（不中断整棵树）。
    """
    global _LLM_SEM
    if _LLM_SEM is None:
        _LLM_SEM = asyncio.Semaphore(MAX_LLM_CONCURRENCY)
    arr = np.asarray(embs, dtype=np.float32)
    clusters = _greedy_cluster(arr)

    async def _process(idx: int, idxs: list[int]) -> dict:
        members_text = [texts[i] for i in idxs]
        if len(idxs) == 1 or level >= MAX_LEVEL:
            # 叶子（原文块）——level 0 为原文；上层单成员簇直接透传摘要文本
            return _node(uuid.uuid4().hex[:8], level, members_text[0], embs[idxs[0]])
        cluster_text = "\n".join(members_text)[:CLUSTER_CHARS]
        async with _LLM_SEM:
            try:
                summ = await _cluster_summary(cluster_text, f"L{level}-c{idx}")
                summary_text = f"{summ.get('summary', '')}\n（原文关键句）\n" + "\n".join(summ.get("quotes", []))
                print(f"[raptor] L{level}-c{idx} 摘要完成（{len(idxs)} 块成员）", flush=True)
            except Exception as e:
                # 单簇摘要失败 → 降级原文透传（树继续，不中断整棵）——止损挂账哲学
                # （2026-08-21 培根建树事故：裸 _cluster_summary 无容错，一次 LLM 失败中断整棵树）
                print(f"[raptor] L{level}-c{idx} 摘要失败，降级原文透传: {str(e)[:60]}", flush=True)
                summary_text = members_text[0][:500]
        children = await _build_level(members_text, [embs[i] for i in idxs], level + 1)
        emb = arr[idxs].mean(axis=0).tolist()
        return _node(uuid.uuid4().hex[:8], level, summary_text, emb, children)

    return await asyncio.gather(*[_process(i, idxs) for i, idxs in enumerate(clusters)])


async def build_tree(raw_text: str, sage_id: str, title: str = "") -> dict:
    """建树并落盘 data/council_trees/<sage_id>.json，返回树根。"""
    from app.council.distill_core import extract_book, chunk_text

    body = extract_book(raw_text)
    texts = chunk_text(body)
    print(f"[raptor] {sage_id}：{len(texts)} 块 → 嵌入中（Ollama bge-m3 GPU）", flush=True)
    # embed 走 Ollama 服务（方案 D，2026-08-21）：单一 GPU 实例，单 CUDA context 根治并发 OOM。
    # 原 08-19 定案"CPU 防抢显存"已过时（详见模块 docstring）。
    embs: list[list[float]] = []
    for i in range(0, len(texts), 20):
        embs.extend(await _cpu_embed(texts[i : i + 20]))
        print(f"[raptor] {sage_id}：嵌入 {min(i + 20, len(texts))}/{len(texts)} 块", flush=True)
    print(f"[raptor] {sage_id}：嵌入完成，开始递归聚类摘要", flush=True)
    roots = await _build_level(texts, embs, 0)
    tree = {"sage_id": sage_id, "title": title, "chunks": len(texts), "roots": roots,
            "built_at": __import__("datetime").datetime.now().isoformat(timespec="seconds")}
    TREES_DIR.mkdir(parents=True, exist_ok=True)
    (TREES_DIR / f"{sage_id}.json").write_text(json.dumps(tree, ensure_ascii=False), encoding="utf-8")
    print(f"[raptor] {sage_id}：树已落盘（根节点 {len(roots)} 个，chunks {len(texts)}）", flush=True)
    return tree


def _flatten_nodes(node: dict, acc: list[dict]) -> None:
    if node["level"] > 0:  # 检索只针对摘要节点（叶子原文块不进检索池，避免碎片）
        acc.append(node)
    for c in node.get("children", []):
        _flatten_nodes(c, acc)


def load_tree(sage_id: str) -> dict | None:
    p = TREES_DIR / f"{sage_id}.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


async def query_tree(question: str, sage_id: str, top_k: int = 3) -> list[dict]:
    """检索星宿的树：问题向量 vs 全部摘要节点 → top-k 节点（含路径摘要文本，供引用）。"""
    tree = load_tree(sage_id)
    if not tree:
        return []
    nodes: list[dict] = []
    for r in tree["roots"]:
        _flatten_nodes(r, nodes)
    if not nodes:
        return []
    qemb = np.asarray((await _cpu_embed([question]))[0], dtype=np.float32)
    scored = []
    for n in nodes:
        s = float(np.dot(qemb, np.asarray(n["embedding"], dtype=np.float32)))
        scored.append((s, n))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [{"score": round(s, 3), "level": n["level"], "text": n["text"][:500]} for s, n in scored[:top_k]]


async def _main() -> None:
    """CLI：python -m app.council.raptor --text <书文本> --id <sage_id> [--title 书名]"""
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--text", required=True)
    ap.add_argument("--id", required=True)
    ap.add_argument("--title", default="")
    args = ap.parse_args()
    raw = Path(args.text).read_text(encoding="utf-8", errors="ignore")
    await build_tree(raw, args.id, args.title)


if __name__ == "__main__":
    asyncio.run(_main())
