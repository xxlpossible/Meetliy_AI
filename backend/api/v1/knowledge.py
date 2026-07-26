import uuid

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger

from api.schemas import resp_200
from database.models.knowledge import Knowledge, KnowledgeDao
from database.models.knowledge_file import KnowledgeFileDao
from database.models.user import User
from database.schemas.schema import (
    KnowledgeCreate,
    KnowledgeDelete,
    KnowledgeQuery,
    KnowledgeUpdate,
)
from utils.dependencies import get_current_user
from utils.siliconflow_embedding import db_manager

router = APIRouter(prefix="/kb", tags=["knowledge"])


# ----------------------------- 辅助函数 ----------------------------- #

def _ensure_knowledge(knowledge_id: str, user: User) -> Knowledge:
    """
    按 ID 查询知识库并校验当前用户访问权限。
    - 不存在或已删除 → 404
    - 存在但无权 → 403
    - 有权 → 返回 Knowledge 实体
    """
    knowledge = KnowledgeDao.get_by_id(k_id=knowledge_id, user_id=user.id)
    if knowledge is None:
        # 再次查询判断是"不存在"还是"无权"
        raw = KnowledgeDao.get_by_id_raw(k_id=knowledge_id)
        if raw is None:
            raise HTTPException(status_code=404, detail="知识库不存在或已被删除")
        raise HTTPException(status_code=403, detail="无权访问该知识库")
    return knowledge


def _ensure_knowledge_owner(knowledge_id: str, user: User) -> Knowledge:
    """
    校验当前用户是否为知识库创建者。
    - 不存在 → 404
    - 不是创建者 → 403
    - 是创建者 → 返回 Knowledge 实体
    """
    knowledge = KnowledgeDao.get_by_id_raw(k_id=knowledge_id)
    if knowledge is None:
        raise HTTPException(status_code=404, detail="知识库不存在或已被删除")
    if knowledge.creater != user.id:
        raise HTTPException(status_code=403, detail="仅知识库创建者有权限执行此操作")
    return knowledge


# ----------------------------- 接口 ----------------------------- #

@router.post("/create", summary="创建知识库")
async def create_knowledge(
    body: KnowledgeCreate,
    current_user: User = Depends(get_current_user),
):
    """
    创建一个新的知识库。
    - 自动生成 UUID 主键。
    - 当前用户为知识库创建者（creater）。
    - accept_users 中的用户将被授予访问权限，创建者不存入 accept_users。
    - 自动在 Chroma 中创建对应的向量集合 collection_kb_{knowledge_id}。
    """
    # accept_users 仅为被授权用户，创建者不存入
    accept_users = body.accept_users if body.accept_users else []
    # 确保创建者不在 accept_users 中（防止冗余）
    accept_users = [uid for uid in accept_users if uid != current_user.id]
    # 去重
    accept_users = list(dict.fromkeys(accept_users))

    knowledge = Knowledge(
        id=uuid.uuid4().hex,
        name=body.name,
        description=body.description,
        creater=current_user.id,
        accept_users=accept_users,
    )
    KnowledgeDao.add(knowledge)
    logger.info(f"用户 {current_user.id} 创建知识库: {knowledge.id}, accept_users: {accept_users}")
    
    # 在 Chroma 中创建知识库对应的向量集合
    try:
        collection_name = f"collection_kb_{knowledge.id}"
        db_manager.get_or_create_collection(name=collection_name)
        logger.info(f"知识库向量集合创建成功，集合名称：{collection_name}")
    except Exception:
        logger.error("知识库向量集合创建失败", exc_info=True)
    
    return resp_200(data={
        "id": knowledge.id,
        "name": knowledge.name,
        "description": knowledge.description,
        "creater": knowledge.creater,
        "accept_users": knowledge.accept_users,
        "create_time": str(knowledge.create_time) if knowledge.create_time else None,
    })


