"""
知识库（Knowledge）管理 REST 接口：创建 / 列表 / 详情 / 更新 / 删除 / 授权。

路由前缀 /api/v1/kb（与已有的 knowledge_file.py 的 /knowledge 前缀区分开，避免路由冲突）。
"""
import uuid

from fastapi import APIRouter, HTTPException, Depends
from loguru import logger

from api.schemas import resp_200
from database.models.user import User
from database.models.knowledge import Knowledge, KnowledgeDao
from database.schemas.schema import (
    KnowledgeCreate,
    KnowledgeUpdate,
    KnowledgeQuery,
    KnowledgeGrant,
    KnowledgeGrantBatch,
    KnowledgeDelete,
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
        raw = KnowledgeDao.get_by_id(k_id=knowledge_id)
        if raw is None:
            raise HTTPException(status_code=404, detail="知识库不存在或已被删除")
        raise HTTPException(status_code=403, detail="无权访问该知识库")
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
    - 当前用户自动加入 user_ids 列表（知识库创建者默认可访问）。
    - accept_users 中的用户也会被授予访问权限。
    - 自动在 Chroma 中创建对应的向量集合 collection_kb_{knowledge_id}。
    """
    # 构建 user_ids：创建者 + accept_users，去重
    user_ids = [current_user.id]
    if body.accept_users:
        for uid in body.accept_users:
            if uid not in user_ids:
                user_ids.append(uid)
    
    knowledge = Knowledge(
        id=uuid.uuid4().hex,
        name=body.name,
        description=body.description,
        user_ids=user_ids,
    )
    KnowledgeDao.add(knowledge)
    logger.info(f"用户 {current_user.id} 创建知识库: {knowledge.id}, user_ids: {user_ids}")
    
    # 在 Chroma 中创建知识库对应的向量集合
    try:
        collection_name = f"collection_kb_{knowledge.id}"
        db_manager.get_or_create_collection(name=collection_name)
        logger.info(f"知识库向量集合创建成功，集合名称：{collection_name}")
    except Exception as e:
        logger.error(f"知识库向量集合创建失败: {e}", exc_info=True)
    
    return resp_200(data={
        "id": knowledge.id,
        "name": knowledge.name,
        "description": knowledge.description,
        "user_ids": knowledge.user_ids,
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
            "user_ids": k.user_ids,
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
        "user_ids": knowledge.user_ids,
        "create_time": str(knowledge.create_time) if knowledge.create_time else None,
        "update_time": str(knowledge.update_time) if knowledge.update_time else None,
    })


@router.post("/update", summary="更新知识库信息")
async def update_knowledge(
    body: KnowledgeUpdate,
    current_user: User = Depends(get_current_user),
):
    """
    更新知识库的名称和/或描述。
    - knowledge_id 必填，用于定位目标知识库。
    - 仅 knowledge_id 对应的知识库在 user_ids 中才可更新。
    """
    _ensure_knowledge(body.knowledge_id, current_user)

    knowledge = KnowledgeDao.get_by_id(k_id=body.knowledge_id)
    if body.name is not None:
        knowledge.name = body.name
    if body.description is not None:
        knowledge.description = body.description
    KnowledgeDao.update(knowledge)
    logger.info(f"用户 {current_user.id} 更新知识库: {knowledge.id}")
    return resp_200(data={
        "id": knowledge.id,
        "name": knowledge.name,
        "description": knowledge.description,
        "update_time": str(knowledge.update_time) if knowledge.update_time else None,
    })


@router.post("/delete", summary="删除知识库（软删除）")
async def delete_knowledge(
    body: KnowledgeDelete,
    current_user: User = Depends(get_current_user),
):
    """
    软删除知识库：将 is_delete 设为 -1，前端不再可见。
    - 仅知识库 owner（在 user_ids 中）可删除。
    - 注意：软删除后知识库下的文件记录仍保留（del_flag 机制），
      但无法通过正常接口访问到。如需物理删除文件，需额外扩展。
    """
    _ensure_knowledge(body.knowledge_id, current_user)
    KnowledgeDao.delete(k_id=body.knowledge_id, user_id=current_user.id)
    logger.info(f"用户 {current_user.id} 删除知识库: {body.knowledge_id}")
    return resp_200(message="知识库已删除", data={"id": body.knowledge_id})


@router.post("/grant", summary="授权其他用户访问知识库")
async def grant_knowledge_access(
    body: KnowledgeGrant,
    current_user: User = Depends(get_current_user),
):
    """
    将知识库访问权限授予指定用户。
    - knowledge_id 通过请求体传输。
    - 仅当前用户已拥有该知识库访问权时可放权。
    - 幂等操作：已授权用户不会重复添加。
    """
    # 校验当前用户是否有权访问该知识库
    knowledge = _ensure_knowledge(body.knowledge_id, current_user)

    if body.user_id in (knowledge.user_ids or []):
        return resp_200(message="该用户已有访问权限", data={
            "id": body.knowledge_id,
            "user_ids": knowledge.user_ids,
        })

    KnowledgeDao.grant_user(
        k_id=body.knowledge_id,
        user_id=body.user_id,
        operator_id=current_user.id,
    )
    logger.info(
        f"用户 {current_user.id} 授权用户 {body.user_id} 访问知识库: {body.knowledge_id}"
    )
    updated = KnowledgeDao.get_by_id(k_id=body.knowledge_id, user_id=current_user.id)
    return resp_200(message="授权成功", data={
        "id": body.knowledge_id,
        "user_ids": updated.user_ids,
    })


@router.post("/grant_batch", summary="批量授权多个用户访问知识库")
async def grant_knowledge_access_batch(
    body: KnowledgeGrantBatch,
    current_user: User = Depends(get_current_user),
):
    """
    将知识库访问权限一次性授予多个用户。
    - knowledge_id 通过请求体传输。
    - 仅当前用户已拥有该知识库访问权时可放权。
    - 幂等操作：已授权用户不会重复添加。
    """
    # 校验当前用户是否有权访问该知识库
    knowledge = _ensure_knowledge(body.knowledge_id, current_user)
    
    # 批量授权
    granted_count = 0
    for user_id in body.user_ids:
        if user_id not in (knowledge.user_ids or []):
            KnowledgeDao.grant_user(
                k_id=body.knowledge_id,
                user_id=user_id,
                operator_id=current_user.id,
            )
            granted_count += 1
            # 更新 knowledge 对象以反映最新状态
            knowledge = KnowledgeDao.get_by_id(k_id=body.knowledge_id, user_id=current_user.id)
    
    logger.info(
        f"用户 {current_user.id} 批量授权 {granted_count} 个用户访问知识库: {body.knowledge_id}"
    )
    return resp_200(message=f"成功授权 {granted_count} 个用户", data={
        "id": body.knowledge_id,
        "user_ids": knowledge.user_ids,
    })
