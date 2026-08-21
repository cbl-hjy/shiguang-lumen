"""实验 C：检索质量随记忆量（STATEFRESH-EXPERIMENT-DESIGN.md）
H3：记忆从 43 条模拟扩到 150 条，三因子排序精确率稳定（候选池 top_k*4 假设、recency 不随规模失衡）。

方法：主库 43 条 + 程序化生成 107 条模拟条目（主题/日期/imp 分布真实感）→ 本地 embed 全量
      重跑三查询，对比 43 条 vs 150 条的三因子 top-6 排序质量。
判据：精确率下降 >10% = 三因子参数重调或候选池改造。
"""
import asyncio
import random
import sys
from pathlib import Path

sys.path.insert(0, ".")

ROOT = Path(".")
random.seed(42)

# 模拟条目主题池（贴合真实用户：学习记录为主 + 生活/秋招/杂项混合）
TOPICS = [
    # 机器学习/面试相关（会被查询召回——关键观察对象）
    ("学习记录", "imp=8", "复习逻辑回归与 softmax 的联系，二分类边界直觉已建立"),
    ("学习记录", "imp=7", "今天推导了 MSE 和交叉熵的关系，发现分类任务两者差异很大"),
    ("进度", "imp=7", "学习 SVM 核函数，RBF 的映射直觉卡住了"),
    ("进度", "imp=6", "复习偏差方差权衡，过拟合识别基本掌握"),
    ("学习记录", "imp=6", "看了 Transformer 位置编码，RoPE 和绝对位置编码对比"),
    ("学习记录", "imp=7", "注意力机制 QKV 的维度关系推导完成"),
    ("进度", "imp=6", "RNN/LSTM 复习，梯度消失部分重温"),
    ("学习记录", "imp=5", "学习率调度 warmup 的原理记录"),
    ("学习记录", "imp=6", "BN 和 LN 的区别，NLP 用 LN 的原因"),
    ("进度", "imp=7", "机器学习基础复习：决策树与集成学习"),
    # 秋招/方向相关（易与困惑记忆混淆——观察 cat 混淆）
    ("困惑", "imp=7", "是否该把重心从算法岗转向 AI 应用岗？"),
    ("进度", "imp=6", "整理了秋招投递公司清单，分了三个梯队"),
    ("偏好", "imp=5", "面试复盘喜欢先自己口述再对照标准答案"),
    # 生活/杂项（噪声——观察是否被错误召回）
    ("偏好", "imp=4", "喜欢喝冰美式，写代码时习惯听白噪音"),
    ("进度", "imp=3", "看完了一部纪录片，关于人工智能简史"),
    ("note", "imp=3", "周末和朋友去了图书馆自习"),
]


def _gen_mock_entries(n: int) -> list[tuple[str, str, str]]:
    """生成 n 条模拟条目：(日期, imp, cat, 内容) 的四元组列表"""
    import datetime
    today = datetime.date(2026, 8, 17)
    out = []
    for i in range(n):
        # 日期分布：40% 近 7 天，30% 近 30 天，30% 更旧（防 recency 全高失真）
        r = random.random()
        if r < 0.4:
            days = random.randint(0, 7)
        elif r < 0.7:
            days = random.randint(8, 30)
        else:
            days = random.randint(31, 120)
        d = (today - datetime.timedelta(days=days)).isoformat()
        cat, imp, text = random.choice(TOPICS)
        out.append((d, imp, cat, f"{text}（模拟{i+1}）"))
    return out


async def main():
    import numpy as np
    from app.memory.vector import aembed

    # 读主库 43 条真实记忆
    lines = [l for l in (ROOT / "memory" / "user_memory.md").read_text(encoding="utf-8").splitlines() if l.startswith("- ")]
    import re
    from datetime import date

    def parse(line: str):
        imp_m = re.search(r"imp=(\d+)", line)
        date_m = re.search(r"^\- (\d{4}-\d{2}-\d{2})", line)
        return {
            "content": line.split("|")[-1].strip(),
            "imp": int(imp_m.group(1)) if imp_m else 5,
            "date": date_m.group(1) if date_m else "2026-08-15",
        }

    real = [parse(l) for l in lines]
    print(f"主库真实条目: {len(real)}")

    # 生成模拟条目，凑到 150
    mocks = []
    for d, imp, cat, text in _gen_mock_entries(150 - len(real)):
        mocks.append({"content": text, "imp": int(imp.replace("imp=", "")), "date": d})
    all_entries = real + mocks
    print(f"扩充后总量: {len(all_entries)}")

    # 全量 embed（本地 bge-m3）
    texts = [e["content"] for e in all_entries]
    vecs = np.array(await aembed(texts))

    today = date(2026, 8, 17)
    imp_norm = np.array([e["imp"] / 10 for e in all_entries])
    days = np.array([max(0, (today - date.fromisoformat(e["date"])).days) for e in all_entries])
    recency = 1.0 / (1.0 + days)

    queries = [
        "面试机器学习基础复习什么",
        "我最近在准备什么",
        "交叉熵和 softmax 什么关系",
    ]

    for q in queries:
        qv = np.array((await aembed([q]))[0])
        sims = vecs @ qv
        score = 0.7 * sims + 0.15 * imp_norm + 0.15 * recency
        order = np.argsort(-score)[:6]
        print(f"\n=== 查询：{q}（150 条规模）===")
        for j in order:
            e = all_entries[j]
            tag = "真实" if j < len(real) else "模拟"
            print(f"  [{tag}] imp={e['imp']} {e['date']} s={score[j]:.2f} | {e['content'][:42]}")


asyncio.run(main())
