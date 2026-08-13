"""M2 记忆向量层：bge-m3 嵌入（懒加载 GPU）+ chromadb 索引（cosine space）
设计依据：research/2026-08-10-m2-memory-retrieval-details.md
- chromadb space 默认 l2，bge-m3 必须显式 cosine（否则距离无意义）
- cosine 空间下 distance = 1 - cosine_sim（embedding 归一化后 = 1 - dot）
"""
import hashlib
from pathlib import Path
from app.config import DATA_DIR

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CHROMA_DIR = DATA_DIR / "data" / "vector_mem"
COLLECTION = "memory"
# bge-m3 模型路径：优先 .env 的 BGE_M3_PATH（可指向本地快照）；未设置则用 HF 默认缓存（首次自动下载）
from app.config import ENV

BGE_M3_PATH = ENV.get("BGE_M3_PATH") or "BAAI/bge-m3"

# 去重护栏阈值（护栏=提供信息，不是替模型做决定）：
# 0.97 = 硬拒（近字面重复）；0.85~0.97 = 写穿 + 警告交模型判断；<0.85 正常写
DEDUP_HARD = 0.97
DEDUP_SOFT = 0.85

_embed_model = None
_client = None
_collection = None


def _get_embed_model():
    global _embed_model
    if _embed_model is None:
        from sentence_transformers import SentenceTransformer
        import torch

        device = "cuda" if torch.cuda.is_available() else "cpu"
        _embed_model = SentenceTransformer(BGE_M3_PATH, device=device)
    return _embed_model


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
    vecs = _get_embed_model().encode(texts, normalize_embeddings=True)
    return [v.tolist() for v in vecs]


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


def count() -> int:
    return _get_collection().count()


def existing_ids() -> set[str]:
    return set(_get_collection().get(include=[])["ids"])


def find_similar(content: str, top_k: int = 1) -> list[tuple[str, str, float]]:
    """写入前去重探测：返回最相似的现有记忆"""
    vec = embed([content])[0]
    return search(vec, top_k)
