"""M2 记忆向量层：Ollama bge-m3 服务化（方案 D，2026-08-21）+ chromadb 索引（cosine space）
设计依据：research/2026-08-10-m2-memory-retrieval-details.md
- chromadb space 默认 l2，bge-m3 必须显式 cosine（否则距离无意义）
- cosine 空间下 distance = 1 - cosine_sim（embedding 归一化后 = 1 - dot）
- 服务化背景：本地多进程加载 bge-m3 各持 CUDA context 抢 8GB 显存 → OOM/TDR 卡死；
  Ollama serve 单一 GPU 实例（bge-m3 Q8_0，ModelScope 导入，OLLAMA_MODELS=<ollama-models-dir>）
  → 单 CUDA context 根治并发；R2 验证（exp_ollama_vs_local）：与本地 PyTorch 版 cosine 0.9997 一致
- 降级策略（B+C）：Ollama 挂 → embed 熔断 10s → 上层返回"检索暂不可用"（对话不阻断，画像/状态轮常驻）
"""

import hashlib
import json
import math
import os
import re
import time
import urllib.request
from pathlib import Path
from app.auth_core import get_current_user_id
from app.config import DATA_DIR
from app.user_data import get_user_data_dir

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CHROMA_DIR = DATA_DIR / "data" / "vector_mem"  # legacy（未登录/未迁移兜底）
COLLECTION = "memory"

# Ollama bge-m3 服务端点（docs.ollama.com/api/embed：input 支持 string[] 批量）
OLLAMA_URL = "http://127.0.0.1:11434/api/embed"
OLLAMA_MODEL = "bge-m3"
OLLAMA_TIMEOUT = 60
# 请求级 keep_alive（2026-08-25 工程化补齐，消 4.15s 冷启动）：Ollama 默认 5min 空闲卸载模型，
# 每次请求后驻留 30m——GPU 仅 ~1.3GB/8GB，驻留几乎免费；服务级已在看门狗 env 双保险
OLLAMA_KEEP_ALIVE = "30m"
# 熔断：Ollama 连续失败后短路 10s（防每次等 HTTP 超时），成功自动清零
OLLAMA_CIRCUIT_SECONDS = 10

# ---- 向量维度护栏（2026-08-30）----
#
# 病灶：chroma collection 的维度在**第一次写入时锁定**（实测 1.5.9：delete 掉全部记录后
# 维度仍是旧值，只有 delete_collection 重建才解锁），而本模块建库时从不声明维度。
# 于是用户换 embedding 模型（bge-m3 1024 → 别的维度）后，每次 upsert 都抛 chroma 的裸错：
#   InvalidArgumentError: Collection expecting embedding with dimension of 1024, got 768
# 上层（store.remember / lifecycle）catch 的是 OllamaUnavailableError，接不住它；
# 更底层的兜底 except 会把它吞掉 → **向量记忆整体静默失效**，且报错里没有"该重建索引"这层归因。
#
# 对策（三道，缺一不可）：
#   ① 建库/首写时把维度写进 collection metadata（DIM_KEY）——维度由首次写入锁定，记录同语义
#   ② 开库校验：记录维度 vs 当前模型期望维度，不符 → EmbeddingDimensionMismatch（换模型当场炸）
#   ③ 写入/检索校验：向量长度 vs 记录维度，不符 → 同上。③不依赖"期望维度已知"，
#      所以维度表没登记的新模型也拦得住——它是最后一道网
#   另加安全网：chroma 抛出的裸维度错一律翻译成 EmbeddingDimensionMismatch
#      （覆盖"记录值与事实不符"的情形，例如护栏上线前就换过模型）
#
# 恢复路径：reset_collection()（删 collection，维度锁的唯一解锁方式）+ rebuild_index()
# （从 user_memory.md 全量重灌）。索引是派生数据，user_memory.md 才是权威。

DIM_KEY = "shiguang:embed_dim"

