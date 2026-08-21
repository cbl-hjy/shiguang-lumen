"""个人知识库：LlamaIndex + bge-m3(GPU) + chromadb + DeepSeek（POC5 已验证）
分工：知识库=用户积累的外部资料/笔记；记忆=用户自身状态（chromadb 在 memory 层）
"""
import os
from pathlib import Path
from app.config import DATA_DIR

os.environ.setdefault("HF_HOME", "D:/work_buddy/.caches/huggingface")
os.environ.setdefault("HF_HUB_CACHE", "D:/work_buddy/.caches/huggingface/hub")

from app.config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL

KB_DIR = DATA_DIR / "data" / "kb"
CHROMA_DIR = KB_DIR / "chroma"
# bge-m3 模型路径：优先 .env 的 BGE_M3_PATH（可指向本地快照）；未设置则用 HF 默认缓存（首次自动下载）
from app.config import ENV

BGE_M3_PATH = ENV.get("BGE_M3_PATH") or "BAAI/bge-m3"

_engine = None


def _get_engine():
    """懒加载（首次调用才加载 bge-m3 GPU + 建索引）"""
    global _engine
    if _engine is not None:
        return _engine
    from llama_index.core import Settings, VectorStoreIndex
    from llama_index.core.node_parser import SentenceSplitter
    from llama_index.embeddings.huggingface import HuggingFaceEmbedding
    from llama_index.llms.openai_like import OpenAILike
    from llama_index.vector_stores.chroma import ChromaVectorStore
    import chromadb

    Settings.embed_model = HuggingFaceEmbedding(model_name=BGE_M3_PATH, device="cuda")
    Settings.llm = OpenAILike(
        model=DEEPSEEK_MODEL,
        api_key=DEEPSEEK_API_KEY,
        api_base=DEEPSEEK_BASE_URL,
        is_chat_model=True,
        context_window=128000,
    )
    chroma_client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    collection = chroma_client.get_or_create_collection("kb_main")
    vector_store = ChromaVectorStore(chroma_collection=collection)
    _engine = VectorStoreIndex.from_vector_store(vector_store).as_query_engine(
        similarity_top_k=3
    )
    return _engine


async def kb_ingest(text: str, source: str = "用户资料") -> str:
    """把一段资料/笔记加入个人知识库（落盘一份 + 入向量索引）。重阻塞（GPU embedding + chromadb）丢专用 executor"""
    from app.tools.errors import arg_error, timeout_error

    import asyncio
    from concurrent.futures import ThreadPoolExecutor

    if not text.strip():
        return arg_error("知识库入库", "内容为空")
    loop = asyncio.get_running_loop()
    with ThreadPoolExecutor(max_workers=1) as ex:
        # 超时护栏（2026-08-17）：嵌入+索引可能慢，120s 上限
        try:
            return await asyncio.wait_for(
                loop.run_in_executor(ex, _kb_ingest_sync, text, source), timeout=120
            )
        except asyncio.TimeoutError:
            return timeout_error("知识库入库", "超时 >120s")


def _kb_ingest_sync(text: str, source: str) -> str:
    """同步实现：落盘 + 入向量索引（GPU 加载/embedding 重阻塞，由 async 包装丢 executor）"""
    text = text.strip()
    if not text:
        return "(内容为空)"
    import hashlib

    from llama_index.core import Document
    from llama_index.core.ingestion import IngestionPipeline
    from llama_index.core.node_parser import SentenceSplitter
    from llama_index.vector_stores.chroma import ChromaVectorStore
    import chromadb

    KB_DIR.mkdir(parents=True, exist_ok=True)
    # 先初始化 Settings（embed_model/llm），from_documents 依赖
    _get_engine()
    # 文件持久化一份（人可审）——路径存入 metadata，供"命中后精读原文"
    # 文件名=source 清洗 + 内容 md5 前 8 位（确定性——修复 2026-08-20：原 hash(text) 受
    # PYTHONHASHSEED 随机化影响，同一内容每次进程生成不同文件名 → 重复入库产生多份文件）
    safe = "".join(c for c in source if c.isalnum() or c in "-_")[:40] or "doc"
    digest = hashlib.md5(text.encode("utf-8")).hexdigest()[:8]
    doc_file = KB_DIR / f"{safe}_{digest}.md"
    if not doc_file.exists():
        doc_file.write_text(f"# {source}\n\n{text}\n", encoding="utf-8")
    chroma_client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    collection = chroma_client.get_or_create_collection("kb_main")
    vector_store = ChromaVectorStore(chroma_collection=collection)
    # IngestionPipeline.run 只做切分返回 nodes（不自动嵌入/落库，0.14 实测），需手动嵌入 + add
    pipeline = IngestionPipeline(
        transformations=[SentenceSplitter(chunk_size=200, chunk_overlap=20)]
    )
    nodes = pipeline.run(
        documents=[
            Document(text=text, metadata={"source": source, "file_path": str(doc_file)})
        ]
    )
    if not nodes:
        return tool_err("知识库入库", "没有生成节点")
    try:
        from llama_index.core import Settings

        embed_model = Settings.embed_model
        embeddings = embed_model.get_text_embedding_batch(
            [n.get_content(metadata_mode="none") for n in nodes]
        )
        for n, emb in zip(nodes, embeddings):
            n.embedding = emb
        vector_store.add(nodes)
    except Exception as e:
        return tool_err("知识库入库", str(e))
    return f"已加入知识库（{len(text)} 字符，来源 {source}）"


