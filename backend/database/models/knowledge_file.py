from datetime import datetime
from enum import IntEnum
from typing import Optional, Dict, Any, List

from sqlalchemy import Column, DateTime, String, text, Text, JSON, desc
from sqlmodel import Field, SQLModel, select

from database.base import session_getter
from sqlalchemy import select, and_
from sqlalchemy.sql import func


class KnowledgeType(IntEnum):
    """知识类型：0文本 1语音 2图片"""
    TEXT = 0
    AUDIO = 1
    IMAGE = 2


class FileState(IntEnum):
    """文件解析状态：0解析中 1解析成功 2解析失败"""
    PROCESSING = 0
    SUCCESS = 1
    FAILED = 2


class KnowledgeFileBase(SQLModel):
    file_name: Optional[str] = Field(default=None, description="文件名")
    knowledge_id: Optional[str] = Field(default=None, description="知识库ID")
    chunks_counts: Optional[int] = Field(default=0, description="文档片段数量")
    type: Optional[int] = Field(default=KnowledgeType.TEXT.value, description="知识类型 0文本 1语音 2图片")
    # 文件解析状态：0解析中 1解析成功 2解析失败，默认0。
    # upload 接口创建记录时置为0，Celery 后台任务解析完成后更新为1/2。
    state: Optional[int] = Field(default=FileState.PROCESSING.value, description="解析状态 0解析中 1成功 2失败")
    # 解析失败原因，供前端展示；成功时为 None。
    fail_reason: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True, comment="解析失败原因"))
    user_id: Optional[int] = Field(default=0)
    del_flag: Optional[int] = Field(default=0, description="删除标识 0默认 -1被删除")
    create_time: Optional[datetime] = Field(sa_column=Column(
        DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(
        sa_column=Column(DateTime,
                         nullable=False,
                         server_default=text('CURRENT_TIMESTAMP'),
                         onupdate=text('CURRENT_TIMESTAMP')))


class KnowledgeFile(KnowledgeFileBase, table=True):
    # 主键为 uuid.uuid4().hex 生成的字符串，与 knowledge_id / file_id 上下游一致
    # 注意：声明为 str 而非 int，避免 Pydantic 序列化时类型不匹配告警
    id: Optional[str] = Field(default=None, primary_key=True, unique=True)


class KnowledgeFileDao:
    @classmethod
    def get_list_by_knowledge_id(cls, knowledge_id: str, page_size: int, page_num: int):
        with session_getter() as session:
            query = select(KnowledgeFile).where(
                KnowledgeFile.knowledge_id == knowledge_id
            ).where(KnowledgeFile.del_flag == 0)
            count = select(func.count()).select_from(KnowledgeFile).where(
                KnowledgeFile.knowledge_id == knowledge_id
            ).where(KnowledgeFile.del_flag == 0)

            total_count = session.scalar(count) or 0

            if total_count == 0:
                return [], 0

            offset = (page_num - 1) * page_size

            res = session.scalars(query.offset(offset).limit(page_size)).all()

            return res, total_count

    @classmethod
    def add(cls, knowledge_file: KnowledgeFile):
        with session_getter() as session:
            session.add(knowledge_file)
            session.commit()
            session.refresh(knowledge_file)
            return knowledge_file

    @classmethod
    def update(cls, knowledge_file: KnowledgeFile):
        with session_getter() as session:
            db_knowledge_file = session.merge(knowledge_file)
            session.commit()
            session.refresh(db_knowledge_file)
            return db_knowledge_file

    @classmethod
    def update_state(cls, file_id: str, state: int,
                     fail_reason: Optional[str] = None,
                     chunks_counts: Optional[int] = None) -> Optional[KnowledgeFile]:
        """
        更新文件解析状态（供 Celery 后台任务调用）。

        :param file_id: 文件ID
        :param state: FileState 枚举值（0/1/2）
        :param fail_reason: 失败原因（state=2 时填写）
        :param chunks_counts: 解析成功的分块数（state=1 时填写）
        :return: 更新后的记录，文件不存在或已软删则返回 None
        """
        with session_getter() as session:
            statement = select(KnowledgeFile).where(
                KnowledgeFile.id == file_id,
                KnowledgeFile.del_flag == 0,
            )
            knowledge_file = session.scalars(statement).first()
            if knowledge_file is None:
                return None
            knowledge_file.state = state
            if fail_reason is not None:
                knowledge_file.fail_reason = fail_reason
            if chunks_counts is not None:
                knowledge_file.chunks_counts = chunks_counts
            session.add(knowledge_file)
            session.commit()
            session.refresh(knowledge_file)
            return knowledge_file

    @classmethod
    def get_by_id(cls, file_id: str) -> KnowledgeFile:
        with session_getter() as session:
            statement = select(KnowledgeFile).where(KnowledgeFile.id == file_id)
            return session.scalars(statement).first()
