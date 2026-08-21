# -*- coding: utf-8 -*-
"""阶段 3：画像差异度实验（3 persona × 001 × 3 种子）——v02 独立目录"""
import sys, asyncio, json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import sim_runner
from sim_runner import load_persona, run_persona_scenario
from app.config import SHIGUANG_TOKEN, DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL

# 防线（2026-08-13 失误教训）：批次实验（串扰/画像分化）必须干净起步——
# 实验库 user_memory 非空 → 拒绝启动（画像=全量聚合，污染会让差异度数据无效）
_mem = ROOT / "data-experiment" / "memory" / "user_memory.md"
if _mem.exists() and len([l for l in _mem.read_text(encoding="utf-8").splitlines() if l.strip().startswith("- ")]) > 0:
    raise SystemExit("❌ 实验库非空——串扰/画像实验必须干净起步，请先清空 data-experiment/memory/ 再跑")

# 批次目录参数化（2026-08-14 教训：组A复用raw_v02覆盖了组B raw——批次必须独立目录）
import argparse
_ap = argparse.ArgumentParser()
_ap.add_argument("--outdir", default="raw_v02", help="批次目录名，如 raw_a / raw_b（复用旧目录=覆盖风险）")
_args, _ = _ap.parse_known_args()
RAW = ROOT / "reports" / f"raw_{_args.outdir}"
CKPT = ROOT / "reports" / f"checkpoints_{_args.outdir}"
# 防线：目录已存在且含旧数据 → 拒绝启动（防复用覆盖）
if RAW.exists() and any(RAW.glob("*.json")):
    raise SystemExit(f"❌ 批次目录 {RAW.name} 非空——复用会覆盖旧批次数据，请用 --outdir 新批次名")
RAW.mkdir(exist_ok=True)
CKPT.mkdir(exist_ok=True)

# 快照落 v02 独立目录（绝对路径——export_profile_snapshot 内部 relative_to(ROOT) 需要绝对）
_orig_snap = sim_runner.export_profile_snapshot


def _snap(persona, sid, out_dir=None):
    return _orig_snap(persona, sid, CKPT)


sim_runner.export_profile_snapshot = _snap

PERSONAS = ["exam_crammer", "fragment_learner", "deep_diver"]


async def main():
    n = 0
    for pn in PERSONAS:
        p = load_persona(pn)
        sc = json.load(open(ROOT / "scenarios" / "scenario_001.json", encoding="utf-8"))
        for seed in [1, 2, 3]:
            n += 1
            print(f"[{n}/9] {pn} × 001 × s{seed}", flush=True)
            r = await run_persona_scenario(p, sc, seed, "http://127.0.0.1:9000", SHIGUANG_TOKEN,
                                           DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL)
            (RAW / f"{pn}_001_s{seed}.json").write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
    print("阶段3完成: 9 会话", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
