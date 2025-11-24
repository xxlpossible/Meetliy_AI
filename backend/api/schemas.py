from typing import Union, Any, Generic, TypeVar

from pydantic import BaseModel

# 创建泛型变量
DataT = TypeVar('DataT')


class UnifiedResponseModel(BaseModel, Generic[DataT]):
    """统一响应模型"""
    status_code: int
    status_message: str
    data: DataT = None


def resp_200(data: Union[list, dict, str, Any] = None,
             message: str = 'SUCCESS') -> UnifiedResponseModel:
    """成功的代码"""
    return UnifiedResponseModel(status_code=200, status_message=message, data=data)


# 新增：登录成功返回的结构
class TokenData(BaseModel):
    token: str
    token_type: str = "bearer"
