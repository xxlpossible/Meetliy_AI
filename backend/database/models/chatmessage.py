from datetime import datetime
from enum import IntEnum
from typing import Optional, Dict, Any, List

from sqlalchemy import Column, DateTime, String, text, Text, JSON, desc
from sqlmodel import Field, SQLModel, select

from database.base import session_getter
from database.schemas.schema import TranscriptionQueryVo, ChatMessageQuery
from sqlalchemy import select, and_
from sqlalchemy.sql import func


class ChatMessageBase(SQLModel):
    task_id: Optional[str] = Field(default=None)
    chat_messages: Optional[List[str]] = Field(default=None, sa_column=Column(JSON))
    user_id: Optional[int] = Field(default=None)
    create_time: Optional[datetime] = Field(sa_column=Column(
        DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(
        sa_column=Column(DateTime,
                         nullable=False,
                         server_default=text('CURRENT_TIMESTAMP'),
                         onupdate=text('CURRENT_TIMESTAMP')))


class ChatMessage(ChatMessageBase, table=True):
    chat_id: Optional[int] = Field(default=None, primary_key=True, unique=True)


class ChatMessageDao:
    @classmethod
    def get_list_by_task_id(cls, task_id: str, page_size: int, page_num: int, user_id: int = None):
        """
        分页查询某 task 下的聊天记录。
        传入 user_id 时仅返回该用户的记录（越权防护，用户间互不可见）。
        """
        with session_getter() as session:
            conditions = [ChatMessage.task_id == task_id]
            if user_id is not None:
                conditions.append(ChatMessage.user_id == user_id)

            query = select(ChatMessage).where(*conditions)
            count = select(func.count()).select_from(ChatMessage).where(*conditions)

            total_count = session.scalar(count) or 0

            if total_count == 0:
                return [], 0

            offset = (page_num - 1) * page_size

            res = session.scalars(query.offset(offset).limit(page_size)).all()

            return res, total_count

    @classmethod
    def add(cls, chat_message: ChatMessage):
        with session_getter() as session:
            session.add(chat_message)
            session.commit()
            session.refresh(chat_message)
            return chat_message

    @classmethod
    def update(cls, chat_message: ChatMessage):
        with session_getter() as session:
            db_message = session.merge(chat_message)
            session.commit()
            session.refresh(db_message)
            return db_message

    @classmethod
    def get_chat_by_chat_id(cls, chat_id: str = None, user_id: int = None) -> Optional[ChatMessage]:
        """
        按 chat_id 查询聊天记录。
        传入 user_id 时仅返回属于该用户的记录（越权防护）。
        """
        with session_getter() as session:
            conditions = [ChatMessage.chat_id == chat_id]
            if user_id is not None:
                conditions.append(ChatMessage.user_id == user_id)
            statement = select(ChatMessage).where(*conditions)
            return session.scalars(statement).first()

    @classmethod
    def delete(cls, chat_id: str, user_id: int = None) -> bool:
        """
        按 chat_id 删除聊天记录。
        传入 user_id 时校验归属权限，非本人记录删除 0 行返回 False。
        返回是否实际删除了记录。
        """
        with session_getter() as session:
            conditions = [ChatMessage.chat_id == chat_id]
            if user_id is not None:
                conditions.append(ChatMessage.user_id == user_id)
            statement = select(ChatMessage).where(*conditions)
            chat = session.scalars(statement).first()
            if chat is None:
                return False
            session.delete(chat)
            session.commit()
            return True


