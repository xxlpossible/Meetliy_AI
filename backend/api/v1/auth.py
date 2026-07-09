"""
认证接口：注册 / 登录 / Token 刷新。

设计要点：
    1. 注册：参数校验由 Schema 完成，重复注册检测，密码哈希存储，DB 异常兜底。
    2. 登录：用户名与密码校验失败统一返回"用户名或密码错误"，防止用户名枚举攻击；
       成功后签发 access + refresh 双 Token。
    3. 刷新：校验 refresh token 的签名、过期与类型，通过后签发全新双 Token。
"""
from fastapi import APIRouter, HTTPException
from loguru import logger

from api.schemas import resp_200
from database.models.user import UserDao
from database.schemas.schema import RefreshTokenRequest, UserLogin, UserRegister
from utils.security import (
    TOKEN_TYPE_REFRESH,
    create_tokens,
    decode_token,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["认证"])


@router.post("/register", summary="用户注册")
async def register(user: UserRegister):
    # 1. 两次密码一致性校验
    if user.password != user.confirmPassword:
        raise HTTPException(status_code=400, detail="两次密码不一致")

    # 2. 重复注册检测
    if UserDao.get_by_username(user.username):
        raise HTTPException(status_code=400, detail="用户名已存在")

    # 3. 入库（密码哈希在 UserDao.add 内部完成）
    try:
        UserDao.add(username=user.username, password=user.password)
    except Exception as e:
        logger.exception(f"注册入库失败: {e}")
        raise HTTPException(status_code=500, detail="注册失败，请稍后重试")

    return resp_200(message="注册成功")


@router.post("/login", summary="用户登录")
async def login(user: UserLogin):
    db_user = UserDao.get_by_username(user.username)

    # 用户不存在与密码错误返回同一提示，避免攻击者通过差异判断用户是否存在
    if not db_user or not verify_password(user.password, db_user.hashed_password):
        raise HTTPException(status_code=400, detail="用户名或密码错误")

    # 签发双 Token
    token_payload = {"user_name": db_user.username, "user_id": db_user.id}
    return resp_200(message="登录成功", data=create_tokens(token_payload))


@router.post("/refresh", summary="刷新 Access Token")
async def refresh_token(body: RefreshTokenRequest):
    # 校验 refresh token：签名 / 过期 / 类型，任一不通过 decode_token 内部抛 401
    payload = decode_token(body.refresh_token, expected_type=TOKEN_TYPE_REFRESH)

    user_id = payload.get("user_id")
    db_user = UserDao.get_by_id(user_id) if user_id is not None else None

    # refresh token 有效但用户已被删除，视为失效
    if not db_user:
        raise HTTPException(
            status_code=401,
            detail="Refresh Token 已失效，请重新登录",
        )

    # 签发全新的双 Token（refresh token 滚动续期）
    token_payload = {"user_name": db_user.username, "user_id": db_user.id}
    return resp_200(message="刷新成功", data=create_tokens(token_payload))
