# -*- coding: utf-8 -*-
"""长任务 harness 双模式（2026-08-30，docs/2026-08-30-LONGTASK-HARNESS-DESIGN.md）——学习计划 = 拾光的长任务。

plan.json 承载「目标拆解 → 每会话增量推进 → 接地验收 → 结构化接续」。
JSON 不用 Markdown（Anthropic 2025-11 一手核验：模型乱改/覆写 JSON 的概率显著更低）。

核心不变量（锁在代码里，模型无口绕过）：
- passes=true 只能经 plan_advance，且证据代码核验——quiz/practice 查 learning.py 台账
  （_is_correct 判定 + 主题匹配 + 近期记录存在）；user_confirm 直接接受但标最弱档。
  防「过早宣布完工」（谄媚/虚报在长任务形态下的样子）。
- plan_update 拒写 passes（防污染——Anthropic 用 prompt 限定"只许改 passes"，我们反向锁：
  其余字段都可改，唯独 passes 在此工具不可写）。
- 同一时刻只有一个活跃计划（「向外一件事」产品红线）；归档计划只读。

红线：决策归模型（拆什么目标、每项完成标准、何时推进），循环归代码
（schema 校验 / 证据核验 / 单一活跃约束 / change_log 留痕）。
"""

import json
from datetime import datetime, timedelta
from pathlib import Path

from app.auth_core import get_current_user_id
from app.config import DATA_DIR
from app.user_data import get_user_data_dir
from app.utils.atomic_io import atomic_write_text

# 测试注入点（对齐 learning._LEDGER_OVERRIDE / wakeups._DB_OVERRIDE 惯例：
# 钩子优先于 uid 解析，测试零侵入生产路径）
_PLAN_OVERRIDE: Path | None = None


def PLAN_FILE(uid=None) -> Path:
    """per-user plan.json（参照 evolution._evo_dir 模式；legacy 回退全局 data/plan.json）"""
    if _PLAN_OVERRIDE is not None:
        return _PLAN_OVERRIDE
    if not uid:
        uid = get_current_user_id()
    if uid:
        return get_user_data_dir(uid) / "plan.json"
    return DATA_DIR / "data" / "plan.json"


# 证据三档（值域白名单——乱值在 plan_advance 入口直接拒绝，不落盘）
EVIDENCE_QUIZ = "quiz"
EVIDENCE_PRACTICE = "practice"
EVIDENCE_USER_CONFIRM = "user_confirm"
EVIDENCE_TYPES = (EVIDENCE_QUIZ, EVIDENCE_PRACTICE, EVIDENCE_USER_CONFIRM)

# 证据强度分档（设计 §3：user_confirm 标最弱档，统计时分档——评估体系看档位构成）
STRENGTH_STRONG = "strong"  # quiz/practice：台账接地证据
STRENGTH_WEAK = "weak"  # user_confirm：用户说"会了"也算证据，但最弱档

# 证据时效窗口（设计 §3「近期记录存在」）：超过窗口的台账记录不算数——
# 一个月前答对过不等于现在会（间隔遗忘是常识，也是 spacing 机制的同一条依据）
_EVIDENCE_RECENT_DAYS = 30

_TS_FMT = "%Y-%m-%d %H:%M:%S"  # 与 learning.py 台账时间戳同一套字面量


def _now() -> str:
    return datetime.now().strftime(_TS_FMT)


def _empty_plan() -> dict:
    return {"goal": "", "created": "", "items": [], "archived": []}


def _load() -> dict:
    """读 plan.json。文件不存在/损坏 → 空计划（读失败不崩，也绝不覆写原文件）。"""
    f = PLAN_FILE()
    if not f.exists():
        return _empty_plan()
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except Exception as _e:
        print(f"[tools/plan] plan.json 解析失败（按无计划处理，未覆写）: {_e}", flush=True)
        return _empty_plan()
    if not isinstance(data, dict):
        return _empty_plan()
    out = _empty_plan()
    out.update({k: data[k] for k in out if k in data})
    if not isinstance(out["items"], list):
        out["items"] = []
    if not isinstance(out["archived"], list):
        out["archived"] = []
    return out


