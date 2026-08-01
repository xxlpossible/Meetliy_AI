
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File

from app.api.schemas import resp_200
from app.api.request import PasswordChange, UserProfileUpdate
from core.database.models.user import User, UserDao
from core.storage.oss import oss_client
from core.storage.uploader import AvatarUploader
from app.api.deps import get_current_user
from utils.security import verify_password

router = APIRouter(prefix='/user', tags=['user'])


@router.get('/profile', summary="获取当前用户信息")
async def get_my_profile(
    current_user: User = Depends(get_current_user)
):
    """获取当前登录用户的资料（用户名、头像等）。"""
    return resp_200(data={
        "id": current_user.id,
        "username": current_user.username,
        "avatar": current_user.avatar,
    })


@router.put('/profile', summary="更新用户资料（用户名）")
async def update_my_profile(
    body: UserProfileUpdate,
    current_user: User = Depends(get_current_user)
):
    """更新当前用户的用户名。头像请使用 POST /user/avatar 单独上传。"""
    if body.username is None or body.username == current_user.username:
        return resp_200(data={
            "id": current_user.id,
            "username": current_user.username,
            "avatar": current_user.avatar,
        }, message="资料更新成功")

    # 修改用户名前，校验是否与其他用户冲突
    existing = UserDao.get_by_username(body.username)
    if existing and existing.id != current_user.id:
        raise HTTPException(status_code=400, detail="用户名已存在")

    updated = UserDao.update_profile(
        user_id=current_user.id,
        username=body.username,
        avatar=None,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="用户不存在")

    return resp_200(data={
        "id": updated.id,
        "username": updated.username,
        "avatar": updated.avatar,
    }, message="资料更新成功")


@router.post('/avatar', summary="上传头像")
async def upload_my_avatar(
    file: UploadFile = File(..., description="头像图片文件"),
    current_user: User = Depends(get_current_user)
):
    """
    上传头像图片到 OSS，返回公共访问 URL 并保存到当前用户。

    仅支持 png/jpg/jpeg/gif/webp，大小不超过 2MB。
    """
    # 1. 类型校验（依据 Content-Type 白名单）
    content_type = (file.content_type or "").lower()
    allowed_content_types = {"image/png", "image/jpeg", "image/gif", "image/webp"}
    if content_type not in allowed_content_types:
        raise HTTPException(status_code=400, detail="仅支持 png/jpg/jpeg/gif/webp 格式图片")

    # 2. 读取文件内容（并做大小限制，避免内存占用过大）
    image_bytes = await file.read(AvatarUploader.MAX_SIZE + 1)
    if len(image_bytes) > AvatarUploader.MAX_SIZE:
        raise HTTPException(status_code=400, detail="头像图片过大（超过 2MB）")

    # 3. 上传到 OSS，得到公共 URL（唯一文件名，避免缓存问题）
    try:
        avatar_url = AvatarUploader.upload_from_bytes(image_bytes, file.filename or "avatar.png")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        raise HTTPException(status_code=500, detail="头像上传失败，请稍后重试")

    # 记录旧头像 URL，待新头像保存成功后删除旧 OSS 对象
    old_avatar_url = current_user.avatar

    # 4. 保存新 URL 到数据库
    updated = UserDao.update_profile(user_id=current_user.id, username=None, avatar=avatar_url)
    if not updated:
        raise HTTPException(status_code=404, detail="用户不存在")

    # 5. 删除旧的 OSS 头像文件（避免存储积压；失败不阻断主流程）
    if old_avatar_url and old_avatar_url != avatar_url:
        old_key = oss_client.parse_key_from_url(old_avatar_url)
        if old_key:
            oss_client.delete_file(key=old_key)

    return resp_200(data={
        "id": updated.id,
        "username": updated.username,
        "avatar": updated.avatar,
    }, message="头像上传成功")


@router.put('/password', summary="修改密码")
async def change_my_password(
    body: PasswordChange,
    current_user: User = Depends(get_current_user)
):
    """修改当前用户密码：验证原密码，新密码需两次输入一致。"""
    # 1. 两次新密码一致性校验
    if body.new_password != body.confirm_password:
        raise HTTPException(status_code=400, detail="两次输入的新密码不一致")

    # 2. 验证原密码
    if not verify_password(body.old_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="原密码错误")

    # 3. 新密码不能与原密码相同（可选，建议提醒）
    if body.new_password == body.old_password:
        raise HTTPException(status_code=400, detail="新密码不能与原密码相同")

    # 4. 更新密码
    ok = UserDao.update_password(current_user.id, body.new_password)
    if not ok:
        raise HTTPException(status_code=500, detail="修改密码失败，请稍后重试")

    return resp_200(message="密码修改成功")


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
