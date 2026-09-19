# -*- coding: utf-8 -*-
"""深度学习工具面（2026-08-27 HARNESS-V2）——机制在 harness，模型自主调用。

设计原则（调研依据：Harvard RCT 2025 / Dunlosky 2013 / Sal Khan / DeepTutor mastery）：
- 工具是"可用能力"不是"强制流程"——模型自己判断何时出题/批改/提醒复习
- mastery 台账只记录（attempt+结果），**绝不门控**（不强制"答对才前进"——反 Synthesis 式约束）
- 间隔信号只提供信息（"上次练 X 天前"），提醒与否归模型判断
- 证据最强机制落地：主动回忆（练习/测验）+ 分散练习（间隔信号）+ 挑战-接住（出题含挑战模式）
"""

import json
from datetime import datetime

from app.config import DATA_DIR
from app.auth_core import get_current_user_id
from app.user_data import get_user_data_dir
from pathlib import Path


# 测试注入点（2026-08-30，对齐 wakeups._DB_OVERRIDE / topics_store._TOPICS_OVERRIDE 惯例）：
# 存量测试从模块常量注入迁到这里，避免测试写项目根真实台账。
_LEDGER_OVERRIDE: Path | None = None


def MASTERY_LEDGER() -> Path:
    if _LEDGER_OVERRIDE is not None:
        return _LEDGER_OVERRIDE
    uid = get_current_user_id()
    if uid:
        return get_user_data_dir(uid) / "mastery.jsonl"
    return DATA_DIR / "data" / "mastery.jsonl"


# 掌握判定的唯一口径（2026-08-30 R1）：只有 judge=="对" 算掌握，"部分对"不算。
# 改造前三处口径互不相同——spacing 认"部分对"、mastery 与 /api/learning/mastery 不认，
# 且三处都认一个 prompt 从不输出的"完全对"死值 → 同一份台账算出两个正答率。
# 收敛到一个函数：任何"算不算掌握"的判断都必须走这里，禁止再写 in (...) 字面量。
JUDGE_CORRECT = "对"


def _is_correct(rec: dict) -> bool:
    """掌握判定的唯一入口（R1）：judge=="对" → True；"部分对"/"不对"/空/乱值 → False。

    spacing_signal / mastery_signal / routers.learning 三处必须都调它——
    口径分散是这一层最贵的债（同一份数据两个正答率，且事后无法回溯哪个是对的）。

    2026-08-30 R8 兜底：实践轨永不参与掌握判定。
    实践记录没有对错，只有证据；哪怕模型漏字段、把 judge="对" 写进了一条实践记录，
    也不许它抬高正答率——那等于把"用户自述的证据"当成了"成绩"。

    2026-08-30 teach-back：teach_back 记录同样永不参与掌握判定——
    它是"用户教 AI"的角色扮演台账，没有对错可判；哪怕手改台账塞了 judge="对"，
    也不许一次角色扮演抬高正答率。
    """
    if str(rec.get("type", DEFAULT_LEDGER_TYPE)) in (LEDGER_TYPE_PRACTICE, LEDGER_TYPE_TEACH_BACK):
        return False
    return str(rec.get("judge", "")).strip() == JUDGE_CORRECT


# 样本量封顶（2026-08-30 R1b）：答对 1 次就报 100% 是虚高信号——样本太小，比率不代表水平。
# 只压低【报告值】，绝不门控任何行为（本文件头部红线：台账只记录，绝不门控）。
_CONFIDENCE_CAP = {1: 0.5, 2: 0.8}


def _capped_rate(ok: int, total: int) -> float:
    """样本量封顶的正答率：n=1→≤0.5，n=2→≤0.8，n≥3 不封顶，n=0→0.0。"""
    if total <= 0:
        return 0.0
    rate = ok / total
    cap = _CONFIDENCE_CAP.get(total)
    return min(rate, cap) if cap is not None else rate


# 台账时间戳格式（读写两侧必须同一套字面量——散写格式串是"解析失败静默变 0"的经典来源）
_TS_FMT = "%Y-%m-%d %H:%M:%S"


# ---- 校准闭环（2026-08-30 CALIBRATION-LOOP，docs/2026-08-30-CALIBRATION-LOOP-DESIGN.md）----
# 机制：每道题「先押把握（0-100%）再开奖，给用户看差距」——治"AI 一用就高估自己"。
# 红线与本文件头部一致：台账只记录不门控；给数据不给评价（"押高实际低"是事实，
# "你太自信"是评价——前者归代码，后者不许出现）；用户跳过=没有数据，绝不报 0%。


