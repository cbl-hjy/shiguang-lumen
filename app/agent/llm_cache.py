"""LLM 响应缓存（2026-08-21 harness 加厚；2026-08-27 B5 升级：阈值分级 + TTL 分级 + prompt_version 失效；
2026-08-31 P1：行级 uid 隔离——多用户下 A 的语义命中不得串到 B）。

原则（用户纲领：harness 做厚=规避犯错损失，不约束 agent，不做死约束）：
- 只缓存"纯问答轮"（无工具调用、无上传文件）的 (用户消息, 模型回复)
- 阈值分级（调研 llmbestpractices/truefoundry/llmwiki 共识 0.92-0.97）：
  · SIM_STRICT 0.97 —— 代码/数学/精确定义（答案唯一，误命中代价高）→ TTL 7 天
  · SIM_MID    0.95 —— 事实问答默认 → TTL 24h
  · SIM_LOOSE  0.92 —— 闲聊/FAQ 换问法（容忍轻微误命中）→ TTL 30min（宽松命中要求条目更新鲜）
- 命中回复带标记（信息给觉察）；0.92 档额外标"低置信"——用户/模型知道这是缓存
- prompt_version 失效：系统提示词变更 → 整组缓存跳过（业界：prompt 变更勿只靠 TTL）
- 不命中就照常调用模型（缓存只是可能加分项，不做死约束）；容量上限防膨胀
- uid 隔离（2026-08-31 P1）：条目带 uid，lookup 只命中同 uid 条目；
  legacy 无 uid 条目视作 uid=None——对登录用户永不命中（可能是任何人的，命中=串数据），
  对未登录请求保留单用户 legacy 行为；旧条目不迁移，靠 TTL+容量自然出清
"""

import json
import math
import time
from pathlib import Path

from app.config import DATA_DIR

CACHE_FILE = DATA_DIR / "data" / "llm_cache.jsonl"

# 测试注入点（对齐 learning._LEDGER_OVERRIDE / error_loop._LEDGER_OVERRIDE 惯例：
# 钩子优先于默认路径，测试零侵入生产路径）
_CACHE_OVERRIDE: Path | None = None


def _cache_path() -> Path:
    return _CACHE_OVERRIDE if _CACHE_OVERRIDE is not None else CACHE_FILE

# 阈值分级（B5 2026-08-27，调研依据见模块 docstring）
SIM_STRICT = 0.97  # 精确档：代码/数学/定义
SIM_MID = 0.95  # 标准档：事实问答
SIM_LOOSE = 0.92  # 宽松档：闲聊/FAQ 换问法
TTL_STRICT = 7 * 24 * 3600  # 精确档 7 天
TTL_MID = 24 * 3600  # 标准档 24h
TTL_LOOSE = 30 * 60  # 宽松档 30min（宽松命中要求更新鲜）
MAX_ENTRIES = 300  # 容量上限


def _prompt_version() -> str:
    """当前系统提示词版本（缓存失效键之一——prompt 变更整组失效）。"""
    try:
        from app.routers.observability import prompt_version

        return prompt_version()
    except Exception:
        return "v0"


def _query_vec(text: str) -> list[float]:
    from app.memory.vector import embed

    return embed([text])[0]


def _cos(a: list[float], b: list[float]) -> float:
    n1 = math.sqrt(sum(x * x for x in a))
    n2 = math.sqrt(sum(y * y for y in b))
    if not n1 or not n2:
        return 0.0
    return sum(x * y for x, y in zip(a, b, strict=True)) / (n1 * n2)


def _ttl_for(sim: float) -> int:
    """按相似度落档 TTL：越宽松的命中要求条目越新鲜（B5 调研：TTL 由内容易变性驱动）。"""
    if sim >= SIM_STRICT:
        return TTL_STRICT
    if sim >= SIM_MID:
        return TTL_MID
    return TTL_LOOSE


def lookup(user_text: str) -> str | None:
    """查缓存：命中返回带标记的回复（觉察）；否则 None（照常调模型）。"""
    try:
        qv = _query_vec(user_text)
    except Exception:
        return None
    path = _cache_path()
    if not path.exists():
        return None
    from app.auth_core import get_current_user_id

    uid = get_current_user_id()  # None=未登录 legacy
    best: tuple[float, str, str] | None = None  # (sim, reply, tag)
    now = time.time()
    pv = _prompt_version()
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            d = json.loads(line)
            # uid 隔离（P1）：只命中同 uid 条目；无 uid 字段的 legacy 条目视作 None
            # ——对登录用户永不命中（可能是任何人的，命中=串数据），对未登录请求保留 legacy 行为
            if d.get("uid") != uid:
                continue
            # prompt_version 失效（B5）：版本不匹配整组跳过（勿只靠 TTL）
            if d.get("pv", "v0") != pv:
                continue
            sim = _cos(qv, d.get("vec", []))
            # 分级命中：低于最宽松档不命中；命中则按档位检查该条目的新鲜度
            if sim < SIM_LOOSE:
                continue
            ttl = _ttl_for(sim)
            if now - d.get("ts", 0) > ttl:
                continue
            if best is None or sim > best[0]:
                tag = "（缓存回复——你之前问过类似的问题，这是当时的回答）"
                if sim < SIM_MID:
                    tag = "（缓存回复·低置信——问法相近但未必同义，仅供参考；不放心可重新问）"
                best = (sim, d.get("reply", ""), tag)
        except Exception as _ce:
            print(f"[llm_cache] 跳过坏缓存行: {_ce}", file=__import__('sys').stderr)
            continue
    if best and best[2]:
        return f"{best[2]}\n{best[1]}"
    return None


def store(user_text: str, reply: str) -> None:
    """存缓存（仅纯问答轮——调用方保证无工具调用）。失败静默（缓存是加分项不是必须）。"""
    try:
        if len(user_text) < 8 or not reply:
            return
        vec = _query_vec(user_text)
        from app.auth_core import get_current_user_id

        entry = {
            "text": user_text[:200],
            "vec": vec,
            "reply": reply[:2000],
            "ts": time.time(),
            "pv": _prompt_version(),  # B5：prompt 版本键
            "uid": get_current_user_id(),  # P1：行级 uid 隔离（None=未登录 legacy）
        }
        path = _cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        # 容量控制：超限截断（保留最近 MAX_ENTRIES 条）
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        if len(lines) > MAX_ENTRIES:
            path.write_text("\n".join(lines[-MAX_ENTRIES:]) + "\n", encoding="utf-8")
    except Exception as _e:
        print(f"[agent/llm_cache] 静默异常已可见化: {_e}", flush=True)
