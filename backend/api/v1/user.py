
from fastapi import APIRouter, Depends, Query

from api.schemas import resp_200
from database.models.user import User, UserDao
from utils.dependencies import get_current_user

router = APIRouter(prefix='/user', tags=['user'])


@router.get('/list', summary="获取用户列表")
async def get_user_list(
    page_num: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=10, ge=1, le=100, description="每页数量"),
    username: str | None = Query(default=None, description="按用户名模糊搜索"),
    current_user: User = Depends(get_current_user)
):
    """
    分页获取所有用户的 id 和用户名。
    
    支持按用户名模糊搜索。
    """
    users, total = UserDao.get_user_list(
        page_num=page_num,
        page_size=page_size,
        username=username,
    )

    # 只返回 id 和 username，避免泄露敏感信息（如 phone_number）
    items = [{"id": u.id, "username": u.username} for u in users]

    return resp_200(data={
        "items": items,
        "total": total,
    })