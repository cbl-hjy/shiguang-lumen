"""会话压缩核心逻辑（Phase 2 C-1，2026-08-29）：长会话早期历史 → 锚定增量摘要。

升级对象：chat.py 现有 compaction（2026-08-17 状态保鲜 1.0——自由文本摘要 + 全量重建）。
本模块补上前沿机制（2026-08-29 调研）：
- Claude Code auto-compact：78-83.5% 窗口触发、保留最近 8-10 轮原文、摘要作续会消息；
  社区实测提前到 60-70% 触发压缩质量更高
- LangMem running summary：增量合并不重建（max_tokens_before_summary）
- Chroma context rot：30K token 后模型性能开始下降——压缩对抗 context rot
- JetBrains 2508.21433：摘要抹平"卡住"信号 → 多跑 15% 无效轮次——失败/停滞信号强制保留
- Anthropic compaction 文档：触发下限防短会话抖动；缓存保护（压缩不破坏前缀缓存）

拾光决策（128K 窗口 + 166 轮静默失效案例）：
- 触发：历史估算 > 60K token（约 47% 窗口）且距上次压缩增量 > 20K（防抖防频繁打断缓存）
- 保留：最近 ~14K token 原文（现有 COMPACT_TAIL_CHARS=20K 字符 ≈ 10-15 轮，Claude Code 共识）
- 增量：已有纪要 JSON + 新片段 → LLM 合并更新（不重建）
- 注入：四字段纪要渲染后作 history 前缀 system 消息（压缩后 history 稳定，缓存重新积累）
- 可见：摘要以 JSON 存 sessions.summary（B2 兜底/读链零改动），UI「它记得我」渲染成结构化纪要

纪律（红线）：触发归代码（阈值/防抖锁死为确定性不变量）；内容归模型（LLM 自由提炼，
模板只约束四字段结构）；失败静默不阻断主流程（幂等重试）。

兼容：DB 旧摘要（自由文本）解析失败 → 视为无 prev（重新生成，不报错）。
"""

from __future__ import annotations

import json
from typing import Any, Callable

from app.prompts.loader import extractor_prompt

# ---- 确定性不变量（触发归代码，锁死） -------------------------------------
COMPACT_TRIGGER_TOKENS = 60_000  # 历史估算超此值触发（47% 窗口；旧版 90K 字符≈63K token，语义一致）
COMPACT_MIN_DELTA_TOKENS = 20_000  # 距上次压缩至少再积累这么多（防抖，防频繁打断前缀缓存）
CJK_TOKEN_PER_CHAR = 0.7  # 中文 0.6-0.7 token/字（阈值启发式，不需要 tiktoken 精确）
SUMMARY_MAX_CHARS = 450  # 纪要总长上限（注入预算管控）
SUMMARY_FIELDS = ("goal", "decisions", "open", "entities")


def estimate_tokens(text: str) -> int:
    """轻量 token 估算：中文 0.7 token/字。"""
    if not text:
        return 0
    return int(len(text) * CJK_TOKEN_PER_CHAR)


def estimate_history_tokens(history: list[Any], msg_len: Callable[[Any], int]) -> int:
    """整段历史 token 估算（msg_len=字符粗估函数，调用方注入复用现有实现）。"""
    return int(sum(msg_len(m) for m in history) * CJK_TOKEN_PER_CHAR)


def should_compact(
    est_tokens: int,
    stored_raw: str | None,
) -> bool:
    """触发判断（确定性规则）：
    ① 历史估算 > 60K token（远离 90K+ 静默失效区与 110K 硬限）
    ② 距上次压缩增量 > 20K（防抖——压缩后需再积累才允许二次压缩）
    """
    if est_tokens <= COMPACT_TRIGGER_TOKENS:
        return False
    prev = parse_stored(stored_raw)
    if prev:
        last_tokens = int(prev.get("tokens_at_compact", 0) or 0)
        if est_tokens - last_tokens < COMPACT_MIN_DELTA_TOKENS:
            return False
    return True


def parse_stored(raw: str | None) -> dict[str, Any] | None:
    """解析 DB 里存的纪要：新版 JSON（四字段）→ dict；旧版自由文本/坏数据 → None（重新生成）。"""
    if not raw:
        return None
    try:
        d = json.loads(raw)
        if isinstance(d, dict) and any(d.get(k) for k in SUMMARY_FIELDS):
            return d
    except Exception:
        # 旧版自由文本/坏数据 → 视为无 prev（重新生成），静默属预期路径
        return None
    return None


