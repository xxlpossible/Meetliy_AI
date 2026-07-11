"""
会议实体模型。

设计说明：
    Meeting 记录一场多人会议的全生命周期：创建 → 进行中 → 结束(触发转录)。
    与 Transcription/Knowledge 一致，用 user_ids(JSON 数组) 管理参会者权限，
    查询时用 JSON_CONTAINS 在 SQL 层过滤。会议结束后关联一个 Transcription 记录
    (task_id)，承载会后整段转写 + 说话人分离 + AI 纪要的结果。
"""
from datetime import datetime
from enum import IntEnum
from typing import Optional, List

from sqlalchemy import Column, DateTime, JSON, text, desc, cast, select, and_
from sqlalchemy.sql import func
from sqlmodel import Field, SQLModel

from database.base import session_getter


class MeetingStatus(IntEnum):
    ACTIVE = 0   # 进行中
    ENDED = 1    # 已结束（已触发转录）
    ERROR = -1   # 异常


class MeetingBase(SQLModel):
    meeting_name: Optional[str] = Field(default=None, description="会议名称")
    host_user_id: int = Field(nullable=False, index=True, description="会议发起人(主持人)ID")
    # 参会者ID列表，存为 JSON 数组，查询时用 JSON_CONTAINS 过滤
    user_ids: Optional[List[int]] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False, comment="参会者用户ID列表")
    )
    status: Optional[int] = Field(default=MeetingStatus.ACTIVE.value, description="会议状态 0进行中 1已结束 -1异常")
    # 会议结束后关联的 Transcription.id，承载会后转录+纪要结果
    task_id: Optional[str] = Field(default=None, description="结束后关联的转录任务ID")
    create_time: Optional[datetime] = Field(sa_column=Column(
        DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(
        sa_column=Column(DateTime,
                         nullable=False,
                         server_default=text('CURRENT_TIMESTAMP'),
                         onupdate=text('CURRENT_TIMESTAMP')))


class Meeting(MeetingBase, table=True):
    id: Optional[str] = Field(default=None, primary_key=True, unique=True)


class MeetingDao:
    @classmethod
    def add(cls, meeting: Meeting) -> Meeting:
        with session_getter() as session:
            session.add(meeting)
            session.commit()
            session.refresh(meeting)
            return meeting

    @classmethod
    def update(cls, meeting: Meeting) -> Meeting:
        with session_getter() as session:
            db_meeting = session.merge(meeting)
            session.commit()
            session.refresh(db_meeting)
            return db_meeting

    @classmethod
    def get_by_id(cls, m_id: str, user_id: int = None) -> Optional[Meeting]:
        """
        按主键查询会议。
        传入 user_id 时，仅当该用户在 user_ids 中才返回记录（越权防护）。
        """
        with session_getter() as session:
            statement = select(Meeting).where(Meeting.id == m_id)
            if user_id is not None:
                statement = statement.where(
                    func.json_contains(Meeting.user_ids, cast(user_id, JSON))
                )
            return session.exec(statement).scalars().first()

    @classmethod
    def update_status(cls, m_id: str, status: int):
        """更新会议状态。"""
        with session_getter() as session:
            meeting = session.get(Meeting, m_id)
            if meeting:
                meeting.status = status
                session.commit()

    @classmethod
    def update_task_id(cls, m_id: str, task_id: str):
        """会议结束后关联转录任务ID。"""
        with session_getter() as session:
            meeting = session.get(Meeting, m_id)
            if meeting:
                meeting.task_id = task_id
                session.commit()

    @classmethod
    def add_participant(cls, m_id: str, user_id: int):
        """给会议追加一个参会者（加入会议时调用）。"""
        meeting = cls.get_by_id(m_id=m_id)
        if not meeting:
            raise ValueError(f"Meeting with id '{m_id}' not found")
        if user_id not in (meeting.user_ids or []):
            meeting.user_ids = list(meeting.user_ids or []) + [user_id]
            cls.update(meeting)

    @classmethod
    def list(cls, user_id: int, page_num: int = 1, page_size: int = 10):
        """分页查询当前用户参加的会议列表。"""
        with session_getter() as session:
            conditions = [
                func.json_contains(Meeting.user_ids, cast(user_id, JSON)),
            ]
            statement = select(Meeting).where(and_(*conditions)).order_by(desc(Meeting.create_time))
            offset = (page_num - 1) * page_size
            results = session.exec(statement.offset(offset).limit(page_size)).scalars().all()

            count_statement = select(func.count()).select_from(Meeting).where(and_(*conditions))
            total_count = session.scalar(count_statement) or 0

            return results, total_count
