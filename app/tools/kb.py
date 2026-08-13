"""个人知识库：LlamaIndex + bge-m3(GPU) + chromadb + DeepSeek（POC5 已验证）
分工：知识库=用户积累的外部资料/笔记；记忆=用户自身状态（chromadb 在 memory 层）
"""
import os
from pathlib import Path
from app.config import DATA_DIR

os.environ.setdefault("HF_HOME", str(Path(__file__).resolve().parent.parent.parent / ".cache" / "huggingface"))
os.environ.setdefault("HF_HUB_CACHE", str(Path(__file__).resolve().parent.parent.parent / ".cache" / "huggingface" / "hub"))

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
    import asyncio
    from concurrent.futures import ThreadPoolExecutor

    if not text.strip():
        return "(内容为空)"
    loop = asyncio.get_running_loop()
    with ThreadPoolExecutor(max_workers=1) as ex:
        return await loop.run_in_executor(ex, _kb_ingest_sync, text, source)


def _kb_ingest_sync(text: str, source: str) -> str:
    """同步实现：落盘 + 入向量索引（GPU 加载/embedding 重阻塞，由 async 包装丢 executor）"""
    text = text.strip()
    if not text:
        return "(内容为空)"
    from llama_index.core import Document
    from llama_index.core.ingestion import IngestionPipeline
    from llama_index.core.node_parser import SentenceSplitter
    from llama_index.vector_stores.chroma import ChromaVectorStore
    import chromadb

    KB_DIR.mkdir(parents=True, exist_ok=True)
    # 先初始化 Settings（embed_model/llm），from_documents 依赖
    _get_engine()
    # 文件持久化一份（人可审）——路径存入 metadata，供"命中后精读原文"
    safe = "".join(c for c in source if c.isalnum() or c in "-_")[:40] or "doc"
    doc_file = KB_DIR / f"{safe}_{abs(hash(text)) % 10000}.md"
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
        return "(入库失败：没有生成节点)"
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
        return f"(入库失败: {e})"
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
    import asyncio
    from concurrent.futures import ThreadPoolExecutor

    q = query.strip()
    if not q:
        return "(查询为空)"
    try:
        # query_engine.query 是重阻塞（GPU embedding + LLM 生成答案）——丢专用 executor，避免堵事件循环
        engine = _get_engine()
        loop = asyncio.get_running_loop()
        with ThreadPoolExecutor(max_workers=1) as ex:
            resp = await loop.run_in_executor(ex, engine.query, q)
    except Exception as e:
        return f"(知识库检索失败: {e})"
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
