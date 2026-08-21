"""数字自我（woshi）真实体验拾光 40 分钟。
双 agent 循环：
  woshi（DeepSeek + persona）→ 生成用户消息（像真实用户学"机器学习面试题"）
  → 拾光（HTTP /api/chat，同一 session）→ 真实响应
  → 记录 → 循环直到 40 分钟（约 30-40 轮）
产出：data/ux_stress/woshi_experience.jsonl（时间戳/用户消息/拾光回复/工具）
"""
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import sys as _sys
from pathlib import Path as _Path

_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))
from _auth import headers_json


sys.path.insert(0, r"D:\work_buddy\personal-agent")
from app.config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL

import subprocess

OUT = Path(r"D:\work_buddy\personal-agent\data\ux_stress")
OUT.mkdir(exist_ok=True)
LOG = OUT / "woshi_experience2.jsonl"

DURATION_MIN = 40
BASE = "http://127.0.0.1:8000"

WOSHI_SYSTEM = """你是"我"——一个 2027 届秋招生的数字镜像，正在用拾光（一个 AI 学习搭子）学习"机器学习面试高频题"。
你的说话风格：直接、爱反问、要证据；先直觉后公式；卡壳就说"没听懂重讲"；对泛泛而谈会直接说"别背百科，讲点能用的"。
下面是拾光刚讲的内容片段。请像真实用户一样回应它——根据内容做出具体反应：
- 听懂了一个点 → 追问具体细节（如"那 QKV 具体怎么算的？"、"这跟过拟合有什么关系？"、"给我个具体例子"）
- 没听懂/太快 → 直接说"没听懂，重讲"或"太快了，慢点"
- 觉得在背百科 → 说"别背百科，讲点能用的"
- 讲得好 → 说"这个讲法不错，记一下"并可能问延伸问题
- 偶尔也可以主动换一个相关话题
绝不要说"继续讲讲"这类空话。输出 1-2 句话，只输出你要说的话。"""


def woshi_says(history: list[dict]) -> str:
    """woshi persona 生成用户消息：只看最近 1 轮（针对拾光刚讲的内容具体回应）"""
    from openai import OpenAI

    client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
    msgs = [{"role": "system", "content": WOSHI_SYSTEM}]
    if history:
        last_user = history[-2]["content"] if len(history) >= 2 else ""
        last_ai = history[-1]["content"][:600] if history else ""
        if last_ai:
            msgs.append({"role": "assistant", "content": f"（拾光刚讲的：）{last_ai}"})
    resp = client.chat.completions.create(
        model=DEEPSEEK_MODEL, messages=msgs, max_tokens=150, temperature=0.9,
    )
    return (resp.choices[0].message.content or "").strip()


def tutor_reply(sid: str, msg: str) -> tuple[str, list[str]]:
    """发消息给拾光，返回（回复全文, 工具列表）"""
    body = {"message": msg, "session_id": sid}
    r = subprocess.run(
        ["curl", "-s", "-N", "-X", "POST", f"{BASE}/api/chat"]
        + headers_json()
        + ["-d", json.dumps(body, ensure_ascii=False), "--max-time", "180"],
        capture_output=True, text=True, encoding="utf-8", errors="ignore", timeout=200,
    )
    out = r.stdout
    import re

    tools = re.findall(r'"name": "([a-z_]+)"', out)
    text = "".join(
        (json.loads(line[5:])["text"] if '"type": "delta"' in line else "")
        for line in out.splitlines() if line.startswith("data:")
    )
    return text, list(dict.fromkeys(tools))


def main():
    # 新会话
    r = subprocess.run(["curl", "-s", "-X", "POST", f"{BASE}/api/session/new"] + headers_json() + ["--max-time", "10"],
                       capture_output=True, text=True, encoding="utf-8")
    sid = json.loads(r.stdout)["session_id"]
    print(f"会话: {sid} · 目标 {DURATION_MIN} 分钟", flush=True)

    history: list[dict] = []
    t0 = time.time()
    round_no = 0

    # 开场：woshi 主动发起
    first = "我想准备算法岗面试，先帮我讲讲机器学习基础吧，从最重要的开始"
    history.append({"role": "user", "content": first})

    while time.time() - t0 < DURATION_MIN * 60:
        round_no += 1
        # 1. 取用户消息（首轮用预设，之后 woshi 生成）
        if round_no == 1:
            user_msg = first
        else:
            user_msg = woshi_says(history)
        if not user_msg:
            user_msg = "继续讲讲？"
        # 2. 发给拾光
        reply, tools = tutor_reply(sid, user_msg)
        # 3. 记录
        rec = {
            "round": round_no,
            "t": datetime.now().isoformat(timespec="minutes"),
            "elapsed_min": round((time.time() - t0) / 60, 1),
            "user": user_msg[:120],
            "reply_len": len(reply),
            "tools": tools,
        }
        with LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"[{round_no:>2}] {rec['elapsed_min']:>4}min user={len(user_msg)}字 reply={rec['reply_len']}字 tools={tools}", flush=True)
        # 4. 更新 woshi 上下文（保持最近 8 轮）
        history.append({"role": "user", "content": user_msg})
        history.append({"role": "assistant", "content": reply[:1500]})
        history = history[-8:]

    print(f"=== 40 分钟体验完成，共 {round_no} 轮 ===", flush=True)


if __name__ == "__main__":
    main()
