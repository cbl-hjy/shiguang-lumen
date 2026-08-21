"""M6 调度器：后台 asyncio 循环，每分钟扫描到期唤醒 → 独立 agent 生成鲜活提醒 → 写 notifications
设计依据：docs/M6-DESIGN.md
红线：应用层零"该不该提醒"判断——时间和理由全是模型写的（schedule_wakeup 工具），
调度器只做"到点取数 → 生成 → 投递"。提醒内容用独立 agent 生成（不污染主对话）。
"""
import asyncio
from datetime import datetime

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
    except Exception:
        return reason


async def _tick():
    """扫描一次到期唤醒（应用层只投递，不判断该不该）"""
    from app.config import EXPERIMENT_MODE

    if EXPERIMENT_MODE:
        return  # 实验模式：真实世界副作用全关（提醒不投递）——模型不知道被测试，拦截在投递前不在生成前
    due = wakeups.due_wakeups()
    for w in due:
        content = await _generate_reminder(w["reason"])
        wakeups.add_notification(content)
        wakeups.mark_fired(w["id"])


async def run_scheduler():
    """常驻循环：每分钟扫一次；异常吞掉不退出（调度器不能死）"""
    while True:
        try:
            await _tick()
        except Exception:
            pass  # 单次失败不影响循环（原因在 wakeups 表里不丢）
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
