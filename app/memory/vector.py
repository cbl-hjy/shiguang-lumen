"""M2 记忆向量层：Ollama bge-m3 服务化（方案 D，2026-08-21）+ chromadb 索引（cosine space）
设计依据：research/2026-08-10-m2-memory-retrieval-details.md
- chromadb space 默认 l2，bge-m3 必须显式 cosine（否则距离无意义）
- cosine 空间下 distance = 1 - cosine_sim（embedding 归一化后 = 1 - dot）
- 服务化背景：本地多进程加载 bge-m3 各持 CUDA context 抢 8GB 显存 → OOM/TDR 卡死；
  Ollama serve 单一 GPU 实例（bge-m3 Q8_0，ModelScope 导入，OLLAMA_MODELS=D:/ollama_models）
  → 单 CUDA context 根治并发；R2 验证（exp_ollama_vs_local）：与本地 PyTorch 版 cosine 0.9997 一致
- 降级策略（B+C）：Ollama 挂 → embed 熔断 10s → 上层返回"检索暂不可用"（对话不阻断，画像/状态轮常驻）
"""
import hashlib
import json
import math
import time
import urllib.request
from pathlib import Path
from app.config import DATA_DIR

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CHROMA_DIR = DATA_DIR / "data" / "vector_mem"
COLLECTION = "memory"

# Ollama bge-m3 服务端点（docs.ollama.com/api/embed：input 支持 string[] 批量）
OLLAMA_URL = "http://127.0.0.1:11434/api/embed"
OLLAMA_MODEL = "bge-m3"
OLLAMA_TIMEOUT = 60
# 熔断：Ollama 连续失败后短路 10s（防每次等 HTTP 超时），成功自动清零
OLLAMA_CIRCUIT_SECONDS = 10

# 去重护栏阈值（护栏=提供信息，不是替模型做决定）：
# 0.97 = 硬拒（近字面重复）；0.85~0.97 = 写穿 + 警告交模型判断；<0.85 正常写
DEDUP_HARD = 0.97
DEDUP_SOFT = 0.85

_client = None
_collection = None
_circuit_until = 0.0


class OllamaUnavailableError(RuntimeError):
    """Ollama 服务不可用（降级信号：上层捕获后返回提示，不阻断对话）"""


def _get_collection():
    global _client, _collection
    if _collection is None:
        import chromadb

        _client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        _collection = _client.get_or_create_collection(
            COLLECTION, metadata={"hnsw:space": "cosine"}
        )
    return _collection


def embed(texts: list[str]) -> list[list[float]]:
    """批量编码（Ollama /api/embed，input 传 string[]）。Ollama 挂 → OllamaUnavailableError。"""
    global _circuit_until
    if time.time() < _circuit_until:
        raise OllamaUnavailableError("Ollama 服务熔断中（自动重试）")
    try:
        req = urllib.request.Request(
            OLLAMA_URL,
            data=json.dumps({"model": OLLAMA_MODEL, "input": texts}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=OLLAMA_TIMEOUT) as r:
            d = json.loads(r.read())
        _circuit_until = 0.0  # 成功清零
        return d["embeddings"]
    except OllamaUnavailableError:
        raise
    except Exception as e:
        _circuit_until = time.time() + OLLAMA_CIRCUIT_SECONDS
        raise OllamaUnavailableError(f"Ollama 服务不可用: {str(e)[:80]}") from e


# 异步版：embed 丢专用单线程池（SentenceTransformer 非线程安全——必须 max_workers=1，
# 默认线程池并发会踩内存墙；同步调用阻塞事件循环是 8-12 remember 卡 250s 的直接因）
import asyncio
from concurrent.futures import ThreadPoolExecutor

_EMBED_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="embed")


async def aembed(texts: list[str]) -> list[list[float]]:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_EMBED_EXECUTOR, embed, texts)


def entry_id(content: str) -> str:
    return hashlib.sha1(content.encode("utf-8")).hexdigest()[:16]


