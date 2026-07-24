"""
聊天会话（ChatSession）实体模型。

设计说明：
    ChatSession 记录一次 AI 对话会话的元信息：会话ID、会话名称、关联的会议任务ID列表、
    关联的知识库ID列表、创建者用户ID。
    
    会话在 WebSocket /ws/chat 首次收到消息时自动创建（无需单独的 add 接口）。
    session_name 默认取用户第一条问题的前 20 个字符，可通过 update 接口修改。
"""
from datetime import datetime
from typing import Optional, List

from sqlalchemy import Boolean, Column, DateTime, JSON, text, String, desc, select
from sqlalchemy.sql import func
from sqlmodel import Field, SQLModel

from database.base import session_getter


class ChatSessionBase(SQLModel):
    session_id: str = Field(primary_key=True, description="会话ID（前端生成或 WS 传入），主键")
    session_name: Optional[str] = Field(
        default=None, 
        sa_column=Column(String(255), nullable=True, comment="会话名称，默认取用户第一条问题")
    )
    user_id: int = Field(nullable=False, index=True, description="会话创建者用户ID")
    # 关联的会议任务ID列表，存为 JSON 数组
    task_ids: Optional[List[str]] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False, comment="关联的会议任务ID列表")
    )
    # 关联的知识库ID列表，存为 JSON 数组
    knowledge_ids: Optional[List[str]] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False, comment="关联的知识库ID列表")
    )
    # 会话级别：是否启用知识库检索
    need_kb: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, default=False, comment="是否启用知识库检索")
    )
    create_time: Optional[datetime] = Field(sa_column=Column(
        DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(
        sa_column=Column(DateTime,
                         nullable=False,
                         server_default=text('CURRENT_TIMESTAMP'),
                         onupdate=text('CURRENT_TIMESTAMP')))


class ChatSession(ChatSessionBase, table=True):
    pass


class ChatSessionDao:
    @classmethod
    def add(cls, session: ChatSession) -> ChatSession:
        with session_getter() as db_session:
            db_session.add(session)
            db_session.commit()
            db_session.refresh(session)
            return session

    @classmethod
    def get_by_session_id(cls, session_id: str, user_id: int = None) -> Optional[ChatSession]:
        """按 session_id 查询会话。传入 user_id 时校验权限。"""
        with session_getter() as db_session:
            statement = select(ChatSession).where(ChatSession.session_id == session_id)
            if user_id is not None:
                statement = statement.where(ChatSession.user_id == user_id)
            return db_session.exec(statement).scalars().first()

    @classmethod
    def list(cls, user_id: int, page_num: int = 1, page_size: int = 20):
        """分页查询当前用户的会话列表，按更新时间倒序。"""
        with session_getter() as db_session:
            statement = (
                select(ChatSession)
                .where(ChatSession.user_id == user_id)
                .order_by(desc(ChatSession.update_time))
            )
            offset = (page_num - 1) * page_size
            results = db_session.exec(statement.offset(offset).limit(page_size)).scalars().all()

            count_statement = (
                select(func.count())
                .select_from(ChatSession)
                .where(ChatSession.user_id == user_id)
            )
            total_count = db_session.scalar(count_statement) or 0

            return results, total_count

    @classmethod
    def update(cls, session: ChatSession) -> ChatSession:
        """
        更新会话信息。
        
        merge() 返回新实例，旧实例不在当前 Session 内，需使用 merge 返回值的 refresh。
        """
        with session_getter() as db_session:
            merged = db_session.merge(session)
            db_session.commit()
            db_session.refresh(merged)
            return merged

    @classmethod
    def delete(cls, session_id: str, user_id: int) -> bool:
        """删除会话。仅创建者可删除。返回是否成功。"""
        with session_getter() as db_session:
            statement = select(ChatSession).where(
                ChatSession.session_id == session_id,
                ChatSession.user_id == user_id,
            )
            session = db_session.exec(statement).scalars().first()
            if not session:
                return False
            db_session.delete(session)
            db_session.commit()
            return True
