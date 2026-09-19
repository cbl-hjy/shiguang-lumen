"""通用验证器（P0-2 2026-08-27，自进化把关轴——对齐 LLM-as-a-Verifier 三档 CR + SkillForge 职责分离）。

设计依据（research/2026-08-27-self-evolution-research.md 共识 + 模型+harness 协同调研）：
- 定位：harness 把关（给 pass/fail 信号）+ 结果对模型可见可查（trace/上下文）——不是暗箱，不约束模型输出
- 三档 Consistent/Partial/Inconsistent（对齐 SkillForge Strict CR）；criteria 按任务类型分解（对齐 Verifier 三轴）
- 防自证：独立评审角色 prompt + 固定标准 + 只给 task+candidate（不给模型思维链）——评审视角与生成视角分离
- 输出结构化（grade/score/reason/issues）供归因/回灌使用；obs.hook 留痕观测台可见

用法：
  v = await verify("讲解列表推导式", "列表推导式是……", mode="teach")
  v.grade in ("consistent", "partial", "inconsistent")
"""
import json
import re

from pydantic_ai import Agent

from app import observability as obs
from app.agent.model import get_model

# criteria 按任务类型分解（对齐 LLM-as-a-Verifier criteria 分解轴）
CRITERIA = {
    "teach": [
        ("准确性", "核心概念/结论是否正确，有无错误或误导"),
        ("完整性", "是否覆盖问题核心（不只是开头），关键点有无遗漏"),
        ("可执行性", "给出的方法/步骤用户能否照着做"),
    ],
    "code": [
        ("Spec 符合", "是否满足任务的功能要求"),
        ("Output 正确", "输出/结果是否正确（边界、异常）"),
        ("Errors 处理", "错误处理与失败场景是否覆盖"),
    ],
    "tool": [
        ("参数", "工具参数是否正确/必要"),
        ("结果", "返回结果是否真实可用（有无谎报/幻觉）"),
        ("副作用", "有无意外副作用（重复执行/污染）"),
    ],
    "general": [
        ("准确性", "内容是否正确，有无错误或误导"),
        ("完整性", "是否完整回应，关键点有无遗漏"),
    ],
}

# 评审角色 prompt（防自证：与生成视角分离的严格第三方评审）
_JUDGE_SYSTEM = """你是严格的第三方评审员（评审视角与生成视角分离——不偏袒、不自证）。
对给定的「任务 + 候选回答」，按评审标准逐条评估，输出 JSON：
{"grade": "consistent|partial|inconsistent", "score": 0-100, "reason": "一句话总评",
 "issues": [{"point": "违反/不足的标准名", "detail": "具体问题定位（引用原文片段，≥1 条，无则空数组）"}]}
档位定义：
- consistent：全部标准通过，或仅轻微可忽略问题（score>=80）
- partial：部分标准通过，有明显缺陷但方向正确（50<=score<80）
- inconsistent：关键标准不通过/答非所问/方向错误（score<50）
注意（防过度严格——校准 2026-08-27）：回答**简洁但正确完整**应判 consistent，不因未展开细节/未举例而降级；
只有"关键点缺失/错误"才降级。
只输出 JSON，不要多余文字。"""


async def verify(
    task: str,
    candidate: str,
    mode: str = "teach",
    criteria: list[tuple[str, str]] | None = None,
    run_id: str = "",
) -> dict:
    """验证候选回答/产出（harness 把关轴）。返回 {grade, score, reason, issues, criteria}。"""
    cs = criteria or CRITERIA.get(mode, CRITERIA["general"])
    # temperature=0（校准做精 2026-08-27）：验证器必须稳定——LLM 验证的判定波动
    # （同用例不同轮次漂移 84.6-92.3%）用确定性采样收紧（验证属确定性不变量，非创意任务）
    judge = Agent(
        get_model(),
        system_prompt=_JUDGE_SYSTEM,
        model_settings={"temperature": 0},
    )
    criteria_txt = "\n".join(f"- {name}：{desc}" for name, desc in cs)
    inp = f"【任务】\n{task[:1500]}\n\n【候选回答】\n{candidate[:4000]}\n\n【评审标准】\n{criteria_txt}\n"
    try:
        r = await judge.run(inp)
        data = _extract_json(r.output)
    except Exception as e:
        # 验证器失败：fail-loud（记录 + 返回 unknown 档，不阻塞主流程）
        if run_id:
            obs.hook(run_id, "verify", False, f"verifier 异常: {str(e)[:80]}")
        return {"grade": "unknown", "score": None, "reason": f"验证器异常: {str(e)[:60]}", "issues": [], "criteria": cs}
    if not data:
        if run_id:
            obs.hook(run_id, "verify", False, "verifier 输出解析失败")
        return {"grade": "unknown", "score": None, "reason": "验证器输出解析失败", "issues": [], "criteria": cs}
    data["criteria"] = cs
    if run_id:
        obs.hook(run_id, "verify", True, f"grade={data.get('grade')} score={data.get('score')}")
    return data


def _extract_json(text: str) -> dict | None:
    """从模型输出提取 JSON（容忍包裹/前缀）。"""
    if not text:
        return None
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
        return d if isinstance(d, dict) else None
    except Exception:
        return None


# ---------- 工具化（P0+P1 做精 2026-08-27）：模型可自主调用的验证工具 ----------
# 红线：控制流归模型——工具可选调用（不强制自动验证每个回答，成本+约束双避）；
# harness 侧不替模型判定"何时该验证"，由模型在重要输出后自查（对齐协同调研：harness 供能力，模型决定用不用）。


async def verify_answer(task: str, answer: str, mode: str = "teach") -> str:
    """验证一条回答/产出的质量（三档+缺陷定位）。重要讲解/代码/工具结果输出后建议自查——
    返回 consistent（通过）/ partial（部分通过，附缺陷）/ inconsistent（未通过，附缺陷），
    模型可据此自我修订后再交付。mode: teach(讲解)/code(代码)/tool(工具结果)。"""
    v = await verify(task, answer, mode=mode)
    grade = v.get("grade", "unknown")
    score = v.get("score")
    reason = v.get("reason", "")
    issues = v.get("issues", [])
    lines = [f"验证结果：{grade}（{score}/100）——{reason}"]
    if issues:
        lines.append("缺陷定位：")
        for it in issues[:3]:
            lines.append(f"- {it.get('point', '')}: {it.get('detail', '')[:80]}")
    if grade == "consistent":
        lines.append("可以交付；若想更稳可针对 issues 精修。")
    elif grade == "partial":
        lines.append("建议针对上述缺陷修订后重验。")
    else:
        lines.append("建议重写——方向或关键点不通过。")
    return "\n".join(lines)

