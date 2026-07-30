from datetime import datetime
from enum import IntEnum
from typing import Any

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    String,
    and_,
    cast,
    desc,
    text,
)
from sqlalchemy.sql import func
from sqlmodel import Field, SQLModel, select

from core.database.session import session_getter


class TranscriptionQueryVo(SQLModel):
    task_name: str | None = Field(default=None)
    page_num: int = Field(default=1, description='页数')
    page_size: int = Field(default=10, description='页大小')


class Status(IntEnum):
    PENDING = 0  # 正在解析
    COMPLETE = 1  # 解析完成
    ERROR = -1  # 解析错误


class Delete(IntEnum):
    NOT = 0
    YES = -1


class TranscriptionBase(SQLModel):
    task_name: str | None = Field(default=None)
    # 有权访问该会议转录结果的用户ID列表（会议可多人参与，后续可放权）
    # 存为 JSON 数组，查询时用 JSON_CONTAINS 在 SQL 层过滤，保证分页正确
    user_ids: list[int] | None = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False, comment="有权访问的用户ID列表")
    )
    status: int | None = Field(default=Status.PENDING.value)
    task_result: dict[str, Any] | None = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False)
    )
    is_delete: int | None = Field(default=Delete.NOT.value)
    realtime_asr_text: list[str] | None = Field(
        default=None,
        sa_column=Column(JSON, nullable=True, comment="实时转录文本行列表")
    )
    note: str | None = Field(default=None)
    # 会议合并后音频文件的 OSS 公网下载地址（mp3 已上传至 OSS，本地不保留）
    file_url: str | None = Field(
        default=None,
        sa_column=Column(String(1024), nullable=True, comment="OSS合并音频公网URL")
    )
    create_time: datetime | None = Field(sa_column=Column(
        DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP')))
    update_time: datetime | None = Field(
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
    def delete(cls, task_id: str, user_id: int | None = None):
        """删除转录记录。传入 user_id 时校验该用户是否有权操作。"""
        transcription = cls.get_by_id(t_id=task_id, user_id=user_id)
        if not transcription:
            raise ValueError(f"Transcription with task_id '{task_id}' not found or no permission")

        with session_getter() as session:
            session.delete(transcription)
            session.commit()

    @classmethod
    def get_by_id(cls, t_id: str, user_id: int | None = None) -> Transcription | None:
        """
        按主键查询转录记录。
        传入 user_id 时，仅当该用户在 user_ids 中才返回记录（越权防护）；
        不传 user_id 则不做权限校验（仅内部/管理用途）。
        """
        with session_getter() as session:
            statement = select(Transcription).where(Transcription.id == t_id)
            if user_id is not None:
                statement = statement.where(
                    func.json_contains(Transcription.user_ids, cast(user_id, JSON))
                )
            return session.exec(statement).first()

    @classmethod
    def list(cls, body: TranscriptionQueryVo, user_id: int | None = None):
        """
        分页查询转录列表。
        传入 user_id 时，仅返回该用户有权访问（user_ids 包含该用户）的记录。
        """
        with session_getter() as session:
            # 构建基础查询
            statement = select(Transcription)

            # 添加条件查询
            conditions = [Transcription.is_delete != Delete.YES.value]
            if body.task_name:
                conditions.append(Transcription.task_name.contains(body.task_name))
            if user_id is not None:
                conditions.append(
                    func.json_contains(Transcription.user_ids, cast(user_id, JSON))
                )

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
            results = session.exec(statement).all()

            # 查询总记录数（用于分页信息）
            count_statement = select(func.count(Transcription.id))
            if conditions:
                count_statement = count_statement.where(and_(*conditions))
            total_count = session.exec(count_statement).one()

            return results, total_count

    @classmethod
    def soft_delete_by_task_id(cls, task_id: str) -> bool:
        """按 task_id 软删除转录记录（会议删除时联动）。"""
        with session_getter() as session:
            transcription = session.get(Transcription, task_id)
            if not transcription:
                return False
            transcription.is_delete = Delete.YES.value
            session.commit()
            return True

