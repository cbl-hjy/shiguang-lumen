"""画像客观性护栏（2026-08-19，适配自 DeepTutor guards.py——不纯手搓，参考其模式）。

DeepTutor 原版：L3 op 发出时运行时拦截 BANNED_PHRASES（绝对化/情绪化词），
命中丢弃 + 警告日志（"prompt 后过滤是静默丢弃，op 发出时拦截模型能收到反馈改写"）。

适配说明（我们的差异）：
- DeepTutor 拦 ops（小粒度，可单条丢弃）；我们画像是一次生成整段文本 → 拦截点改为
  update_profile 写入前检查，命中则【拒绝写入 + 警告】——旧画像保留，下次记忆变化自然重提炼
- 引号豁免保留：用户原话（「…」/ "…"）可含绝对化词（可能是用户真话），剥离后检查
- 对应哲学"判断无墙，不变量无口"：禁绝对化是确定性不变量（代码拦），不是判断
"""

import re

# 绝对化/情绪化词表（参考 DeepTutor 中文表 + 我们的画像语境——规律性断言无证据时会命中）
# 命中 = 该断言可能是"把一次当规律"的过度泛化，拒绝写入画像
BANNED_PHRASES: tuple[str, ...] = (
    # 绝对化（无证据的强断言）
    "总是",
    "从来不",
    "从不",
    "永远",
    "所有",
    "每次",
    "一直",
    "从不",
    "彻底",
    "完全",
    "深刻",
    "完美",
    "百分之百",
    "绝对",
    # 情绪化（画像不该有强情绪词，除非用户原话在引号内）
    "热爱",
    "讨厌",
    "厌恶",
    "痛恨",
    "极其喜欢",
    "极度",
)

# 引号豁免：用户原话可含上述词（用户可能真说"我每次都想要例子"）
_QUOTED_RE = re.compile(r"「[^」]*」|\"[^\"]*\"")


def has_banned(text: str) -> bool:
    """文本是否含禁止词（剥离引号后检查）。True=命中（应拒绝写入）。"""
    stripped = _QUOTED_RE.sub("", text or "")
    return any(p in stripped for p in BANNED_PHRASES)


def banned_hits(text: str) -> list[str]:
    """返回命中的禁止词列表（用于日志/反馈，可调词表的依据）。"""
    stripped = _QUOTED_RE.sub("", text or "")
    return [p for p in BANNED_PHRASES if p in stripped]
