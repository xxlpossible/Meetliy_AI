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
    def get_list_by_task_id(cls, task_id: str, page_size: int, page_num: int):
        with session_getter() as session:
            query = select(ChatMessage).where(ChatMessage.task_id == task_id)
            count = select(func.count()).select_from(ChatMessage).where(ChatMessage.task_id == task_id)

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
    def get_chat_by_chat_id(cls, chat_id: str = None) -> ChatMessage:
        with session_getter() as session:
            state = select(ChatMessage).where(ChatMessage.chat_id == chat_id)
            return session.scalars(state).first()

