# -*- coding: utf-8 -*-
"""知识库路由（B7 拆分，2026-08-20）：kb 文档治理权四件套（可见/删除/改名）+ 重索引。"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


@router.get("/api/kb/reindex")
def kb_reindex_api():
    """手动重建知识库索引（源文件权威；删库/索引损坏/检索引空时用）"""
    from app.tools.kb import kb_reindex

    return {"ok": True, "msg": kb_reindex()}


class KbRenameRequest(BaseModel):
    title: str


@router.get("/api/kb/documents")
def kb_documents_api():
    """知识库文档列表（治理权#可见，2026-08-20 最小落地清单⑤）"""
    from app.tools.kb import kb_list_documents

    return {"documents": kb_list_documents()}


@router.delete("/api/kb/documents/{doc_id}")
def kb_document_delete(doc_id: str):
    """删除文档（可撤销：移回收站 trash/ + 同步清 chroma 向量——防幽灵检索）"""
    from app.tools.kb import kb_delete_document

    return kb_delete_document(doc_id)


@router.patch("/api/kb/documents/{doc_id}")
def kb_document_rename(doc_id: str, req: KbRenameRequest):
    """重命名文档（改首行标题 + 同步 chroma metadata.source）"""
    from app.tools.kb import kb_rename_document

    return kb_rename_document(doc_id, req.title)
