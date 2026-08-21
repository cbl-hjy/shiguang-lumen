"""判链质量探针（2026-08-17）：测 A-MEM 式"LLM 判链接"能否复现
设计：零风险（只读主库 memory/user_memory.md，不写任何文件，不起服务，直接调 LLM）
     6 条种子记忆 × 候选（相关 + 陷阱不相关混合），测：
       ① 精确率：模型判"该链接"的，有多少真相关
       ② 假阳性率：模型对陷阱（明显不相关）判链接的比例
       ③ 理由质量：模型能否说出链接类型（同主题/因果/时间/同一决策），而非笼统"相似"
判据：精确率 ≥ 70% 且 假阳性率 ≤ 30% → 判链可行；否则搁置或换策略
"""
import asyncio
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, ".")

# 种子记忆（手工标定，含正确答案）：
# 每条种子 = {id, 相关候选id列表, 陷阱候选id列表}
SEEDS = [
    {
        "seed_id": 13, "label": "交叉熵一句话核心",
        "related": [12, 14, 15, 17, 18],   # 同主题交叉熵
        "traps": [2, 37, 39],               # 正则化/拾光设计/深夜哲学
    },
    {
        "seed_id": 36, "label": "学习偏好先直觉后公式",
        "related": [1, 11, 24],             # 同偏好
        "traps": [23, 26, 41],              # LR vs SVM/诊断临时/秋招
    },
    {
        "seed_id": 31, "label": "目标准备算法岗面试",
        "related": [23, 30, 33],            # 面试相关
        "traps": [13, 38, 15],              # 交叉熵/平等搭子/交叉熵直觉
    },
    {
        "seed_id": 42, "label": "秋招目标 AI Agent 方向",
        "related": [41, 43],                # 秋招/简历
        "traps": [2, 39, 5],                # 正则化/深夜哲学/学完正则化
    },
    {
        "seed_id": 38, "label": "期望平等搭子",
        "related": [37, 40],                # 拾光设计/2.0方向
        "traps": [13, 30, 26],              # 交叉熵/面试准备/诊断
    },
    {
        "seed_id": 28, "label": "简历编造被抓",
        "related": [27, 29],                # 面试故事库/简历母本
        "traps": [18, 37, 34],              # softmax/拾光设计/CONC测试
    },
]


def load_memories() -> dict[int, str]:
    """只读主库记忆，返回 {id: content}"""
    lines = [
        l for l in Path("memory/user_memory.md").read_text(encoding="utf-8").splitlines()
        if l.startswith("- ")
    ]
    return {i: l.split("|")[-1].strip() for i, l in enumerate(lines, 1)}


def build_prompt(seed: dict, mems: dict[int, str]) -> str:
    seed_content = mems[seed["seed_id"]]
    candidates = seed["related"] + seed["traps"]
    cand_lines = "\n".join(f"  [{cid}] {mems[cid][:60]}" for cid in candidates)
    return f"""你是一个记忆链接判定器。判断下面这条"种子记忆"和候选记忆之间，是否存在值得建立"链接"的关联。

链接的定义：两条记忆指向同一个主题、同一件事、同一个决策、或存在因果/时间先后/同一来源的关系。链接的意义是"检索到一条时能顺着找到另一条"。

种子记忆：
  {seed_content[:80]}

候选记忆（编号）：
{cand_lines}

要求：
1. 对每条候选，判断是否该与种子建链接
2. 该链接的，给出链接类型（同主题 / 同一决策 / 因果 / 时间先后 / 同一来源）
3. 只有真正有实质关联才链接；仅仅是"都是学习相关内容"这种宽泛关联不算链接

严格按 JSON 输出，不要其他文字：
{{"links": [{{"id": 候选编号, "type": "链接类型", "reason": "一句话理由"}}]}}"""


async def main():
    mems = load_memories()
    print(f"主库记忆 {len(mems)} 条，测试 {len(SEEDS)} 条种子\n")

    from app.agent.model import get_model
    from pydantic_ai import Agent

    model = get_model()
    judge = Agent(model, system_prompt="你是记忆链接判定器，只输出 JSON，不输出其他。")

    results = []
    for seed in SEEDS:
        prompt = build_prompt(seed, mems)
        try:
            r = await judge.run(prompt)
            out = r.output.strip()
        except Exception as e:
            print(f"[{seed['label']}] 调用失败: {e}")
            results.append({"seed": seed, "raw": None, "error": str(e)})
            continue
        # 解析 JSON
        try:
            parsed = json.loads(out)
            links = parsed.get("links", [])
        except Exception:
            # 尝试提取 JSON 片段
            m = re.search(r"\{.*\}", out, re.DOTALL)
            try:
                parsed = json.loads(m.group(0)) if m else {}
                links = parsed.get("links", [])
            except Exception:
                links = []
                out = out[:200]
        results.append({"seed": seed, "links": links, "raw": out[:300]})
        # 打印结果
        print(f"种子[{seed['seed_id']}] {seed['label']}:")
        linked_ids = [x.get("id") for x in links]
        print(f"  判链接 {len(links)} 条: {linked_ids}")
        for x in links:
            print(f"    → [{x.get('id')}] {x.get('type')} | {x.get('reason', '')[:50]}")
        print()

    # 汇总：精确率 + 假阳性率
    print("=" * 50)
    print("汇总统计（人工标定答案 vs 模型输出）")
    print("=" * 50)
    total_prec, total_fp = 0, 0
    for seed, res in zip(SEEDS, results):
        if res["links"] is None:
            continue
        related = set(seed["related"])
        traps = set(seed["traps"])
        linked = set(x.get("id") for x in res["links"])
        true_pos = linked & related      # 判对了（真相关且判了）
        false_pos = linked & traps       # 假阳性（陷阱判了链接）
        false_neg = related - linked     # 漏判（真相关没判）
        print(f"[{seed['label']}] 命中{len(true_pos)}/{len(related)} 假阳{len(false_pos)}/{len(traps)} 漏判{len(false_neg)}")
        total_prec += len(true_pos) + len(false_pos)  # 分母=所有判了的
        total_fp += len(false_pos)
    # 精确率 = 所有判链接里，真相关的占比
    # 这里简化：汇总所有种子的真阳/假阳
    all_links = sum(len(r["links"]) for r in results if r["links"])
    all_true = sum(len(set(s["related"]) & set(x.get("id") for x in r["links"]))
                   for s, r in zip(SEEDS, results) if r["links"])
    all_fp = sum(len(set(s["traps"]) & set(x.get("id") for x in r["links"]))
                 for s, r in zip(SEEDS, results) if r["links"])
    all_related = sum(len(s["related"]) for s in SEEDS)
    print(f"\n总判链接 {all_links} 条：真相关 {all_true} 条，假阳性 {all_fp} 条")
    if all_links:
        precision = all_true / all_links
        recall = all_true / all_related
        print(f"精确率 = {precision:.0%}  召回率 = {recall:.0%}  假阳性率 = {all_fp/all_links:.0%}")
        print(f"判据：精确率≥70% 且 假阳≤30% → {'✅ 判链可行' if precision >= 0.7 and all_fp/all_links <= 0.3 else '❌ 需搁置或换策略'}")


if __name__ == "__main__":
    asyncio.run(main())
