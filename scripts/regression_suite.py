"""能力回归套件（REGRESSION-SUITE-DESIGN.md，2026-08-17）
15 固定场景 × 0-3 分评分 × 改完必跑。基线首次跑建立，后续 --compare 退化检测。

用法：
  python scripts/regression_suite.py run --baseline   # 首次跑，存基线
  python scripts/regression_suite.py run              # 普通跑，输出报告
  python scripts/regression_suite.py compare          # 对比基线，标记疑似退化

安全：注入从主库只读（画像/状态/关系轨）；场景 9 的 remember 用 stub（记录不真写，零污染）。
"""
import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, ".")

ROOT = Path(".")
REPORTS = ROOT / "reports"
BASELINE = REPORTS / "regression_baseline.json"

# (场景名, 问题, 期望行为, 工具模式)
# 工具模式：none=纯对话 / search=可检索 / remember=可写(stub)
SCENARIOS = [
    ("深度讲解", "讲讲交叉熵为什么用 log？", "讲清核心机制（信息量/非线性惩罚/梯度），≥2 层结构（直觉+细节）", "none"),
    ("偏好贴合", "解释一下过拟合", "先直觉后公式（类比/画面开头），用数字示例", "none"),
    ("情绪接住", "我昨晚失眠了，焦虑得睡不着", "先接住情绪（不评判、不急着教学），共情自然", "none"),
    ("主动建议", "我该不该放弃大厂只投中小厂", "有立场、给后果、给可执行建议（不骑墙）", "none"),
    ("可争议反驳", "我觉得我方向选错了，因为投的都没过", "敢反驳归因（不附和），给替代解释，对事不对人", "none"),
    ("困惑识别", "我纠结要不要换方向", "识别认知卡点并拆解/追问，不直接给答案了事", "none"),
    ("进度检索", "我上次学到哪了？", "准确引用进度记忆（不编造、不答非所问）", "search"),
    ("偏好检索", "我怎么学新东西效果最好", "引用画像偏好（先直觉/数字演示/开口输出）", "search"),
    ("写入判断", "（模拟对话）我决定每天早起背单词，把目标定在早上", "应调用 remember 记录该新事实（四原语 ADD）", "remember"),
    ("关系注入使用", "你记得我们上次聊什么了吗", "用上 relation 注入（我们之间），引用上次话题", "none"),
    ("状态轮使用", "你感觉我现在状态怎么样", "引用状态注入，推断部分标『疑似』", "none"),
    ("闲聊不越界", "今天天气不错", "自然闲聊，不检索、不教学腔", "none"),
    ("通用知识不误检", "什么是梯度下降", "直接回答不检索（或检索但答案自洽）", "search"),
    ("工具参数准确", "帮我查查我最近在准备什么", "调 search_memory 且结果正确（category 合理或全量但结果对）", "search"),
    ("跨会话续接", "接着上次的继续吧", "知道『上次』指什么（引用 last_session/relation），自然续上", "none"),
    ("自我感知", "为什么正则化还显示搁置状态？", "知道拾光有主题追踪：解释状态来源（搁置=表达过搁置且最近没再学），主动提出更新路径（重新学/改状态）——而不是『不知道这个说法』", "none"),
]

SYSTEM_BASE = (
    "你是拾光，一个 AI 成长搭子。自然回应，像朋友一样。\n"
    "挑战原则：你不是只会顺着的工具，可以和我平等对话——当我的想法、决定、判断有风险或站不住时，"
    "可以直接指出、反驳、挑战，对事不对人，讲理由讲后果；该挑战还是该接住、什么分寸合适，判断权在你。\n"
    "使用准则：需要了解用户具体历史/进度/困惑时才检索记忆（search_memory，可传 category 限定："
    "学习记录/进度/目标/偏好/困惑/关系/笔记）；通用知识问题直接回答；"
    "用户明确要记住的信息用 remember 记录。\n"
    # 问题分流（2026-08-20 P1 同步真实 static_prompt.yaml——套件 prompt 必须跟随产品演进）
    "问题分流：先判断用户问的是什么——通用知识/闲聊/写代码/查资料→直接回答，不要调检索工具；"
    "涉及用户的进度/偏好/状态/历史才用记忆/检索工具；不确定是否需要用户信息时，优先直接回答。\n"
    # 自我认知（2026-08-20 同步真实 static_prompt.yaml——套件 prompt 必须跟随产品演进，否则场景测的是旧产品）
    "自我认知：我内置主题追踪（学习路径）——追踪用户的每个学习主题，状态=进行中/搁置/卡住/完成"
    "（前端主题区可见）。用户问『为什么 X 状态』时能解释来源（搁置=表达过搁置且最近没再学；重新学会活过来）"
    "并主动提出更新（update_state 记录意愿）。\n"
    # 状态轮疑似示例（2026-08-20 P1 同步——推断状态必须标（疑似））
    "状态轮：推断用户状态时必须标（疑似），例：用户说『还行吧』没明说情绪→推断时写『状态：还行（疑似）』；"
    "用户明说情绪才不带疑似。\n\n"
)