# 已知 embedding 模型的输出维度。换模型时先查这张表；表外模型 → expected_dim() 返回 None
# → 开库校验跳过（保留 Ollama 不可用时的降级路径），写入校验（③）仍然生效。
# 只登记能确证的模型（维度随变体变的，如 snowflake-arctic-embed 各尺寸 768/1024 不一，不登记）。
MODEL_EMBED_DIMS = {
    "bge-m3": 1024,
    "bge-large": 1024,
    "mxbai-embed-large": 1024,
    "nomic-embed-text": 768,
}

# chroma 维度报错原文形如 "Collection expecting embedding with dimension of 1024, got 4"
_DIM_MSG_RE = re.compile(r"dimension of (\d+), got (\d+)")


class EmbeddingDimensionMismatch(RuntimeError):
    """向量索引维度与当前 embedding 模型不匹配——换模型后必须重建索引。

    刻意**不**继承 OllamaUnavailableError：后者是"暂时不可用、稍后自动恢复"的降级信号，
    上层会静默兜底；维度不匹配不会自愈，静默兜底 = 向量记忆永久失效。必须响亮地失败。
    """

    def __init__(
        self,
        collection_dim: int,
        model_dim: int,
        path: str = "",
        where: str = "",
        cause: str = "",
    ):
        self.collection_dim = int(collection_dim)
        self.model_dim = int(model_dim)
        self.path = str(path)
        self.where = where
        self.cause = cause
        super().__init__(self._render())

    def _render(self) -> str:
        head = (
            f"向量索引维度不匹配（{self.where}）：collection={COLLECTION} 现有维度 "
            f"{self.collection_dim}，当前模型 {OLLAMA_MODEL} 维度 {self.model_dim}"
        )
        if self.cause:
            head += f"（chroma 原文：{self.cause}）"
        return (
            f"{head}\n"
            f"  索引目录：{self.path or '(未知)'}\n"
            f"  后果：重建索引之前，向量写入与语义检索**全部失败**。记忆文件（user_memory.md）没丢，"
            f"但语义检索整体不可用——这是换 embedding 模型后的必然后果，不是临时故障。\n"
            f"  代价：{_rebuild_cost()}\n"
            f"  恢复：await app.memory.vector.rebuild_index()  "
            f"（删掉 collection={COLLECTION} 后从 user_memory.md 全量重灌；索引可重建，文件不动）"
        )


def _rebuild_cost() -> str:
    """重建代价：需重新 embed 的记忆条数。算不出来就给定性描述——算代价绝不能抛错。"""
    try:
        from app.memory.store import read_entries

        n = len(read_entries())
    except Exception:
        return "全量记忆需重新 embed（条数读取失败，不影响下面的恢复步骤）"
    return f"{n} 条记忆需重新 embed（bge-m3 走 Ollama 批量接口，百条秒级、千条分钟级）"


def expected_dim() -> int | None:
    """当前 embedding 模型应当产出的维度。

    优先级：env SHIGUANG_EMBED_DIM（换模型/自托管端点时显式覆盖）> MODEL_EMBED_DIMS 表。
    返回 None = 该模型未登记 → 开库校验跳过，写入校验（③）兜底。

    刻意**不发 embed 探针量维度**：那会让"Ollama 在不在"改变代码路径，
    正是 2026-08-30 要根治的"依赖没起反而把套件洗绿"那类病——护栏必须与依赖状态无关。
    """
    raw = os.environ.get("SHIGUANG_EMBED_DIM")
    if raw:
        try:
            d = int(raw)
        except ValueError:
            d = 0
        if d > 0:
            return d
    return MODEL_EMBED_DIMS.get(OLLAMA_MODEL)


def _vector_dir(uid: str | None) -> str:
    """collection 落盘目录（报错信息里要给得出路径，否则用户无从下手）"""
    return str(get_user_data_dir(uid) / "vector_mem") if uid else str(CHROMA_DIR)


def _recorded_dim(coll):
    """collection metadata 里登记的维度；无/损坏 → None"""
    try:
        v = (coll.metadata or {}).get(DIM_KEY)
        return int(v) if v is not None else None
    except Exception:
        return None