def _save(plan: dict) -> None:
    """原子写（不可再生数据禁止 write_text 直写——见 utils/atomic_io 铁律）。"""
    atomic_write_text(PLAN_FILE(), json.dumps(plan, ensure_ascii=False, indent=2))


def _log(action: str, summary: str) -> None:
    """全部变更写 change_log（复用 memory/store 现有 log_change 通道——同一仪器禁第二份实现）。"""
    try:
        from app.memory.store import log_change

        log_change(action, summary)
    except Exception as _e:
        print(f"[tools/plan] change_log 留痕失败（静默）: {_e}", flush=True)


def _is_active(plan: dict) -> bool:
    """有活跃计划 = goal 非空且 items 非空（归档后 goal/items 清空，快照进 archived）。"""
    return bool(plan.get("goal")) and bool(plan.get("items"))


def _done_count(plan: dict) -> int:
    return sum(1 for it in plan["items"] if it.get("passes"))


def _next_item(plan: dict) -> dict | None:
    for it in plan["items"]:
        if not it.get("passes"):
            return it
    return None


def _summary_line(plan: dict) -> str:
    nxt = _next_item(plan)
    nxt_txt = nxt["description"] if nxt else "（全部完成——可 plan_update(action='archive') 归档）"
    return f"{plan['goal']}（{_done_count(plan)}/{len(plan['items'])} 项，下一项：{nxt_txt}）"


def active_plan_line() -> str | None:
    """注入用单行摘要（设计 §4：prompt 薄 + 指针哲学——上下文只放指针，细节模型自调 plan_status）。

    无活跃计划/异常 → None（调用方逐字节不变是硬约束，有单测）。"""
    plan = _load()
    if not _is_active(plan):
        return None
    return _summary_line(plan)


def _validate_items(items) -> str | None:
    """schema 校验（设计 §3-1：items 非空、每项有 description+steps）。返回 None=合法，否则错误说明。"""
    if not isinstance(items, list) or not items:
        return "items 必须是非空列表（计划至少拆出一项）"
    for i, it in enumerate(items):
        if not isinstance(it, dict):
            return f"第 {i + 1} 项不是对象（每项需 {{description, steps}}）"
        if not str(it.get("description", "")).strip():
            return f"第 {i + 1} 项缺 description（这项要达成什么）"
        steps = it.get("steps")
        if not isinstance(steps, list) or not [s for s in steps if str(s).strip()]:
            return f"第 {i + 1} 项缺 steps（完成标准——怎样算这项做完了）"
    return None


def _new_item(item_id: str, description: str, steps: list) -> dict:
    """item 唯一构造入口：passes 强制 False、evidence 强制 None——
    即使调用方传了 passes=true 也不认（schema 层就锁死，不靠模型自觉）。"""
    return {
        "id": item_id,
        "description": str(description).strip(),
        "steps": [str(s).strip() for s in steps if str(s).strip()],
        "passes": False,
        "evidence": None,
    }


def plan_create(goal: str, items: list) -> str:
    """创建学习计划（长任务初始化器）——把学习目标拆成有条目、有完成标准的机器可读计划。

    使用时机：用户提出一个跨会话的学习目标（"一个月内搞定动态规划"、"系统复习算法基础"）时。
    拆什么目标、每项完成标准怎么定，归你判断；schema 校验与单一活跃约束归 harness。

    items 每项 = {"description": "要达成什么", "steps": ["完成标准1", ...]}。
    ⚠️ passes 由 harness 强制为 False——完工只能经 plan_advance 且证据核验，这里写了也不算。

    同一时刻只允许一个活跃计划（向外一件事）：已有活跃计划时本调用被拒绝，
    先 plan_update(action="archive") 归档现有计划，再来建新计划。"""
    goal = str(goal).strip()
    if not goal:
        return "(拒绝) goal 不能为空——计划要回答「往哪去」"
    err = _validate_items(items)
    if err:
        return f"(拒绝) schema 校验失败：{err}"
    plan = _load()
    if _is_active(plan):
        return (
            f"(拒绝) 已有进行中的计划：{_summary_line(plan)}。"
            f"同一时刻只推进一件事——要换计划，先 plan_update(action='archive') 归档现有计划再重建。"
        )
    new_items = [_new_item(str(i + 1), it["description"], it["steps"]) for i, it in enumerate(items)]
    plan["goal"] = goal
    plan["created"] = _now()
    plan["items"] = new_items
    _save(plan)
    _log("plan_create", f"建计划「{goal}」{len(new_items)} 项 | 首项：{new_items[0]['description'][:40]}")
    return (
        f"计划已建立：{goal}（{len(new_items)} 项）。"
        f"第一项：{new_items[0]['description']}（完成标准：{'；'.join(new_items[0]['steps'])}）。"
        f"推进时用 plan_advance 逐项验收——passes 只有证据核验通过才能置位。"
    )


