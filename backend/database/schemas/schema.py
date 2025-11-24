from typing import Optional, List

from sqlmodel import Field, SQLModel


class TranscriptionQueryVo(SQLModel):
    task_name: Optional[str] = Field(default=None)
    page_num: int = Field(default=1, description='页数')
    page_size: int = Field(default=10, description='页大小')


class UserQA(SQLModel):
    task_id: Optional[str] = Field(default=None)
    question: Optional[str] = Field(default=None)
    history: Optional[List[str]] = Field(default=None)


class UserTempQA(SQLModel):
    text: Optional[str] = Field(default=None)
    question: Optional[str] = Field(default=None)
    history: Optional[List[str]] = Field(default=None)


class ChatMessageQuery(SQLModel):
    task_id: Optional[str] = Field(default=None)
    page_size: Optional[int] = Field(default=10)
    page_num: Optional[int] = Field(default=1)


class ChatMessageAdd(SQLModel):
    task_id: Optional[str]
    chat_messages: Optional[List[str]]
    user_id: Optional[int] = Field(default=None)


class ChatMessageUpdate(SQLModel):
    chat_messages: Optional[List[str]]
    chat_id: Optional[str]


class TransUpdate(SQLModel):
    task_name: Optional[str] = None
    task_id: Optional[str] = None
    note: Optional[str] = None


# 登录注册时接收的字段
class UserLogin(SQLModel):
    username: Optional[str]
    password: Optional[str]


class UserRegister(SQLModel):
    username: Optional[str] = None
    password: Optional[str] = None
    confirmPassword: Optional[str]


