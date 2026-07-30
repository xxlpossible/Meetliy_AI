from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, Text, and_, text
from sqlalchemy.sql import func
from sqlmodel import Field, SQLModel, select

from core.database.session import session_getter


class ChatMessageBase(SQLModel):
    """聊天记录基础模型 - 每条记录对应一条用户输入或助手输出"""
    session_id: str | None = Field(default=None, index=True)
    role: str | None = Field(default=None, description="消息角色: user / assistant")
    content: str | None = Field(default=None, sa_column=Column(Text))
    turn_index: int | None = Field(default=0, description="会话内轮次序号，从 0 开始自增")
    user_id: int | None = Field(default=None)
    create_time: datetime | None = Field(sa_column=Column(
        DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP')))
    update_time: datetime | None = Field(
        sa_column=Column(DateTime,
                         nullable=False,
                         server_default=text('CURRENT_TIMESTAMP'),
                         onupdate=text('CURRENT_TIMESTAMP')))


class ChatMessage(ChatMessageBase, table=True):
    """聊天记录表 - 每条数据对应一个输入或输出"""
    chat_id: int | None = Field(
        default=None,
        sa_column=Column(Integer, primary_key=True, autoincrement=True)
    )


class ChatMessageDao:
    @classmethod
    def get_session_messages(
        cls,
        session_id: str,
        user_id: int,
        page_num: int = 1,
        page_size: int = 50,
    ) -> tuple[list[ChatMessage], int]:
        """
        获取指定会话下、指定用户的所有聊天记录。
        
        过滤：session_id + user_id（越权防护）
        排序：turn_index 升序（对话时间线），前端可直接渲染
        """
        with session_getter() as session:
            conditions = [
                ChatMessage.session_id == session_id,
                ChatMessage.user_id == user_id,
            ]

            total_count = session.scalar(
                select(func.count()).select_from(ChatMessage).where(and_(*conditions))
            ) or 0

            if total_count == 0:
                return [], 0

            offset = (page_num - 1) * page_size

            res = session.scalars(
                select(ChatMessage)
                .where(and_(*conditions))
                .order_by(ChatMessage.turn_index.asc())
                .offset(offset)
                .limit(page_size)
            ).all()

            return res, total_count

    @classmethod
    def get_max_turn_index(cls, session_id: str) -> int | None:
        """获取会话内最大 turn_index，用于重启后恢复计数器"""
        with session_getter() as session:
            return session.scalar(
                select(func.max(ChatMessage.turn_index))
                .where(ChatMessage.session_id == session_id)
            )

    @classmethod
    def get_recent_turns(cls, session_id: str, turns: int = 3) -> list[ChatMessage]:
        """
        获取指定会话最近 N 轮的聊天记录（每轮 = 1 条 user + 1 条 assistant = 2 条消息）。
        用于 context_builder 的 SESSION_HISTORY 初始化。
        """
        with session_getter() as session:
            # 先获取最近 2*turns 条消息
            query = (
                select(ChatMessage)
                .where(ChatMessage.session_id == session_id)
                .order_by(ChatMessage.turn_index.desc())
                .limit(turns * 2)
            )
            rows = list(session.scalars(query).all())
            # 按 turn_index 升序返回
            rows.sort(key=lambda r: r.turn_index or 0)
            return rows

    @classmethod
    def add(cls, chat_message: ChatMessage) -> ChatMessage:
        with session_getter() as session:
            session.add(chat_message)
            session.commit()
            session.refresh(chat_message)
            return chat_message

    @classmethod
    def update(cls, chat_message: ChatMessage) -> ChatMessage:
        with session_getter() as session:
            db_message = session.merge(chat_message)
            session.commit()
            session.refresh(db_message)
            return db_message

    @classmethod
    def get_chat_by_chat_id(cls, chat_id: int | None = None, user_id: int | None = None) -> ChatMessage | None:
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
    def delete(cls, chat_id: int, user_id: int | None = None) -> bool:
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

    @classmethod
    def delete_by_session_id(cls, session_id: str, user_id: int | None = None) -> bool:
        """
        按 session_id 删除整个会话的聊天记录。
        传入 user_id 时校验归属权限。
        """
        with session_getter() as session:
            conditions = [ChatMessage.session_id == session_id]
            if user_id is not None:
                conditions.append(ChatMessage.user_id == user_id)
            statement = select(ChatMessage).where(*conditions)
            chats = session.scalars(statement).all()
            if not chats:
                return False
            for chat in chats:
                session.delete(chat)
            session.commit()
            return True
