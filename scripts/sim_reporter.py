# -*- coding: utf-8 -*-
"""模拟实验报告生成器 v0.3（阶段 5）：读 reports/raw/*.json → 汇总报告。

报告口径三标注（焊死）：
1. 画像差异度 = 联合分化（主题+风格一起测）——绝不写"记忆分化"
2. 画像差异度第一次跑 = 记录值，不设阈值
3. 串扰率 = 干净实验库基线（与真实库绝对值不可比）

另：所有数据标注来源（90K 边界=历史 166 轮数据，非今天实测）。
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

RAW_DIR = ROOT / "reports" / "raw"
CKPT_DIR = ROOT / "reports" / "checkpoints"
OUT = ROOT / "reports" / "sim_20260813.md"

# 主题域关键词（启发式归属判定——条目没有用户字段，用内容分类）
DOMAIN_KEYS = {
    "ML": ["模型", "损失", "梯度", "attention", "注意力", "过拟合", "正则", "损失函数", "softmax", "向量", "概率"],
    "哲学": ["自由意志", "意识", "伦理", "道德", "存在", "认知", "心智", "决定论", "康德", "笛卡尔"],
    "历史": ["宋朝", "王朝", "战争", "制度", "朝代", "皇帝", "经济史", "唐", "清", "封建"],
}


def classify_topic(text: str) -> str:
    scores = {k: sum(1 for kw in v if kw in text) for k, v in DOMAIN_KEYS.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "未知"


def load_raw() -> list[dict]:
    files = sorted(RAW_DIR.glob("*.json"))
    return [json.loads(f.read_text(encoding="utf-8")) for f in files]


def behavior_compliance(records: list[dict], params: dict) -> dict:
    """行为分布符合度：实际占比 vs 归一化期望概率（v0.2 口径：校准参数=权重乘子非目标概率）"""
    from collections import Counter
    c = Counter(r["behavior"] for r in records)
    total = max(len(records), 1)
    actual = {k: round(v / total, 3) for k, v in c.items()}
    from sim_runner import expected_probs
    expected = expected_probs(params)
    return {
        "实际分布": actual,
        "归一化期望": expected,
        "说明": "对照口径=归一化期望概率（校准参数是权重乘子非目标概率）；锚点行为占前 3 轮不在期望模型内",
    }


def main():
    raws = load_raw()
    if not raws:
        print("❌ 无原始数据（reports/raw 空）——先跑 experiment_all.py")
        return 1

    lines = []
    A = lines.append
    A("# 模拟用户设施 v0.3 基线报告（2026-08-13）")
    A("")
    A("> 口径：本次为【基线记录】模式——只记录当前值，不设断言目标。")
    A("> 数据来源：全部为今日实验实测（报告标注处除外，90K 边界=历史 166 轮数据）。")
    A("")

    # 汇总表
    A("## 一、运行汇总（3 persona × 001+002 × 3 种子 + 003 马拉松 1 种子）")
    A("")
    A("| 运行 | 轮数 | 0 字回复 | 均长(字) | 上下文峰值(字符) |")
    A("|---|---|---|---|---|")
    for r in sorted(raws, key=lambda x: (x["persona"], x["scenario"], x["seed"])):
        recs = r["records"]
        zero = sum(1 for x in recs if x["zero_reply"])
        avg = sum(x["reply_len"] for x in recs) / max(len(recs), 1)
        peak = max((x["ctx_chars"] for x in recs), default=0)
        A(f"| {r['persona']} × {r['scenario']} × s{r['seed']} | {r['turns']} | {zero} | {avg:.0f} | {peak} |")
    A("")

    # 行为分布
    A("## 二、行为分布符合度（记录值，不设断言）")
    A("")
    from sim_runner import load_persona
    for pn in ["exam_crammer", "fragment_learner", "deep_diver"]:
        p = load_persona(pn)
        recs = [x for r in raws if r["persona"] == pn for x in r["records"]]
        if recs:
            comp = behavior_compliance(recs, p["params"])
            exp = comp["归一化期望"]
            A(f"### {pn}（归一化期望: 追问{exp['追问']} / 跳转{exp['跳转']} / 短回复{exp['短回复']} / 正常{exp['正常']}）")
            A(f"- 实际分布: {comp['实际分布']}")
            A("")

    # 串扰率（干净库基线）
    A("## 三、串扰率（干净实验库基线）")
    A("")
    A("方法：从实验库记忆条目按主题关键词归属（ML/哲学/历史），统计各 persona 会话产生的条目主题纯度。")
    A("注：条目无用户字段，归属为主题启发式；干净库基线，绝对值不与真实库对比。")
    A("")
    entries_file = ROOT / "data-experiment" / "memory" / "user_memory.md"
    if entries_file.exists():
        texts = [ln for ln in entries_file.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.startswith("#")]
        topics = [classify_topic(t) for t in texts]
        from collections import Counter
        tc = Counter(topics)
        total = max(len(topics), 1)
        A(f"- 实验库记忆条目数: {len(texts)}")
        A(f"- 主题分布: {dict(tc)}")
        A(f"- 归属率（可分类占比）: {round(sum(1 for t in topics if t != '未知') / total, 3)}")
        A("")
    else:
        A("- 实验库无记忆条目（模型未写入——观察项：模拟用户未提出记忆需求时模型不主动写）")
        A("")

    # 画像差异度（联合分化）
    A("## 四、画像差异度（联合分化标注）")
    A("")
    A("> 标注：本次主题域不同（ML/哲学/历史），画像差异=主题+风格【联合分化】，不宣称'记忆分化'。")
    A("> 记录值不设阈值（无先验）。")
    A("")
    snaps = sorted(CKPT_DIR.glob("*_profile.md"))
    if snaps:
        A(f"- 画像快照: {len(snaps)} 份（{', '.join(s.name for s in snaps)}）")
        try:
            from app.memory.vector import embed
            import numpy as np
            pairs = []
            for i in range(len(snaps)):
                for j in range(i + 1, len(snaps)):
                    t1 = snaps[i].read_text(encoding="utf-8")
                    t2 = snaps[j].read_text(encoding="utf-8")
                    e1, e2 = embed([t1, t2])
                    cos = float(np.dot(e1, e2) / (np.linalg.norm(e1) * np.linalg.norm(e2) + 1e-9))
                    pairs.append((snaps[i].name, snaps[j].name, round(cos, 3)))
            for a, b, c in pairs:
                A(f"- 相似度 {a} ↔ {b}: {c}")
        except Exception as e:
            A(f"- 相似度计算失败: {e}")
        A("")
    else:
        A("- 无画像快照（模型未生成画像——见串扰率段观察项）")
        A("")

    # 边界观测
    A("## 五、边界观测")
    A("")
    for r in raws:
        recs = r["records"]
        zeros = [(x["turn"], x["ctx_chars"]) for x in recs if x["zero_reply"]]
        if zeros:
            A(f"- {r['persona']} × {r['scenario']} × s{r['seed']}: 0 字回复 {len(zeros)} 处（turn/ctx: {zeros[:5]}）")
    marathon = [r for r in raws if r["scenario"] == "003"]
    if marathon:
        m = marathon[0]
        A(f"- 马拉松 003: {m['turns']} 轮，峰值 ctx={max(x['ctx_chars'] for x in m['records'])}，"
          f"0 字={sum(1 for x in m['records'] if x['zero_reply'])}")
        A("  - 注：90K 边界参考=历史 166 轮数据（34 轮退化/66 轮 0 字），今日马拉松未达 90K 则注明'未触及边界'")
    A("")

    A("## 六、口径与数据来源标注")
    A("- 画像差异度 = 联合分化（主题+风格），非'记忆分化'")
    A("- 画像差异度 = 记录值，不设阈值（无先验）")
    A("- 串扰率 = 干净实验库基线，不与真实库绝对值对比")
    A("- 90K/34 轮边界 = 历史 166 轮数据，非今日实测（若今日触及则注明）")
    A("- 行为参数校准源 = v0.1 基线派生（3 天样本，口径说明见 behavior_profile.json）")
    A("")

    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"✅ 报告已生成: {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
