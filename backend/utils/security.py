"""
安全工具模块：密码哈希与 JWT 双 Token 机制。

Token 设计：
    - Access Token：短期有效（默认 30 分钟），用于接口鉴权，载荷含 type=access。
    - Refresh Token：长期有效（默认 7 天），用于刷新 Access Token，载荷含 type=refresh。
    两种 Token 共用同一 SECRET_KEY 签名，通过 type 声明严格区分，互不通用。
"""
import os
from datetime import UTC, datetime, timedelta

import jwt
from dotenv import load_dotenv
from fastapi import HTTPException, status
from passlib.context import CryptContext

# 提前加载 .env，确保本模块在 import 时即可读取到 JWT 配置
# （main.py 的 load_dotenv 执行较晚，这里以本文件位置定位 backend/.env）
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

# 从环境变量读取密钥与有效期，提供安全默认值兜底
SECRET_KEY = os.getenv("JWT_SECRET_KEY", "your_very_strong_secret_key_2025_change_it")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))

# Token 类型声明，用于区分 access / refresh，防止混用
TOKEN_TYPE_ACCESS = "access"
TOKEN_TYPE_REFRESH = "refresh"


def hash_password(password: str) -> str:
    """使用 pbkdf2_sha256 对明文密码加盐哈希。"""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """校验明文密码与哈希值是否匹配。"""
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(data: dict) -> str:
    """签发短期 Access Token（默认 30 分钟）。"""
    to_encode = data.copy()
    expire = datetime.now(UTC) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire, "type": TOKEN_TYPE_ACCESS})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_token(data: dict) -> str:
    """签发长期 Refresh Token（默认 7 天）。"""
    to_encode = data.copy()
    expire = datetime.now(UTC) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire, "type": TOKEN_TYPE_REFRESH})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def create_tokens(data: dict) -> dict:
    """同时签发 Access Token 与 Refresh Token，返回统一结构的字典。"""
    return {
        "access_token": create_access_token(data),
        "refresh_token": create_refresh_token(data),
        "token_type": "bearer",
        "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60,  # 秒，供前端倒计时
    }


def decode_token(token: str, expected_type: str = TOKEN_TYPE_ACCESS) -> dict:
    """
    解码并校验 JWT。

    校验项：签名合法性、是否过期、type 是否与期望一致。
    任一校验失败均抛出 401 异常，并携带 WWW-Authenticate 头。
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="无效的认证凭据",
        headers={"WWW-Authenticate": "Bearer"},
    )
    expired_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token 已过期，请重新登录",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise expired_exception
    except jwt.InvalidTokenError:
        # 涵盖签名错误、格式错误、缺失声明等情况
        raise credentials_exception

    # 严格校验 Token 类型，防止用 refresh token 访问受保护接口或反之
    if payload.get("type") != expected_type:
        raise credentials_exception

    return payload
