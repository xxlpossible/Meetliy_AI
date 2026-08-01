"""API 请求/响应 Schema（从 database/schemas/schema.py 提取，不含 TranscriptionQueryVo）。"""

import re

from pydantic import field_validator
from sqlmodel import Field, SQLModel


class UserQA(SQLModel):
    task_id: str | None = Field(default=None)
    question: str | None = Field(default=None)
    history: list[str] | None = Field(default=None)


class UserTempQA(SQLModel):
    text: str | None = Field(default=None)
    question: str | None = Field(default=None)
    history: list[str] | None = Field(default=None)


class ChatMessageQuery(SQLModel):
    """聊天记录列表查询请求体"""
    session_id: str | None = Field(default=None, description="会话ID")
    page_size: int | None = Field(default=10, description="每页数量")
    page_num: int | None = Field(default=1, description="页码")


class ChatMessageAdd(SQLModel):
    """添加聊天记录请求体 - 单条消息"""
    session_id: str | None = Field(default=None, description="会话ID")
    role: str | None = Field(default=None, description="消息角色: user / assistant")
    content: str | None = Field(default=None, description="消息内容")
    turn_index: int | None = Field(default=0, description="会话内轮次序号")
    user_id: int | None = Field(default=None)


class ChatSSERequest(SQLModel):
    """SSE 流式聊天请求体"""
    question: str = Field(..., description="用户问题")
    session_id: str = Field(..., description="会话ID")
    meeting_ids: list[str] | None = Field(default=None, description="会议ID列表")
    need_kb: bool | None = Field(default=False, description="是否查询知识库")
    knowledge_ids: list[str] | None = Field(default=None, description="知识库ID列表")


class ChatMessageUpdate(SQLModel):
    """更新聊天记录请求体"""
    content: str | None = Field(default=None, description="消息内容")
    chat_id: int | None = Field(default=None, description="聊天记录ID")


class TransUpdate(SQLModel):
    task_name: str | None = None
    task_id: str | None = None
    note: str | None = None


class UserLogin(SQLModel):
    username: str | None = Field(default=None, description="用户名")
    password: str | None = Field(default=None, description="密码")

    @field_validator("username", "password")
    @classmethod
    def not_blank(cls, v):
        if v is None or not str(v).strip():
            raise ValueError("用户名和密码不能为空")
        return v


class UserRegister(SQLModel):
    username: str | None = Field(default=None, description="用户名")
    password: str | None = Field(default=None, description="密码")
    confirmPassword: str | None = Field(default=None, description="确认密码")

    @field_validator("username")
    @classmethod
    def validate_username(cls, v):
        if v is None or not str(v).strip():
            raise ValueError("用户名不能为空")
        v = str(v).strip()
        if not re.match(r"^[a-zA-Z][a-zA-Z0-9_]{2,19}$", v):
            raise ValueError("用户名需 3-20 位，以字母开头，仅含字母、数字、下划线")
        return v

    @field_validator("password")
    @classmethod
    def validate_password(cls, v):
        if v is None or not str(v).strip():
            raise ValueError("密码不能为空")
        v = str(v)
        if len(v) < 8 or len(v) > 20:
            raise ValueError("密码长度需为 8-20 位")
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


class UserProfileUpdate(SQLModel):
    """更新用户资料请求体（用户名）"""
    username: str | None = Field(default=None, description="新用户名")

    @field_validator("username")
    @classmethod
    def validate_username(cls, v):
        if v is None:
            return v
        v = str(v).strip()
        if not v:
            raise ValueError("用户名不能为空")
        if not re.match(r"^[a-zA-Z][a-zA-Z0-9_]{2,19}$", v):
            raise ValueError("用户名需 3-20 位，以字母开头，仅含字母、数字、下划线")
        return v


class PasswordChange(SQLModel):
    """修改密码请求体"""
    old_password: str | None = Field(default=None, description="原密码")
    new_password: str | None = Field(default=None, description="新密码")
    confirm_password: str | None = Field(default=None, description="确认新密码")

    @field_validator("old_password")
    @classmethod
    def old_not_blank(cls, v):
        if v is None or not str(v).strip():
            raise ValueError("原密码不能为空")
        return v

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, v):
        if v is None or not str(v).strip():
            raise ValueError("新密码不能为空")
        v = str(v)
        if len(v) < 8 or len(v) > 20:
            raise ValueError("新密码长度需为 8-20 位")
        if not re.search(r"[A-Za-z]", v) or not re.search(r"\d", v):
            raise ValueError("新密码必须同时包含字母和数字")
        return v

    @field_validator("confirm_password")
    @classmethod
    def confirm_not_blank(cls, v):
        if v is None or not str(v).strip():
            raise ValueError("确认新密码不能为空")
        return v


class KnowledgeCreate(SQLModel):
    """创建知识库请求体"""
    name: str = Field(min_length=1, max_length=128, description="知识库名称")
    description: str | None = Field(default=None, max_length=500, description="知识库描述")
    accept_users: list[int] | None = Field(default=None, description="有权限访问该知识库的用户ID列表，默认只有创建者有权限")


class KnowledgeUpdate(SQLModel):
    """更新知识库请求体"""
    knowledge_id: str = Field(..., description="知识库ID")
    name: str | None = Field(default=None, min_length=1, max_length=128, description="知识库名称")
    description: str | None = Field(default=None, max_length=500, description="知识库描述")
    accept_users: list[int] | None = Field(default=None, description="有权限访问该知识库的用户ID列表（全量替换，创建者不存入）")


class KnowledgeQuery(SQLModel):
    """知识库列表查询请求体"""
    page_num: int = Field(default=1, ge=1, description="页码")
    page_size: int = Field(default=10, ge=1, le=100, description="每页数量")
    name: str | None = Field(default=None, description="按名称模糊搜索（可选）")


class KnowledgeDelete(SQLModel):
    """知识库删除请求体"""
    knowledge_id: str = Field(..., description="要删除的知识库ID")
