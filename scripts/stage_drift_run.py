# -*- coding: utf-8 -*-
"""漂移治理验证：3 persona × 002(30轮压力) × 2 种子 = 6 会话
验证指标：收尾语残留 / 非短回复行为短消息 / 0字"""
import sys, asyncio, json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from sim_runner import load_persona, run_persona_scenario, _is_closing
from app.config import SHIGUANG_TOKEN, DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL

PERSONAS = ["exam_crammer", "fragment_learner", "deep_diver"]
CLOSING = ["明天见", "晚安", "今天到这儿", "再见", "下次聊", "就到这", "收工", "结束吧", "先这样", "拜拜"]


async def main():
    sc = json.load(open(ROOT / "scenarios" / "scenario_002.json", encoding="utf-8"))
    for pn in PERSONAS:
        p = load_persona(pn)
        for seed in [1, 2]:
            print(f"=== {pn} × 002 × s{seed} ===", flush=True)
            r = await run_persona_scenario(p, sc, seed, "http://127.0.0.1:9000", SHIGUANG_TOKEN,
                                           DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL)
            recs = r["records"]
            closing = sum(1 for x in recs if _is_closing(x["user"]) and x["behavior"] != "结束")
            short = sum(1 for x in recs if len(x["user"]) < 5 and x["behavior"] not in ("短回复", "结束"))
            zero = sum(1 for x in recs if x["zero_reply"])
            print(f"  {len(recs)}轮 收尾语={closing} 非短行为短消息={short} 0字={zero}", flush=True)
    print("漂移治理验证完成", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
