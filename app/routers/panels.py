# -*- coding: utf-8 -*-
"""数据面板路由（B7 拆分，2026-08-20）：main.py 瘦身——非 chat 端点按领域归位。
含：星尘（记忆）/星图（主题）/夜谈记录（会话）/领航（进度）/通知/任务进度/反馈。
auth 由 main 的全局 HTTP 中间件覆盖（对 include_router 路由同样生效）。"""
from __future__ import annotations

import json

from fastapi import APIRouter
from pydantic import BaseModel

from app.agent.delegation import ProgressTracker
from app.db import wakeups
from app.memory.store import recall_profile

router = APIRouter()


@router.get("/api/memory")
def get_memory():
    from app.agent.evolution import list_reflections, list_skills
    from app.memory.store import read_entries

    return {
        "profile": recall_profile(),
        "entries": [
            {
                "content": e.content,
                "category": e.category,
                "importance": e.importance,
                "date": e.created_at,
                "source": e.source,
                "strength": e.strength,  # S 强度（治理权：前端显示"用过 N 次"，2026-08-19）
            }
            for e in read_entries()
        ],
        "reflections": list_reflections(),
        "skills": list_skills(),
    }


class MemoryEditRequest(BaseModel):
    old: str
    new: str


@router.get("/api/memory/changes")
def memory_changes():
    """记忆变更日志（治理权#3，2026-08-18）：最近 N 条记忆写操作（谁改了什么/前后什么样）"""
    from app.memory.store import read_changes

    return {"changes": read_changes()}


class TopicRenameRequest(BaseModel):
    old: str
    new: str


class TopicMergeRequest(BaseModel):
    from_name: str
    to_name: str


class TopicSplitRequest(BaseModel):
    source: str
    new_name: str
    aliases: list[str] = []


@router.get("/api/topics")
def topics_view():
    """主题视图（P3）：带派生状态 + parent（树状数据源）+ 候选池"""
    from app.memory.topics_store import view_topics

    return {"topics": view_topics()}


@router.post("/api/topics/rename")
def topic_rename(req: TopicRenameRequest):
    """用户纠错·改名（P3）：改索引零迁移（旧名进 aliases）"""
    from app.memory.topics_store import rename_topic

    return rename_topic(req.old, req.new)


@router.post("/api/topics/merge")
def topic_merge(req: TopicMergeRequest):
    """用户纠错·合并（P3）：from 并入 to，from 的 aliases 迁移，零迁移"""
    from app.memory.topics_store import merge_topics

    return merge_topics(req.from_name, req.to_name)


@router.post("/api/topics/split")
def topic_split(req: TopicSplitRequest):
    """用户纠错·拆分（P3）：从 source 拆出独立新主题（B 的 aliases 从 A 移除，防抢归拢）"""
    from app.memory.topics_store import split_topic

    return split_topic(req.source, req.new_name, req.aliases)


class MemoryDeleteRequest(BaseModel):
    content: str


@router.post("/api/memory/edit")
async def memory_edit(req: MemoryEditRequest):
    from app.memory.store import edit_memory

    return {"ok": True, "msg": await edit_memory(req.old, req.new)}


@router.post("/api/memory/delete")
def memory_delete(req: MemoryDeleteRequest):
    from app.memory.store import forget

    return {"ok": True, "msg": forget(req.content)}


class EvolutionDeleteRequest(BaseModel):
    kind: str  # reflection | skill
    content: str


@router.post("/api/evolution/delete")
def evolution_delete(req: EvolutionDeleteRequest):
    """M5 人可删：删除反思/技能条目（文件 + 向量）"""
    from app.agent.evolution import delete_item

    return {"ok": True, "msg": delete_item(req.kind, req.content)}


@router.get("/api/sessions")
def sessions_list():
    """历史会话列表（B，DeepSeek 式）：标题 + 时间 + 消息数"""
    from app.db.sessions import list_sessions

    return {"sessions": list_sessions()}


@router.delete("/api/session/{sid}")
def session_delete(sid: str):
    """用户治理权（2026-08-18）：删除会话。安全=归档先行（data/archive/<sid>.jsonl），
    归档成功才删库行——不可逆操作有兜底。返回 deleted=True/False（False=会话不存在）。"""
    from app.db.sessions import delete_session

    ok = delete_session(sid)
    if not ok:
        return {"ok": False, "msg": "会话不存在或归档失败（已放弃删除）"}
    return {"ok": True, "msg": "已删除（原始对话链已归档到 data/archive）"}


@router.post("/api/session/new")
def session_new():
    """新建会话：返回新 session_id（前端切到新会话）"""
    from app.db.sessions import new_session

    return {"session_id": new_session()}