def _record_dim(coll, dim: int) -> None:
    """把维度写进 collection metadata。

    坑（1.5.9 实测）：modify() 会**整体替换** metadata，且禁止携带 hnsw:space
    （带了就抛 "Changing the distance function ... not supported"）。所以先合并再剔除 space。
    已实测 space 存在 configuration 里，metadata 里没有它也不会退化成 l2。
    """
    meta = dict(coll.metadata or {})
    meta.pop("hnsw:space", None)
    meta[DIM_KEY] = int(dim)
    coll.modify(metadata=meta)


def _guard_collection_dim(coll, path: str) -> None:
    """护栏②：开库即校验——记录维度 vs 当前模型期望维度。"""
    rec = _recorded_dim(coll)
    exp = expected_dim()
    if rec is not None and exp is not None and rec != exp:
        raise EmbeddingDimensionMismatch(rec, exp, path=path, where="开库校验")


def _check_dim(coll, embedding, path: str, where: str, *, record: bool = False) -> None:
    """护栏③：写入/检索向量长度 vs 记录维度。

    record=True 仅用于写入路径：记录缺失时按首写维度登记（与 chroma"维度由首写锁定"同语义）。
    检索路径不登记——拿一条查询向量去给空索引定维度是错的。
    """
    rec = _recorded_dim(coll)
    dim = len(embedding)
    if rec is None:
        if record:
            _record_dim(coll, dim)
        return
    if rec != dim:
        raise EmbeddingDimensionMismatch(rec, dim, path=path, where=where)


def _reraise_dim(e: Exception, path: str) -> None:
    """安全网：把 chroma 的裸维度错翻译成可归因错误；非维度错原样放过（由调用方 raise）。"""
    m = _DIM_MSG_RE.search(str(e))
    if m:
        raise EmbeddingDimensionMismatch(
            int(m.group(1)), int(m.group(2)), path=path, where="chroma 拒绝", cause=str(e)
        ) from e


# 去重护栏阈值（护栏=提供信息，不是替模型做决定）：
# 0.97 = 硬拒（近字面重复）；0.85~0.97 = 写穿 + 警告交模型判断；<0.85 正常写
DEDUP_HARD = 0.97
DEDUP_SOFT = 0.85

_clients: dict = {}  # uid -> (client, collection)；None 键=legacy 全局
_circuit_until = 0.0


class OllamaUnavailableError(RuntimeError):
    """Ollama 服务不可用（降级信号：上层捕获后返回提示，不阻断对话）"""


def _get_collection(uid: str | None = None):
    """按用户取 chroma collection（2026-08-28 P0 隔离：每用户独立目录 data/users/<uid>/vector_mem）"""
    if not uid:
        uid = get_current_user_id()
    if uid in _clients:
        return _clients[uid][1]
    import chromadb

    path = _vector_dir(uid)
    client = chromadb.PersistentClient(path=path)
    coll = client.get_or_create_collection(COLLECTION, metadata={"hnsw:space": "cosine"})
    _guard_collection_dim(coll, path)  # 护栏②：维度不符当场炸，不留到写入时
    _clients[uid] = (client, coll)
    return coll


def reset_collection(uid: str | None = None) -> int:
    """删掉 collection——维度锁死的**唯一**解锁方式。

    ⚠️ 实测（1.5.9）：delete(全部 id) 之后维度仍是旧值，只有 delete_collection 重建才解锁。
    本函数只删索引，不重灌；调用方随后应该走 rebuild_index()。
    返回被丢弃的条目数（仅供日志/回报）。索引是派生数据，删掉不丢记忆（user_memory.md 才是权威）。
    """
    if not uid:
        uid = get_current_user_id()
    _clients.pop(uid, None)  # 丢弃缓存句柄，否则 Windows 上目录/文件解不开
    import chromadb

    client = chromadb.PersistentClient(path=_vector_dir(uid))
    try:
        dropped = client.get_collection(COLLECTION).count()
        existed = True
    except Exception:
        dropped, existed = 0, False
    try:
        client.delete_collection(COLLECTION)
    except Exception as e:  # 不存在/被占用 → 交给后续 get_or_create 兜底，不吞：打出来
        if existed:
            print(f"[memory/vector] 删 collection 失败（重建可能不彻底）: {e}", flush=True)
    return dropped


