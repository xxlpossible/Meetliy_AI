from datetime import datetime
from enum import IntEnum
from typing import Optional, Dict, Any

from sqlalchemy import Column, DateTime, String, text, Text, JSON, desc
from sqlmodel import Field, SQLModel, select

from database.base import session_getter
from database.schemas.schema import TranscriptionQueryVo
from sqlalchemy import select, and_
from sqlalchemy.sql import func


class Status(IntEnum):
    ERROR = -1  # 解析错误
    PENDING = 0  # 正在解析
    COMPLETE = 1  # 解析完成


class Delete(IntEnum):
    NOT = 0
    YES = -1


class TranscriptionBase(SQLModel):
    task_name: Optional[str] = Field(default=None)
    status: Optional[int] = Field(default=Status.PENDING.value)
    task_result: Optional[Dict[str, Any]] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False)
    )
    is_delete: Optional[int] = Field(default=Delete.NOT.value)
    realtime_asr_text: Optional[str] = Field(default=None)
    note: Optional[str] = Field(default=None)
    create_time: Optional[datetime] = Field(sa_column=Column(
        DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(
        sa_column=Column(DateTime,
                         nullable=False,
                         server_default=text('CURRENT_TIMESTAMP'),
                         onupdate=text('CURRENT_TIMESTAMP')))


class Transcription(TranscriptionBase, table=True):
    id: str = Field(default=None, primary_key=True)


class TranscriptionDao:
    @classmethod
    def add(cls, transcription: Transcription):
        with session_getter() as session:
            session.add(transcription)
            session.commit()
            session.refresh(transcription)
            return transcription

    @classmethod
    def update(cls, transcription: Transcription):
        with session_getter() as session:
            db_transcription = session.merge(transcription)
            session.commit()
            session.refresh(db_transcription)
            return transcription

    @classmethod
    def delete(cls, task_id: str):
        with session_getter() as session:
            transcription = cls.get_by_id(t_id=task_id)
            if not transcription:
                raise ValueError(f"Transcription with task_id '{task_id}' not found")

            session.delete(transcription)
            session.commit()

    @classmethod
    def get_by_id(cls, t_id: str) -> Transcription:
        with session_getter() as session:
            statement = select(Transcription).where(Transcription.id == t_id)
            return session.exec(statement).scalars().first()

    @classmethod
    def list(cls, body: TranscriptionQueryVo):
        with session_getter() as session:
            # 构建基础查询
            statement = select(Transcription)

            # 添加条件查询
            conditions = [Transcription.is_delete != Delete.YES.value]
            if body.task_name:
                conditions.append(Transcription.task_name.contains(body.task_name))

            # 如果有条件，则添加到查询中
            if conditions:
                statement = statement.where(and_(*conditions))

            # 添加时间排序（从新到旧，即从现在到以前）
            statement = statement.order_by(desc(Transcription.create_time))
            # 计算偏移量用于分页
            offset = (body.page_num - 1) * body.page_size

            # 添加分页
            statement = statement.offset(offset).limit(body.page_size)

            # 执行查询
            results = session.exec(statement).scalars().all()

            # 查询总记录数（用于分页信息）- 修复错误
            count_statement = select(func.count(Transcription.id))
            if conditions:
                count_statement = count_statement.where(and_(*conditions))
            total_count = session.exec(count_statement).scalars().one()

            return results, total_count
