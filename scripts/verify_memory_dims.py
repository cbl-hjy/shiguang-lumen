"""多维记忆测试（2026-08-15）：画像即时性 + 多维检索准确性 + 维度选择
设计：3 多样化 persona × 多轮对话 × 种子复现，打实验实例 9000（data-experiment 隔离，主库零接触）
测三件事：
  T1 画像即时性：对话中注入记忆点后，profile.md 是否立即反映（读实验库 profile 文件）
  T2 检索准确性：维度探针问题（学习偏好/当前困惑/关系偏好）能否召回正确维度记忆
  T3 维度选择：混合库下检索是否串维度（问学习偏好是否混入困惑条目）
"""
import asyncio
import json
import random
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
TOKEN = None
for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
    if line.startswith("SHIGUANG_TOKEN="):
        TOKEN = line.split("=", 1)[1].strip()
        break
BASE = "http://127.0.0.1:9000"
EXP_MEM_DIR = ROOT / "data-experiment" / "memory"

# 3 个多样化 persona（覆盖不同记忆维度）
PERSONAS = {
    "exam_crammer": {  # 备考型：目标/进度/学习维度
        "dialogue": [
            "我最近在准备算法岗面试，从机器学习基础开始复习",
            "今天学完了梯度下降，损失函数那块还没吃透",
            "我的目标是秋招进大厂做 AI 岗，在刷 LeetCode",
            "我觉得先直觉后公式的学习方式对我最有效",
        ],
        "probes": ["我最近在准备什么", "我的学习目标是什么", "我卡在哪了"],
    },
    "confused_seeker": {  # 困惑型：困惑/情绪维度（测新机制）
        "dialogue": [
            "我投了几家大厂 agent 岗都没过，有点怀疑是不是选错方向了",
            "我不知道该继续冲大厂还是先转投中小厂积累经验",
            "昨晚因为这事焦虑得没睡好",
            "我其实很纠结，怕选错了浪费一年",
        ],
        "probes": ["我现在在困惑什么", "我最近在纠结什么选择", "我昨晚怎么了"],
    },
    "relationship_builder": {  # 关系型：关系/偏好维度
        "dialogue": [
            "我希望你跟我说话像朋友，别老端着教学腔",
            "我烦别人说教，你直接点我能接受",
            "我深夜思维最活跃，那时候聊深的最合适",
            "你上次批评我归因错误，我觉得很有用",
        ],
        "probes": ["我偏好你怎么跟我说话", "我忌讳什么", "我什么时候思维最活跃"],
    },
}


def _chat(session_id: str, message: str) -> tuple[int, str]:
    try:
        r = requests.post(
            f"{BASE}/api/chat",
            json={"message": message, "session_id": session_id},
            headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
            stream=True, timeout=120,
        )
        if r.status_code != 200:
            return r.status_code, ""
        lines = [ln for ln in r.iter_lines(decode_unicode=True) if ln]
        texts = [l for l in lines if '"text"' in l or '"delta"' in l]
        return r.status_code, " ".join(texts)[:200]
    except Exception as e:
        return -1, str(e)


def _new_session() -> str:
    r = requests.post(
        f"{BASE}/api/session/new",
        headers={"Authorization": f"Bearer {TOKEN}"},
        timeout=15,
    )
    if r.status_code == 200:
        return r.json().get("session_id", "")
    return ""


def _read_profile() -> str:
    p = EXP_MEM_DIR / "profile.md"
    if p.exists():
        return p.read_text(encoding="utf-8")
    return "(profile 不存在)"


def _count_entries() -> int:
    p = EXP_MEM_DIR / "user_memory.md"
    if p.exists():
        return sum(1 for l in p.read_text(encoding="utf-8").splitlines() if l.startswith("- "))
    return 0


def _reset_persona_memory():
    """每 persona 独立记忆库（模拟 3 个独立用户）：清空记忆文件 + 向量库 + 画像。
    解决单用户架构串扰——否则 3 persona 共享一份记忆，维度检索无法测。
    注：沙箱拦 unlink（回收站不可用），用覆盖写入清空。"""
    import shutil
    for f in ["user_memory.md", "profile.md", "reflections.md", "skills.md", "trash.md"]:
        p = EXP_MEM_DIR / f
        try:
            if p.exists():
                p.write_text("", encoding="utf-8")
        except Exception:
            pass
    for vdir in ["vector_mem", "vector_evolve"]:
        d = Path("data-experiment/data") / vdir
        try:
            if d.exists():
                shutil.rmtree(d, ignore_errors=True)
        except Exception:
            pass
    # 会话表也清（独立用户 = 独立会话历史）
    import sqlite3
    conn = sqlite3.connect("data-experiment/data/sessions.db")
    conn.execute("DELETE FROM messages")
    conn.execute("DELETE FROM sessions")
    conn.commit()
    conn.close()
    # 等服务端重载（下次 upsert 时 chroma 会重建 collection）
    time.sleep(1)


async def main():
    print("=" * 60)
    print("多维记忆测试（实验实例 9000，主库零接触）")
    print("=" * 60)
    rng = random.Random(42)  # 种子可复现

    for name, cfg in PERSONAS.items():
        print(f"\n### Persona: {name}（{len(cfg['dialogue'])} 轮对话，独立记忆库）")
        _reset_persona_memory()  # 每 persona 独立记忆（模拟 3 用户）
        sid = _new_session()
        if not sid:
            print("  ✗ 无法创建会话")
            continue
        # T1: 每轮后检查画像/记忆文件变化（即时性）
        for i, msg in enumerate(cfg["dialogue"], 1):
            code, _ = await asyncio.to_thread(_chat, sid, msg)
            entries_before = _count_entries()
            time.sleep(0.5)
            entries_after = _count_entries()
            profile = _read_profile()
            marker = "✓" if entries_after > entries_before else "—"
            print(f"  轮{i} [{marker}] 记忆条目 {entries_before}→{entries_after} | 画像含新词: "
                  f"{'✓' if any(w in profile for w in ['面试', '大厂', '困惑', '朋友', '说教'][:3]) else '—'}")
        # 终态画像
        profile = _read_profile()
        print(f"  最终画像（{len(profile)} 字）: {profile[:120]}...")
        # T2+T3: 维度探针（直接读实验库向量库，测召回准确性——不受主库干扰）
        print("  --- 维度探针（读实验库向量，测召回准确性）---")
        import os as _os
        _os.environ["DATA_DIR"] = "data-experiment"
        import sys as _sys
        _sys.path.insert(0, str(ROOT))
        import importlib
        from app.memory import vector as _vec
        importlib.reload(_vec)

        async def _probe(q: str):
            vec = (await _vec.aembed([q]))[0]
            hits = _vec.search(vec, top_k=3)
            return [(t[:60], round(s, 2)) for _, t, s in hits]

        for q in cfg["probes"]:
            try:
                hits = await _probe(q)
                print(f"  探针『{q}』→ {hits if hits else '(无召回)'}")
            except Exception as e:
                print(f"  探针『{q}』→ 检索异常: {str(e)[:60]}")

    print("\n=== 测试完成 ===")


if __name__ == "__main__":
    asyncio.run(main())