def upsert(entry_id: str, text: str, embedding: list[float]):
    _get_collection().upsert(ids=[entry_id], documents=[text], embeddings=[embedding])


def delete(entry_id: str):
    try:
        _get_collection().delete(ids=[entry_id])
    except Exception:
        pass


def search(embedding: list[float], top_k: int = 5) -> list[tuple[str, str, float]]:
    """返回 [(id, text, cosine_sim)]，sim 越接近 1 越相似"""
    res = _get_collection().query(query_embeddings=[embedding], n_results=top_k, include=["documents", "distances"])
    ids = res["ids"][0]
    docs = res["documents"][0]
    dists = res["distances"][0]
    return [(i, d, 1.0 - dist) for i, d, dist in zip(ids, docs, dists)]


def search_ranked(
    embedding: list[float],
    top_k: int = 3,
    entries: list | None = None,
    weights: tuple[float, float, float] = (0.7, 0.15, 0.15),
    category: str | None = None,
) -> list[tuple[str, str, float]]:
    """三因子排序检索（实验验证 2026-08-17：rel0.7+imp0.15+rec0.15 最优，imp 权重 0.3 会喧宾夺主）。

    - 候选池 = 向量 top(max(top_k*4, 12))，再按 相似度/重要度/新鲜度 加权重排取 top_k
    - entries: list[MemoryEntry]，提供 importance 与 created_at；缺省/无匹配时该条仅按相似度（weights[0]）
    - category: 限定类别（如"学习记录"/"进度"）——实验 C 实证（2026-08-17）：困惑类条目
      （imp 高+日期新）会串扰学习类查询，需维度隔离；过滤在 Python 层做（先取更大池防过滤后不足）
    - 纯相似度路径（search/find_similar）不受影响——去重探测保持确定性不变量
    """
    import re
    from datetime import date

    from app.memory.schema import normalize_category

    want = normalize_category(category) if category else None

    if category:
        pool = search(embedding, top_k=max(top_k * 8, 24))  # 过滤后可能不足，池子加大
    else:
        pool = search(embedding, top_k=max(top_k * 4, 12))
    if not pool or not entries:
        return pool[:top_k]
    by_id = {e.entry_id: e for e in entries if e.entry_id}
    by_text = {e.content: e for e in entries}
    today = date.today()
    scored = []
    for eid, text, sim in pool:
        e = by_id.get(eid) or by_text.get(text)
        if e is None:
            if want:
                # 无条目对象：从文本解析 cat=（9 字段行格式），不匹配则跳过
                m = re.search(r"cat=([^|]+)", text)
                if not m or normalize_category(m.group(1).strip()) != want:
                    continue
            scored.append((eid, text, weights[0] * sim))
            continue
        if want and e.category != want:
            continue
        imp_norm = min(1.0, max(0.0, e.importance / 10))
        try:
            days = max(0, (today - date.fromisoformat(e.created_at)).days)
        except Exception:
            days = 0
        # 用进废退（2026-08-18 补洞）：rec = e^(-days/S)（MemoryBank arXiv:2305.10250），
        # S=命中强度（1-5，schema.strength），S 越大遗忘越慢——被用过的记忆比冷门记忆衰减慢数倍
        S = max(1, min(5, int(getattr(e, "strength", 1) or 1)))
        rec = math.exp(-days / S)
        score = weights[0] * sim + weights[1] * imp_norm + weights[2] * rec
        scored.append((eid, text, score))
    scored.sort(key=lambda x: x[2], reverse=True)
    return scored[:top_k]


def count() -> int:
    return _get_collection().count()


def existing_ids() -> set[str]:
    return set(_get_collection().get(include=[])["ids"])


def find_similar(content: str, top_k: int = 1) -> list[tuple[str, str, float]]:
    """写入前去重探测：返回最相似的现有记忆"""
    vec = embed([content])[0]
    return search(vec, top_k)
