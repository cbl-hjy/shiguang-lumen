# -*- coding: utf-8 -*-
"""先贤会议 · 会议引擎（M1 骨架）

编排 = 代码 round-robin（固定圆桌顺序，无需 Manager 选人——[C2] AutoGen 借鉴）；
判定 = 主持人 agent 单调用 LLM-as-judge（[C1] RedDebate evaluator + [R8] 单调用最稳）；
停止 = 四层：天花板(max_rounds) / 边际收益(主持人) / 强制收敛轮 / 发言软预算递减；
只读：全程不写记忆不改状态，落盘 data/debates/<id>.jsonl（错误天然零损失）。

CLI: python -m app.council.engine "问题" --sages influence,poor [--max-rounds 2]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import time
from pathlib import Path
from typing import AsyncIterator

from pydantic_ai import Agent, UsageLimits

from app.agent.model import get_model
from app.config import DATA_DIR
from app.council.models import DebateRecord, DebateReport, DebateTurn, ModeratorVerdict, SageCard

SAGES_DIR = DATA_DIR / "data" / "sages"
DEBATES_DIR = DATA_DIR / "data" / "debates"

# 停止四层参数（设计共识 §4；预算按轮次比例递减）
MAX_ROUNDS_DEFAULT = 4
WORD_BUDGETS = {1: 400, 2: 150, 3: 120, 4: 100}  # 首轮充分立论，后续只说增量
SAGE_LIMITS = UsageLimits(request_limit=12, total_tokens_limit=24000)  # 2026-08-21 二次加宽：request 8→12、total 16000→24000（培根树落库后树证据更长，星宿翻树工具循环仍偶发超限——verification-deep-20260821 笛卡尔第1/2轮失败实证）
JUDGE_LIMITS = UsageLimits(request_limit=5, total_tokens_limit=8000)

SAGE_RULES = (
    "你是一位星宿，受邀参加一场围绕用户问题的跨领域研讨会。\n"
    "你的发言必须严格遵循三明治结构：\n"
    "1. 锚点：先直接回应用户的问题/困境（“针对你说的 X，我的看法是……”）——不是回应书，是回应人。\n"
    "2. 交锋：再回应上一位发言者的最强论点（“上一位说的 Y 有道理，但它的边界是……”）。第一轮没有上一位可省略。\n"
    "3. 来源：最后落回你代表的书的证据（“这在《书》中表现为……”）。\n"
    "硬性规则：\n"
    "- 只使用你立场卡里的观点与证据，绝不编造书里没有的内容。\n"
    "- 必须锚在用户问题上，禁止离题；可以自由交锋，但围绕问题本身。\n"
    "- 本轮是第 {round} 轮：{increment_hint}\n"
    "- 发言不超过 {budget} 字，直接输出内容，不要标题、不要客套。\n"
)

# 有树星宿的工具使用规则（2026-08-20 工具化：无树星宿不拼接——避免误导模型调必空工具）
TREE_TOOL_RULES = (
    "- 你有一个只读工具 query_tree（翻阅你自己代表的书）：需要书的具体证据/案例/原文时就先检索再发言，"
    "可按不同关键词多次检索；检索到多个相关簇时也可多次调用。\n"
    "- 发言的证据只能来自立场卡或 query_tree 的检索结果——检索失败/为空时只用立场卡内容，绝不编造书中没有的原文。\n"
)

JUDGE_RULES = (
    "你是跨领域研讨会的主持人，无立场。你只做元判断，不产出观点内容。\n"
    "基于用户问题、本轮全部发言与上一轮判定，输出 JSON（不要输出任何其他内容）：\n"
    "{\"repeated\": 是否重复观点(true/false), \"off_topic\": 是否离题(true/false), "
    "\"new_claims\": 新增有效观点数(整数), \"marginal_gain\": 边际收益(true/false, new_claims>=1), "
    "\"should_converge\": 是否建议收敛(true/false, 连续一轮无新观点即 true), "
    "\"notes\": \"简短批注(一两句话, 供用户看到判定过程)\"}\n"
    "判定口径：- repeated: 本轮出现已提出过的重复观点(展开新证据不算重复) "
    "- off_topic: 有发言脱离用户问题 - new_claims: 新观点/新证据/新反驳计数"
)

FINAL_REPORT_RULES = (
    "你是跨领域研讨会的主持人，无立场。现在会议结束，请基于用户问题与全部发言输出 JSON（不要输出任何其他内容）：\n"
    "{\"actionable\": [对用户的问题可行动的结论/建议/取舍, 最重要放前面], "
    "\"consensus\": [共识点], \"divergences\": [分歧点(各自立场)], "
    "\"complementarities\": [互补点(不同领域互相补全)], "
    "\"unanswered\": [未解答或证据不足的问题(诚实标注)]}\n"
    "每条不超过 60 字。actionable 至少 2 条（收益判定铁律：无收益的会议不允许结束）。"
)

# ---------- 模式差异化（2026-08-20：deep 同源深挖=聚焦分歧定位，主持人/报告规则按 mode 微调）----------
JUDGE_RULES_DEEP = (
    "你是同一领域内部研讨的主持人，无立场。两位星宿来自同一领域但方法论对立（如理性演绎 vs 经验归纳）。"
    "你只做元判断，不产出观点内容。\n"
    "基于用户问题、本轮全部发言与上一轮判定，输出 JSON（不要输出任何其他内容）：\n"
    "{\"repeated\": 是否重复观点(true/false), \"off_topic\": 是否离题(true/false), "
    "\"new_claims\": 新增有效观点数(整数), \"marginal_gain\": 边际收益(true/false, new_claims>=1), "
    "\"should_converge\": 是否建议收敛(true/false, 连续一轮无新观点即 true), "
    "\"notes\": \"简短批注(一两句话，必须指明：本轮分歧点在哪、各方论据是什么——分歧定位是核心职责)\"}\n"
    "判定口径：- repeated: 本轮出现已提出过的重复观点(展开新证据不算重复) "
    "- off_topic: 有发言脱离用户问题 - new_claims: 新观点/新证据/新反驳计数。"
    "收敛标准比跨领域模式更宽容（同领域分歧值得多轮交锋，不应过早收敛）。"
)

FINAL_REPORT_RULES_DEEP = (
    "你是同一领域内部研讨的主持人，无立场。会议结束，请基于用户问题与全部发言输出 JSON（不要输出任何其他内容）：\n"
    "{\"actionable\": [对用户的问题可行动的结论/建议/取舍, 最重要放前面], "
    "\"consensus\": [共识点], "
    "\"divergences\": [分歧点——必须详述分歧内核: 各自论据+分歧根源(如方法论对立), 这是本模式的核心产出], "
    "\"complementarities\": [互补点(方法论对立中可互相补全之处)], "
    "\"unanswered\": [未解答或证据不足的问题(诚实标注)]}\n"
    "每条不超过 60 字。actionable 至少 2 条；divergences 必须给出分歧根源（不只是立场不同，要说清为什么不同）。"
)


def _extract_json(text: str) -> dict | None:
    """从模型输出中提取 JSON 对象（DeepSeek thinking 模式无 output_type，纯文本+解析是项目惯例）"""
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


# ---------- 星笺加载 ----------
def load_sages(ids: list[str]) -> list[SageCard]:
    sages: list[SageCard] = []
    for sid in ids:
        p = SAGES_DIR / f"{sid}.json"
        if not p.exists():
            raise FileNotFoundError(f"星笺不存在：{p}（可先跑 scripts/council_recompose.py 生成）")
        sages.append(SageCard.model_validate(json.loads(p.read_text(encoding="utf-8"))))
    return sages


# ---------- 星宿发言 ----------
def _sage_prompt(card: SageCard, round_no: int, budget: int, has_tree: bool = False) -> str:
    hint = "第一轮，充分立论。" if round_no == 1 else "前面已经说过的不要复述，只补充新观点（增量）。"
    block = f"{card.stance_block()}\n\n{SAGE_RULES.format(round=round_no, budget=budget, increment_hint=hint)}"
    if has_tree:
        # 工具使用规则插在"硬性规则"之后（2026-08-20：有树才挂工具，才告知工具存在）
        block = block.replace("硬性规则：", "硬性规则：\n" + TREE_TOOL_RULES, 1)
    return block


def _make_tree_tool(sage_id: str, counter: dict | None = None):
    """query_tree 的只读工具变体（闭包绑 sage_id）——星宿翻自己的书。
    无树/检索失败返回友好提示，模型自然降级纯立场卡（不抛错不中断=错误影响最小化）。
    counter（观察机制 2026-08-20）：跨工具调用累计本轮次数，供 turn 事件带 tool_calls 算调用率。"""
    from app.council.raptor import query_tree

    async def query_my_tree(question: str, top_k: int = 3) -> str:
        """翻阅你自己代表的书，检索与问题相关的证据簇（含原文关键句）。返回证据文本；检索不到返回提示。"""
        if counter is not None:
            counter["calls"] = counter.get("calls", 0) + 1
        try:
            hits = await query_tree(question, sage_id, top_k=max(1, min(top_k, 5)))
        except Exception as e:
            print(f"⚠ [{sage_id}] 树检索失败: {e}", flush=True)
            return "(检索失败——本次发言请只用立场卡里的观点与引用)"
        if not hits:
            return "(你的书暂无检索结果——本次发言请只用立场卡里的观点与引用)"
        return "\n".join(f"· [{h['score']}] {h['text']}" for h in hits)

    query_my_tree.__name__ = f"query_tree_{sage_id}"
    return query_my_tree


def _build_sage_agent(card: SageCard, round_no: int, budget: int, counter: dict | None = None) -> Agent:
    """星宿 agent（2026-08-20 工具化）：有树→挂 query_tree 只读工具+工具规则；无树→纯立场卡（动态不挂，省 schema token）。"""
    from app.council.raptor import load_tree

    has_tree = load_tree(card.id) is not None
    if has_tree:
        return Agent(get_model(), system_prompt=_sage_prompt(card, round_no, budget, True),
                     tools=[_make_tree_tool(card.id, counter)])
    return Agent(get_model(), system_prompt=_sage_prompt(card, round_no, budget, False))


def _sage_input(question: str, history: list[DebateTurn]) -> str:
    parts = [f"用户的问题：{question}"]
    if history:
        parts.append("\n前面已发生的发言（按顺序）：")
        for t in history:
            parts.append(f"[第{t.round}轮·{t.sage_name}]{t.speech[:180]}")
    else:
        parts.append("\n（你是第一位发言者）")
    return "\n".join(parts)


async def _speak(card: SageCard, question: str, history: list[DebateTurn], round_no: int) -> DebateTurn | None:
    budget = WORD_BUDGETS.get(round_no, 100)
    # 2026-08-20 工具化：不再预注入证据——星宿自己调 query_tree 翻阅自己的书（纯自主检索）
    counter: dict = {"calls": 0}  # 观察机制：本轮工具调用计数
    agent = _build_sage_agent(card, round_no, budget, counter)
    try:
        r = await agent.run(_sage_input(question, history), usage_limits=SAGE_LIMITS)
    except Exception as e:
        # 2026-08-20 缺陷 A 降级：模型默认 180s 单次调用超时——超时/异常不中断会议，
        # 该星宿该轮跳过（错误影响最小化：会议继续，其余星宿照常）
        msg = f"[{card.id}] 第{round_no}轮发言失败（{type(e).__name__}），跳过: {str(e)[:120]}"
        print(f"⚠ {msg}", flush=True)
        # 2026-08-21 可观测性补洞：uvicorn stdout 不落盘，失败原因丢了（笛卡尔第1/2轮失败只能靠猜）——
        # 失败详情写 data/logs/council_errors.log，下次直接看根因
        try:
            logf = DATA_DIR / "data" / "logs" / "council_errors.log"
            logf.parent.mkdir(parents=True, exist_ok=True)
            with open(logf, "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {msg}\n")
        except Exception:
            pass
        return None
    # 成本台账（天下大同：谁调用都记同一文件；失败静默——成本觉察非主流程）
    _council_token(f"council_sage:{card.id}", r)
    speech = r.output.strip()
    return DebateTurn(round=round_no, sage_id=card.id, sage_name=card.name, speech=speech,
                      words=len(speech), tool_calls=counter.get("calls", 0))


# ---------- 主持人 ----------
def _judge_rules(mode: str) -> str:
    return JUDGE_RULES_DEEP if mode == "deep" else JUDGE_RULES


def _report_rules(mode: str) -> str:
    return FINAL_REPORT_RULES_DEEP if mode == "deep" else FINAL_REPORT_RULES


async def _judge(question: str, turns: list[DebateTurn], prev: ModeratorVerdict | None,
                 mode: str = "cross") -> ModeratorVerdict:
    agent = Agent(get_model(), system_prompt=_judge_rules(mode))
    inp = f"用户问题：{question}\n\n本轮发言：\n"
    for t in turns[-3:]:  # 只看本轮（最多 3 位星宿）
        inp += f"[{t.sage_name}]{t.speech[:300]}\n"
    if prev:
        inp += f"\n上一轮判定：new_claims={prev.new_claims}, repeated={prev.repeated}"
    r = await agent.run(inp, usage_limits=JUDGE_LIMITS)
    _council_token("council_judge", r)  # 成本台账（2026-08-20 观察机制）
    data = _extract_json(r.output)
    if not data:
        print("⚠ 主持人判定解析失败，按继续处理（fail loud）")
        return ModeratorVerdict(notes="（判定解析失败）")
    return ModeratorVerdict.model_validate(data)


async def _final_report(question: str, turns: list[DebateTurn], mode: str = "cross") -> DebateReport:
    agent = Agent(get_model(), system_prompt=_report_rules(mode))
    inp = f"用户问题：{question}\n\n全部发言：\n"
    for t in turns:
        inp += f"[第{t.round}轮·{t.sage_name}]{t.speech[:250]}\n"
    for attempt in (1, 2):  # 可重试一次（综合报告是收尾产品，失败影响大）
        r = await agent.run(inp, usage_limits=JUDGE_LIMITS)
        _council_token("council_report", r)  # 成本台账（2026-08-20 观察机制）
        data = _extract_json(r.output)
        if data:
            return DebateReport.model_validate(data)
        print(f"⚠ 综合报告解析失败（第 {attempt} 次），重试")
    return DebateReport(actionable=["（综合报告生成失败——请直接阅读上方原始发言）"], unanswered=[question])


def _council_token(sid: str, r) -> None:
    """星宿/主持人/报告共用成本入账（失败静默——成本觉察非主流程）。"""
    try:
        from app import observability as obs
        obs.token_usage(sid, getattr(r, "usage", None))
    except Exception:
        pass


# ---------- 编排 ----------
def _announce(record: DebateRecord, sages: list[SageCard]) -> None:
    est_in = 3000 + len(sages) * 800 * record.max_rounds
    est_out = sum(WORD_BUDGETS.get(r, 100) for r in range(1, record.max_rounds + 1)) * len(sages) * 1.5
    print("📋 会议预算告知")
    print(f"  星宿：{len(sages)} 位（{' × '.join(s.name for s in sages)}）")
    print(f"  轮数上限：{record.max_rounds}（观点穷尽即止）｜模式：{record.mode}")
    print(f"  预计 token：输入 ~{est_in//1000}K + 输出 ~{int(est_out)//1000}K ≈ {(est_in+int(est_out))//1000}K")
    print(f"  预计成本：≈ ¥{(est_in+int(est_out))*0.000002:.3f}-{((est_in+int(est_out))*2)*0.000004:.3f}（可随时中止）\n")


# 用户停止标记（进程级；API 的 /stop 端点置位，流式循环每轮检查——harness 层，不是 prompt）
_STOP_FLAGS: dict[str, bool] = {}


def stop_debate(debate_id: str) -> None:
    _STOP_FLAGS[debate_id] = True


def _budget_event(sages: list[SageCard], max_rounds: int, debate_id: str) -> dict:
    est_in = 3000 + len(sages) * 800 * max_rounds
    est_out = sum(WORD_BUDGETS.get(r, 100) for r in range(1, max_rounds + 1)) * len(sages) * 1.5
    total = est_in + int(est_out)
    return {
        "type": "budget",
        "debate_id": debate_id,  # 前端凭此 id 才能调 /stop（2026-08-19 测试抓出的缺字段）
        "sages": [s.name for s in sages],
        "max_rounds": max_rounds,
        "est_tokens_k": total // 1000,
        "est_cost": f"¥{total*0.000002:.3f}-{total*0.000004:.3f}",
    }


async def stream_debate(question: str, sage_ids: list[str], max_rounds: int = MAX_ROUNDS_DEFAULT,
                        debate_id: str | None = None, mode: str = "cross") -> AsyncIterator[dict]:
    """会议引擎流式版（SSE 用）：yield 事件字典，全程只读。
    事件：budget / round_start / turn / verdict / converged / report / stopped / done
    mode：deep 用分歧聚焦版主持人/报告规则（2026-08-20 模式差异化）"""
    sages = load_sages(sage_ids)
    did = debate_id or f"d-{int(time.time())}"
    yield _budget_event(sages, max_rounds, did)

    prev_verdict: ModeratorVerdict | None = None
    all_turns: list[DebateTurn] = []
    for round_no in range(1, max_rounds + 1):
        if _STOP_FLAGS.get(did):
            yield {"type": "stopped", "debate_id": did}
            return
        yield {"type": "round_start", "round": round_no}
        for card in sages:
            turn = await _speak(card, question, all_turns, round_no)
            if turn is None:
                # 2026-08-20 缺陷 A：星宿发言失败（超时/异常）→ 跳过不中断会议
                yield {"type": "error", "message": f"{card.name} 第{round_no}轮发言失败（超时或异常），已跳过", "debate_id": did}
                continue
            all_turns.append(turn)
            yield {"type": "turn", "round": round_no, "sage_id": card.id,
                   "sage_name": card.name, "speech": turn.speech, "words": turn.words,
                   "tool_calls": turn.tool_calls}  # 观察机制：工具调用率数据源（SSE 全量持久化）
        verdict = await _judge(question, all_turns, prev_verdict, mode)
        prev_verdict = verdict
        yield {"type": "verdict", "round": round_no, **verdict.model_dump()}
        if verdict.should_converge:
            yield {"type": "converged", "reason": "marginal_gain"}
            break
    else:
        yield {"type": "converged", "reason": "max_rounds"}

    if _STOP_FLAGS.get(did):  # 收敛报告前最后检查一次
        yield {"type": "stopped", "debate_id": did}
        _STOP_FLAGS.pop(did, None)  # B10 清理（2026-08-20：防只增不删泄漏）
        return
    report = await _final_report(question, all_turns, mode)
    yield {"type": "report", **report.model_dump()}
    yield {"type": "done", "debate_id": did}
    _STOP_FLAGS.pop(did, None)  # B10 清理（2026-08-20）


async def run_debate(question: str, sage_ids: list[str], max_rounds: int = MAX_ROUNDS_DEFAULT) -> DebateRecord:
    """CLI/内部用：消费 stream_debate 组装 DebateRecord（保留打印与落盘）"""
    sages = load_sages(sage_ids)
    record = DebateRecord(
        id=f"d-{int(time.time())}",
        question=question,
        sages=[s.id for s in sages],
        max_rounds=max_rounds,
    )
    _announce(record, sages)
    async for ev in stream_debate(question, sage_ids, max_rounds, record.id):
        t = ev["type"]
        if t == "turn":
            record.turns.append(DebateTurn(round=ev["round"], sage_id=ev["sage_id"],
                                           sage_name=ev["sage_name"], speech=ev["speech"], words=ev["words"],
                                           tool_calls=ev.get("tool_calls", 0)))
            print(f"\n◈ {ev['sage_name']}（{ev['words']}字）\n{ev['speech']}")
        elif t == "verdict":
            v = ModeratorVerdict.model_validate(ev)
            record.verdicts.append(v)
            print(f"\n☞ 主持人：新增观点 {v.new_claims}｜重复 {v.repeated}｜离题 {v.off_topic}｜{v.notes}")
        elif t == "converged":
            record.ended_reason = "converged" if ev["reason"] == "marginal_gain" else "max_rounds"
            print(f"（主持人判定观点已穷尽，提前进入综合报告）" if ev["reason"] == "marginal_gain"
                  else "（到达轮数上限，进入综合报告）")
        elif t == "report":
            record.report = DebateReport.model_validate(ev)
        elif t == "stopped":
            record.ended_reason = "user_stop"
            print("（已按用户要求中止）")
    if record.report:
        _print_report(record.report)
    DEBATES_DIR.mkdir(parents=True, exist_ok=True)
    (DEBATES_DIR / f"{record.id}.json").write_text(
        record.model_dump_json(indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return record


def _print_report(r: DebateReport) -> None:
    print("\n\n📄 综合报告（用户裁决前为候选，不入记忆）")
    print("【对你有用的结论】")
    for x in r.actionable:
        print(f"  • {x}")
    print("\n【共识】")
    for x in r.consensus:
        print(f"  • {x}")
    print("\n【分歧】")
    for x in r.divergences:
        print(f"  • {x}")
    print("\n【互补】")
    for x in r.complementarities:
        print(f"  • {x}")
    if r.unanswered:
        print("\n【未解答/证据不足】")
        for x in r.unanswered:
            print(f"  • {x}")


async def _main() -> None:
    ap = argparse.ArgumentParser(description="先贤会议引擎（M1 骨架）")
    ap.add_argument("question", help="用户问题/困境")
    ap.add_argument("--sages", default="influence,poor", help="星宿 id 列表，逗号分隔")
    ap.add_argument("--max-rounds", type=int, default=2, help="轮数上限（M1 验证建议 2）")
    args = ap.parse_args()
    record = await run_debate(args.question, [s.strip() for s in args.sages.split(",") if s.strip()], args.max_rounds)
    if record.report:
        _print_report(record.report)
    print(f"\n（会议记录已落盘：{DEBATES_DIR / (record.id + '.json')}）")


if __name__ == "__main__":
    asyncio.run(_main())