def _read_original_context(file_path: str, probe: str, window: int = 600) -> str:
    """精读：定位切片在源文件中的位置，返回上下文窗口（±600 字符）"""
    try:
        text = Path(file_path).read_text(encoding="utf-8")
    except Exception:
        return ""
    idx = text.find(probe[:50])
    if idx < 0:
        return text[: window * 2]
    start = max(0, idx - window)
    end = min(len(text), idx + window + len(probe))
    return text[start:end]


async def kb_search(query: str, deep: bool = False) -> str:
    """检索个人知识库并回答（带出处）。deep=True 附原文段落（需完整细节时用）"""
    from app.tools.errors import arg_error, timeout_error, tool_err

    import asyncio
    from concurrent.futures import ThreadPoolExecutor

    q = query.strip()
    if not q:
        return arg_error("知识库", "查询为空")
    try:
        # query_engine.query 是重阻塞（GPU embedding + LLM 生成答案）——丢专用 executor，避免堵事件循环
        engine = _get_engine()
        loop = asyncio.get_running_loop()
        with ThreadPoolExecutor(max_workers=1) as ex:
            # 超时护栏（2026-08-17）：LLM 生成最易慢/卡——60s 上限，超时返回提示而非干等
            resp = await asyncio.wait_for(
                loop.run_in_executor(ex, engine.query, q), timeout=60
            )
    except asyncio.TimeoutError:
        return timeout_error("知识库", "检索超时 >60s")
    except Exception as e:
        return tool_err("知识库", str(e))
    cites = []
    originals = []
    for i, n in enumerate(resp.source_nodes, 1):
        meta = getattr(n.node, "metadata", {}) or {}
        cites.append(f"  [{i}] {meta.get('source', '?')}: {n.node.text[:50]}…")
        if deep:
            fp = meta.get("file_path", "")
            if fp and Path(fp).exists():
                ctx = _read_original_context(fp, n.node.text)
                if ctx:
                    originals.append(f"  [{i}] {ctx[:800]}")
    out = f"{str(resp.response)[:800]}\n引用:\n" + "\n".join(cites)
    if originals:
        out += "\n\n原文段落（精读）:\n" + "\n\n".join(originals)
    return out


def kb_reindex() -> str:
    """从源文件重建索引（源文件是权威，索引可重建——删库/索引损坏后调用）。返回重建统计。"""
    files = sorted(KB_DIR.glob("*.md"))
    if not files:
        return "(没有源文件可重建)"
    from llama_index.core import Document, Settings
    from llama_index.core.ingestion import IngestionPipeline
    from llama_index.core.node_parser import SentenceSplitter
    from llama_index.vector_stores.chroma import ChromaVectorStore
    import chromadb

    _get_engine()  # 初始化 Settings（embed_model/llm）
    chroma_client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    collection = chroma_client.get_or_create_collection("kb_main")
    old = collection.get(include=[])["ids"]
    if old:
        collection.delete(ids=old)  # 重建语义：清空旧索引
    pipeline = IngestionPipeline(
        transformations=[SentenceSplitter(chunk_size=200, chunk_overlap=20)]
    )
    embed_model = Settings.embed_model
    total_nodes = 0
    total_files = 0
    for f in files:
        try:
            raw = f.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            raw = f.read_text(encoding="gbk", errors="replace")  # 历史 GBK 文件兜底
        text = raw.strip()
        source = f.stem.split("_")[0] or "用户资料"
        if text.startswith("#"):
            lines = text.split("\n", 1)
            source = lines[0].lstrip("# ").strip() or source
            text = lines[1].strip() if len(lines) > 1 else ""
        if not text:
            continue
        nodes = pipeline.run(
            documents=[
                Document(text=text, metadata={"source": source, "file_path": str(f)})
            ]
        )
        if not nodes:
            continue
        embeddings = embed_model.get_text_embedding_batch(
            [n.get_content(metadata_mode="none") for n in nodes]
        )
        for n, emb in zip(nodes, embeddings):
            n.embedding = emb
        ChromaVectorStore(chroma_collection=collection).add(nodes)
        total_nodes += len(nodes)
        total_files += 1
    return f"已从 {total_files} 个源文件重建索引（{total_nodes} 个切片）"


