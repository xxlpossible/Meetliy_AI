from datetime import datetime
from enum import IntEnum
from typing import Optional, Dict, Any, List

from sqlalchemy import Column, DateTime, String, text, Text, JSON, desc
from sqlmodel import Field, SQLModel, select

from database.base import session_getter
from sqlalchemy import select, and_
from sqlalchemy.sql import func


class KnowledgeFileBase(SQLModel):
    file_name: Optional[str] = Field(default=None, description="文件名")
    knowledge_id: Optional[str] = Field(default=None, description="知识库ID")
    chunks_counts: Optional[int] = Field(default=0, description="文档片段数量")
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
    id: Optional[int] = Field(default=None, primary_key=True, unique=True)


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
    def get_by_id(cls, file_id: str) -> KnowledgeFile:
        with session_getter() as session:
            statement = select(KnowledgeFile).where(KnowledgeFile.id == file_id)
            return session.scalars(statement).first()
