from typing import Optional, List, Tuple

from sqlalchemy import select
from sqlalchemy.sql import func
from sqlmodel import SQLModel, Field

from database.base import session_getter
from utils.security import hash_password, verify_password


class UserBase(SQLModel):
    username: Optional[str] = Field(default=None)
    phone_number: Optional[str] = Field(default=None)
    hashed_password: str = Field(nullable=False)  # 加密后的密码


class User(UserBase, table=True):
    id: Optional[int] = Field(primary_key=True, nullable=False, index=True)


class UserDao:
    @classmethod
    def get_by_username(cls, username: str) -> Optional[User]:
        with session_getter() as session:
            statement = select(User).where(User.username == username)
            return session.scalars(statement).first()

    @classmethod
    def get_by_id(cls, user_id: int) -> Optional[User]:
        with session_getter() as session:
            return session.get(User, user_id)

    @classmethod
    def get_user_list(
        cls,
        page_num: int = 1,
        page_size: int = 10,
        username: Optional[str] = None,
    ) -> Tuple[List[User], int]:
        """
        分页获取用户列表。
        
        Args:
            page_num: 页码（从1开始）
            page_size: 每页数量
            username: 按用户名模糊搜索（可选）
            
        Returns:
            (用户列表, 总用户数)
        """
        with session_getter() as session:
            conditions = []
            if username:
                conditions.append(User.username.contains(username))

            total_count = session.scalar(
                select(func.count()).select_from(User)
            ) or 0

            if total_count == 0:
                return [], 0

            offset = (page_num - 1) * page_size
            statement = select(User).offset(offset).limit(page_size)
            if conditions:
                statement = statement.where(*conditions)
            res = session.scalars(statement).all()

            return res, total_count

    @classmethod
    def add(cls, username: str, password: str, phone_number: Optional[str] = None) -> User:
        hashed = hash_password(password)
        user = User(username=username, hashed_password=hashed, phone_number=phone_number)
        with session_getter() as session:
            session.add(user)
            session.commit()
            session.refresh(user)
        return user