def plan_status() -> str:
    """读计划进度（增量模式的「进行到哪了」）——会话开始/需要接续时自调。

    返回 goal、完成度、下一未完成项（含完成标准）、最近变更。
    刻意只呈现下一项而不给全清单压力（设计 §5：防 one-shot 烧穿——一次只推进一项）。"""
    plan = _load()
    if not _is_active(plan):
        n_arch = len(plan["archived"])
        tail = f"（已归档 {n_arch} 个历史计划）" if n_arch else ""
        return f"当前没有进行中的学习计划{tail}。用户提出跨会话学习目标时，用 plan_create 拆解。"
    lines = [
        f"目标：{plan['goal']}（{plan['created']} 建立）",
        f"完成度：{_done_count(plan)}/{len(plan['items'])} 项",
    ]
    nxt = _next_item(plan)
    if nxt:
        lines.append(f"下一项 [{nxt['id']}]：{nxt['description']}")
        lines.append(f"完成标准：{'；'.join(nxt['steps'])}")
    else:
        lines.append("全部条目已完成——可 plan_update(action='archive') 归档，再开启下一件事。")
    changes = _recent_plan_changes(3)
    if changes:
        lines.append("最近变更：" + "；".join(changes))
    return "\n".join(lines)


def _recent_plan_changes(limit: int) -> list:
    """change_log 里 plan_* 动作的最近 N 条（最新在前→反转为时间正序呈现）。"""
    try:
        from app.memory.store import read_changes

        recs = [r for r in read_changes(50) if str(r.get("action", "")).startswith("plan")]
        return [f"{r.get('time', '')} {r.get('summary', '')}" for r in recs[:limit]][::-1]
    except Exception:
        return []


def _topic_match(ref: str, topic: str) -> bool:
    """主题匹配口径（与 spacing_signal/mastery_signal 同一口径，禁第二份实现）：
    大小写不敏感子串——ref 应是台账里的主题名或其一部分。"""
    ref, topic = ref.strip().lower(), str(topic).strip().lower()
    return bool(ref) and bool(topic) and ref in topic


