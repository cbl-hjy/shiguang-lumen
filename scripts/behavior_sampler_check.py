# -*- coding: utf-8 -*-
"""采样器自洽回归（v0.2 审计落盘）：纯采样器掷骰 vs 归一化期望——可重跑，改权重后的哨兵。
用法：python scripts/behavior_sampler_check.py   （不改动任何数据，纯随机验证）
"""
import sys, random
from collections import Counter
sys.path.insert(0, ".")
sys.path.insert(0, "scripts")
from sim_runner import sample_behavior, expected_probs

PARAMS = {
    "exam_crammer": {"追问率": 0.8, "话题跳转率": 0.3, "短回复率": 0.5},
    "fragment_learner": {"追问率": 0.5, "话题跳转率": 0.8, "短回复率": 0.7},
    "deep_diver": {"追问率": 0.3, "话题跳转率": 0.1, "短回复率": 0.2},
}
N = 5000  # 大样本——"±0.05 内"在此量级才统计可达（审计：n=21 时不可达）


def main() -> int:
    ok = True
    for pn, params in PARAMS.items():
        rng = random.Random(42)
        c = Counter(sample_behavior(rng, params, t, no_end=True) for t in range(N))
        exp = expected_probs(params, no_end=True)
        worst = 0.0
        for k, e in exp.items():
            a = c.get(k, 0) / N
            d = abs(a - e)
            worst = max(worst, d)
        passed = worst < 0.01  # 5000 样本下二项标准差 ~0.007，0.01 是 1.5σ 上限
        ok &= passed
        print(f"{'✅' if passed else '❌'} {pn}: 最差偏差 {worst:.4f}（N={N}，阈值 0.01）")
    print("结论:", "✅ 采样器与归一化期望自洽" if ok else "❌ 采样器漂移——查 sample_behavior")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
