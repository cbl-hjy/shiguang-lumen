# -*- coding: utf-8 -*-
"""先贤会议 API（M3）——挂载到 main.py 的 /api/council/*。

端点：
- GET  /api/council/sages            星宿列表（注册表，含领域/确认状态）
- POST /api/council/debate           发起会议（SSE 流式：budget/turn/verdict/report/done）
- POST /api/council/debate/{id}/stop 随时中止（进程级标记，harness 层）
- POST /api/council/distill          用户上传书文本 → 蒸馏（SSE 流式阶段进度）
- POST /api/council/sages/{id}/confirm  人审确认星笺
"""
from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.config import DATA_DIR
from app.council import engine, registry

router = APIRouter(prefix="/api/council", tags=["council"])

DEBATES_DIR = DATA_DIR / "data" / "debates"


class DebateRequest(BaseModel):
    question: str = Field(min_length=2, max_length=500)
    sage_ids: list[str] | None = None  # 可省略：未传时按 mode 预设解析（默认模式=固定星宿，自由定义未上）
    max_rounds: int | None = Field(default=None, ge=1, le=6)  # 省略时用模式预设值
    mode: str = "cross"
    session_id: str | None = None  # 辩论事件随会话持久化（M3：进消息流，刷新可恢复）


class DistillRequest(BaseModel):
    text: str = Field(default="", max_length=2_000_000, description="书本文本（新建任务必填；续传可空——后端读存盘 raw）")
    sage_id: str = Field(pattern=r"^[a-z0-9_-]{2,30}$")
    title: str = Field(default="", max_length=60)
    job_id: str | None = Field(default=None, max_length=40, description="断点续传任务 id（续传时带，可不传文本）")


class ConfirmRequest(BaseModel):
    confirmed: bool = True


class ReportMemorizeRequest(BaseModel):
    """综合报告用户裁决进记忆（2026-08-19）：只有用户确认后才写入（actionable 压缩为记忆条目）"""
    debate_id: str
    question: str
    actionable: list[str] = []
    confirmed: bool = True


def _sse(obj: dict) -> str:
    import json
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


@router.get("/sages")
def council_sages():
    try:
        return {"sages": registry.list_sages()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"星阁读取失败：{e}")


@router.get("/sages/{sid}")
def council_sage_detail(sid: str):
    """单卡全文（治理权可见性：管理窗展开卡内容用）"""
    try:
        return registry.get_sage(sid).model_dump()
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"星宿读取失败：{e}")


@router.delete("/sages/{sid}")
def council_sage_delete(sid: str):
    """删除星宿 → 回收站 trash/（不真删，可恢复）"""
    try:
        return registry.trash_sage(sid)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除失败：{e}")


class SageMetaRequest(BaseModel):
    name: str | None = None
    stance: str | None = None


@router.patch("/sages/{sid}")
def council_sage_meta(sid: str, req: SageMetaRequest):
    """改元信息（name/stance；claim/quote 不可改=忠实度不变量）"""
    try:
        return registry.update_sage_meta(sid, name=req.name, stance=req.stance)
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"更新失败：{e}")


@router.post("/sages/{sid}/claims/{idx}/delete")
def council_claim_delete(sid: str, idx: int):
    """删观点（quote 锚点其余不动）"""
    try:
        return registry.delete_claim(sid, idx)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除观点失败：{e}")


@router.get("/modes")
def council_modes():
    """模式预设列表（含参会星宿组合）——前端只展示模式，不暴露星宿 id"""
    from app.council import modes
    from app.council.registry import get_sage

    out = []
    for mid, m in modes.MODES.items():
        sages = []
        for sid in m["sage_ids"]:
            try:
                card = get_sage(sid)
                sages.append({"id": sid, "name": card.name})
            except FileNotFoundError:
                pass
        out.append({"id": mid, "name": m["name"], "desc": m["desc"], "sages": sages,
                    "max_rounds": m["max_rounds"], "available": len(sages) > 0})
    return {"modes": out}


