from fastapi import APIRouter, HTTPException

from database.models.user import UserDao
from database.schemas.schema import UserRegister, UserLogin
from utils.security import verify_password, create_access_token
from api.schemas import resp_200, TokenData

router = APIRouter(prefix="/auth", tags=["认证"])


@router.post("/register")
async def register(user: UserRegister):
    if user.password != user.confirmPassword:
        raise HTTPException(status_code=400, detail="两次密码不一致")

    if UserDao.get_by_username(user.username):
        raise HTTPException(status_code=400, detail="用户名已存在")

    UserDao.add(username=user.username, password=user.password)
    return resp_200(message="注册成功")


@router.post("/login")
async def login(user: UserLogin):
    db_user = UserDao.get_by_username(user.username)

    if not db_user:
        raise HTTPException(status_code=400, detail="用户不存在，请先注册")

    if not verify_password(user.password, db_user.hashed_password):
        raise HTTPException(status_code=400, detail="密码错误")

    token = create_access_token({"user_name": db_user.username, "user_id": db_user.id})
    return resp_200(
        message="登录成功",
        data=TokenData(token=token).dict() if hasattr(TokenData, 'dict') else TokenData(token=token).model_dump()
    )