def _evidence_gap(evidence_type: str, ref: str) -> str | None:
    """接地核验（纯代码，不变量无口）。返回 None=核验通过；否则返回缺什么证据。

    quiz     → mastery 台账近期存在该主题 judge=="对" 的知识轨记录（_is_correct 唯一判定入口）
    practice → 台账近期存在该主题的实践轨记录（实践没有对错，存在即证据）
    """
    from app.tools.learning import LEDGER_TYPE_PRACTICE, _is_correct, _ledger_read

    if not ref.strip():
        return "evidence_ref 不能为空——传该条目对应的台账主题名（如「正则化」）"
    cutoff = datetime.now() - timedelta(days=_EVIDENCE_RECENT_DAYS)
    recs = []
    for r in _ledger_read():
        try:
            ts = datetime.strptime(str(r.get("ts", "")), _TS_FMT)
        except ValueError:
            continue  # ts 解析不了的记录不作证据（宁可缺证据，不认来路不明的记录）
        if ts >= cutoff and _topic_match(ref, r.get("topic", "")):
            recs.append(r)
    if evidence_type == EVIDENCE_QUIZ:
        if any(_is_correct(r) for r in recs):
            return None
        if recs:
            return (
                f"「{ref}」近 {_EVIDENCE_RECENT_DAYS} 天有 {len(recs)} 条练习记录，但没有判「对」的"
                f"（部分对/不对按掌握口径不算）——先练习并由 grade_answer 批改通过再来验收"
            )
        return (
            f"「{ref}」近 {_EVIDENCE_RECENT_DAYS} 天没有任何练习记录——"
            f"先用 generate_practice 出题、grade_answer 批改，判「对」后证据自然就位"
        )
    # practice
    if any(str(r.get("type", "")) == LEDGER_TYPE_PRACTICE for r in recs):
        return None
    return (
        f"「{ref}」近 {_EVIDENCE_RECENT_DAYS} 天没有实践轨记录——"
        f"真实场景做完一次后，用 grade_answer(attempt_type='practice') 记录复盘证据再来验收"
    )


def plan_advance(item_id: str, evidence_type: str, evidence_ref: str = "") -> str:
    """推进计划：验收一个条目为已完成（passes=true 的唯一通道——不变量锁死，无口绕过）。

    evidence_type 三档：
    - quiz：知识类条目。代码核验 mastery 台账近 30 天存在该主题判「对」的记录，核验不过拒绝置位。
    - practice：实践类条目。代码核验台账近 30 天存在该主题实践轨记录，核验不过拒绝置位。
    - user_confirm：用户明确说"会了"。直接接受，但标最弱档（统计时分档——自述证据强度最低）。
    evidence_ref：条目对应的台账主题名（quiz/practice 必填；user_confirm 可留空）。

    使用时机：有把握某条目的完成标准已达成时。核验被拒不是失败——返回里会写明缺什么证据，
    补齐证据（练习/实践/用户确认）后再来。"""
    et = str(evidence_type).strip().lower()
    if et not in EVIDENCE_TYPES:
        return f"(拒绝) evidence_type 只能是 {'/'.join(EVIDENCE_TYPES)}"
    plan = _load()
    if not _is_active(plan):
        return "(拒绝) 当前没有进行中的计划——先 plan_status 确认，或 plan_create 建计划"
    item = next((it for it in plan["items"] if str(it.get("id")) == str(item_id).strip()), None)
    if item is None:
        ids = "、".join(str(it.get("id")) for it in plan["items"])
        return f"(拒绝) 找不到条目 id={item_id}（现有：{ids}）"
    if item.get("passes"):
        return f"条目 [{item['id']}]「{item['description']}」此前已验收通过，无需重复推进"
    if et == EVIDENCE_USER_CONFIRM:
        strength = STRENGTH_WEAK
    else:
        gap = _evidence_gap(et, evidence_ref)
        if gap:
            return f"(拒绝) 证据核验未通过：{gap}"
        strength = STRENGTH_STRONG
    item["passes"] = True
    item["evidence"] = {"type": et, "ref": evidence_ref.strip(), "ts": _now(), "strength": strength}
    _save(plan)
    _log(
        "plan_advance",
        f"验收 [{item['id']}]「{item['description'][:40]}」| 证据 {et}({strength}) {evidence_ref.strip()[:30]}",
    )
    done, total = _done_count(plan), len(plan["items"])
    nxt = _next_item(plan)
    tier_note = "（用户确认档=最弱档证据，评估统计会分档呈现）" if strength == STRENGTH_WEAK else ""
    if nxt:
        return f"已验收 [{item['id']}]「{item['description']}」{tier_note}。进度 {done}/{total}，下一项：{nxt['description']}"
    return (
        f"已验收 [{item['id']}]「{item['description']}」{tier_note}。"
        f"全部 {total} 项完成——可 plan_update(action='archive') 归档这个计划。"
    )


