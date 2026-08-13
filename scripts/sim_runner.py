# -*- coding: utf-8 -*-
"""模拟用户 runner v0.3：persona 驱动 + 行为采样 + 打真实拾光实例。

架构（五件套）：
- persona_loader：读 persona.md + behavior_profile.json
- behavior_sampler：每轮掷骰定行为（追问/跳转/短回复/质疑/正常/结束）——行为靠采样不靠 prompt 期望
- dialog_driver：打【真实拾光实例】（实验实例 9000 或主实例 8000），绝不 LLM 对聊
- recorder：逐轮记录（用户消息/回复/字数/0 字标记/上下文估算）
- reporter：输出 reports/sim_YYYYMMDD.md

关键设计（写死）：
1. 行为靠采样：每轮先掷骰定"这轮干什么"，再让模拟用户 LLM 生成语言——分布受控、语言自然
2. 前 15 轮禁"结束"采样（长度控制，防随机截断）
3. 种子可复现：random.Random(seed)
4. 基线模式：只记录值，不设断言目标
5. 上下文估算：对话链字符数累计（塌陷定位）
"""
import argparse
import asyncio
import json
import random
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PERSONAS_DIR = ROOT / "memory" / "personas"
SCENARIOS_DIR = ROOT / "scenarios"
REPORTS_DIR = ROOT / "reports"
BEHAVIOR_FILE = PERSONAS_DIR / "behavior_profile.json"

BEHAVIORS = ["追问", "跳转", "短回复", "质疑", "正常", "结束"]
BEHAVIOR_WEIGHTS = {  # 由 persona 参数派生，见 sample_behavior
    "追问": 1.0, "跳转": 1.0, "短回复": 1.0, "质疑": 0.4, "正常": 1.0, "结束": 0.15,
}
END_FORBIDDEN_TURNS = 15  # 前 15 轮禁"结束"


def load_persona(name: str) -> dict:
    """persona_loader：读 persona.md 头部字段 + behavior_profile.json 参数"""
    params = json.loads(BEHAVIOR_FILE.read_text(encoding="utf-8"))["personas"].get(name, {})
    pf = PERSONAS_DIR / f"{name}.md"
    if not pf.exists():
        raise FileNotFoundError(f"persona 文件不存在: {pf}")
    # 主题域从 frontmatter 读
    meta = {}
    for line in pf.read_text(encoding="utf-8").splitlines()[:8]:
        m = re.match(r"(\w+):\s*(.+)", line)
        if m:
            meta[m.group(1)] = m.group(2)
    return {"name": name, "domain": meta.get("主题域", ""), "params": params}


def sample_behavior(rng: random.Random, params: dict, turn: int, no_end: bool = False) -> str:
    """behavior_sampler：按 persona 参数派生权重，归一化为概率后掷骰定本回合行为。

    口径（v0.2 修正，D2/D6）：校准参数（追问率等）是【权重乘子】不是【目标概率】——
    实际概率 = 归一化后权重（如 exam 追问 = 0.8/(0.8+0.3+0.5+0.4+1.0+0.15) ≈ 0.254）。
    '正常' 固定基数 1.0、'质疑' 固定 0.4——不随 persona 缩放（设计选择，保留对话自然基线）。
    报告对照口径用"归一化期望概率"，不是校准原始值。
    """
    w = dict(BEHAVIOR_WEIGHTS)
    w["追问"] *= params.get("追问率", 0.5)
    w["跳转"] *= params.get("话题跳转率", 0.5)
    w["短回复"] *= params.get("短回复率", 0.5)
    if turn < END_FORBIDDEN_TURNS or no_end:
        w["结束"] = 0  # 前 15 轮禁结束；马拉松(no_end)全程禁
    behaviors = list(w.keys())
    total = sum(w.values())
    probs = [v / total for v in w.values()]  # 权重 → 概率（显式归一化，rng.choices 隐含同逻辑）
    return rng.choices(behaviors, weights=probs, k=1)[0]


def expected_probs(params: dict, no_end: bool = False) -> dict:
    """归一化期望概率（报告对照口径）：与 sample_behavior 同公式"""
    w = dict(BEHAVIOR_WEIGHTS)
    w["追问"] *= params.get("追问率", 0.5)
    w["跳转"] *= params.get("话题跳转率", 0.5)
    w["短回复"] *= params.get("短回复率", 0.5)
    if no_end:
        w["结束"] = 0
    total = sum(w.values())
    return {k: round(v / total, 3) for k, v in w.items()}


def context_estimate(history: list[dict]) -> int:
    """上下文估算：对话链字符数累计（塌陷定位靠它）"""
    return sum(len(u) + len(r) for u, r in history)


