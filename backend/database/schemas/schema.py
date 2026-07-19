from typing import Optional, List

import re
from pydantic import field_validator
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
    username: Optional[str] = Field(default=None, description="用户名")
    password: Optional[str] = Field(default=None, description="密码")

    @field_validator("username", "password")
    @classmethod
    def not_blank(cls, v):
        if v is None or not str(v).strip():
            raise ValueError("用户名和密码不能为空")
        return v


class UserRegister(SQLModel):
    username: Optional[str] = Field(default=None, description="用户名")
    password: Optional[str] = Field(default=None, description="密码")
    confirmPassword: Optional[str] = Field(default=None, description="确认密码")

    @field_validator("username")
    @classmethod
    def validate_username(cls, v):
        if v is None or not str(v).strip():
            raise ValueError("用户名不能为空")
        v = str(v).strip()
        # 3-20 位，字母/数字/下划线，必须以字母开头
        if not re.match(r"^[a-zA-Z][a-zA-Z0-9_]{2,19}$", v):
            raise ValueError("用户名需 3-20 位，以字母开头，仅含字母、数字、下划线")
        return v

    @field_validator("password")
    @classmethod
    def validate_password(cls, v):
        if v is None or not str(v).strip():
            raise ValueError("密码不能为空")
        v = str(v)
        # 6-20 位，必须同时包含字母和数字
        if len(v) < 6 or len(v) > 20:
            raise ValueError("密码长度需为 6-20 位")
        if not re.search(r"[A-Za-z]", v) or not re.search(r"\d", v):
            raise ValueError("密码必须同时包含字母和数字")
        return v

    @field_validator("confirmPassword")
    @classmethod
    def confirm_not_blank(cls, v):
        if v is None or not str(v).strip():
            raise ValueError("确认密码不能为空")
        return v


class RefreshTokenRequest(SQLModel):
    """Token 刷新请求体"""
    refresh_token: str = Field(description="登录时签发的 Refresh Token")


# ----------------------------- 知识库（Knowledge）请求体 ----------------------------- #

class KnowledgeCreate(SQLModel):
    """创建知识库请求体"""
    name: str = Field(min_length=1, max_length=128, description="知识库名称")
    description: Optional[str] = Field(default=None, max_length=500, description="知识库描述")


class KnowledgeUpdate(SQLModel):
    """更新知识库请求体"""
    knowledge_id: str = Field(..., description="知识库ID")
    name: Optional[str] = Field(default=None, min_length=1, max_length=128, description="知识库名称")
    description: Optional[str] = Field(default=None, max_length=500, description="知识库描述")


class KnowledgeQuery(SQLModel):
    """知识库列表查询请求体"""
    page_num: int = Field(default=1, ge=1, description="页码")
    page_size: int = Field(default=10, ge=1, le=100, description="每页数量")
    name: Optional[str] = Field(default=None, description="按名称模糊搜索（可选）")


class KnowledgeGrant(SQLModel):
    """知识库放权请求体：给指定用户追加访问权限"""
    knowledge_id: str = Field(..., description="知识库ID")
    user_id: int = Field(..., description="要授予权限的用户ID")


class KnowledgeDelete(SQLModel):
    """知识库删除请求体"""
    knowledge_id: str = Field(..., description="要删除的知识库ID")



