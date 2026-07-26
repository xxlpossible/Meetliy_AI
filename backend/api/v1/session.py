"""
会话管理 REST 接口：list / update / delete。

注意：无 add 接口，因为 Session 在 WebSocket /ws/chat 中自动创建。
"""

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from pydantic import BaseModel

from api.schemas import resp_200
from database.models.chat_session import ChatSessionDao
from database.models.user import User
from utils.dependencies import get_current_user
from utils.siliconflow_embedding import db_manager

router = APIRouter(prefix="/session", tags=["session"])


class SessionListResponse(BaseModel):
    """会话列表响应项"""
    session_id: str
    session_name: str | None
    task_ids: list[str] | None
    knowledge_ids: list[str] | None
    need_kb: bool
    user_id: int
    create_time: str | None
    update_time: str | None


class SessionUpdateRequest(BaseModel):
    """更新会话请求体"""
    session_id: str
    session_name: str | None = None
    task_ids: list[str] | None = None
    knowledge_ids: list[str] | None = None
    need_kb: bool | None = None


class SessionListRequest(BaseModel):
    page_num: int = 1
    page_size: int = 20


@router.post("/list", summary="获取当前用户的会话列表")
async def list_sessions(
    body: SessionListRequest,
    current_user: User = Depends(get_current_user),
):
    """
    分页查询当前用户的 AI 对话会话列表，按更新时间倒序。
    仅返回自己创建的会话。
    """
    items, total = ChatSessionDao.list(
        user_id=current_user.id,
        page_num=body.page_num,
        page_size=body.page_size,
    )
    serialized = []
    for s in items:
        serialized.append({
            "session_id": s.session_id,
            "session_name": s.session_name,
            "user_id": s.user_id,
            "task_ids": s.task_ids or [],
            "knowledge_ids": s.knowledge_ids or [],
            "need_kb": s.need_kb,
            "create_time": str(s.create_time) if s.create_time else None,
            "update_time": str(s.update_time) if s.update_time else None,
        })
    return resp_200(data={
        "items": serialized,
        "total": total,
        "page_num": body.page_num,
        "page_size": body.page_size,
    })


@router.post("/update", summary="更新会话信息")
async def update_session(
    body: SessionUpdateRequest,
    current_user: User = Depends(get_current_user),
):
    """
    更新会话的名称、关联任务或知识库。
    - session_id 必填，仅会话创建者可更新。
    - 提供的字段会覆盖原有值（全量替换）。
    """
    session = ChatSessionDao.get_by_session_id(
        session_id=body.session_id,
        user_id=current_user.id,
    )
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在或无权访问")

    if body.session_name is not None:
        session.session_name = body.session_name
    if body.task_ids is not None:
        session.task_ids = body.task_ids
    if body.knowledge_ids is not None:
        session.knowledge_ids = body.knowledge_ids
    if body.need_kb is not None:
        session.need_kb = body.need_kb

    ChatSessionDao.update(session)
    logger.info(f"用户 {current_user.id} 更新会话: {body.session_id}")
    return resp_200(data={
        "session_id": session.session_id,
        "session_name": session.session_name,
        "task_ids": session.task_ids,
        "knowledge_ids": session.knowledge_ids,
        "need_kb": session.need_kb,
        "update_time": str(session.update_time) if session.update_time else None,
    })


@router.delete("/delete", summary="删除会话")
async def delete_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
):
    """
    删除指定的 AI 对话会话（物理删除）。
    - 仅会话创建者可删除。
    - 同步删除关联的 ChatMessage 记录。
    - 同步删除 Chroma 向量库中该会话的记忆数据。
    """
    deleted = ChatSessionDao.delete(session_id=session_id, user_id=current_user.id)
    if not deleted:
        raise HTTPException(status_code=404, detail="会话不存在或无权访问")
    # 清理 Chroma 向量库中的会话记忆
    try:
        db_manager.delete_by_session_id(user_id=current_user.id, session_id=session_id)
    except Exception as e:
        logger.warning(f"删除 Chroma 记忆失败（session={session_id}）: {e}")
    logger.info(f"用户 {current_user.id} 删除会话: {session_id}")
    return resp_200(message="会话已删除", data={"session_id": session_id})