@router.post("/debate")
async def council_debate(req: DebateRequest):
    from app.council import modes

    sage_ids = modes.resolve_sages(req.mode, req.sage_ids)
    if not sage_ids:
        mode = modes.get_mode(req.mode)
        raise HTTPException(status_code=422, detail=f"模式「{mode['name'] if mode else req.mode}」当前书库不支持（需扩充同领域书籍）")
    try:
        engine.load_sages(sage_ids)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    max_rounds = req.max_rounds or modes.get_mode(req.mode).get("max_rounds", 2)
    debate_id = f"d-{uuid.uuid4().hex[:8]}"

    async def gen():
        from app.db import sessions

        async for ev in engine.stream_debate(req.question, sage_ids, max_rounds, debate_id, req.mode):
            # 随会话持久化（role='debate' 行，消息流恢复用）；失败不阻塞流（harness：落库是增强非主流程）
            try:
                if req.session_id and sessions.session_exists(req.session_id):
                    sessions.save_debate_event(req.session_id, json.dumps(ev, ensure_ascii=False))
            except Exception as e:
                print(f"[council] 辩论事件落库失败（跳过）: {e}", flush=True)
            yield _sse(ev)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/debate/{debate_id}/stop")
def council_stop(debate_id: str):
    engine.stop_debate(debate_id)
    return {"stopped": True, "debate_id": debate_id}


@router.post("/distill")
async def council_distill(req: DistillRequest):
    """用户上传书文本 → 蒸馏 → 星笺（SSE 流式汇报阶段进度）。
    断点续传（2026-08-20）：带 job_id 且任务在 → 续传（text 可空，后端读存盘 raw）；完成入库后删 job 目录。"""
    from app.council import distill_core

    if not req.job_id and len(req.text) < 500:
        raise HTTPException(status_code=400, detail="书文本过短（至少 500 字符）")

    async def gen():
        try:
            async for ev in distill_core.stream_distill(req.text, req.sage_id, req.title, req.job_id):
                if ev["type"] == "done":
                    card = ev["sage"]
                    (DATA_DIR / "data" / "sages" / f"{req.sage_id}.json").write_text(
                        __import__("json").dumps(card, ensure_ascii=False, indent=2), encoding="utf-8")
                    registry.list_sages()  # 刷新注册表
                    distill_core.delete_job(ev.get("job_id", ""))  # 完成即清（中断的保留）
                    yield _sse({"type": "registered", "sage_id": req.sage_id,
                                "claims": card.get("audit", {}).get("claims_count"),
                                "quote_verified": card.get("audit", {}).get("quote_verified")})
                else:
                    yield _sse(ev)
        except Exception as e:
            yield _sse({"type": "error", "detail": str(e)})

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/distill/jobs")
def council_distill_jobs():
    """所有可续传任务（断点续传 2026-08-20）：job_id/书名/进度/时间。"""
    from app.council import distill_core

    return {"jobs": distill_core.list_jobs()}


@router.post("/sages/{sage_id}/confirm")
def council_confirm(sage_id: str, req: ConfirmRequest):
    try:
        return registry.confirm_sage(sage_id, req.confirmed)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/report/memorize")
async def council_report_memorize(req: ReportMemorizeRequest):
    """综合报告用户裁决进记忆（2026-08-19）：只有用户确认后才写入。
    - 权限：用户主动点击（前端只在报告出现后显示按钮）= 授权；记忆写入自带四层去重护栏
    - 分类：笔记（词汇表无 decision 类，分类是确定性不变量不扩表）
    - 溯源：debate_id + 问题标注在条目里（可追溯会议记录 data/debates/ 或会话 debate_events）"""
    from app.memory.store import remember

    if not req.confirmed:
        return {"memorized": False, "reason": "未确认不写入"}
    if not req.actionable:
        return {"memorized": False, "reason": "报告无可行动结论"}
    note = f"【先贤会议·{req.question.strip()[:30]}】" + "；".join(req.actionable)[:200]
    result = await remember(note, source="agent", importance=6, category="笔记")
    return {"memorized": True, "result": result}
