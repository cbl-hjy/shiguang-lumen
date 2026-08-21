"""POC5: LlamaIndex 检索链路 —— bge-m3(GPU) 嵌入 + chromadb 向量库 + DeepSeek 生成 + 引用溯源"""
import os
import sys
from pathlib import Path

# 用户铁律：缓存走 D 盘，不碰 C 盘
os.environ.setdefault("HF_HOME", "D:/work_buddy/.caches/huggingface")
os.environ.setdefault("HF_HUB_CACHE", "D:/work_buddy/.caches/huggingface/hub")
os.environ.setdefault("TRANSFORMERS_CACHE", "D:/work_buddy/.caches/huggingface")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from envutil import load_env

env = load_env()

from llama_index.core import Document, Settings, VectorStoreIndex
from llama_index.core.node_parser import SentenceSplitter
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.llms.openai_like import OpenAILike
from llama_index.vector_stores.chroma import ChromaVectorStore
import chromadb

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "poc_chroma"


# 复用旧项目已下载的 bge-m3（HF 缓存快照，完整：config+tokenizer+2.27G 权重）
BGE_M3_PATH = r"D:\work_buddy\2026-07-19-15-17-59\.cache\huggingface\models--BAAI--bge-m3\snapshots\5617a9f61b028005a4858fdac845db406aefb181"


def main():
    print("[1/4] 加载 bge-m3 嵌入（GPU，本地路径）...")
    Settings.embed_model = HuggingFaceEmbedding(model_name=BGE_M3_PATH, device="cuda")
    Settings.llm = OpenAILike(
        model=env["DEEPSEEK_MODEL"],
        api_key=env["DEEPSEEK_API_KEY"],
        api_base=env["DEEPSEEK_BASE_URL"],
        is_chat_model=True,
        context_window=128000,
    )

    print("[2/4] 建索引（3 段学习笔记 -> chromadb）...")
    docs = [
        Document(
            text="梯度下降是一种通过反复调整参数、让损失函数不断下降来找到最优解的优化算法。它沿着损失函数梯度的反方向更新参数，步长叫学习率。",
            metadata={"source": "笔记-机器学习基础", "topic": "梯度下降"},
        ),
        Document(
            text="学习率过大时，梯度下降可能来回震荡甚至发散；学习率过小则收敛极慢。实践中常用学习率衰减或自适应优化器（如 Adam）来平衡。",
            metadata={"source": "笔记-调参经验", "topic": "学习率"},
        ),
        Document(
            text="过拟合指模型在训练数据上表现很好，但对新数据泛化差。缓解方法：增加数据、正则化（L1/L2）、早停、Dropout、交叉验证。",
            metadata={"source": "笔记-泛化", "topic": "过拟合"},
        ),
    ]
    chroma = chromadb.PersistentClient(path=str(DATA_DIR))
    collection = chroma.get_or_create_collection("poc_notes")
    vector_store = ChromaVectorStore(chroma_collection=collection)
    index = VectorStoreIndex.from_documents(
        docs, transformations=[SentenceSplitter(chunk_size=100, chunk_overlap=10)], vector_store=vector_store
    )

    print("[3/4] 检索 + DeepSeek 生成...")
    query_engine = index.as_query_engine(similarity_top_k=2)
    resp = query_engine.query("学习率太大会怎么样？")
    print("回答:", str(resp.response).strip()[:300])
    print("[4/4] 引用溯源:")
    for i, node in enumerate(resp.source_nodes, 1):
        meta = node.node.metadata
        print(f"  [{i}] score={node.score:.3f} | {meta.get('source')} | {node.node.text[:50]}...")

    print("PASS-POC5 LlamaIndex 检索链路 OK（bge-m3 GPU + chromadb + DeepSeek + 引用）")
    return True


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)
