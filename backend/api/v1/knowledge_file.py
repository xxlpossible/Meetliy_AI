import os
import uuid
from loguru import logger
import aiofiles
from fastapi import APIRouter, UploadFile, File, HTTPException, Form, Depends

from api.schemas import resp_200
from database.models.knowledge import Knowledge, KnowledgeDao
from database.models.knowledge_file import KnowledgeFileDao, KnowledgeFile, FileState
from database.models.user import User
from utils.dependencies import get_current_user
from utils.siliconflow_embedding import db_manager
from utils.markitdown_converter import get_supported_extensions, get_knowledge_type
from task.tasks import parse_knowledge_file

router = APIRouter(prefix='/knowledge', tags=['knowledge'])

# 支持的文件类型白名单（扩展名不含点），从 markitdown_converter 动态获取，保持单一数据源
SUPPORTED_SUFFIXES = {ext.lstrip(".") for ext in get_supported_extensions()}

# 持久化上传目录：文件保存于此，路径传给 Celery worker 解析，解析完成后由任务清理。
# Celery worker 与 FastAPI 需部署在同一机器方可访问该路径（毕设单机部署场景）。
# 路径基于本文件位置推导出 backend 根目录，避免依赖运行时 CWD。
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
UPLOAD_DIR = os.path.join(_BACKEND_DIR, "data", "knowledge_uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


def _ensure_knowledge(knowledge_id: str, user: User) -> str:
    """
    确保知识库存在且当前用户有权访问。
    - knowledge_id 为空：自动生成并创建知识库（creater=当前用户），同时创建 Chroma 集合。
    - knowledge_id 对应知识库不存在：创建并绑定当前用户，同时创建 Chroma 集合。
    - 已存在但当前用户无权：抛 403。
    返回有效的 knowledge_id。
    """
    if not knowledge_id:
        knowledge_id = uuid.uuid4().hex
    # 先带权限查
    if KnowledgeDao.get_by_id(k_id=knowledge_id, user_id=user.id) is not None:
        return knowledge_id
    # 查不到，判断是不存在还是无权
    if KnowledgeDao.get_by_id_raw(k_id=knowledge_id) is None:
        # 不存在，创建知识库
        KnowledgeDao.add(Knowledge(
            id=knowledge_id,
            name=knowledge_id,
            creater=user.id,
            accept_users=[],
        ))
        # 在 Chroma 中创建知识库对应的向量集合
        try:
            collection_name = f"collection_kb_{knowledge_id}"
            db_manager.get_or_create_collection(name=collection_name)
            logger.info(f"知识库向量集合创建成功，集合名称：{collection_name}")
        except Exception as e:
            logger.error(f"知识库向量集合创建失败", exc_info=True)
        return knowledge_id
    # 存在但无权
    raise HTTPException(status_code=403, detail="无权访问该知识库")


def _check_knowledge_permission(knowledge_id: str, user: User):
    """校验当前用户对知识库的访问权限，无权抛 403。"""
    if not knowledge_id or KnowledgeDao.get_by_id(k_id=knowledge_id, user_id=user.id) is None:
        raise HTTPException(status_code=403, detail="无权访问该知识库")


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    knowledge_id: str = Form(default=None),
    current_user: User = Depends(get_current_user),
):
    """
    上传知识库文件并异步解析。

    接口仅负责：校验格式 → 持久化保存文件 → 创建 KnowledgeFile 记录(state=0 解析中)
    → 触发 Celery 后台解析任务 → 立即返回 file_id 与 state。
    文档解析（加载/分块/向量化）在 Celery worker 中异步执行，前端通过
    /knowledge/file_state 轮询获取解析进度与结果。
    """
    suffix = file.filename.split(".")[-1].lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: .{suffix}，支持 PDF/Word/Excel/PPT/图片/音频/文本/代码 等格式"
        )

    # 确保知识库存在且当前用户有权（knowledge_id 为空则自动创建）
    knowledge_id = _ensure_knowledge(knowledge_id, current_user)

    file_id = uuid.uuid4().hex
    # 持久化保存路径（任务结束后由 Celery 清理，不在接口层删除）
    save_path = os.path.join(UPLOAD_DIR, f"{file_id}.{suffix}")

    try:
        # 1. 异步分块写入持久化上传目录
        async with aiofiles.open(save_path, "wb") as f:
            while chunk := await file.read(1024 * 1024):
                await f.write(chunk)
    except Exception as e:
        # 写入失败：清理可能残留的半成品文件
        if os.path.exists(save_path):
            try:
                os.remove(save_path)
            except Exception:
                pass
        logger.error(f"文件保存失败: {e}")
        raise HTTPException(status_code=500, detail=f"文件保存失败: {e}")
    finally:
        await file.close()

    # 2. 创建 KnowledgeFile 记录，state=0(解析中)，先于任务触发，保证前端可立即轮询
    # 知识类型按扩展名判定（纯函数查表，无外部调用），保持与原逻辑一致
    ktype = get_knowledge_type(f".{suffix}")
    KnowledgeFileDao.add(KnowledgeFile(
        id=file_id,
        knowledge_id=knowledge_id,
        file_name=file.filename,
        type=ktype,
        state=FileState.PROCESSING.value,
        user_id=current_user.id,
    ))

    # 3. 触发 Celery 后台解析任务
    try:
        parse_knowledge_file.delay(
            file_path=save_path,
            file_suffix=suffix,
            knowledge_id=knowledge_id,
            file_id=file_id,
        )
    except Exception as e:
        # 任务提交失败（如 Redis 不可达）：标记为解析失败，并清理已保存文件
        logger.exception(f"Celery 任务提交失败 file_id={file_id}")
        KnowledgeFileDao.update_state(
            file_id=file_id,
            state=FileState.FAILED.value,
            fail_reason=f"解析任务提交失败: {e}",
        )
        if os.path.exists(save_path):
            try:
                os.remove(save_path)
            except Exception:
                pass
        raise HTTPException(status_code=500, detail=f"解析任务提交失败: {e}")

    # 4. 立即返回，解析在后台异步执行
    return resp_200(data={
        "msg": "文件已上传，正在后台解析",
        "file_id": file_id,
        "knowledge_id": knowledge_id,
        "state": FileState.PROCESSING.value,
    })