def render_summary(meta: dict[str, Any]) -> str:
    """纪要 dict → 注入文本（history 前缀 system 消息用；无内容字段返回空串）。"""
    lines: list[str] = []
    if meta.get("goal"):
        lines.append(f"目标：{meta['goal']}")
    if meta.get("decisions"):
        lines.append("已决定：" + "；".join(meta["decisions"]))
    if meta.get("open"):
        lines.append("未完成/卡住：" + "；".join(meta["open"]))
    if meta.get("entities"):
        lines.append("重要对象：" + "、".join(meta["entities"]))
    if not lines:
        return ""
    return (
        "（以下是与你的更早对话纪要，历史已压缩——涉及早期细节拿不准时可以直接问用户）\n"
        + "\n".join(lines)
    )


def summarize_span(prev_raw: str | None, span_text: str, llm: Callable[[str, str], str | None]) -> dict[str, Any] | None:
    """LLM 增量合并：prev 纪要 + 新片段 → 四字段 JSON（内容归模型，模板只约束结构）。

    失败 → None（幂等，调用方下次重试）。
    """
    prev = parse_stored(prev_raw)
    prev_json = (
        json.dumps({k: prev.get(k) for k in SUMMARY_FIELDS if prev.get(k)}, ensure_ascii=False)
        if prev
        else "（无）"
    )
    prompt = extractor_prompt("compact")
    if not prompt:
        return None
    # 模板槽位：{prev} / {span}（extractors.yaml 里定义的动态槽位约定）
    user_msg = prompt.replace("{prev}", prev_json).replace("{span}", span_text)
    if user_msg == prompt:  # 模板无槽位（fallback 兜底形态）——直接拼接
        user_msg = f"{prompt}\n\n【已有纪要】\n{prev_json}\n\n【新对话片段】\n{span_text}"
    try:
        raw = llm(user_msg, "")
        if not raw:
            return None
        # 剥代码围栏（LLM 偶发输出 ```json ... ```）
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```", 2)[1].lstrip("json").strip()
        d = json.loads(raw)
        if not isinstance(d, dict):
            return None
        return {
            "goal": str(d.get("goal", "")).strip(),
            "decisions": [str(x).strip() for x in (d.get("decisions") or []) if str(x).strip()],
            "open": [str(x).strip() for x in (d.get("open") or []) if str(x).strip()],
            "entities": [str(x).strip() for x in (d.get("entities") or []) if str(x).strip()],
        }
    except Exception:
        return None


def build_stored_json(meta: dict[str, Any], covered_rounds: int, est_tokens: int) -> str:
    """纪要 + 元数据 → 落库 JSON 字符串（sessions.summary）。"""
    return json.dumps(
        {
            **meta,
            "covered_rounds": covered_rounds,  # 累计覆盖消息条数（UI 展示）
            "tokens_at_compact": est_tokens,  # 防抖基准
            "version": 2,
        },
        ensure_ascii=False,
    )


# ---------- chat.py 迁入（Phase 4 A-2，2026-08-29：compaction 区整体并入，纯移动） ----------

from app.db import sessions as _sessions
from pydantic_ai.messages import ModelRequest, SystemPromptPart


def history_to_text(history) -> str:
    """ModelMessage 列表 → 可读对话文本（供摘要 LLM 输入）"""
    lines = []
    for m in history:
        for p in getattr(m, "parts", []):
            pn = type(p).__name__
            if pn == "UserPromptPart":
                lines.append(f"用户：{p.content}")
            elif pn == "SystemPromptPart":
                lines.append(f"系统：{p.content}")
            elif pn == "TextPart":
                lines.append(f"AI：{p.content}")
            elif pn == "ToolCallPart":
                lines.append(f"[工具调用：{p.tool_name}]")
            elif pn == "ToolReturnPart":
                lines.append(f"[工具返回：{str(p.content)[:80]}]")
    return "\n".join(lines)


def _summarize(conversation_text: str) -> str | None:
    """独立 LLM 调用生成学习向摘要（Pi compaction 的摘要步骤）；失败返回 None（幂等，下次重试）。

    ⚠️ 2026-08-29 Phase2 C-1：本函数仅保留为兼容垫片（外部引用防断），
    新压缩链路走 summarize_span（四字段增量合并）→ llm_compact。
    """
    return llm_compact(conversation_text, "")


def llm_compact(user_msg: str, system_hint: str) -> str | None:
    """C-1 压缩 LLM 调用（summarize_span 注入）：四字段增量合并。
    独立 openai 调用（不依赖 pydantic-ai Agent，轻量）；失败返回 None（幂等，下次重试）。"""
    try:
        from openai import OpenAI

        from app.config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL

        client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
        system = (
            system_hint
            or "你是会话纪要合并器。只输出 JSON（严格四字段：goal/decisions/open/entities），不要解释，不要输出其他。"
        )
        resp = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_msg[-40000:]},
            ],
            max_tokens=800,
            temperature=0.3,
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception:
        return None


def msg_len(m) -> int:
    """单条消息文本字符粗估（尾部保留预算用）"""
    total = 0
    for p in getattr(m, "parts", []):
        pn = type(p).__name__
        if pn in ("UserPromptPart", "SystemPromptPart", "TextPart"):
            total += len(getattr(p, "content", "") or "")
        elif pn == "ThinkingPart":
            total += len(getattr(p, "content", "") or "")
        elif pn == "ToolCallPart":
            total += len(getattr(p, "tool_name", "") or "") + 40
        elif pn == "ToolReturnPart":
            total += len(str(getattr(p, "content", "") or "")) // 2
    return total


def apply_compaction(sid: str, history, uid: str | None = None):
    """长程 compaction（C-1 升级版，2026-08-29：锚定增量摘要）：
    - 已压缩 → [四字段纪要 system 消息, ...尾部保留消息]
    - 未压缩且超阈值 → 增量合并生成纪要并存储，同样构建
    - 触发（归代码，锁死）：历史估算 > 60K token 且距上次压缩增量 > 20K（防抖）
    - 失败幂等（纪要生成失败返回原 history，下次重试）；未超阈值原样返回
    返回 (history, est)——est 供预算感知分级注入
    """
    if not history:
        return history, 0
    stored = _sessions.get_summary(sid, uid)
    est = sum(msg_len(m) for m in history)
    est_tokens = estimate_history_tokens(history, msg_len)
    if not should_compact(est_tokens, stored):
        return history, est
    print(
        f"[compaction] 会话 {sid[:8]} 触发：est≈{est_tokens} token（阈值 60K token）",
        flush=True,
    )
    # 划分：尾部保留（字符预算 + 用户回合开头保证——2026-08-17 设计，保持）→ 更早的压成纪要
    tail, used = [], 0
    for m in reversed(history):
        ml = msg_len(m)
        if tail and used + ml > COMPACT_TAIL_CHARS:
            break
        tail.append(m)
        used += ml
    tail.reverse()
    while tail and type(tail[0]).__name__ == "ModelResponse":
        tail.pop(0)
    span = history[: len(history) - len(tail)] if len(history) > len(tail) else []
    if not span:
        return history, est  # 全量都在尾部预算内（异常态），不压
    # 增量合并（内容归模型）：prev 纪要 + 本次片段 → 四字段 JSON；失败幂等下次重试
    meta = summarize_span(stored, history_to_text(span), llm_compact)
    if not meta:
        return history, est
    prev_meta = parse_stored(stored)
    covered = int(prev_meta.get("covered_rounds", 0) or 0) if prev_meta else 0
    summary_json = build_stored_json(meta, covered + len(span), est_tokens)
    _sessions.set_summary(sid, summary_json, uid)
    # #5 存储 O(n²)→O(n)：压缩成功即清空旧 messages_json（保留 MAX(id) 行=重放源；归档失败不阻塞）
    _sessions.clear_old_chains(sid, uid)
    rendered = render_summary(meta)
    print(
        f"[compaction] 会话 {sid[:8]} 已压缩 {len(span)} 条 → 纪要（累计覆盖 {covered + len(span)} 条，"
        f"goal={meta.get('goal', '')[:20] or '无'}）",
        flush=True,
    )
    prefix = ModelRequest(
        parts=[
            SystemPromptPart(
                content=(
                    f"（以下是与你的更早对话纪要，历史已压缩，继续本轮：）\n{rendered}"
                    "\n\n（纪要可能不完整，涉及早期细节拿不准时可以直接问用户）"
                )
                if rendered
                else "（与你的更早对话已压缩，继续本轮；早期细节拿不准时可以直接问用户）"
            )
        ]
    )
    return [prefix] + tail, est


# 尾部保留预算（chat.py 迁入，保持原值）
COMPACT_TAIL_CHARS = 20_000
