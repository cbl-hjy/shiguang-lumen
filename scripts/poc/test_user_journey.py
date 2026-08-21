"""真实用户体验测试：模拟用户学习"梯度下降"的完整旅程，串行监控 M1-M8 机制
每个场景：发消息 → 记录工具调用 + 回答摘要 → 检查对应数据层
"""
import json
import re
import subprocess
import sys
import time
from pathlib import Path

import sys as _sys
from pathlib import Path as _Path

_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))
from _auth import headers_json


sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

BASE = "http://127.0.0.1:8000/api/chat"


def chat(message: str, sid: str | None = None, timeout: int = 300) -> dict:
    """发一条消息（curl 子进程读 SSE——本环境 requests/urllib 流式不稳，curl 稳定）"""
    body = {"message": message}
    if sid:
        body["session_id"] = sid
    r = subprocess.run(
        ["curl", "-s", "-N", "-X", "POST", BASE]
        + headers_json()
        + ["-d", json.dumps(body, ensure_ascii=False), "--max-time", str(timeout)],
        capture_output=True, text=True, encoding="utf-8", errors="ignore",
    )
    out = r.stdout
    text, tools, thinking, session_id = "", [], "", None
    for line in out.splitlines():
        if not line.startswith("data:"):
            continue
        try:
            ev = json.loads(line[5:])
        except Exception:
            continue
        t = ev.get("type")
        if t == "delta":
            text += ev["text"]
        elif t == "thinking":
            thinking += ev.get("text", "")
        elif t == "tool":
            tools.append(ev.get("name"))
        elif t == "done":
            session_id = ev["session_id"]
    return {"session_id": session_id, "text": text, "tools": tools, "thinking_len": len(thinking)}


def report(step: str, r: dict, extra: str = ""):
    tools = ",".join(dict.fromkeys(r["tools"])) or "—"
    head = r["text"].strip()[:110].replace("\n", " ")
    print(f"[{step}] tools={tools} | 思考{ r['thinking_len']}字")
    print(f"    → {head}{'…' if len(r['text']) > 110 else ''}")
    if extra:
        print(f"    {extra}")


