from typing import Optional

from sqlalchemy import select
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
    def get_by_username(cls, username: str) -> User:
        with session_getter() as session:
            statement = select(User).where(User.username == username)
            return session.scalars(statement).first()

    @classmethod
    def add(cls, username: str, password: str, phone_number: Optional[str] = None) -> User:
        hashed = hash_password(password)
        user = User(username=username, hashed_password=hashed, phone_number=phone_number)
        with session_getter() as session:
            session.add(user)
            session.commit()
            session.refresh(user)
        return user
