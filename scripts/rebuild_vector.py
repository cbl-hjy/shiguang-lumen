"""向量库重建（2026-08-17，写入侧归一工程第二步）：
清 ver=unverified 前缀污染 + 用归一后的 read_entries 全量重建。
安全：执行前已停服务 + 备份 vector_mem/vector_evolve 到 D:/work_buddy/backups/。
"""
import asyncio
import sys

sys.path.insert(0, ".")

from app.memory.store import read_entries  # noqa: E402


async def main():
    from app.memory.vector import _get_collection, aembed, entry_id, upsert

    col = _get_collection()
    before = col.count()
    all_ids = col.get(include=[])["ids"]
    if all_ids:
        col.delete(ids=all_ids)
    print(f"已清空旧 collection（原 {before} 条，含 ver= 前缀污染）")

    entries = read_entries()
    texts = [e.content for e in entries]
    vecs = await aembed(texts)
    for e, v in zip(entries, vecs):
        upsert(entry_id(e.content), e.content, v)
    after = col.count()
    print(f"重建完成: {after} 条（文件条目 {len(entries)} 条）")

    # 验证：无 ver= 前缀残留
    res = col.get(include=["documents"])
    bad = [d for d in res["documents"] if "ver=unverified" in d]
    print(f"ver= 前缀残留: {len(bad)} 条", "✓" if not bad else "✗")


asyncio.run(main())
