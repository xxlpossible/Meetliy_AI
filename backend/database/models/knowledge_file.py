from datetime import datetime
from enum import IntEnum

from sqlalchemy import Column, DateTime, Text, text
from sqlalchemy.sql import func
from sqlmodel import Field, SQLModel, select

from database.base import session_getter


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
    file_name: str | None = Field(default=None, description="文件名")
    knowledge_id: str | None = Field(default=None, description="知识库ID")
    chunks_counts: int | None = Field(default=0, description="文档片段数量")
    type: int | None = Field(default=KnowledgeType.TEXT.value, description="知识类型 0文本 1语音 2图片")
    # 文件解析状态：0解析中 1解析成功 2解析失败，默认0。
    # upload 接口创建记录时置为0，Celery 后台任务解析完成后更新为1/2。
    state: int | None = Field(default=FileState.PROCESSING.value, description="解析状态 0解析中 1成功 2失败")
    # 解析失败原因，供前端展示；成功时为 None。
    fail_reason: str | None = Field(default=None, sa_column=Column(Text, nullable=True, comment="解析失败原因"))
    user_id: int | None = Field(default=0)
    del_flag: int | None = Field(default=0, description="删除标识 0默认 -1被删除")
    create_time: datetime | None = Field(sa_column=Column(
        DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP')))
    update_time: datetime | None = Field(
        sa_column=Column(DateTime,
                         nullable=False,
                         server_default=text('CURRENT_TIMESTAMP'),
                         onupdate=text('CURRENT_TIMESTAMP')))


class KnowledgeFile(KnowledgeFileBase, table=True):
    # 主键为 uuid.uuid4().hex 生成的字符串，与 knowledge_id / file_id 上下游一致
    # 注意：声明为 str 而非 int，避免 Pydantic 序列化时类型不匹配告警
    id: str | None = Field(default=None, primary_key=True, unique=True)


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
                     fail_reason: str | None = None,
                     chunks_counts: int | None = None) -> KnowledgeFile | None:
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

    @classmethod
    def delete_all_by_knowledge_id(cls, knowledge_id: str) -> int:
        """软删除指定知识库下的所有文件。返回实际被删除的文件数量。"""
        with session_getter() as session:
            statement = select(KnowledgeFile).where(
                KnowledgeFile.knowledge_id == knowledge_id,
                KnowledgeFile.del_flag == 0,
            )
            files = session.exec(statement).all()
            count = 0
            for f in files:
                f.del_flag = -1
                session.add(f)
                count += 1
            if count > 0:
                session.commit()
            return count