async def rebuild_index(uid: str | None = None) -> str:
    """维度不匹配/索引损坏后的重建路径：删 collection → 从 user_memory.md 全量重灌。

    代价：全量重新 embed（bge-m3 走 Ollama 批量接口，百条秒级、千条分钟级）。
    安全闸门：源文件读不出任何条目 → **拒绝重建**。宁可留一个不可用的旧索引，
    也不能把索引删了却无源可灌（那就真没了）。
    """
    from app.memory.store import read_entries

    entries = read_entries()
    if not entries:
        return (
            "重建中止：user_memory.md 读不到任何条目——源文件为空时不删索引"
            "（删了就无源可灌）。请先确认记忆文件路径，或手动处理。"
        )
    if not uid:
        uid = get_current_user_id()  # 先定 uid：否则下面的报错路径可能指向与写入不同的目录
    dropped = reset_collection(uid)
    texts = [e.content for e in entries]
    vecs = await aembed(texts)
    coll = _get_collection(uid)
    # 重建后索引是空的，维度由本次写入重新锁定
    _check_dim(coll, vecs[0], _vector_dir(uid), "重建写入", record=True)
    coll.upsert(
        ids=[entry_id(e.content) for e in entries], documents=texts, embeddings=vecs
    )
    return (
        f"重建完成：丢弃旧索引 {dropped} 条，重灌 {len(entries)} 条，"
        f"维度 {len(vecs[0])}（collection={COLLECTION}）"
    )


def embed(texts: list[str]) -> list[list[float]]:
    """批量编码（Ollama /api/embed，input 传 string[]）。Ollama 挂 → OllamaUnavailableError。"""
    global _circuit_until
    if time.time() < _circuit_until:
        raise OllamaUnavailableError("Ollama 服务熔断中（自动重试）")
    try:
        req = urllib.request.Request(
            OLLAMA_URL,
            data=json.dumps(
                {"model": OLLAMA_MODEL, "input": texts, "keep_alive": OLLAMA_KEEP_ALIVE}
            ).encode(),
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
    coll = _get_collection()
    path = _vector_dir(get_current_user_id())
    _check_dim(coll, embedding, path, "写入校验", record=True)  # 护栏③
    try:
        coll.upsert(ids=[entry_id], documents=[text], embeddings=[embedding])
    except Exception as e:
        _reraise_dim(e, path)  # 安全网：chroma 裸维度错 → 可归因
        raise


def delete(entry_id: str):
    try:
        _get_collection().delete(ids=[entry_id])
    except Exception as _e:
        print(f"[memory/vector] 静默异常已可见化: {_e}", flush=True)


def search(embedding: list[float], top_k: int = 5) -> list[tuple[str, str, float]]:
    """返回 [(id, text, cosine_sim)]，sim 越接近 1 越相似"""
    coll = _get_collection()
    path = _vector_dir(get_current_user_id())
    _check_dim(coll, embedding, path, "检索校验")  # 护栏③（检索不登记维度，空索引除外）
    try:
        res = coll.query(
            query_embeddings=[embedding], n_results=top_k, include=["documents", "distances"]
        )
    except Exception as e:
        _reraise_dim(e, path)
        raise
    ids = res["ids"][0]
    docs = res["documents"][0]
    dists = res["distances"][0]
    return [(i, d, 1.0 - dist) for i, d, dist in zip(ids, docs, dists, strict=True)]


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
        # 用进废退 v2（2026-08-28 Phase1 M-2，FadeMem arXiv:2601.18642）：
        # rec = e^(-days / (S × τ_type))——S=命中强度（1-5，命中越多遗忘越慢），
        # τ_type=类别半衰期（偏好/目标 120 天 → 困惑/笔记 21-30 天，schema.CAT_TAU）。
        # v1（e^(-days/S)）3 天即衰减殆尽导致 rec 因子形同虚设；v2 让"新 vs 旧"与
        # "身份级 vs 事件级"恢复真实区分度（MemoryBank 公式 + FadeMem 类别调制）
        from app.memory.schema import cat_tau

        S = max(1, min(5, int(getattr(e, "strength", 1) or 1)))
        tau = cat_tau(getattr(e, "category", ""))
        rec = math.exp(-days / (S * tau))
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
