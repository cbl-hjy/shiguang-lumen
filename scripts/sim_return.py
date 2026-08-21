"""sim_return.py —— 北极星模拟测（哨兵层）：4 代理指标，不依赖真人

复用 sim_runner 的 chat_once/sample_behavior + personas + woshi 适配器。
测"愿意回来"的机制侧：①回来行为 ②记得上次 ③主动续接 ④体验自评。

用法：python scripts/sim_return.py [--persona woshi|exam_crammer|...] （需 9000 实例）
"""
import asyncio
import json
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from sim_runner import chat_once, load_persona  # noqa: E402

BASE = "http://127.0.0.1:9000"

# woshi 适配器：sim_runner 只消费 name/domain/params——把 Layer 0-5 拼进 domain
WOSHI_DOMAIN = (
    "用户数字镜像：2027届秋招生（算法岗/AI应用开发），"
    "说话直接尖锐常用反问、要证据不要感觉、反过度工程、讨厌说教、"
    "深夜型、对焦虑驱动敏感、卡壳直接说'重讲'、满意说'记一下'"
)


def load_persona_any(name: str) -> dict:
    """加载 persona 或 woshi（适配器：woshi 不在 personas/ 目录，格式不同）"""
    if name == "woshi":
        return {"name": "woshi", "domain": WOSHI_DOMAIN,
                "params": {"追问率": 0.7, "话题跳转率": 0.2, "短回复率": 0.4, "结束倾向": "low"}}
    return load_persona(name)


async def run_return_probe(persona: dict, seed: int, token: str, api_key: str, api_base: str, model: str) -> dict:
    """单视角：会话 1 聊困惑 → 会话 2 回来 → 4 代理指标"""
    from app.config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    out = {"persona": persona["name"]}

    # ① 会话 1：聊困惑（不 remember 的对话——测提炼不依赖记忆变化）
    r = requests.post(f"{BASE}/api/session/new", headers=headers, timeout=15)
    sid1 = r.json().get("session_id", "")
    out["session1_created"] = bool(sid1)
    msgs = [
        "我最近在纠结要不要换方向，投了几家大厂都没过，有点自我怀疑",
        "你觉得我应该继续冲大厂还是先稳住中小厂？",
    ]
    for m in msgs:
        reply, tools = await chat_once(BASE, token, sid1, m)
        out.setdefault("session1_replies", []).append(reply[:80])
    time.sleep(3)  # 等收尾钩子三件套

    # ② 会话 2：模拟"第二天回来"
    r2 = requests.post(f"{BASE}/api/session/new", headers=headers, timeout=15)
    sid2 = r2.json().get("session_id", "")
    out["session2_created"] = bool(sid2)

    # ③ 主动续接探针：新会话第一条发无关闲聊
    reply, tools = await chat_once(BASE, token, sid2, "早")
    out["proactive_reply"] = reply[:120]
    out["proactive_ok"] = any(k in reply for k in ("上次", "继续", "接着", "我们聊过", "上次我们"))

    # ④ 记得上次：新会话问"上次聊到哪"
    reply2, _ = await chat_once(BASE, token, sid2, "上次我们聊到哪了？")
    out["remember_reply"] = reply2[:120]
    out["remember_ok"] = any(k in reply2 for k in ("大厂", "中小厂", "方向", "秋招", "纠结"))

    # ⑤ 体验自评（LLM-as-judge：persona 视角自评）
    from openai import OpenAI

    client = OpenAI(api_key=api_key, base_url=api_base, timeout=60.0, max_retries=1)
    judge_prompt = f"""你是{persona['name']}（{persona['domain']}）。
你刚和拾光（AI 学习搭子）聊了两轮：第一轮聊困惑，第二轮回来问上次聊到哪。
它的回复：
回合1: {out['session1_replies'][-1][:100]}
回合2(闲聊"早"后): {out['proactive_reply'][:100]}
回合3(问上次): {out['remember_reply'][:100]}

请以你的视角打分（0-5，一行一个数字）：
1) 这次对话后，你愿意下次再来吗？
2) 它接住了你的困惑吗？
3) 它记得上次、能接着聊吗？
只输出三个数字，每行一个。"""
    try:
        resp = client.chat.completions.create(
            model=model, messages=[{"role": "user", "content": judge_prompt}],
            max_tokens=20, temperature=0,
        )
        raw = resp.choices[0].message.content or ""
        # 提取所有数字（容错：模型可能输出 "4\n3\n4" 或 "4, 3, 4" 或带文字）
        import re

        nums = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", raw)][:3]
        out["self_scores"] = [min(n, 5) for n in nums]  # 防越界
    except Exception as e:
        out["self_scores"] = []
        out["judge_error"] = str(e)[:60]
    return out


async def main():
    import argparse

    from app.config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL, SHIGUANG_TOKEN

    ap = argparse.ArgumentParser()
    ap.add_argument("--persona", default="woshi", help="woshi/exam_crammer/fragment_learner/deep_diver/typical_learner")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    persona = load_persona_any(args.persona)
    print(f"=== 北极星模拟测：{args.persona}（seed={args.seed}）===", flush=True)
    result = await run_return_probe(persona, args.seed, SHIGUANG_TOKEN, DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL)

    print(f"\n【{result['persona']}】")
    print(f"  ① 回来行为: 会话1={'✅' if result['session1_created'] else '❌'} 会话2={'✅' if result['session2_created'] else '❌'}")
    print(f"  ② 记得上次: {'✅' if result.get('remember_ok') else '❌'} → {result.get('remember_reply','')[:60]}")
    print(f"  ③ 主动续接: {'✅' if result.get('proactive_ok') else '❌'} → {result.get('proactive_reply','')[:60]}")
    scores = result.get("self_scores", [])
    if scores:
        print(f"  ④ 体验自评: 愿意再来={scores[0]}/5 接住={scores[1] if len(scores)>1 else '?'}/5 记得={scores[2] if len(scores)>2 else '?'}/5")
        avg = sum(scores) / len(scores)
        print(f"     均值={avg:.1f} {'✅ ≥3.5' if avg >= 3.5 else '❌ <3.5'}")
    else:
        print(f"  ④ 体验自评: 失败 {result.get('judge_error','?')}")
    print(f"  判定: {'✅ 该视角通过' if (result.get('remember_ok') and result.get('proactive_ok') and (not scores or sum(scores)/len(scores) >= 3.5)) else '❌ 未通过'}")


if __name__ == "__main__":
    asyncio.run(main())