def main():
    print("=" * 60)
    print("拾光 · 真实用户体验旅程（学习'梯度下降'）")
    print("=" * 60)

    # ---------- 场景 0：新会话，欢迎语境 ----------
    print("\n■ 场景 0｜M1 对话循环：全新会话第一个问题")
    r0 = chat("你好，我想开始学机器学习。你是？")
    report("M1-对话", r0)
    sid = r0["session_id"]
    print(f"    [M1] 会话创建: {sid} | 会话持久化 → sessions.db")

    # ---------- 场景 1：记忆偏好注入生效？ ----------
    print("\n■ 场景 1｜M1+M2 记忆注入：'先直觉后公式'偏好是否自动生效")
    r1 = chat("先别管我是什么水平，直接讲：什么是梯度下降？", sid)
    report("M1-记忆注入", r1)
    print("    [观察] 回答是否先直觉类比、公式放后（画像'先直觉后公式'驱动）")

    # ---------- 场景 2：记忆写入 ----------
    print("\n■ 场景 2｜M2 记忆写入：主动透露偏好")
    r2 = chat("我喜欢用类比和故事学习，抽象公式放后面，记住这个。", sid)
    report("M2-remember", r2)
    mem_file = Path("memory/user_memory.md")
    if mem_file.exists():
        n = sum(1 for l in mem_file.read_text(encoding="utf-8").splitlines() if l.startswith("- "))
        print(f"    [检查] user_memory.md 现有 {n} 条")

    # ---------- 场景 3：负面反馈 → 反思（M8 核心） ----------
    print("\n■ 场景 3｜M8 反思：明确说没听懂，观察是否自主反思")
    r3 = chat("你刚才讲得太术语了，什么 loss 什么导数，我完全听不懂，换个人话方式重新讲！", sid)
    report("M8-反思", r3)
    refl_file = Path("memory/reflections.md")
    if refl_file.exists():
        n = sum(1 for l in refl_file.read_text(encoding="utf-8").splitlines() if l.startswith("## ["))
        print(f"    [检查] reflections.md 现有 {n} 条反思")

    # ---------- 场景 4：表扬 → 技能（M8） ----------
    print("\n■ 场景 4｜M8 技能库：满意并让记下讲法")
    r4 = chat("这个下山类比特别好！把这种讲法记到技能库里。", sid)
    report("M8-save_skill", r4)
    skill_file = Path("memory/skills.md")
    if skill_file.exists():
        n = sum(1 for l in skill_file.read_text(encoding="utf-8").splitlines() if l.startswith("## ["))
        print(f"    [检查] skills.md 现有 {n} 条技能")

    # ---------- 场景 5：跨会话记忆回忆（M2 核心） ----------
    print("\n■ 场景 5｜M2 跨会话回忆：新会话问'我怎么学习'")
    r5 = chat("新的一天。问你个事：你觉得我适合什么样的学习方式？回忆一下我的偏好。")
    report("M2-回忆", r5)
    print("    [观察] 回答是否引用'类比/先直觉'偏好（search_memory/画像注入）")

    # ---------- 场景 6：知识库（M3 工具） ----------
    print("\n■ 场景 6｜M3 知识库：让模型把资料存进知识库再检索（走服务端，与真实用户一致）")
    r6 = chat("给你一段我的笔记，存进我的知识库：『动量法（Momentum）让梯度下降像滚球一样：如果球一直往一个方向滚，就给它加速；如果方向反复横跳，就被平均掉。更新公式在原有梯度上叠加历史的梯度方向。』", sid)
    report("M3-kb_ingest", r6)
    r6b = chat("我的知识库里关于动量法说了什么？", sid)
    report("M3-kb_search", r6b)
    print("    [观察] ingest 与 search 是否都走 kb_* 工具")

    # ---------- 场景 7：督促（M6） ----------
    print("\n■ 场景 7｜M6 督促：安排提醒")
    r7 = chat("明天早上 9 点提醒我复习梯度下降，别让我鸽了。", sid)
    report("M6-schedule", r7)
    import sqlite3
    try:
        conn = sqlite3.connect("data/wakeups.db")
        rows = conn.execute("SELECT status, at, reason FROM wakeups ORDER BY created_at DESC LIMIT 1").fetchall()
        for st, at, reason in rows:
            print(f"    [检查] wakeups: {st} | {at} | {reason[:30]}")
        conn.close()
    except Exception as e:
        print(f"    [检查] wakeups 读取受限（沙箱）：{type(e).__name__}")

    # ---------- 场景 8：多 agent（M7） ----------
    print("\n■ 场景 8｜M7 多 agent：拆任务并行研究")
    r8 = chat("帮我系统学梯度下降的变体（SGD/动量/Adam），拆成独立子任务并行研究，然后整合成一份对比总结。", sid)
    report("M7-deleg", r8)
    print("    [观察] 是否 deleg_study（工具内并行子 agent）")

    # ---------- 场景 9：学习日志 + streak（M6） ----------
    print("\n■ 场景 9｜M6 学习日志：学完记一笔")
    r9 = chat("今天把梯度下降学完了，帮我记录一下。", sid)
    report("M6-log", r9)
    try:
        conn = sqlite3.connect("data/wakeups.db")
        streak = conn.execute("SELECT COUNT(*) FROM daily_activity").fetchone()[0]
        print(f"    [检查] daily_activity {streak} 天")
        conn.close()
    except Exception as e:
        print(f"    [检查] daily_activity 读取受限（沙箱）：{type(e).__name__}")

    # ---------- 场景 10：反思是否注入新回答（M8 进化闭环） ----------
    print("\n■ 场景 10｜M8 进化验证：再问一个易踩'术语'的问题，看是否按反思改进")
    r10 = chat("学习率是什么？给我讲讲。", sid)
    report("M8-进化", r10)
    print("    [观察] 回答是否刻意'先直觉、带检查点、不堆术语'（反思注入生效的证据）")

    print("\n" + "=" * 60)
    print("旅程结束。汇总各里程碑信号见上方 [检查]/[观察] 标注")
    print("=" * 60)


if __name__ == "__main__":
    main()
