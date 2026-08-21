# -*- coding: utf-8 -*-
"""阶段 4 批量实验：3 persona × (001+002) × 3 种子 + 003 马拉松 1 种子
输出统一进度日志（实时监控用），结果存 reports/raw/"""
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from sim_runner import load_persona, run_persona_scenario
from app.config import SHIGUANG_TOKEN, DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL

BASE = "http://127.0.0.1:9000"
PERSONAS = ["exam_crammer", "fragment_learner", "deep_diver"]
SCENARIOS = ["001", "002"]
SEEDS = [1, 2, 3]
RAW_DIR = ROOT / "reports" / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)


async def main():
    results = []
    total = len(PERSONAS) * len(SCENARIOS) * len(SEEDS) + 1  # +003
    n = 0
    for persona_name in PERSONAS:
        persona = load_persona(persona_name)
        for sc_id in SCENARIOS:
            scenario = json.loads((ROOT / "scenarios" / f"scenario_{sc_id}.json").read_text(encoding="utf-8"))
            for seed in SEEDS:
                n += 1
                print(f"\n[{n}/{total}] {persona_name} × {sc_id} × s{seed}", flush=True)
                r = await run_persona_scenario(persona, scenario, seed, BASE, SHIGUANG_TOKEN,
                                               DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL)
                results.append(r)
                (RAW_DIR / f"{persona_name}_{sc_id}_s{seed}.json").write_text(
                    json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
    # 003 马拉松 1 种子（deep_diver——深挖型最可能触发长会话）
    n += 1
    print(f"\n[{n}/{total}] deep_diver × 003 × s1（马拉松 160 轮）", flush=True)
    scenario3 = json.loads((ROOT / "scenarios" / "scenario_003.json").read_text(encoding="utf-8"))
    r3 = await run_persona_scenario(load_persona("deep_diver"), scenario3, 1, BASE, SHIGUANG_TOKEN,
                                    DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL)
    results.append(r3)
    (RAW_DIR / "deep_diver_003_s1.json").write_text(json.dumps(r3, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n✅ 全部完成：{len(results)} 次运行，原始数据在 reports/raw/", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