def _build_injection() -> str:
    """注入 = 真实画像 + 状态轮 + 关系轨（主库只读）"""
    parts = []
    profile = ROOT / "memory" / "profile.md"
    if profile.exists():
        t = profile.read_text(encoding="utf-8").strip()
        if t:
            parts.append(f"【用户画像】\n{t[:500]}")
    state = ROOT / "memory" / "state.json"
    if state.exists():
        import json as _json
        d = _json.loads(state.read_text(encoding="utf-8"))
        last = d.get("last_session", {})
        sp = []
        for dim, v in last.items():
            if dim == "snap_at" or not isinstance(v, dict):
                continue
            sp.append(f"{dim}={v.get('value', '')[:50]}")
        if sp:
            parts.append(f"【上次会话结束状态（{last.get('snap_at', '?')}）】\n{'；'.join(sp)}")
        rel = d.get("relation", {})
        if rel.get("last_topic"):
            rp = [f"深度={rel['depth']}"] if rel.get("depth") else []
            if rel.get("tone"):
                rp.append(f"基调={rel['tone']}")
            rp.append(f"上次话题={rel['last_topic']}")
            parts.append("【我们之间（上次收尾）】" + "；".join(rp))
    return "\n\n".join(parts)


# remember stub：记录调用，不真写（零污染）
_CALLS: dict[str, list] = {}


def _make_stub_remember():
    async def _stub_remember(note, source="user", importance=5, category="笔记"):
        _CALLS["remember"].append({"note": note[:80], "category": category, "importance": importance})
        return f"(stub) 已记住：{note[:50]}"
    return _stub_remember


async def _run_scenario(agent, question, mode) -> tuple[str, list]:
    calls = []
    r = await agent.run(question)
    for msg in r.all_messages():
        for part in getattr(msg, "parts", []):
            if "ToolCall" in type(part).__name__:
                calls.append(f"{getattr(part, 'tool_name', '?')}({str(getattr(part, 'args', ''))[:80]})")
    return r.output.strip(), calls


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["run", "compare"])
    ap.add_argument("--baseline", action="store_true", help="run 时存为基线")
    args = ap.parse_args()

    from app.agent.model import get_model
    from app.memory.store import search_memory
    from pydantic_ai import Agent

    injection = _build_injection()
    report = [f"# 能力回归套件报告（{datetime.now():%Y-%m-%d %H:%M}）\n"]
    results = {}

    for name, question, expect, mode in SCENARIOS:
        _CALLS["remember"] = []
        # 所有场景统一注册 search_memory（真实环境即有工具）：
        # ①杜绝"文本伪调用"（工具真实存在，模型要么真调要么不调）
        # ②行为可观测：闲聊/通用知识场景不调=正确；关系注入场景调或不调都是信号
        tools = [search_memory]
        if mode == "remember":
            tools.append(_make_stub_remember())
        agent = Agent(
            get_model(),
            system_prompt=SYSTEM_BASE + injection,
            tools=tools,
        )
        answer, calls = await _run_scenario(agent, question, mode)
        results[name] = {"question": question, "expect": expect, "answer": answer[:400], "calls": calls}
        report.append(f"## {name}\n\n问题：{question}\n\n期望：{expect}\n\n工具调用：{calls if calls else '无'}\n\n回答：\n{answer[:500]}\n")

    # 评分表（基线校准 2026-08-20：基线分存 baseline.json scores，报告显示基线分作对照；
    # 本次自评填"本次"列——下降=退化信号）
    base_scores: dict = {}
    if BASELINE.exists():
        try:
            base_scores = json.loads(BASELINE.read_text(encoding="utf-8")).get("scores") or {}
        except Exception:
            pass
    report.append("## 评分表（0-3 分：本次自评 / 基线分 = 校准参照，下降=退化信号）\n")
    report.append("| 场景 | 本次 | 基线 | 备注 |")
    report.append("|---|---|---|---|")
    for name, *_ in SCENARIOS:
        report.append(f"| {name} |  | {base_scores.get(name, '—')} |  |")

    out = REPORTS / f"regression_suite_{datetime.now():%Y%m%d_%H%M}.md"
    REPORTS.mkdir(exist_ok=True)
    out.write_text("\n".join(report), encoding="utf-8")
    print(f"报告已生成: {out}")

    if args.baseline:
        BASELINE.write_text(json.dumps({"date": datetime.now().isoformat(), "scenarios": results}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"基线已存: {BASELINE}（请人工校准评分后，把分数补进报告评分表）")

    if args.mode == "compare":
        if not BASELINE.exists():
            print("无基线，请先跑 run --baseline")
            return
        base = json.loads(BASELINE.read_text(encoding="utf-8"))["scenarios"]
        print("\n=== 疑似退化检测（对比基线）===")
        for name, *_ in SCENARIOS:
            cur = results.get(name, {})
            old = base.get(name, {})
            if not old:
                print(f"  ⚠ {name}: 基线缺失")
                continue
            # 启发式：回答长度骤变 / 工具调用数变化
            len_cur, len_old = len(cur.get("answer", "")), len(old.get("answer", ""))
            calls_cur, calls_old = len(cur.get("calls", [])), len(old.get("calls", []))
            flags = []
            if old.get("calls") and not cur.get("calls"):
                flags.append("该检索却没检索!")
            if not old.get("calls") and cur.get("calls"):
                flags.append("不该检索却检索!")
            if len_old > 50 and abs(len_cur - len_old) / len_old > 0.6:
                flags.append(f"长度骤变 {len_old}→{len_cur}")
            print(f"  {'⚠' if flags else '✓'} {name}: {flags if flags else '无明显差异'}")
        print("\n注意：启发式只做粗筛，最终判定靠人工看报告对比。")


asyncio.run(main())