@router.get("/api/session/{sid}")
def get_session(sid: str):
    """恢复会话：把持久化的对话链 + 辩论事件转成前端格式返回（刷新后恢复消息列表）"""
    from app.db.sessions import load_debate_events, load_messages_json
    from pydantic_ai.messages import ModelMessagesTypeAdapter

    raw = load_messages_json(sid)
    if not raw:
        return {"messages": [], "debate_events": load_debate_events(sid)}
    try:
        msgs = ModelMessagesTypeAdapter.validate_json(raw)
    except Exception as e:
        return {"messages": [], "debate_events": load_debate_events(sid), "error": str(e)}
    out = []
    for m in msgs:
        parts = getattr(m, "parts", []) or []
        content, thinking = "", ""
        tool_calls = []
        is_user = any(getattr(p, "part_kind", "") == "user-prompt" for p in parts)
        for p in parts:
            kind = getattr(p, "part_kind", "")
            if kind == "user-prompt":
                content += getattr(p, "content", "")
            elif kind == "text":
                content += getattr(p, "content", "")
            elif kind == "thinking":
                thinking += getattr(p, "content", "")
            elif kind == "tool-call":
                args = str(getattr(p, "args", "") or "")[:80]
                tool_calls.append(
                    {
                        "id": getattr(p, "tool_call_id", None),
                        "name": getattr(p, "tool_name", ""),
                        "status": "done",
                        "args": args or None,
                    }
                )
        # 跳过 system-prompt / tool-return 专用消息（无用户内容也无模型内容）
        if not content and not thinking and not tool_calls and not is_user:
            continue
        out.append(
            {
                "role": "user" if is_user else "assistant",
                "content": content or ("(调用了工具)" if tool_calls else ""),
                "thinking": thinking,
                "toolCalls": tool_calls,
                "done": True,
            }
        )
    return {"messages": out, "debate_events": load_debate_events(sid)}


@router.get("/api/progress")
def get_progress():
    """学习进度（可视化左栏）：聚合中枢（Memory Hub，2026-08-19）——
    主题视图（状态机+联动数+最后活动）+ 画像 + 统计，读取端派生视图零落盘。"""
    from app.memory.hub import build_hub_view
    from app.memory.store import read_entries

    view = build_hub_view()
    view["streak"] = wakeups.streak_days()
    view["hasLearningLog"] = wakeups.has_learning_log()
    # 容量软阈值（治理权#4 前端横幅数据源，2026-08-19）：>100 条前端提示"该整理记忆了"
    from app.memory.schema import MEMORY_SOFT_LIMIT, MEMORY_LINE_LIMIT

    view["memory_soft_limit"] = MEMORY_SOFT_LIMIT
    view["memory_hard_limit"] = MEMORY_LINE_LIMIT
    # 本周目标（S3，2026-08-19）：本周学习天数/目标 6 天——数据源 daily_activity
    view["week_days"] = wakeups.week_learning_days()
    view["week_target"] = 6
    view["week_progress"] = round(view["week_days"] / view["week_target"] * 100)
    view["recentActivity"] = [
        {"date": a["date"], "topics": json.loads(a.get("topics") or "[]")}
        for a in wakeups.recent_activity(7)
    ]
    return view


# ---------- M6 通知 API（前端轮询投递）----------

@router.get("/api/notifications")
def get_notifications():
    return {"notifications": wakeups.notifications(20)}


# ---------- M7 多 agent 任务进度（前端进度卡轮询）----------

@router.get("/api/tasks/{run_id}")
async def get_task_progress(run_id: str):
    snap = await ProgressTracker(run_id).snapshot()
    return {"run_id": run_id, "progress": snap}


# ---------- M8 进化层反馈（前端 👎/👍 按钮 → 反思/技能）----------

class FeedbackRequest(BaseModel):
    rating: int  # -1=不满意（触发反思）, 1=满意（提示可存技能）
    message: str  # 用户当时说的话
    response: str | None = None  # 模型的回复（上下文）


@router.post("/api/feedback")
async def feedback(req: FeedbackRequest):
    """响应显式用户动作：👎 → 触发反思入库；👍 → 返回提示信息（由模型自主决定是否存技能）"""
    from app.agent.evolution import reflect_teaching

    if req.rating < 0:
        ctx = f"用户说：{req.message}"
        if req.response:
            ctx += f"\n我当时的讲解：{req.response[:500]}"
        result = await reflect_teaching(ctx)
        return {"ok": True, "handled": "reflection", "msg": result}
    return {"ok": True, "handled": "ack", "msg": "已收到 👍，觉得这套讲法好可以直接告诉我存进技能库"}


class NotificationReadRequest(BaseModel):
    id: int


@router.post("/api/notifications/read")
def notification_read(req: NotificationReadRequest):
    wakeups.mark_read(req.id)
    return {"ok": True}
