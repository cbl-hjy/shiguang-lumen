"""LLM 响应缓存（2026-08-21 harness 加厚：规避重复提问的成本浪费）。

原则（用户纲领：harness 做厚=规避犯错损失，不约束 agent，不做死约束）：
- 只缓存"纯问答轮"（无工具调用、无上传文件）的 (用户消息, 模型回复)
- 命中条件保守：语义相似度 > 0.97（几乎重复才命中——用户重复问同一问题，如学习时"再说一遍"）
- 命中回复带"（缓存回复）"标记——信息给觉察（用户/模型知道这是缓存）
- 不命中就照常调用模型（缓存只是可能加分项，不是必须命中——不做死约束）
- 24h 时效 + 容量上限（防陈旧/膨胀）
"""
import json
import math
import time
from pathlib import Path

from app.config import DATA_DIR

CACHE_FILE = DATA_DIR / "data" / "llm_cache.jsonl"
SIM_THRESHOLD = 0.97   # 保守：语义几乎重复才命中（避免错误缓存）
TTL_SECONDS = 24 * 3600  # 24h 时效（学习场景当天重复问）
MAX_ENTRIES = 300       # 容量上限


def _query_vec(text: str) -> list[float]:
    from app.memory.vector import embed

    return embed([text])[0]


def _cos(a: list[float], b: list[float]) -> float:
    n1 = math.sqrt(sum(x * x for x in a))
    n2 = math.sqrt(sum(y * y for y in b))
    if not n1 or not n2:
        return 0.0
    return sum(x * y for x, y in zip(a, b)) / (n1 * n2)


def lookup(user_text: str) -> str | None:
    """查缓存：命中返回带标记的回复（觉察）；否则 None（照常调模型）。"""
    try:
        qv = _query_vec(user_text)
    except Exception:
        return None
    if not CACHE_FILE.exists():
        return None
    best: tuple[float, str] | None = None
    now = time.time()
    for line in CACHE_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            d = json.loads(line)
            if now - d.get("ts", 0) > TTL_SECONDS:
                continue
            sim = _cos(qv, d.get("vec", []))
            if sim >= SIM_THRESHOLD:
                if best is None or sim > best[0]:
                    best = (sim, d.get("reply", ""))
        except Exception:
            continue
    if best and best[1]:
        return f"（缓存回复——你之前问过类似的问题，这是当时的回答）\n{best[1]}"
    return None


def store(user_text: str, reply: str) -> None:
    """存缓存（仅纯问答轮——调用方保证无工具调用）。失败静默（缓存是加分项不是必须）。"""
    try:
        if len(user_text) < 8 or not reply:
            return
        vec = _query_vec(user_text)
        entry = {"text": user_text[:200], "vec": vec, "reply": reply[:2000], "ts": time.time()}
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with CACHE_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        # 容量控制：超限截断（保留最近 MAX_ENTRIES 条）
        lines = CACHE_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
        if len(lines) > MAX_ENTRIES:
            CACHE_FILE.write_text("\n".join(lines[-MAX_ENTRIES:]) + "\n", encoding="utf-8")
    except Exception:
        pass
