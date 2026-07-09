"""
统一鉴权依赖：通过 FastAPI 依赖注入对受保护接口进行 Access Token 校验。

用法：
    from fastapi import Depends
    from utils.dependencies import get_current_user
    from database.models.user import User

    @router.get("/profile")
    async def profile(current_user: User = Depends(get_current_user)):
        return {"username": current_user.username}

未携带 Token、Token 无效或过期，统一返回 401。
"""
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from database.models.user import User, UserDao
from utils.security import TOKEN_TYPE_ACCESS, decode_token

# auto_error=False：不自动抛 403，由我们手动统一返回 401，语义更准确
bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> User:
    """
    解析 Authorization: Bearer <token> 头并校验 Access Token。

    校验失败统一抛 401，并携带 WWW-Authenticate: Bearer 头。
    成功返回当前登录用户对象。
    """
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未提供认证凭据，请先登录",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 解码并校验签名 / 过期 / 类型，失败时 decode_token 内部抛 401
    payload = decode_token(credentials.credentials, expected_type=TOKEN_TYPE_ACCESS)

    user_id = payload.get("user_id")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token 缺少用户信息",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = UserDao.get_by_id(user_id)
    if user is None:
        # Token 有效但用户已被删除
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在或已被删除",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user