def export_profile_snapshot(persona: str, session_id: str, out_dir: Path):
    """画像快照导出（会话结束、切换前）：复制实验库 profile.md 到 checkpoint。
    v0.2 加内容哈希（D4）：md5 相同 = 同一文件复制（防 v0.3 画像 1.0 假象重演——先排重再对比）"""
    import hashlib
    src = ROOT / "data-experiment" / "memory" / "profile.md"
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / f"{persona}_{session_id[:8]}_profile.md"
    if src.exists():
        # 哈希口径（2026-08-13 审计修复）：算在【磁盘实际字节】上——
        # read_text 通用换行(LF) + write_text 默认(CRLF) 会让哈希与磁盘文件不一致（Linux md5sum 验证必败）
        raw_bytes = src.read_bytes()
        dest.write_bytes(raw_bytes)  # 字节级复制，快照=真复制
        md5 = hashlib.md5(raw_bytes).hexdigest()[:8]
        return f"{dest.relative_to(ROOT)} (md5={md5})"
    return "(画像文件尚未生成)"


def _parse_sse(sse_text: str) -> tuple[str, list[str]]:
    """解析拾光 SSE：拼回复文本 + 收集工具调用名"""
    text, tools = "", []
    for line in sse_text.splitlines():
        if not line.startswith("data:"):
            continue
        try:
            ev = json.loads(line[5:])
        except Exception:
            continue
        t = ev.get("type")
        if t == "delta":
            text += ev.get("text", "")
        elif t == "tool":
            tools.append(ev.get("name", ""))
        elif t == "error":
            text += f"\n[error:{ev.get('message','')}]"
    return text, tools


async def chat_once(base_url: str, token: str, session_id: str, message: str, timeout: int = 120) -> tuple[str, list[str]]:
    """dialog_driver：POST 真实拾光 /api/chat，返回（回复文本, 工具名列表）"""
    import threading

    def _req():
        try:
            r = requests.post(
                f"{base_url}/api/chat",
                json={"message": message, "session_id": session_id},
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                stream=True, timeout=timeout,
            )
            if r.status_code != 200:
                return r.status_code, ""
            # SSE 按行读（requests 无 iter_text，用 iter_lines 解码行）
            lines = [ln for ln in r.iter_lines(decode_unicode=True) if ln]
            return r.status_code, "\n".join(lines)
        except Exception as e:
            return -1, str(e)

    # requests 是同步的，放线程池跑（简单够用）
    loop = asyncio.get_event_loop()
    code, body = await loop.run_in_executor(None, _req)
    if code != 200:
        return f"<HTTP {code}>", []
    return _parse_sse(body)


# 漂移治理（v0.2，2026-08-13）：收尾语检测——非"结束"行为出现收尾语 = 模拟用户长会话漂移
# 原则（用户焊死）：治"收尾语循环"不治"短消息"——短消息是真实分布，长度只做下限保护不做正态化
CLOSING_PATTERNS = ["明天见", "晚安", "今天到这儿", "再见", "下次聊", "就到这", "收工", "结束吧", "先这样", "拜拜", "睡吧"]


def _is_closing(text: str) -> bool:
    return any(p in text for p in CLOSING_PATTERNS)


async def generate_user_message(api_key: str, base_url: str, model: str, persona: dict, scenario: dict,
                                behavior: str, history: list[dict], seed: int = 0) -> str:
    """模拟用户语言生成（LLM）：行为类型由采样器定，语言由模拟用户 LLM 生成。
    v0.2 漂移治理：非"结束"行为生成收尾语 / 非短回复行为生成 <5 字无信息量消息 → 重生成（最多 2 次），
    仍失败用场景锚点兜底——只拦"无信息量漂移"，不碰长度分布（真实用户会发'嗯'）"""
    from openai import OpenAI

    client = OpenAI(api_key=api_key, base_url=base_url, timeout=60.0, max_retries=1)  # timeout 防挂死（马拉松 t02 卡住根因）
    persona_block = f"你是{persona['name']}：{persona['domain']}学习者。"
    behavior_guide = {
        "追问": "对刚才的回答追问细节（为什么/怎么算/举个例子）",
        "跳转": "换一个相关但不连续的新话题",
        "短回复": "用一句很短的话回应（≤15字），如'嗯''继续''明白了'",
        "质疑": "质疑刚才回答的依据（'这个结论凭什么？''有反例吗？'）",
        "正常": "按你的学习场景正常提问/回应",
        "结束": "自然地结束这次学习会话（表达收尾）",
    }[behavior]
    scene = scenario["scene"]
    hist = "\n".join(f"你: {u}\n拾光: {r[:150]}" for u, r in history[-6:]) or "(刚开始)"
    prompt = f"""{persona_block}场景：{scene}。本轮行为：{behavior_guide}。
对话历史（最近）：
{hist}
请只输出你作为学习者要说的这一句话，不要任何解释。"""
    anchors = (scenario.get("anchors_by_persona") or {}).get(persona["name"]) or scenario.get("anchors", [])
    for attempt in range(3):
        try:
            resp = client.chat.completions.create(
                model=model, messages=[{"role": "user", "content": prompt}],
                max_tokens=120, temperature=0.9,
            )
            msg = (resp.choices[0].message.content or "嗯").strip()
        except Exception as e:
            return f"(模拟用户生成失败:{str(e)[:50]})"
        # 治理 1：非"结束"行为出现收尾语 = 漂移 → 重生成
        if behavior != "结束" and _is_closing(msg):
            if attempt < 2:
                continue
            return anchors[(seed + len(history)) % len(anchors)] if anchors else "刚才讲的我还想再深挖一点"
        # 治理 2：非"短回复/结束"行为生成 <5 字无信息量消息 = 漂移 → 重生成
        if behavior not in ("短回复", "结束") and len(msg) < 5:
            if attempt < 2:
                continue
            return "再讲细一点，我还是没完全懂。"
        return msg