# ===== 知识库文档治理权（2026-08-20 最小落地清单⑤：可见/可删/可撤销/可改名）=====

TRASH_DIR = KB_DIR / "trash"


def _doc_title(raw: str) -> str:
    """标题真相源=文件首行 # 标题（kb_reindex 同口径）"""
    first = raw.split("\n", 1)[0].strip()
    if first.startswith("#"):
        return first.lstrip("# ").strip()
    return first[:40]


def kb_list_documents() -> list[dict]:
    """文档列表（治理权#可见）：标题/大小/修改时间/向量切片数（chroma where file_path 精确统计）"""
    docs = []
    try:
        import chromadb

        chroma_client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        collection = chroma_client.get_or_create_collection("kb_main")
    except Exception:
        collection = None
    for p in sorted(KB_DIR.glob("*.md")):
        try:
            raw = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            raw = p.read_text(encoding="gbk", errors="replace")
        count = 0
        if collection is not None:
            try:
                count = len(collection.get(where={"file_path": str(p)}, include=[])["ids"])
            except Exception:
                count = 0
        docs.append(
            {
                "id": p.stem,
                "title": _doc_title(raw),
                "size": p.stat().st_size,
                "mtime": p.stat().st_mtime,
                "vectors": count,
            }
        )
    return docs


def kb_delete_document(doc_id: str) -> dict:
    """删除文档（治理权#可删+可撤销）：文件移回收站 trash/（不真删）+ 同步删 chroma 该文档向量。
    关键：向量 metadata.file_path 精确关联，where 过滤删除，防幽灵检索命中。"""
    p = KB_DIR / f"{doc_id}.md"
    if not p.exists():
        return {"ok": False, "msg": f"文档不存在：{doc_id}"}
    TRASH_DIR.mkdir(parents=True, exist_ok=True)
    import shutil

    dest = TRASH_DIR / p.name
    n = 0
    try:
        import chromadb

        chroma_client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        collection = chroma_client.get_or_create_collection("kb_main")
        hits = collection.get(where={"file_path": str(p)}, include=[])["ids"]
        if hits:
            collection.delete(ids=hits)
            n = len(hits)
    except Exception:
        n = -1  # chroma 删除失败——文件照移（索引可重建，源文件是权威）
    shutil.move(str(p), str(dest))
    return {"ok": True, "msg": f"已移入回收站（{p.name}）并清理 {n if n >= 0 else '?'} 个向量切片", "vectors": n}


def kb_rename_document(doc_id: str, new_title: str) -> dict:
    """重命名（治理权#可改）：改文件首行标题 + 同步 chroma metadata.source（检索引用显示新名）"""
    new_title = (new_title or "").strip()
    if not new_title:
        return {"ok": False, "msg": "新标题不能为空"}
    p = KB_DIR / f"{doc_id}.md"
    if not p.exists():
        return {"ok": False, "msg": f"文档不存在：{doc_id}"}
    raw = p.read_text(encoding="utf-8")
    lines = raw.split("\n")
    if lines and lines[0].startswith("#"):
        lines[0] = f"# {new_title}"
    else:
        lines.insert(0, f"# {new_title}")
    p.write_text("\n".join(lines), encoding="utf-8")
    try:
        import chromadb

        chroma_client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        collection = chroma_client.get_or_create_collection("kb_main")
        hits = collection.get(where={"file_path": str(p)}, include=[])["ids"]
        if hits:
            collection.update(
                ids=hits,
                metadatas=[{"source": new_title, "file_path": str(p)}] * len(hits),
            )
    except Exception:
        pass  # chroma 更新失败不阻塞（reindex 会修正 source）
    return {"ok": True, "msg": f"已重命名：{new_title}"}