@router.get("/file_state")
async def get_file_state(
    file_id: str,
    current_user: User = Depends(get_current_user),
):
    """
    查询知识库文件解析状态，供前端轮询。

    返回字段：
        - state: 0解析中 1成功 2失败
        - fail_reason: 失败原因（state=2 时有值）
        - chunks_counts: 解析成功的分块数（state=1 时有值）
        - file_name: 文件名
    权限：通过文件所属知识库的 creater 或 accept_users 校验，无权返回 403。
    """
    knowledge_file = KnowledgeFileDao.get_by_id(file_id=file_id)
    if not knowledge_file:
        raise HTTPException(status_code=404, detail="文件不存在或已被删除")

    # 校验当前用户对该文件所属知识库的访问权限
    _check_knowledge_permission(knowledge_file.knowledge_id, current_user)

    return resp_200(data={
        "file_id": knowledge_file.id,
        "file_name": knowledge_file.file_name,
        "knowledge_id": knowledge_file.knowledge_id,
        "state": knowledge_file.state,
        "fail_reason": knowledge_file.fail_reason,
        "chunks_counts": knowledge_file.chunks_counts,
    })


@router.get("/file_list")
async def get_file_list(
    knowledge_id: str = None,
    page_num: int = 10,
    page_size: int = 1,
    current_user: User = Depends(get_current_user),
):
    _check_knowledge_permission(knowledge_id, current_user)
    chat_messages, total = KnowledgeFileDao.get_list_by_knowledge_id(
        knowledge_id=knowledge_id,
        page_size=page_size,
        page_num=page_num
    )
    data = {
        "items": chat_messages,
        "total": total
    }
    return resp_200(data=data)


@router.get("/get_file_chunks")
async def get_file_chunks(
    file_id: str,
    knowledge_id: str,
    current_user: User = Depends(get_current_user),
):
    _check_knowledge_permission(knowledge_id, current_user)
    try:
        results = db_manager.get_by_file_id_and_knowledge_id(
            file_id=file_id, knowledge_id=knowledge_id
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"查询向量库失败: {e}")

    chunks = results.get("documents") or []

    if not chunks:
        raise HTTPException(status_code=404, detail=f"未找到 file_id={file_id} 的文档片段")

    return resp_200(data=chunks)


@router.get("/delete_file")
async def delete_file(
    file_id: str,
    knowledge_id: str,
    current_user: User = Depends(get_current_user),
):
    _check_knowledge_permission(knowledge_id, current_user)
    # 1. 先查询文件是否存在（需要获取 knowledge_id 来定位集合）
    knowledge_file = KnowledgeFileDao.get_by_id(file_id=file_id)
    if not knowledge_file:
        raise HTTPException(status_code=404, detail="文件不存在或已被删除")

    try:
        # 2. 从 ChromaDB 删除向量
        db_manager.delete_by_file_id(
            knowledge_id=knowledge_id,
            file_id=file_id
        )
    except Exception as e:
        # 向量库删除失败，是否回滚？通常建议报错并阻止 SQL 删除，或者记录日志
        raise HTTPException(status_code=500, detail=f"删除向量数据失败: {e}")

    # 3. 从 SQL 数据库删除文件记录
    # 假设你的 DAO 有 delete 方法
    knowledge_file.del_flag = -1
    KnowledgeFileDao.update(knowledge_file)

    return resp_200(data={"msg": "文件及相关向量已成功删除", "file_id": file_id})