async def run_persona_scenario(persona: dict, scenario: dict, seed: int, base_url: str, token: str,
                               api_key: str, api_base: str, model: str) -> dict:
    """跑一个 persona × 场景 × 种子，返回记录"""
    rng = random.Random(seed)
    history: list[dict] = []
    records = []

    # 新会话
    r = requests.post(f"{base_url}/api/session/new", headers={"Authorization": f"Bearer {token}"}, timeout=15)
    session_id = r.json().get("session_id", "")
    time.sleep(1)

    max_turns = scenario.get("max_turns", 30)
    anchors = (scenario.get("anchors_by_persona") or {}).get(persona["name"]) \
        or scenario.get("anchors", [])  # 锚点按 persona 主题域选（必补 1 落实）
    for turn in range(max_turns):
        # 锚点植入（必补 3）：前 N 轮用户主动提起场景设定的事实（细节锚点——跨会话保持判定的标尺）
        if turn < len(anchors):
            user_msg = anchors[turn]
            behavior = "锚点"
        else:
            behavior = sample_behavior(rng, persona["params"], turn, no_end=scenario.get("no_end", False))
            if behavior == "结束":
                break
            user_msg = await generate_user_message(api_key, api_base, model, persona, scenario, behavior, history, seed=seed)
        t0 = time.perf_counter()
        reply, tools = await chat_once(base_url, token, session_id, user_msg)
        dt_ms = (time.perf_counter() - t0) * 1000
        ctx = context_estimate(history + [(user_msg, reply)])
        records.append({
            "turn": turn + 1, "behavior": behavior,
            "user": user_msg, "reply": reply,
            "reply_len": len(reply), "zero_reply": len(reply.strip()) == 0,
            "tools": tools, "ctx_chars": ctx, "ms": round(dt_ms, 1),
        })
        history.append((user_msg, reply))
        # 实时进度
        print(f"  [{persona['name']}·{seed}] t{turn+1:02d} {behavior} ctx={ctx} 回复={len(reply)}字", flush=True)
        if turn % 5 == 4:
            time.sleep(1)  # 呼吸间隔

    # 画像快照导出（会话结束、切换前）
    snap = export_profile_snapshot(persona["name"], session_id, ROOT / "reports" / "checkpoints")
    return {"persona": persona["name"], "scenario": scenario["id"], "seed": seed,
            "session_id": session_id, "turns": len(records), "records": records, "profile_snapshot": snap}


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--persona", default="exam_crammer")
    ap.add_argument("--scenario", default="001")
    ap.add_argument("--seeds", default="1", help="逗号分隔，如 1,2,3")
    ap.add_argument("--base-url", default="http://127.0.0.1:9000", help="默认实验实例")
    args = ap.parse_args()

    persona = load_persona(args.persona)
    scenario = json.loads((SCENARIOS_DIR / f"scenario_{args.scenario}.json").read_text(encoding="utf-8"))
    seeds = [int(s) for s in args.seeds.split(",")]

    from app.config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL, SHIGUANG_TOKEN

    print(f"=== 模拟实验: {persona['name']} × {scenario['id']} × seeds={seeds} → {args.base_url} ===", flush=True)
    for seed in seeds:
        result = await run_persona_scenario(
            persona, scenario, seed, args.base_url, SHIGUANG_TOKEN,
            DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL,
        )
        # 报告单次运行
        zero = sum(1 for r in result["records"] if r["zero_reply"])
        avg_len = sum(r["reply_len"] for r in result["records"]) / max(len(result["records"]), 1)
        print(f"\n=== {result['persona']} × {result['scenario']} × s{seed}: {result['turns']}轮 "
              f"0字={zero} 均长={avg_len:.0f} 快照={result['profile_snapshot']} ===", flush=True)

    print("\n✅ 完成。完整报告由 reporter 阶段输出（见阶段 5）", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