def plan_update(
    action: str,
    item_id: str = "",
    description: str = "",
    steps: list | None = None,
    order: list | None = None,
    passes: bool | None = None,
) -> str:
    """调整计划结构（加项/删项/改项/改序/归档）。全部变更写 change_log。

    action：
    - add：加条目（需 description+steps）
    - remove：删条目（需 item_id）
    - edit：改条目的 description/steps（需 item_id + 至少一个待改字段）
    - reorder：改序（需 order=条目 id 的完整新顺序）
    - archive：归档当前计划（全部完成或要换方向时；归档后只读，可 plan_create 开新计划）

    ⛔ passes 在此工具不可写（代码拒绝，防污染）——完工只能经 plan_advance 证据核验。"""
    if passes is not None:
        return "(拒绝) passes 不可经 plan_update 修改——完工只能走 plan_advance 且证据核验通过"
    act = str(action).strip().lower()
    plan = _load()
    if act == "archive":
        if not _is_active(plan):
            return "(拒绝) 当前没有进行中的计划可归档"
        snapshot = {
            "goal": plan["goal"],
            "created": plan["created"],
            "archived_at": _now(),
            "items": plan["items"],
        }
        plan["archived"].append(snapshot)
        plan["goal"], plan["created"], plan["items"] = "", "", []
        _save(plan)
        _log("plan_update(archive)", f"归档计划「{snapshot['goal']}」（{_done_count(snapshot)}/{len(snapshot['items'])} 项完成）")
        return f"已归档「{snapshot['goal']}」（只读，不再出现在进行中）。可以 plan_create 开启下一件事。"
    if not _is_active(plan):
        return "(拒绝) 当前没有进行中的计划——先 plan_status 确认，或 plan_create 建计划"
    if act == "add":
        err = _validate_items([{"description": description, "steps": steps or []}])
        if err:
            return f"(拒绝) schema 校验失败：{err}"
        new_id = str(max([int(str(it["id"])) for it in plan["items"] if str(it["id"]).isdigit()] + [0]) + 1)
        plan["items"].append(_new_item(new_id, description, steps))
        _save(plan)
        _log("plan_update(add)", f"加条目 [{new_id}]「{description.strip()[:40]}」")
        return f"已加条目 [{new_id}]：{description.strip()}"
    item = next((it for it in plan["items"] if str(it.get("id")) == str(item_id).strip()), None) if item_id else None
    if act == "remove":
        if item is None:
            return f"(拒绝) 找不到条目 id={item_id}"
        plan["items"] = [it for it in plan["items"] if it is not item]
        _save(plan)
        _log("plan_update(remove)", f"删条目 [{item['id']}]「{item['description'][:40]}」")
        return f"已删条目 [{item['id']}]「{item['description']}」"
    if act == "edit":
        if item is None:
            return f"(拒绝) 找不到条目 id={item_id}"
        changed = []
        if description.strip():
            item["description"] = description.strip()
            changed.append("description")
        if steps:
            valid = [str(s).strip() for s in steps if str(s).strip()]
            if not valid:
                return "(拒绝) steps 不能为空（完成标准至少一条）"
            item["steps"] = valid
            changed.append("steps")
        if not changed:
            return "(拒绝) edit 需要至少一个待改字段（description 或 steps）"
        _save(plan)
        _log("plan_update(edit)", f"改条目 [{item['id']}] {'/'.join(changed)}")
        return f"已改条目 [{item['id']}]（{'/'.join(changed)}）"
    if act == "reorder":
        if not order:
            return "(拒绝) reorder 需要 order=条目 id 的完整新顺序"
        by_id = {str(it["id"]): it for it in plan["items"]}
        new_order = [str(o).strip() for o in order]
        if sorted(new_order) != sorted(by_id):
            return f"(拒绝) order 必须恰好包含全部条目 id（现有：{'、'.join(by_id)}）"
        plan["items"] = [by_id[i] for i in new_order]
        _save(plan)
        _log("plan_update(reorder)", f"改序：{' → '.join(new_order)}")
        return f"已改序：{' → '.join(new_order)}"
    return "(拒绝) action 只能是 add/remove/edit/reorder/archive"
