"""M6 调度器：后台 asyncio 循环，每分钟扫描到期唤醒 → 独立 agent 生成鲜活提醒 → 写 notifications
设计依据：docs/M6-DESIGN.md
红线：应用层零"该不该提醒"判断——时间和理由全是模型写的（schedule_wakeup 工具），
调度器只做"到点取数 → 生成 → 投递"。提醒内容用独立 agent 生成（不污染主对话）。
"""

import asyncio
import sys

from app.db import wakeups

SCAN_INTERVAL = 60  # 秒（M6 验收时可改小）

_task: asyncio.Task | None = None

# 提醒生成器（独立 agent，模型驱动，不用模板）
from pydantic_ai import Agent

_reminder_agent: Agent | None = None


def _get_reminder_agent() -> Agent:
    global _reminder_agent
    if _reminder_agent is None:
        from app.agent.model import get_model

        _reminder_agent = Agent(
            get_model(),
            system_prompt=(
                "你是「拾光」学习搭子的提醒生成器。用户之前主动约定了一个学习提醒，"
                "现在到时间了。请用一句话（不超过 60 字）自然、温暖地提醒用户，"
                "像朋友随口一提，不要客套、不要加感叹号堆砌。只输出提醒本身。"
            ),
        )
    return _reminder_agent


async def _generate_reminder(reason: str) -> str:
    """用独立 agent 把约定理由变成鲜活提醒；失败降级为原文（护栏：不让调度器卡死）"""
    try:
        r = await _get_reminder_agent().run(f"约定的提醒内容：{reason}")
        text = r.output.strip()
        return text[:120] if text else reason
    except Exception as e:
        # 2026-09-17 修复（静默失败可见化）：原 except 无输出——降级事件不可观测
        # （违项目红线"静默失败禁止"；且"生成失败降级率"是实验 D 的 SLA 指标，静默=不可测）。
        # 行为不变：仍降级为原文，仅补可见化。
        print(
            f"[scheduler] 提醒生成失败，降级为原文: {type(e).__name__}: {e}",
            file=sys.stderr,
            flush=True,
        )
        return reason


async def _tick():
    """扫描一次到期唤醒（应用层只投递，不判断该不该）"""
    from app.config import EXPERIMENT_MODE

    if EXPERIMENT_MODE:
        return  # 实验模式：真实世界副作用全关（提醒不投递）——模型不知道被测试，拦截在投递前不在生成前
    from app.auth_core import set_current_user_id

    # 2026-09-17 修复（投递断裂）：此前只扫全局库，多用户改造后用户提醒在
    # per-user 库 → 注册的提醒永不触发。现遍历全局+全部用户库，并逐条设置
    # 对应 uid 上下文（通知/标记写入正确用户的库）。
    due = wakeups.due_wakeups_all()
    from app import mrt  # B 实验拦截层（默认关=零影响）

    for uid, w in due:
        set_current_user_id(uid)  # None = 全局库
        arm = mrt.decide(w)  # 保底（时段/关键词）+ 50% 抽签；实验关 → "off"
        if arm == "suppressed":
            wakeups.mark_fired(w["id"])  # 抽中"拦"：消耗不投递（用户无感知）
            mrt.log_point(uid, w, arm)
            continue
        content = await _generate_reminder(w["reason"])
        wakeups.add_notification(content)
        wakeups.mark_fired(w["id"])
        mrt.log_point(uid, w, arm)


async def run_scheduler():
    """常驻循环：每分钟扫一次；异常吞掉不退出（调度器不能死）"""
    while True:
        try:
            await _tick()
        except Exception as _e:
            print(f"[app/scheduler] 静默异常已可见化: {_e}", flush=True)
        await asyncio.sleep(SCAN_INTERVAL)


def start():
    """由 FastAPI lifespan 调用：启动调度器后台任务"""
    global _task
    if _task is None or _task.done():
        _task = asyncio.create_task(run_scheduler())


def stop():
    global _task
    if _task and not _task.done():
        _task.cancel()
    _task = None


if __name__ == "__main__":
    # 独立自测：把所有 pending 且到期的唤醒立即触发（验收用）
    async def main():
        await _tick()
        for n in wakeups.notifications(5):
            print(n["id"], n["content"][:60])

    asyncio.run(main())