@router.post("/list", summary="查询知识库列表（分页）")
async def list_knowledge(
    body: KnowledgeQuery,
    current_user: User = Depends(get_current_user),
):
    """
    分页查询当前用户有权访问的知识库列表。
    - 可按名称模糊搜索（name 参数非空时）。
    - 按创建时间倒序排列。
    """
    items, total = KnowledgeDao.list(
        user_id=current_user.id,
        page_num=body.page_num,
        page_size=body.page_size,
        name=body.name,
    )
    # 序列化：将 Knowledge 对象转为 dict，便于 JSON 响应
    serialized = []
    for k in items:
        serialized.append({
            "id": k.id,
            "name": k.name,
            "description": k.description,
            "creater": k.creater,
            "accept_users": k.accept_users,
            "create_time": str(k.create_time) if k.create_time else None,
            "update_time": str(k.update_time) if k.update_time else None,
        })
    return resp_200(data={
        "items": serialized,
        "total": total,
        "page_num": body.page_num,
        "page_size": body.page_size,
    })


@router.get("/detail", summary="查询知识库详情")
async def get_knowledge_detail(
    knowledge_id: str,
    current_user: User = Depends(get_current_user),
):
    """
    根据 ID 查询知识库详情（含元信息）。
    - 无需传 body，通过 query 参数 knowledge_id 定位。
    - 无权访问返回 403，不存在返回 404。
    """
    knowledge = _ensure_knowledge(knowledge_id, current_user)
    return resp_200(data={
        "id": knowledge.id,
        "name": knowledge.name,
        "description": knowledge.description,
        "creater": knowledge.creater,
        "accept_users": knowledge.accept_users,
        "create_time": str(knowledge.create_time) if knowledge.create_time else None,
        "update_time": str(knowledge.update_time) if knowledge.update_time else None,
    })


@router.post("/update", summary="更新知识库信息")
async def update_knowledge(
    body: KnowledgeUpdate,
    current_user: User = Depends(get_current_user),
):
    """
    更新知识库的名称、描述或授权用户。
    - knowledge_id 必填，用于定位目标知识库。
    - 仅知识库创建者可调用此接口。
    - accept_users 为全量替换：传入的列表将覆盖原有授权用户列表。
    """
    knowledge = _ensure_knowledge_owner(body.knowledge_id, current_user)

    if body.name is not None:
        knowledge.name = body.name
    if body.description is not None:
        knowledge.description = body.description
    if body.accept_users is not None:
        # 全量替换 accept_users，移除创建者（防止冗余），去重
        new_users = [uid for uid in body.accept_users if uid != current_user.id]
        knowledge.accept_users = list(dict.fromkeys(new_users))

    KnowledgeDao.update(knowledge)
    logger.info(f"用户 {current_user.id} 更新知识库: {knowledge.id}")
    return resp_200(data={
        "id": knowledge.id,
        "name": knowledge.name,
        "description": knowledge.description,
        "creater": knowledge.creater,
        "accept_users": knowledge.accept_users,
        "update_time": str(knowledge.update_time) if knowledge.update_time else None,
    })


@router.post("/delete", summary="删除知识库（软删除）")
async def delete_knowledge(
    body: KnowledgeDelete,
    current_user: User = Depends(get_current_user),
):
    """
    软删除知识库：将 is_delete 设为 -1，前端不再可见。
    - 仅知识库创建者可删除。
    - 删除知识库时同步软删除该知识库下的所有文件（del_flag=-1）。
    """
    _ensure_knowledge_owner(body.knowledge_id, current_user)
    
    # 先软删除该知识库下的所有文件
    deleted_files_count = KnowledgeFileDao.delete_all_by_knowledge_id(knowledge_id=body.knowledge_id)
    logger.info(f"用户 {current_user.id} 删除知识库 {body.knowledge_id} 时同步删除 {deleted_files_count} 个文件")
    
    # 再软删除知识库本身
    KnowledgeDao.delete(k_id=body.knowledge_id, user_id=current_user.id)
    logger.info(f"用户 {current_user.id} 删除知识库: {body.knowledge_id}")
    return resp_200(message="知识库已删除", data={
        "id": body.knowledge_id,
        "deleted_files_count": deleted_files_count,
    })
