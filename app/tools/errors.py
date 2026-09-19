"""工具错误标准化（2026-08-17，行业标准参考 OpenAI/Anthropic 工具错误分类）：
统一格式：(错误|错误域|错误码|原因[|修复建议])

错误码分类（模型据此判断"可重试 vs 不可重试"）：
- ARG    参数/输入错误     → 不可重试（改参数）
- IO     文件/路径错误     → 不可重试（检查路径）
- NET    网络错误          → 可重试（稍后重试）
- TIMEOUT 超时            → 可重试（缩小范围/稍后）
- TOOL   工具内部错误      → 可重试（工具自身故障）
- UNKNOWN 未知            → 保守（重试或告知）

统一格式让模型一眼区分：可重试错误（重试/换法）vs 不可重试（告知用户/改参数）。
"""


def tool_error(domain: str, code: str, reason: str, hint: str = "") -> str:
    parts = f"(错误|{domain}|{code}|{reason}"
    if hint:
        parts += f"|{hint}"
    return parts + ")"


def arg_error(domain: str, reason: str, hint: str = "检查输入后重试") -> str:
    return tool_error(domain, "ARG", reason, hint)


def io_error(domain: str, reason: str, hint: str = "检查路径/文件后重试") -> str:
    return tool_error(domain, "IO", reason, hint)


def net_error(domain: str, reason: str, hint: str = "稍后重试") -> str:
    return tool_error(domain, "NET", reason, hint)


def timeout_error(domain: str, reason: str, hint: str = "缩小范围或稍后重试") -> str:
    return tool_error(domain, "TIMEOUT", reason, hint)


def tool_err(domain: str, reason: str, hint: str = "稍后重试") -> str:
    return tool_error(domain, "TOOL", reason, hint)
