"""实验：猜想2——链接能否补向量检索盲区（对照组实验）
核心假设：向量检索按"语义字面相似"召回，会漏掉"字面不同但强相关"的记忆；
链接能补上这个盲区（检索到 A，沿 A 的链接找到 B）。

对照组 = 纯向量 top-k（现状）
实验组 = 向量 top-k + 沿已判链接扩散一层（A-MEM 式）

只读主库，不写任何文件，直接调向量检索 + 判链。
"""
import asyncio
import sys

sys.path.insert(0, ".")

from pathlib import Path


def load_memories() -> dict[int, str]:
    lines = [
        l for l in Path("memory/user_memory.md").read_text(encoding="utf-8").splitlines()
        if l.startswith("- ")
    ]
    return {i: l.split("|")[-1].strip() for i, l in enumerate(lines, 1)}


async def main():
    mems = load_memories()
    print(f"主库 {len(mems)} 条记忆\n")

    from app.memory.vector import aembed, search

    # 对照组：纯向量检索
    queries = [
        ("交叉熵损失函数怎么算", "期望召回交叉熵簇 + softmax 搭配"),
        ("面试机器学习基础复习什么", "期望召回 LR vs SVM + 梯度下降等面试相关"),
    ]
    for q, expect in queries:
        print(f"=== 查询：{q}（{expect}）===")
        vec = (await aembed([q]))[0]
        hits = search(vec, top_k=6)
        print("【对照组：纯向量 top-6】")
        for i, (_, text, sim) in enumerate(hits, 1):
            # 找回 id
            cid = None
            for k, v in mems.items():
                if v == text:
                    cid = k
                    break
            print(f"  {i}. [{cid}] ({sim:.2f}) {text[:50]}")
        print()


if __name__ == "__main__":
    asyncio.run(main())
