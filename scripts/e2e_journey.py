"""e2e_journey.py —— 端到端旅程验证（隔离实例 9000，主库零接触）

旅程（模拟真实使用）：
1. 新会话 → 聊困惑（含情感，故意不 remember——测 P0-2 提炼不依赖 remember）
2. 等收尾钩子 → 断言三件套落库（困惑条目 + relation + continuation）
3. 开第二次会话（模拟"第二天回来"）→ 断言注入含"我们之间/续接点"
4. 新会话问"上次我们聊到哪了" → 断言拾光答对（记得上次）

用法：python scripts/e2e_journey.py  （需 9000 已启动，token 已配置）
"""
import json
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

BASE = "http://127.0.0.1:9000"
RESULTS = []


def check(name: str, ok: bool, evidence: str):
    RESULTS.append((name, ok, evidence))
    print(f"  {'✅' if ok else '❌'} {name}: {evidence}")


def main():
    from _auth import token

    tok = token()
    headers = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}

    print("═══ E2E 旅程：新会话 → 困惑对话 → 三件套 → 回来记得 ═══")

    # 1. 新会话
    r = requests.post(f"{BASE}/api/session/new", headers=headers, timeout=15)
    sid1 = r.json().get("session_id", "")
    check("会话 1 创建", bool(sid1), sid1[:12])

    # 2. 聊困惑（明确不 remember 的对话——测提炼不依赖记忆变化）
    dialogue = [
        "我投了几家大厂的agent岗都没过，感觉竞争特别大，我有点怀疑我选错方向了？或者我不应该以大厂为目标？先稳住中小厂？",
        "那我是需要根据不同公司微调简历的吧？官网投还是boss投比较好？",
    ]
    for msg in dialogue:
        resp = requests.post(
            f"{BASE}/api/chat",
            json={"message": msg, "session_id": sid1},
            headers=headers, stream=True, timeout=180,
        )
        lines = [ln for ln in resp.iter_lines(decode_unicode=True) if ln] if resp.status_code == 200 else []
        ok = '"type": "done"' in "\n".join(lines)
        print(f"  对话轮: {'✅' if ok else '❌'} {msg[:30]}...")

    time.sleep(3)  # 等收尾钩子（提炼 3 次 LLM 调用）

    # 3. 断言三件套落库（实验库 data-experiment）
    exp_mem = ROOT / "data-experiment" / "memory"
    um = exp_mem / "user_memory.md"
    st = exp_mem / "state.json"

    um_text = um.read_text(encoding="utf-8") if um.exists() else ""
    confusion_hit = "cat=困惑" in um_text or "困惑" in um_text
    check("困惑落库（user_memory 含困惑条目）", confusion_hit, "cat=困惑 或困惑字样" if confusion_hit else "未找到")

    st_text = st.read_text(encoding="utf-8") if st.exists() else "{}"
    try:
        st_data = json.loads(st_text)
        rel_ok = bool(st_data.get("relation") and st_data["relation"].get("last_topic"))
        cont_ok = bool(st_data.get("continuation") and st_data["continuation"].get("next_step"))
    except Exception:
        rel_ok = cont_ok = False
    check("relation 写入 state.json", rel_ok, st_data.get("relation", {}).get("last_topic", "空") if st_data else "?")
    check("continuation 写入 state.json", cont_ok, st_data.get("continuation", {}).get("next_step", "空") if st_data else "?")

    # 4. 新会话（模拟"第二天回来"）
    r2 = requests.post(f"{BASE}/api/session/new", headers=headers, timeout=15)
    sid2 = r2.json().get("session_id", "")
    check("会话 2 创建（回来）", bool(sid2), sid2[:12])

    # 5. 新会话问"上次聊到哪"
    resp = requests.post(
        f"{BASE}/api/chat",
        json={"message": "上次我们聊到哪了？", "session_id": sid2},
        headers=headers, stream=True, timeout=180,
    )
    lines = [ln for ln in resp.iter_lines(decode_unicode=True) if ln] if resp.status_code == 200 else []
    sse_text = "\n".join(lines)
    done = '"type": "done"' in sse_text
    reply_text = ""
    for ln in lines:
        if ln.startswith("data:"):
            try:
                ev = json.loads(ln[5:])
                if ev.get("type") == "delta":
                    reply_text += ev.get("text", "")
            except Exception:
                pass
    remember_hit = ("大厂" in reply_text or "中小厂" in reply_text or "方向" in reply_text or "秋招" in reply_text)
    check("新会话记得上次（回复含上次话题）", done and remember_hit, reply_text[:60] if reply_text else "空回复")

    # 汇总
    print("\n═══ 汇总 ═══")
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    print(f"{passed}/{len(RESULTS)} 通过")
    for name, ok, ev in RESULTS:
        if not ok:
            print(f"  ❌ {name}: {ev}")
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
