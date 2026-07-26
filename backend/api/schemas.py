from typing import Any, Generic, TypeVar

from pydantic import BaseModel

# 创建泛型变量
DataT = TypeVar('DataT')


class UnifiedResponseModel(BaseModel, Generic[DataT]):
    """统一响应模型"""
    status_code: int
    status_message: str
    data: DataT = None


def resp_200(data: list | dict | str | Any = None,
             message: str = 'SUCCESS') -> UnifiedResponseModel:
    """成功的代码"""
    return UnifiedResponseModel(status_code=200, status_message=message, data=data)


# 登录/刷新成功返回的 Token 结构（access + refresh 双 Token）
class TokenData(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = 1800  # access token 有效期（秒），默认 30 分钟
