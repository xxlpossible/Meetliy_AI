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

from sqlalchemy import JSON, Column, DateTime, and_, cast, desc, text
from sqlalchemy.sql import func
from sqlmodel import Field, SQLModel, select

from core.database.session import session_getter


class MeetingStatus(IntEnum):
    ACTIVE = 0              # 会议正在进行中
    END_AND_ANALYZE = 1     # 会议结束，会议内容正在后台解析中
    FINISH = 2              # 内容解析完成
    ERROR = -1              # 会议解析异常


class MeetingDelete(IntEnum):
    NOT = 0                 # 未删除
    DELETED = -1            # 已软删除


class MeetingBase(SQLModel):
    meeting_name: str | None = Field(default=None, description="会议名称")
    host_user_id: int = Field(nullable=False, index=True, description="会议发起人(主持人)ID")
    # 参会者ID列表，存为 JSON 数组，查询时用 JSON_CONTAINS 过滤
    user_ids: list[int] | None = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False, comment="参会者用户ID列表")
    )
    status: int | None = Field(default=MeetingStatus.ACTIVE.value, description="会议状态 0进行中 1结束解析中 2解析完成 -1异常")
    # 会议结束后关联的 Transcription.id，承载会后转录+纪要结果
    task_id: str | None = Field(default=None, description="结束后关联的转录任务ID")
    # 会议结束后是否需要生成纪要（默认True，False则跳过转录任务）
    need_summary: bool | None = Field(default=True, description="会议结束后是否需要生成纪要")
    is_delete: int | None = Field(default=MeetingDelete.NOT.value, description="是否被软删除 0正常 -1已删除")
    create_time: datetime | None = Field(sa_column=Column(
        DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP')))
    update_time: datetime | None = Field(
        sa_column=Column(DateTime,
                         nullable=False,
                         server_default=text('CURRENT_TIMESTAMP'),
                         onupdate=text('CURRENT_TIMESTAMP')))


class Meeting(MeetingBase, table=True):
    id: str | None = Field(default=None, primary_key=True, unique=True)


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
    def get_by_id(cls, m_id: str, user_id: int | None = None) -> Meeting | None:
        """
        按主键查询会议。
        传入 user_id 时，仅当该用户在 user_ids 中才返回记录（越权防护）。
        已软删除的记录不返回。
        """
        with session_getter() as session:
            statement = select(Meeting).where(
                Meeting.id == m_id,
                Meeting.is_delete == MeetingDelete.NOT.value
            )
            if user_id is not None:
                statement = statement.where(
                    func.json_contains(Meeting.user_ids, cast(user_id, JSON))
                )
            return session.exec(statement).first()

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
    def update_need_summary(cls, m_id: str, need_summary: bool):
        """更新会议是否需要生成纪要。"""
        with session_getter() as session:
            meeting = session.get(Meeting, m_id)
            if meeting:
                meeting.need_summary = need_summary
                session.commit()

    @classmethod
    def get_by_task_id(cls, task_id: str) -> Meeting | None:
        """按 task_id 查询会议（供转录任务回调更新状态使用）。"""
        with session_getter() as session:
            statement = select(Meeting).where(Meeting.task_id == task_id)
            return session.exec(statement).first()

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
    def soft_delete(cls, m_id: str, user_id: int | None = None) -> bool:
        """
        软删除会议：将 is_delete 设为 -1。
        传入 user_id 时校验权限（仅 host_user_id 可删除）。
        返回是否成功。
        """
        with session_getter() as session:
            meeting = session.get(Meeting, m_id)
            if not meeting or meeting.is_delete == MeetingDelete.DELETED.value:
                return False
            if user_id is not None and meeting.host_user_id != user_id:
                return False
            meeting.is_delete = MeetingDelete.DELETED.value
            session.commit()
            return True

    @classmethod
    def list(cls, user_id: int, page_num: int = 1, page_size: int = 10,
             meeting_name: str | None = None, status: int | None = None):
        """分页查询当前用户参加的会议列表（过滤已软删除的记录）。"""
        with session_getter() as session:
            conditions = [
                func.json_contains(Meeting.user_ids, cast(user_id, JSON)),
                Meeting.is_delete == MeetingDelete.NOT.value,
            ]
            if meeting_name is not None:
                conditions.append(Meeting.meeting_name.contains(meeting_name))
            if status is not None:
                conditions.append(Meeting.status == status)
            statement = select(Meeting).where(and_(*conditions)).order_by(desc(Meeting.create_time))
            offset = (page_num - 1) * page_size
            results = session.exec(statement.offset(offset).limit(page_size)).all()

            count_statement = select(func.count()).select_from(Meeting).where(and_(*conditions))
            total_count = session.scalar(count_statement) or 0

            return results, total_count

    @classmethod
    def count_status_distribution(cls, user_id: int | None = None) -> dict:
        """
        统计未删除会议按状态的分布，返回 {status(int): count(int)}。
        供 DashBoard 数字仪表盘展示各状态会议数量。
        传入 user_id 时仅统计该用户可见（参与或被主持）的会议，与列表接口保持一致。
        """
        with session_getter() as session:
            conditions = [Meeting.is_delete == MeetingDelete.NOT.value]
            if user_id:
                conditions.append(func.json_contains(Meeting.user_ids, cast(user_id, JSON)))
            statement = (
                select(Meeting.status, func.count())
                .where(and_(*conditions))
                .group_by(Meeting.status)
            )
            rows = session.exec(statement).all()
            return {int(status): count for status, count in rows}
