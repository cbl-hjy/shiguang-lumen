"""M2 学习搭子 agent：画像常驻注入 + JIT 检索 + 模型驱动画像更新
设计依据：docs/M2-DESIGN.md
- instructions 注入"画像摘要"（瘦身）而非全量记忆（上下文工程）
- search_memory 暴露给模型自主触发（Anthropic Memory tool 范式："需要细节先检索"）
- update_profile 内部调 LLM 压缩记忆 → 原地重写 profile（LangMem enable_inserts=False 语义）
"""
from pydantic_ai import Agent

from app.agent.model import get_model
from app.agent.delegation import deleg_study
from app.agent.evolution import (
    recent_pair,
    reflect_teaching,
    save_skill,
    search_skills,
)
from app.db.wakeups import cancel_wakeup, log_learning, schedule_wakeup
from app.memory.schema import WRITE_RULES
from app.memory.store import (
    forget,
    register_profile_writer,
    remember,
    search_memory,
    update_profile,
)
from app.tools.documents import read_document
from app.tools.kb import kb_ingest, kb_search
from app.tools.ocr import ocr_image
from app.tools.sandbox import python_sandbox
from app.tools.web_search import web_search
from app.memory.state import inject_state, update_state
from app.memory import store

MINIMAL_PROMPT = "你是我的学习搭子。自然回应我，像朋友一样，不客套。"

_tutor: Agent | None = None


def _build_model():
    """统一工厂（fallback 链入口，见 app/agent/model.py）"""
    return get_model()


async def _summarize_to_profile(memory_text: str) -> str:
    """画像生成器：把全部记忆压缩成画像（模型驱动，非代码规则）"""
    summarizer = Agent(
        _build_model(),
        system_prompt=(
            "你是记忆整理器。把用户的记忆条目压缩成一份『用户画像』："
            "包含学习偏好、目标、进度、卡点、习惯，按主题分组，每条一行，"
            "用『用户…』口吻，保留具体日期，总长不超过 800 字。"
            "只输出画像本身，不要解释。"
        ),
    )
    r = await summarizer.run(memory_text)
    return r.output.strip()


def build_tutor_agent() -> Agent:
    global _tutor
    if _tutor is not None:
        return _tutor

    register_profile_writer(_summarize_to_profile)
    model = _build_model()

    # D1 事件兜底（v0.2，2026-08-13）：remember 只标记"本会话记忆变化"，
    # 提炼由会话收尾钩子（main.py）触发——触发时机归机器（事件），提炼内容归模型（LLM 压缩）。
    # 粒度 = 会话结束 + 本会话有记忆变化（不是每次 remember 立即提炼，成本可控）。
    async def _remember_mark(note, source="user", importance=5, category="note"):
        r = await remember(note, source, importance, category)
        return r  # mark_memory_changed 已在 store.remember 写入成功后置位

    agent = Agent(
        model,
        system_prompt=MINIMAL_PROMPT,
        tools=[
            _remember_mark,
            search_memory,
            update_profile,
            forget,
            update_state,
            web_search,
            python_sandbox,
            ocr_image,
            read_document,
            kb_search,
            kb_ingest,
            schedule_wakeup,
            cancel_wakeup,
            log_learning,
            deleg_study,
            reflect_teaching,
            save_skill,
            search_skills,
        ],
    )

    @agent.instructions
    def inject_context() -> str:
        from datetime import datetime

        from app.memory.state import inject_state

        now = datetime.now()
        state_line = inject_state()
        if state_line:
            state_line = f"当前状态：{state_line}"
        return f"""现在是 {now.strftime('%Y-%m-%d %H:%M')}（周{'一二三四五六日'[now.weekday()]}）。

行为原则（不是操作手册，判断权在你）：
- 你是我的学习搭子：讲东西怎么讲得清楚怎么来（类比/直觉/举例随你），不用每轮套固定结构；我问的不是学习问题（写代码/查资料/闲聊/操作）就直接处理，不用教学腔
- 工具自主用：记忆/知识库/督促/研究/反思/技能工具齐全，每个工具的描述写明了它何时有用——遇到合适场景自己调，不用等我下指令
- 我的一个稳定偏好：讲新概念先建立直觉再上公式
- 表达方式自主：涉及流程/结构/关系的话题，可考虑用 mermaid 画图（```mermaid 代码块）；涉及对比/对照的话题可用表格。用不用、怎么用由你判断——别滥用，自然为上
- 我的画像（偏好/状态/进度等更多信息）存在 memory/profile.md——涉及我的时间安排、学习计划、进度状态时，用 read_document 读它；日常对话不用读
- 状态轮：我当前的状态（情绪/卡点/节奏/意愿）会注入在下面——它是觉察不是判断，疑似标注的你自己权衡；**我明确说出情绪/卡点/意愿（焦虑、学不动、听不懂、卡住）或纠正/缓解（缓过来了、没那么焦虑）时，先 update_state 记录/覆盖再回应**；你推断的状态必须标疑似；没变化别调

{WRITE_RULES}

我的经验（失败教训按它改进，成功讲法可参考不必套用）：
{recent_pair()}

{state_line}"""

    _tutor = agent
    return _tutor