def _valid_confidence(value) -> int | None:
    """confidence 值域兜底：合法 → int（0-100）；越界/乱类型 → None（= 未采集，不是 0）。

    None 与 0 必须严格区分：0% 是"用户押了完全没把握"，None 是"用户没押"——
    把没押当成押 0%，校准偏差会凭空多出 +0/-100 的假数据。
    bool 是 int 的子类，显式排除（True 不是把握 1%）。
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, float):
        if not value.is_integer():
            return None
        value = int(value)
    if not isinstance(value, int):
        return None
    return value if 0 <= value <= 100 else None


# 校准分桶边界（设计文档 §2）：[0,40) / [40,70) / [70,100]
_CONFIDENCE_BUCKETS = ((0, 40), (40, 70), (70, 101))

# 只有这三种 judge 算"已判定"——解析失败的空 judge 不能进校准统计：
# 把"没判出来"当"答错"，等于用批改失败伪造校准偏差。
_JUDGED_VALUES = ("对", "部分对", "不对")


def _calibration_records(recs: list) -> list:
    """校准统计的唯一分母：知识轨 + 有有效 confidence + 已判定对错。

    返回 (confidence, 是否掌握, ts) 三元组。实践轨永远进不来（没有对错可对照）；
    旧记录没有 confidence 字段（读取侧补 None）也进不来——它们归「没有数据」，不归 0%。
    """
    out = []
    for r in _knowledge_records(recs):
        conf = _valid_confidence(r.get("confidence"))
        if conf is None:
            continue
        if str(r.get("judge", "")).strip() not in _JUDGED_VALUES:
            continue
        out.append((conf, _is_correct(r), str(r.get("ts", ""))))
    return out


def calibration_metrics(recs: list) -> dict:
    """校准数值层（2026-09-02 P2 审计#1 抽取）：结构化数值，summary 只负责渲染。

    返回：{has_data, n, total_bias, buckets:[{lo,hi,n,bias}], overconf:{n,wrong,rate}|None,
           weekly:[{y,w,bias}], skipped_ts, unreliable}
    - 口径与原实现逐字一致（渲染层兼容，旧文本断言不回归）
    - skipped_ts：ts 解析失败计数（原实现静默 continue——审计发现②，改可见）
    - unreliable：n<3 标记（与 mastery_signal 样本不足提示对齐——审计发现③）
    """
    cal = _calibration_records(recs)
    if not cal:
        return {"has_data": False, "n": 0, "total_bias": 0.0, "buckets": [],
                "overconf": None, "weekly": [], "skipped_ts": 0, "unreliable": True}
    n = len(cal)
    total_bias = sum(c - (100 if ok else 0) for c, ok, _ in cal) / n
    buckets = []
    for lo, hi in _CONFIDENCE_BUCKETS:
        seg = [(c, ok) for c, ok, _ in cal if lo <= c < hi]
        if not seg:
            continue
        bias = sum(c - (100 if ok else 0) for c, ok in seg) / len(seg)
        buckets.append({"lo": lo, "hi": min(hi, 100), "n": len(seg), "bias": bias})
    high = [(c, ok) for c, ok, _ in cal if c >= 70]
    overconf = None
    if high:
        wrong = sum(1 for _, ok in high if not ok)
        overconf = {"n": len(high), "wrong": wrong, "rate": wrong / len(high)}
    weeks: dict = {}
    skipped_ts = 0
    for c, ok, ts in cal:
        try:
            key = datetime.strptime(ts, _TS_FMT).isocalendar()[:2]
        except ValueError:
            skipped_ts += 1  # 不再静默：趋势丢数据可见（审计发现②）
            continue
        weeks.setdefault(key, []).append(c - (100 if ok else 0))
    weekly = [{"y": y, "w": w, "bias": sum(v) / len(v)} for (y, w), v in sorted(weeks.items())]
    return {"has_data": True, "n": n, "total_bias": total_bias, "buckets": buckets,
            "overconf": overconf, "weekly": weekly, "skipped_ts": skipped_ts,
            "unreliable": n < 3}


def calibration_summary(recs: list) -> str:
    """分桶校准统计文本（设计文档 §2）——纯渲染层：数值全部来自 calibration_metrics。

    口径：
    - 校准偏差 = confidence − 实际对错（对=100，错=0；部分对按掌握口径不算对），正数=押高实际低
    - 分桶：押 0-40 / 40-70 / 70-100 各自平均偏差；空桶跳过（不是 0%）
    - 过度自信率：押 ≥70% 的题里答错的占比；没有高把握题就整行不出现
    - 趋势：按 ISO 周聚合平均偏差，时间正序
    - 无数据明确说「没有数据」，绝不报 0%
    """
    m = calibration_metrics(recs)
    if not m["has_data"]:
        return "没有押把握的数据（用户跳过=没有数据，与押 0 分是两回事）"
    bucket_parts = [f"押 {b['lo']}-{b['hi']}% 的 {b['n']} 题平均偏差 {b['bias']:+.0f}%" for b in m["buckets"]]
    over_line = ""
    if m["overconf"]:
        o = m["overconf"]
        over_line = f"押 ≥70% 的 {o['n']} 题里答错 {o['wrong']} 题（{round(o['rate'] * 100)}%）。"
    trend_line = ""
    if m["weekly"]:
        parts = [f"{w['y']}-W{w['w']:02d} {w['bias']:+.0f}%" for w in m["weekly"]]
        trend_line = "按周平均偏差：" + "、".join(parts) + "。"
    caveat = "（样本不足，仅供参考）" if m["unreliable"] else ""
    if m["skipped_ts"]:
        caveat += f"（{m['skipped_ts']} 条时间无法解析，未进趋势）"
    return (
        f"{m['n']} 题有押把握数据，总体平均偏差 {m['total_bias']:+.0f}%（正数=押高实际低，负数=押低实际高）："
        f"{'；'.join(bucket_parts)}。{over_line}{trend_line}"
        f"只是事实记录，不构成评价，也不是门槛。{caveat}"
    )


def _is_closed_book_retest(rec: dict) -> bool:
    """闭卷复测的唯一判定口径：is_retest=True 且 assisted=False。

    assisted=True 或 assisted 缺失（None）的复测**不算数**——有 AI 兜底的"复习"不是保持率
    （Barcaui et al. 2025 RCT：无约束 ChatGPT 组 45 天保持率 −11pp）。
    乱值（手改台账写入的 "yes"/1 等）走 is 判定自然落选，不崩、不进统计。
    """
    return rec.get("is_retest") is True and rec.get("assisted") is False


def _retention_side(label: str, group: list) -> str:
    """一侧（首测/复测）的报告文本——空组明确说「没有数据」，绝不报 0%。"""
    if not group:
        return f"{label}没有数据"
    ok = sum(1 for r in group if _is_correct(r))
    return f"{label} {len(group)} 题正确率 {round(_capped_rate(ok, len(group)) * 100)}%"


def retention_summary(recs: list) -> str:
    """保持率统计文本（设计文档 §1-3）——首测 vs 无辅助复测，分主题 + 全局。

    口径：
    - 只统计知识轨（实践轨没有对错，与正答率同一理由不进分母）
    - 复测侧 = _is_closed_book_retest（闭卷才算数）；首测侧 = 其余知识轨记录
      （首测允许是有辅助的——那正是对照的意义：「首测 90% vs 复测 55%」本身就是信号）
    - 对错判定走 _is_correct（全文件唯一入口）；正答率同 mastery 一样按样本量封顶
    - 全局/分主题/对比三处，任一侧无数据都明确说「没有数据」，绝不报 0%
    """
    know = _knowledge_records(recs)
    # 首测侧 = is_retest 不是 True 的记录：is_retest=True 但 assisted!=False 的记录两侧都不进——
    # 它既不是闭卷复测，也不该混进"首测"抬高对照基线。
    first = [r for r in know if r.get("is_retest") is not True]
    retest = [r for r in know if _is_closed_book_retest(r)]
    lines = [f"全局：{_retention_side('首测', first)}；{_retention_side('无辅助复测', retest)}"]
    if first and retest:
        f_rate = _capped_rate(sum(1 for r in first if _is_correct(r)), len(first))
        r_rate = _capped_rate(sum(1 for r in retest if _is_correct(r)), len(retest))
        lines.append(f"对比：复测正确率比首测 {round((r_rate - f_rate) * 100):+d}pp（负=间隔后遗忘，只是事实不是评价）")
    else:
        lines.append("对比：没有数据（首测与无辅助复测两侧都有记录才能对照）")
    topics = sorted({str(r.get("topic", "")) for r in know if r.get("topic")})
    for t in topics:
        trecs = [r for r in know if str(r.get("topic", "")) == t]
        tf = [r for r in trecs if r.get("is_retest") is not True]
        tr = [r for r in trecs if _is_closed_book_retest(r)]
        lines.append(f"「{t}」：{_retention_side('首测', tf)}；{_retention_side('无辅助复测', tr)}")
    return (
        "保持率（无辅助复测 vs 首测；assisted=True 或未标记 assisted 的复测不计入——闭卷才算数）：\n"
        + "\n".join(lines)
        + "\n只是事实记录，不构成评价，也不是门槛。"
    )


def _confidence_feedback(conf: int, judge: str, recs: list) -> str:
    """grade_answer 返回里的事实对照（设计文档 §1-2）——给数据不给评价。

    措辞红线：只许「押高实际低 +X% / 押低实际高 X%」这类事实陈述，
    绝不出现「太自信 / 高估自己」这类评价措辞（谄媚红线的反面也是红线）。
    """
    j = str(judge).strip()
    correct = j == JUDGE_CORRECT
    if j not in _JUDGED_VALUES:
        return (
            f"【校准对照】你押了 {conf}%，但本次未判定对错——不计入校准统计。"
            f"（只是事实对照，不构成评价。）"
        )
    result_txt = {"对": "结果对", "不对": "结果错"}.get(j, "结果：部分对（按掌握口径不算对）")
    diff = conf - (100 if correct else 0)
    if diff > 0:
        bias_txt = f"押高实际低 +{diff}%"
    elif diff < 0:
        bias_txt = f"押低实际高 {diff}%"
    else:
        bias_txt = "押得准"
    line = f"【校准对照】你押了 {conf}%，{result_txt}——{bias_txt}。"
    # 趋势（设计文档：「最近 10 题」）——含本题；只有 1 题时趋势就是它自己，不重复呈现
    cal = _calibration_records(recs)[-10:]
    if len(cal) >= 2:
        high_n = sum(1 for c, ok, _ in cal if c > (100 if ok else 0))
        low_n = sum(1 for c, ok, _ in cal if c < (100 if ok else 0))
        avg = sum(c - (100 if ok else 0) for c, ok, _ in cal) / len(cal)
        line += (
            f"\n最近 {len(cal)} 题校准：押高实际低 {high_n} 次、押低实际高 {low_n} 次，"
            f"平均偏差 {avg:+.0f}%。"
        )
    return line + "\n（只是事实对照，不构成评价——怎么调整后续学习由你判断。）"


def _resolve_type(value) -> str:
    """type 值域归一：非法/空/大小写差异 → 回落 knowledge。

    与 _normalize_record 的回落规则保持一致（harness 只做值域兜底，不做语义判断）——
    两处判"这算不算实践轨"必须用同一个函数，否则写入时是实践、统计时变知识。
    """
    v = str(value or "").strip().lower()
    return v if v in LEDGER_TYPES else DEFAULT_LEDGER_TYPE


def _knowledge_records(recs: list) -> list:
    """正答率的分母——只有知识轨（2026-08-30，双轨落地的伴生修正）。

    为什么必须过滤：实践轨记录没有 judge，把它们留在分母里，
    每多一条实践记录就凭空拉低一次"正答率"，而用户什么都没做错。
    这是把两种不可通约的单位相除——和 R1 修掉的"三处口径不一"是同一类错误，
    只是这次更隐蔽：它不会崩、不会报错，只会安静地报一个越来越低的数字。

    注意：间隔复习（spacing）不过滤——实践也需要间隔，那是时间信号不是成绩信号。
    """
    return [r for r in recs if str(r.get("type", DEFAULT_LEDGER_TYPE)) == LEDGER_TYPE_KNOWLEDGE]


# ---- 台账记录结构（2026-08-30 双轨地基）----
# 双轨共用一张表：知识轨 = 出题-批改-正确率；实践轨 = 设计一次真实实践 → 复盘自述 → 存证据。
# 依据（learning-science-researcher）：Southwick et al. 2026（N=44,213 Chess.com）——
#   战术题与单纯对下统计上无区别，复盘自己的对局 = 5.6× → 出题只对"有标准答案的知识"成立。
# 新字段全部可选、向后兼容：老记录（topic/ts/question/judge/note）读出来自动补默认值。
LEDGER_TYPE_KNOWLEDGE = "knowledge"
LEDGER_TYPE_PRACTICE = "practice"
# 2026-08-30 teach-back（docs/2026-08-30-TEACH-BACK-DESIGN.md）：用户教 AI 的角色反转台账。
# 必须进 LEDGER_TYPES——否则 _normalize_record 的值域兜底会把它回落成 knowledge，
# 角色扮演记录就混进正答率分母（与 R8 "实践轨变成绩" 同一类污染）。
LEDGER_TYPE_TEACH_BACK = "teach_back"
LEDGER_TYPES = (LEDGER_TYPE_KNOWLEDGE, LEDGER_TYPE_PRACTICE, LEDGER_TYPE_TEACH_BACK)
DEFAULT_LEDGER_TYPE = LEDGER_TYPE_KNOWLEDGE

# 新字段默认值。None = 未采集（刻意区别于 False/""——未采集不是"没做"）。
# type 是唯一有非 None 默认的：存量记录的行为全部属于知识轨，缺省按知识轨处理。
_LEDGER_FIELD_DEFAULTS: dict = {
    "type": DEFAULT_LEDGER_TYPE,
    "assisted": None,  # 这次尝试期间 AI 是否可用/被调用（见下方说明，这是全表最关键的一个字段）
    "real_attempt": None,  # 这次是不是真实条件下完成的（限时/无提示/真实场景，相对"在系统里刷题"）
    "context_key": None,  # 实践发生的情境标识（skill 类用；habit 类必填）
    "prompted": None,  # 这次是 AI/提醒促发的，还是用户自己发起的
    "self_rating": None,  # 用户自述原文——只存证据，绝不参与任何自动晋级计算
    "standard": None,  # 判定口径文本（知识轨"答案是否等于 X"，实践轨"是否做到了 Y"）
    "confidence": None,  # 作答前自报把握 0-100（校准闭环，2026-08-30）；None=用户没押，绝不当成 0
    "is_retest": None,  # 本次是不是无辅助延迟复测（检索练习机制，2026-08-30）；None=未标记，绝不当成 False
}
# ⚠️ assisted 是双轨验证的命门（docs/2026-08-30-VERIFICATION-PROTOCOL.md §1.1、§6.1）：
#   real_attempt 说的是"条件真不真实"（限时/没见过/无提示），**不等于"AI 在不在场"**。
#   而三条独立证据都指向同一件事——辅助状态下的表现会骗人：
#     · Bastani et al. 2025（PNAS）：有辅助 +48%，撤走辅助后 −17%
#     · Liu et al. 2026（三实验）：即时提升，但后续无辅助任务的表现与坚持度下降
#     · 26,000 名学生 / 30 个月面板：作业分 +18%，闭卷考试 −20~−24%
#   没有 assisted 就无法把"主要结局"和"陷阱指标"在数据层分开，整套验证是瞎的。
#   verified 之后所有"掌握度/正答率"类统计都必须能按 assisted 分组。
LEDGER_FIELD_KEYS = tuple(_LEDGER_FIELD_DEFAULTS)  # 供下游枚举（测试/API 不必硬编码字段名）


def _normalize_record(rec: dict) -> dict:
    """读取侧兼容层——台账结构升级的唯一入口，禁止在各处散写 .get(...) 兜底。

    - 补齐 7 个新字段默认值；未知字段原样保留（以后再加字段不用动这里）
    - type 非法值 → 回落 knowledge（harness 只做值域兜底，不做语义判断）
    - judge 刻意不给默认值：实践轨记录本来就没有 judge，
      补 "" 会把"未判定"伪装成"判定为空"，而这两者对下游含义不同
    """
    if not isinstance(rec, dict):
        return {}
    out = dict(rec)
    for k, default in _LEDGER_FIELD_DEFAULTS.items():
        if k not in out:
            out[k] = default
    if out["type"] not in LEDGER_TYPES:
        out["type"] = DEFAULT_LEDGER_TYPE
    return out


def _build_ledger_record(
    *,
    topic: str,
    question: str,
    note: str,
    attempt_type: str,
    judge: str = "",
    assisted: bool | None = None,
    real_attempt: bool | None = None,
    standard: str = "",
    self_rating: str = "",
    confidence: int | None = None,
    is_retest: bool | None = None,
) -> dict:
    """台账记录的唯一构造入口（2026-08-30 R8）——实践轨绝不允许带 judge。

    "实践轨不写 judge"是**不变量**，锁在代码里，不是交给模型的选择：
    一旦实践记录里混进 judge，实践轨的自述证据就会变成"成绩"混进正答率，
    而正确率恰恰是我们已知会骗人的那个指标（Bastani 2025：有辅助 +48%、撤走后 −17%）。
    混进去之后，事后无法回溯哪条是真成绩、哪条是证据——不可修复。

    两道防线：
      ① prompt 层——实践轨的 JSON schema 里根本没有 judge 字段（不提，模型就不会给）
      ② 代码层——即使模型仍然输出了 judge，这里也不让它落盘
    两条都要有：① 会随模型/温度漂移，② 单靠它则数据已经污染了才被发现。
    """
    rec = {
        "topic": topic,
        "ts": datetime.now().strftime(_TS_FMT),
        "question": question[:100],
        "note": note[:200],
        "type": _resolve_type(attempt_type),
        "assisted": assisted,
        "real_attempt": real_attempt,
        # 空串统一落成 None：未采集 ≠ 空标准（下游要能区分"没设标准"和"标准就是空"）
        "standard": standard or None,
        "self_rating": self_rating or None,
        # 越界/乱类型在这里统一落成 None（= 未采集）——写入侧兜底一次，
        # 读取侧统计再走 _valid_confidence 兜一次（手改台账/旧写入路径的数据也安全）
        "confidence": _valid_confidence(confidence),
        # 乱类型兜底（手改台账/乱传参）：只有真 bool 才落盘，其余一律 None（= 未标记）。
        # "yes"/1 之类的值若原样落盘，读取侧的 is True 判定会静默把它们当非复测——
        # 不崩但口径污染；在写入侧归一一次，读取侧就不必再防。
        "is_retest": is_retest if isinstance(is_retest, bool) else None,
    }
    # judge 只在知识轨出现；实践轨根本不往 dict 里放（第②道防线）
    if rec["type"] == LEDGER_TYPE_KNOWLEDGE:
        rec["judge"] = judge
    return rec


def _ledger_append(rec: dict) -> None:
    """追加一条掌握记录（尽力而为，失败静默——记录是增强非主流程）。"""
    try:
        MASTERY_LEDGER().parent.mkdir(parents=True, exist_ok=True)
        with open(MASTERY_LEDGER(), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as _e:
        print(f"[tools/learning] 静默异常已可见化: {_e}", flush=True)


def _ledger_read() -> list:
    out = []
    if not MASTERY_LEDGER().exists():
        return out
    try:
        for ln in MASTERY_LEDGER().open(encoding="utf-8", errors="replace"):
            if ln.strip():
                out.append(_normalize_record(json.loads(ln)))
    except Exception as _e:
        print(f"[tools/learning] 静默异常已可见化: {_e}", flush=True)
    return out


async def generate_practice(topic: str, count: int = 3, mode: str = "") -> str:
    """生成练习题目（主动回忆机制，2026-08-27）。

    模型自己判断何时调用（讲解完、用户说要练、学完一个主题后）——工具只提供"出题"能力。
    mode 可选：challenge=挑战模式（先试后教——比用户当前水平略高的前测，配合 productive failure）；
    review=复习模式（检查性提问）；默认=跟随式练习（巩固刚讲的内容）。
    生成的题是给用户在对话里作答的，答完可再调 grade_answer 批改。

    ⚠️ 只对"有标准答案的知识"出题（2026-08-30 双轨边界）：
    学技能/习惯/处事（开会发言、跟人开口、控制情绪、坚持早起）——**不要出题**。
    依据 Southwick et al. 2026（Chess.com，N=44,213）：战术题与单纯对下在统计上无区别，
    真正有效的是复盘自己的对局（5.6×）。也就是说，本工具本质是个"战术题生成器"，
    对没有标准答案的东西，出题只是在制造"我在练习"的错觉。
    这些主题改为：和用户一起设计**一次真实实践**（何时/何地/做到什么算数），
    做完之后用 grade_answer(attempt_type="practice") 记录复盘证据。
    判断权在你：这个主题有没有客观对错？有→出题；没有→设计实践。

    校准闭环（2026-08-30，Lee et al. 2025 CHI RCT：预测→实测→差距反馈，学习增益 +8.9%）：
    出题后先把题给用户，**请 TA 对每道题先报一个把握（0–100%）再作答**；
    之后调 grade_answer 时把把握传给 confidence 参数，返回里会自动带「押 X% vs 实际对错」的事实对照。
    用户不想押就直接作答——不催、不评，跳过就是「没有数据」，绝不是 0%。"""
    from pydantic_ai import Agent

    from app.agent.model import get_model

    mode_line = {
        "challenge": "这是挑战模式：出 1-2 道比用户当前水平略高的前测题（允许用户先试、会错，错后讲解——productive failure：先试后教有效，但要跟讲解收束）。",
        "review": "这是复习模式：出检查性提问（检验是否还记得核心概念，不考细节计算）。",
        "": "这是跟随式练习：巩固刚才讲的内容，难度适中。",
    }.get(mode, mode or "")

    gen = Agent(
        get_model(),
        system_prompt=(
            "你是拾光的学习机制引擎（harness 工具）。你的职责是生成优质练习题目，帮助用户主动回忆。\n"
            "要求：\n"
            "1. 题目要触及核心概念，不是死记硬背细节\n"
            "2. 题型多样（概念解释/判断/小计算/开放思考），避免全是选择题\n"
            "3. 每道题标注【类型】与【考察点】\n"
            "4. 不提供答案（用户作答后再批改）\n"
            "5. 题目用中文，简洁清晰\n"
            f"{mode_line}\n"
            f"主题：{topic}\n"
            f"题目数量：{count} 道"
        ),
    )
    try:
        r = await gen.run(topic)
        return str(r.output).strip()
    except Exception as e:
        return f"(练习生成失败：{str(e)[:120]})"


# 两条轨的批改 prompt 提为模块常量（2026-08-30 双分支）：
# 提上来的直接理由是**可测**——prompt 是这一层唯一的行为契约，必须能被断言，
# 不能埋在函数体里靠 mock 才能看到。
_KNOWLEDGE_GRADER_PROMPT = (
    "你是拾光的学习反馈引擎（harness 工具）。批改用户对练习题的作答。\n"
    "要求：\n"
    "1. 先判断对错（对/部分对/不对，一句话）\n"
    "2. 讲清楚对在哪、错在哪（具体到答案的哪一部分）\n"
    "3. 给改进方向（下一步怎么练）。默认不直接给完整答案——替他想等于替他练。\n"
    "   例外：用户明确说「给我答案 / 标准答案 / 别问我了 / 直接说」，就直给完整答案并简要解释，不再反问。\n"
    "4. 语气诚实：不夸奖、不吹捧、不安慰。错的地方直接说错，对的地方才说对——\n"
    "   虚假的肯定会让用户高估自己的水平（实验显示：用 AI 练习的学生普遍高估自己的学习效果）。\n"
    '5. 以 JSON 格式输出：{"judge":"对/部分对/不对", "feedback":"...", "improve":"...", "confidence":0-1}'
)

_PRACTICE_GRADER_PROMPT = (
    "你是拾光的实践复盘引擎（harness 工具）。用户在真实场景里做完了一次实践，现在来自述复盘。\n"
    "按固定四段输出：\n"
    "1. 回放：复述用户自述里的**事实**（发生了什么、他说了做了什么）。不复述就没法对照。\n"
    "2. 对照：只对照用户自己设的标准（standard 字段）。**绝不用你的标准替代他的标准**；\n"
    "   standard 为空时，不要替他拟一个——先问他想用什么口径判断这次算不算数。\n"
    "3. 下一步：一个**30 秒内能启动**的具体动作。不是「多练习」，是「下次开会前把三个点写在便签上」。\n"
    "4. 反问：一个苏格拉底式问题，让他自己判断这次到底怎么样。\n"
    "硬约束：\n"
    "- 不判对错、不打分、不说「你做对了/做错了」——实践轨没有标准答案，只有证据\n"
    "- 不升级他的标准，也不安慰、不夸奖\n"
    "- 输出里**不要出现 judge 字段**（实践轨不判定；写了也会被丢弃）\n"
    '5. 以 JSON 格式输出：{"replay":"...", "gap":"...", "next":"...", "probe":"..."}'
)


async def grade_answer(
    question: str,
    answer: str,
    topic: str = "",
    attempt_type: str = DEFAULT_LEDGER_TYPE,
    assisted: bool | None = None,
    real_attempt: bool | None = None,
    standard: str = "",
    self_rating: str = "",
    confidence: int | None = None,
    is_retest: bool | None = None,
) -> str:
    """批改/复盘一次尝试，并记入台账 mastery.jsonl（harness 记忆信号，非门控）。

    两条轨，语义完全不同，用 attempt_type 选：

    【knowledge 知识轨】（默认）——用于有客观对错的东西（算法题、八股、行测、概念）。
      产出 judge（对/部分对/不对）+ 反馈 + 改进方向。计入正答率。

    【practice 实践轨】——用于没有标准答案的东西（开会发言、开口沟通、情绪、习惯）。
      用户在真实场景里做完一次，来自述复盘。**不判对错、不打分**，
      产出四段式：回放事实 → 对照用户自设的 standard → 30 秒内能启动的下一步 → 苏格拉底反问。
      **不计入任何正答率**——实践轨只有证据，没有成绩。

    后四个参数是双轨验证的采集项：**能传就传，传不了就留空（= 未采集），不要猜**。
      assisted     这次尝试**当时** AI 在不在场 / 有没有被调用。它和 real_attempt 不是一回事：
                   限时闭卷 = real_attempt=True, assisted=False（真正的主要结局）
                   限时但随时能问 AI = real_attempt=True, assisted=True（已知的陷阱指标）
                   这是全表最关键的字段：Bastani et al. 2025（PNAS）有辅助 +48%，撤走辅助后 −17%。
      real_attempt 条件是否真实（限时 / 没见过 / 无提示 / 真实场景），相对"在系统里随手刷题"
      standard     判定口径原文：知识轨"答案是否等于 X"，实践轨"做到了什么算数"（须由用户自设）
      self_rating  用户自述原文。**只存证据，绝不参与任何自动晋级计算**
      confidence   用户作答前自报的把握（0-100，校准闭环 2026-08-30）。用户报了就原样传；
                   没报就留空（= 没有数据），**不要替用户猜一个**——猜出来的把握比没有更糟。
                   传了有效值时，返回文本会自动附「押 X% vs 实际对错」的事实对照与最近趋势。
      is_retest    本次是不是「延迟复测」（距上次练习 ≥3 天的闭卷再考，检索练习机制 2026-08-30）。
                   复测默认**闭卷流程**：不给提示、不代查、不暗示，并传 assisted=False——
                   有辅助的"复习"不算保持率（Barcaui et al. 2025 RCT：无约束 AI 组 45 天保持率 −11pp）。
                   但宪法红线优先：**用户明确要答案时必须直接给**——闭卷只是流程默认值，不是墙。
                   不是复测就留空（= 未标记），不要乱标；乱类型会按未标记处理。
    """
    from pydantic_ai import Agent

    from app.agent.model import get_model

    is_practice = _resolve_type(attempt_type) == LEDGER_TYPE_PRACTICE
    grader = Agent(
        get_model(),
        system_prompt=_PRACTICE_GRADER_PROMPT if is_practice else _KNOWLEDGE_GRADER_PROMPT,
    )
    try:
        r = await grader.run(f"【题目】{question}\n\n【用户答案】{answer}")
        raw = str(r.output).strip()
    except Exception as e:
        return f"(批改失败：{str(e)[:120]})"

    # judge 只在知识轨解析——实践轨解析了也会被 _build_ledger_record 丢掉，
    # 那属于"解析出一个不该存在的值"，不如根本不去要（R8 防线①的配套动作）
    judge = "" if is_practice else _extract_judge(raw)
    _ledger_append(
        _build_ledger_record(
            topic=topic or question[:30],
            question=question,
            note=raw,
            attempt_type=attempt_type,
            judge=judge,
            assisted=assisted,
            real_attempt=real_attempt,
            standard=standard,
            self_rating=self_rating,
            confidence=confidence,
            is_retest=is_retest,
        )
    )
    # 校准对照只挂知识轨：实践轨没有对错，"押 X% vs 结果"无从对照（设计上押把握也只针对知识题）
    if not is_practice:
        conf = _valid_confidence(confidence)
        if conf is not None:
            raw += "\n\n" + _confidence_feedback(conf, judge, _ledger_read())
    return raw


def _extract_judge(raw: str) -> str:
    """从子 agent 输出里抠出 judge 值（尽力而为，抠不出返回 ""= 未判定）。

    不抛异常是刻意的：批改失败不该让整次对话中断，而""必须能被下游识别为"未判定"，
    绝不能 fallback 成"对"（那会把失败伪装成掌握）。
    """
    import re

    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        return ""
    try:
        return str(json.loads(m.group(0)).get("judge", ""))
    except Exception as _e:
        print(f"[tools/learning] 静默异常已可见化: {_e}", flush=True)
        return ""


def spacing_signal(topic: str) -> str:
    """间隔复习信号（分散练习机制，2026-08-27）——只提供信息，提醒与否归模型判断。

    查询 mastery.jsonl 台账：该主题上次练习时间/间隔/成功率。
    模型自己决定：该提醒复习就提醒，未到期就不打扰（绝不强制）。

    2026-08-30：间隔口径**不过滤轨别**——实践同样需要间隔（那是时间信号，不是成绩信号）；
    但正答率只算知识轨（见 _knowledge_records）。

    2026-08-30 检索练习机制：距上次练习 ≥3 天时附「建议无辅助复测」一行——
    信息不门控：复测不复测、怎么复测归模型与用户判断。"""
    recs = [r for r in _ledger_read() if topic.lower() in str(r.get("topic", "")).lower()]
    if not recs:
        return f"「{topic}」还没有练习记录——首次学习后建议隔段时间回来主动回忆一次（间隔练习是记忆最强的机制之一）"
    last = recs[-1]
    days = (datetime.now() - datetime.strptime(last["ts"], _TS_FMT)).days
    know = _knowledge_records(recs)
    ok = sum(1 for r in know if _is_correct(r))
    # 注意：提醒方向只由间隔（days）决定，口径统一不影响它——
    # "部分对"改判不计入 ok，但仍计入 total（拉低显示的正答率），提醒倾向只会更强不会更弱。
    # 回归锁定见 tests/unit/test_learning_tools.py::TestSpacingSignal::test_partial_credit_still_reminds
    status = (
        "（已超过 3 天——适合做一次复习）"
        if days >= 3
        else "（间隔适中，可自然复习）"
        if days >= 1
        else "（刚练过，可暂缓）"
    )
    # 没有正答率可报时就说没有——不要报 0%。
    # 报 0% 会让模型以为"用户这块很差"，而真相只是这个主题压根不是知识类；
    # 这是把"无数据"伪装成"数据为零"，与 R1 的"未判定伪装成判定为空"是同一类失真。
    # 2026-08-30 teach-back：else 分支不能笼统报"实践记录 N 条"——
    # teach_back 不是实践，混报会把角色扮演当成复盘证据。
    if know:
        rate_txt = f"正答率约 {round(ok / len(know) * 100)}%"
    else:
        _prac = sum(1 for r in recs if str(r.get("type", DEFAULT_LEDGER_TYPE)) == LEDGER_TYPE_PRACTICE)
        _teach = len(recs) - _prac
        _parts = []
        if _prac:
            _parts.append(f"实践记录 {_prac} 条（实践轨没有对错，不计入正答率）")
        if _teach:
            _parts.append(f"teach-back 记录 {_teach} 条（角色扮演台账，不参与对错统计）")
        rate_txt = "，".join(_parts)
    # ≥3 天 → 附「建议无辅助复测」（检索练习机制，2026-08-30）：信息不门控，只是提示。
    retest_line = (
        "\n距上次练习已 ≥3 天——建议做一次无辅助复测（闭卷作答：不给提示、不代查；"
        "批改时调 grade_answer 传 is_retest=True、assisted=False，保持率统计才算数）。"
        "复测不复测由你和用户判断；用户明确要答案时必须直接给。"
        if days >= 3
        else ""
    )
    return (
        f"「{topic}」练习台账：上次 {last['ts'][:10]}（{days} 天前），累计 {len(recs)} 次，"
        f"{rate_txt}{status}。是否复习由你判断——"
        f"想复习就调 generate_practice(mode='review')。{retest_line}"
    )


def mastery_signal(topic: str = "") -> str:
    """掌握度信号（DeepTutor mastery 近因加权思想，非门控）——harness 记录的综合参考。

    模型自主参考：帮用户判断"这个主题学得怎么样、要不要加练"，但**不强制任何前进条件**。

    2026-08-30：正答率只统计知识轨（实践轨没有对错，进分母就是拿两种单位相除）。
    实践记录仍如实报告条数——不报就会让人以为那段经历没被记下来。"""
    recs = _ledger_read()
    if topic:
        recs = [r for r in recs if topic.lower() in str(r.get("topic", "")).lower()]
    if not recs:
        return "暂无掌握记录（还没有批改过的练习）——先练几题，台账会自动积累"
    know = _knowledge_records(recs)
    # 2026-08-30 teach-back：不能用 len(recs)-len(know) 算实践条数——
    # teach_back 记录会被误标成"实践记录"。两条非知识轨分开计数、分开报告。
    prac_n = sum(1 for r in recs if str(r.get("type", DEFAULT_LEDGER_TYPE)) == LEDGER_TYPE_PRACTICE)
    teach_n = sum(1 for r in recs if str(r.get("type", DEFAULT_LEDGER_TYPE)) == LEDGER_TYPE_TEACH_BACK)
    prac_tail = (
        f"另有实践记录 {prac_n} 条（实践轨没有对错，不计入正答率——那是证据不是成绩）。"
        if prac_n
        else ""
    )
    teach_tail = (
        f"另有 teach-back 记录 {teach_n} 条（用户教 AI 的角色扮演台账，不参与对错统计）。"
        if teach_n
        else ""
    )
    if not know:
        return (
            f"暂无知识轨练习记录（{topic or '全主题'}），没有正答率可算。{prac_tail}"
            f"这是参考信号不是门槛——是否加练、学什么，由你和模型共同判断。"
        )
    total = len(know)
    ok = sum(1 for r in know if _is_correct(r))
    recent = know[-5:]
    recent_ok = sum(1 for r in recent if _is_correct(r))
    rate = _capped_rate(ok, total)
    recent_rate = _capped_rate(recent_ok, len(recent))
    # 样本不足提示（R1b）：只影响报告值——绝不门控，是否加练仍归模型与用户
    note = (
        f"（样本不足 {total} 次——正答率已按上限封顶，暂不代表真实水平）"
        if total in _CONFIDENCE_CAP
        else ""
    )
    # 校准小节（2026-08-30）：有押把握数据才出现；没有就整节不出现——绝不显示 0%
    cal_section = ""
    if _calibration_records(recs):
        cal_section = f"\n【校准】{calibration_summary(recs)}"
    # 保持小节（2026-08-30 检索练习机制）：有闭卷复测数据才出现；没有就整节不出现——绝不显示 0%
    ret_section = ""
    if any(_is_closed_book_retest(r) for r in know):
        ret_section = f"\n【保持】{retention_summary(recs)}"
    return (
        f"掌握台账：知识轨共 {total} 次练习（{topic or '全主题'}），累计正答率 {round(rate * 100)}%，"
        f"最近 {len(recent)} 次正答率 {round(recent_rate * 100)}%。{note}"
        f"{prac_tail}"
        f"{teach_tail}"
        f"{cal_section}"
        f"{ret_section}"
        f"这是参考信号不是门槛——是否加练、学什么，由你和模型共同判断。"
    )


# ---- 用户教 AI / Teach-Back（2026-08-30，docs/2026-08-30-TEACH-BACK-DESIGN.md）----
# 角色反转：AI 当学生，用户当老师（用户协议 #8，本人长期验证过的形态）。
# 依据：Chen et al. 2025（AI 太正确 = 剥夺学员调试机会 → 必须犯典型误解）；
#       Arun et al. 2025（教学者会不懂装懂 → 学生的疑惑是 TA 的镜子，必须主动暴露）；
#       Rogers et al. 2025（teachable agent 帮学员更准确评估自己 → 附带校准收益）。
# 红线与本文件头部一致：台账只记录不门控；角色卡是行为准则不是脚本（台词归模型）；
# 绝不夸讲解（反谄媚两个方向：夸 TA 是正向谄媚，假装学会是反向谄媚）。

# 学生角色卡（设计文档 §1 五条，一字不可少——这是本机制的灵魂，提为模块常量以便测试断言）。
# 措辞刻意避开「讲得好」「真棒」类字面量：第 4 条自己就不能违规。
_TEACH_BACK_ROLE_CARD = (
    "【反向教学·学生角色卡】从现在起你是学生，用户是老师。在本轮对话中遵守五条行为准则：\n"
    "1. 问简单问题（「为什么是这样？」）；**每遇到一个术语都要一个例子**——没有例子就追着要。\n"
    "2. **主动暴露疑惑**：「等等，我以为 X 是 Y——我哪里理解错了？」"
    "（教学者会不懂装懂，你的疑惑是 TA 的镜子）。\n"
    "3. 犯 1–2 个该主题的**典型误解**让 TA 纠正（你太正确 = 剥夺 TA 的调试机会）——"
    "误解要典型、可被纠正；被纠正后真的改：**复述纠正版请 TA 验证**。\n"
    "4. **绝不夸奖**——不恭维 TA 的讲解水平、不宣布「我懂了」；"
    "理解与否用后续表现（复述/小考）证明，不用嘴说（装学生最容易变成假装学会的反向谄媚）。\n"
    "5. TA 讲错时：**顺着错逻辑推一步，推到明显荒谬处停下问**「这样会推出 X，对吗？」——"
    "不直接说「你错了」，让 TA 自己看见。\n"
    "这是行为准则不是脚本——具体怎么问、问什么，由你按对话现场判断。"
)

_TEACH_BACK_ACTIONS = ("start", "finish")


def teach_back(topic: str, action: str = "start") -> str:
    """反向教学（teach-back）：角色反转——你当学生，用户当老师，让 TA 把主题讲给你听。

    教是最强的学（learning by teaching）：用户要把一个主题讲明白，必须先自己理清。
    何时调用由你判断：学完一个主题后（讲一遍比做十题更能暴露薄弱点）、
    复测/小考前（讲不通的地方就是该复习的地方）、或用户主动说「我来考考你 / 我给你讲讲」。

    action=start：返回学生角色卡（五条行为准则），你在本轮对话中扮演学生；台账记一次 start。
    action=finish：教完收尾——复述你学到的要点请用户验证，并建议一次**闭卷小考**
      （调 generate_practice 出题，grade_answer 批改时传 assisted=False——教完测，测了才算数）；
      台账记一次 finish。

    台账只记录不门控：teach_back 记录永不参与正答率/保持率/校准统计（角色扮演没有对错）。
    """
    from app.tools.errors import arg_error

    a = str(action or "").strip().lower()
    if a not in _TEACH_BACK_ACTIONS:
        return arg_error(
            "反向教学",
            f"action 只能是 {'/'.join(_TEACH_BACK_ACTIONS)}（收到 {action!r}）",
        )
    t = str(topic or "").strip()
    if not t:
        return arg_error("反向教学", "主题不能为空")
    rec = _build_ledger_record(
        topic=t,
        question=f"teach_back {a}",
        note="",
        attempt_type=LEDGER_TYPE_TEACH_BACK,
    )
    rec["action"] = a  # start/finish——teach_back 记录的核心字段，台账结构见设计 §2
    _ledger_append(rec)
    if a == "start":
        return _TEACH_BACK_ROLE_CARD
    return (
        f"【反向教学·收尾】「{t}」这一轮教学结束：\n"
        "1. 先复述你从 TA 讲解中学到的要点（你的理解版，不是 TA 的原话），请 TA 验证你复述得对不对。\n"
        "2. 然后建议一次闭卷小考（教完测，测了才算数）：调 generate_practice 出题，"
        "批改时调 grade_answer 传 assisted=False（首考 is_retest 留空）——"
        "有辅助的「会」不算会（Bastani et al. 2025：有辅助 +48%，撤走后 −17%）。\n"
        "小考不做强制——做不做归用户判断；但「学会」只能由小考/复述证明，不由台词宣布。"
    )
