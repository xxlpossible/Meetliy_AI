"""
知识库实体模型。

设计说明：
    Knowledge 是知识库的元信息（名称/描述/归属），KnowledgeFile 通过 knowledge_id 挂载到它。
    知识库有唯一的创建者（creater），被授权访问的用户存放在 accept_users（JSON 数组）中。
    创建者不在 accept_users 中存储（避免冗余），权限校验时需同时检查 creater 和 accept_users。
"""
from datetime import datetime
from enum import IntEnum
from typing import Optional, List

from sqlalchemy import Column, DateTime, JSON, text, Integer, desc, cast, select, and_, or_
from sqlalchemy.sql import func
from sqlmodel import Field, SQLModel

from database.base import session_getter


class KnowledgeDelete(IntEnum):
    NOT = 0
    YES = -1


class KnowledgeBase(SQLModel):
    name: Optional[str] = Field(default=None, description="知识库名称")
    description: Optional[str] = Field(default=None, description="知识库描述")
    # 创建者用户ID，创建者拥有最高权限（删除、管理授权）
    creater: Optional[int] = Field(default=None, sa_column=Column(Integer, nullable=True, comment="知识库创建者用户ID"))
    # 有权访问该知识库的用户ID列表（不含创建者），存为 JSON 数组
    accept_users: Optional[List[int]] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False, comment="有权访问的用户ID列表（不含创建者）")
    )
    is_delete: Optional[int] = Field(default=KnowledgeDelete.NOT.value, description="删除标识 0存在 -1删除")
    create_time: Optional[datetime] = Field(sa_column=Column(
        DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(
        sa_column=Column(DateTime,
                         nullable=False,
                         server_default=text('CURRENT_TIMESTAMP'),
                         onupdate=text('CURRENT_TIMESTAMP')))


class Knowledge(KnowledgeBase, table=True):
    # 主键为 uuid.uuid4().hex 生成的字符串，与 KnowledgeFile.knowledge_id 上下游一致
    id: Optional[str] = Field(default=None, primary_key=True, unique=True)


class KnowledgeDao:
    @classmethod
    def add(cls, knowledge: Knowledge) -> Knowledge:
        with session_getter() as session:
            session.add(knowledge)
            session.commit()
            session.refresh(knowledge)
            return knowledge

    @classmethod
    def update(cls, knowledge: Knowledge) -> Knowledge:
        with session_getter() as session:
            db_knowledge = session.merge(knowledge)
            session.commit()
            session.refresh(db_knowledge)
            return db_knowledge

    @classmethod
    def get_by_id(cls, k_id: str, user_id: int = None) -> Optional[Knowledge]:
        """
        按主键查询知识库。
        传入 user_id 时，仅当该用户是创建者在 accept_users 中才返回（越权防护）。
        """
        with session_getter() as session:
            statement = select(Knowledge).where(
                Knowledge.id == k_id,
                Knowledge.is_delete != KnowledgeDelete.YES.value,
            )
            if user_id is not None:
                statement = statement.where(
                    or_(
                        Knowledge.creater == user_id,
                        func.json_contains(Knowledge.accept_users, cast(user_id, JSON))
                    )
                )
            return session.exec(statement).scalars().first()

    @classmethod
    def get_by_id_raw(cls, k_id: str) -> Optional[Knowledge]:
        """按主主键查询知识库，不校验权限（内部使用）。"""
        with session_getter() as session:
            statement = select(Knowledge).where(
                Knowledge.id == k_id,
                Knowledge.is_delete != KnowledgeDelete.YES.value,
            )
            return session.exec(statement).scalars().first()

    @classmethod
    def list(cls, user_id: int, page_num: int = 1, page_size: int = 10, name: str = None):
        """分页查询当前用户有权访问的知识库列表（创建者或被授权者）。"""
        with session_getter() as session:
            conditions = [
                Knowledge.is_delete != KnowledgeDelete.YES.value,
                or_(
                    Knowledge.creater == user_id,
                    func.json_contains(Knowledge.accept_users, cast(user_id, JSON))
                ),
            ]
            if name:
                conditions.append(Knowledge.name.contains(name))

            statement = select(Knowledge).where(and_(*conditions)).order_by(desc(Knowledge.create_time))
            offset = (page_num - 1) * page_size
            results = session.exec(statement.offset(offset).limit(page_size)).scalars().all()

            count_statement = select(func.count()).select_from(Knowledge).where(and_(*conditions))
            total_count = session.scalar(count_statement) or 0

            return results, total_count

    @classmethod
    def delete(cls, k_id: str, user_id: int = None):
        """软删除知识库。传入 user_id 时校验权限（仅创建者可删除）。"""
        knowledge = cls.get_by_id(k_id=k_id, user_id=user_id)
        if not knowledge:
            raise ValueError(f"Knowledge with id '{k_id}' not found or no permission")
        knowledge.is_delete = KnowledgeDelete.YES.value
        cls.update(knowledge)

    @classmethod
    def update_accept_users(cls, k_id: str, accept_users: List[int], operator_id: int = None):
        """
        更新知识库的 accept_users 列表（仅创建者可操作）。
        operator_id 校验操作者是否为创建者。
        """
        knowledge = cls.get_by_id(k_id=k_id, user_id=operator_id)
        if not knowledge:
            raise ValueError(f"Knowledge with id '{k_id}' not found or no permission")
        if knowledge.creater != operator_id:
            raise ValueError("仅知识库创建者可修改授权用户")
        knowledge.accept_users = accept_users
        cls.update(knowledge)
