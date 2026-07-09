import os
import tempfile
import uuid
from loguru import logger
import aiofiles
from fastapi import APIRouter, UploadFile, File, HTTPException, Form, Depends
from starlette.concurrency import run_in_threadpool

from api.schemas import resp_200
from database.models.knowledge_file import KnowledgeFileDao, KnowledgeFile, KnowledgeType
from database.models.user import User
from utils.dependencies import get_current_user
from utils.file_loader import FileLoader
from utils.siliconflow_embedding import db_manager
from utils.splitter import Splitter
from utils.markitdown_converter import get_supported_extensions, get_knowledge_type

router = APIRouter(prefix='/knowledge', tags=['knowledge'])

# 支持的文件类型白名单（扩展名不含点），从 markitdown_converter 动态获取，保持单一数据源
SUPPORTED_SUFFIXES = {ext.lstrip(".") for ext in get_supported_extensions()}


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    knowledge_id: str = Form(default=None),
    current_user: User = Depends(get_current_user),
):
    suffix = file.filename.split(".")[-1].lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: .{suffix}，支持 PDF/Word/Excel/PPT/图片/音频/文本/代码 等格式"
        )

    tmp_path = None
    file_id = uuid.uuid4().hex

    try:
        # 1. 异步创建临时文件路径
        fd, tmp_path = tempfile.mkstemp(suffix=f".{suffix}")
        os.close(fd)  # 关闭 mkstemp 返回的句柄，后面用 aiofiles 打开

        # 2. 异步分块写入
        async with aiofiles.open(tmp_path, "wb") as f:
            while chunk := await file.read(1024 * 1024):
                await f.write(chunk)

        # 3. 将同步耗时操作放入线程池执行，避免阻塞主线程
        # 包装一个内部函数来处理后续逻辑
        def process_document(path, sfx, k_id, f_id, f_name):
            # 判断知识类型：0文本 1语音 2图片
            ktype = get_knowledge_type(f".{sfx}")

            loader = FileLoader()
            docs = loader.load_document(file_path=path, file_type=sfx)

            # 语音转录为纯文本，用通用递归分块；文本/图片（OCR 可能含 Markdown 表格）用 MD 分块
            if ktype == KnowledgeType.AUDIO.value:
                chunks = Splitter.split_documents(docs)
            else:
                chunks = Splitter.split_markdown_documents(docs)

            metadata_list = []
            content_list = []
            for idx, chunk in enumerate(chunks):
                chunk.metadata.update({
                    "knowledge_id": k_id,
                    "file_id": f_id,
                    "type": ktype,  # 知识类型写入 metadata，方便向量库查询过滤
                })
                metadata_list.append(chunk.metadata)
                content_list.append(chunk.page_content)

            # 向量入库
            db_manager.add_documents(
                metadatas=metadata_list,
                collection_name=f"collection_{k_id}",
                documents=content_list,
                ids=[f"{f_id}_{i}" for i in range(len(content_list))]
            )

            # 数据库记录（带知识类型）
            KnowledgeFileDao.add(KnowledgeFile(
                knowledge_id=k_id,
                file_name=f_name,
                chunks_counts=len(content_list),
                type=ktype,
                id=f_id
            ))
            return len(content_list)

        # 在线程池中执行耗时任务
        chunk_count = await run_in_threadpool(
            process_document, tmp_path, suffix, knowledge_id, file_id, file.filename
        )

        return resp_200(data={
            "msg": "Document indexed successfully",
            "file_id": file_id,
            "chunk_count": chunk_count
        })

    except Exception as e:
        # 记录日志 log.error(f"Upload failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        # 4. 彻底清理临时文件
        await file.close()  # 异步关闭上传的文件句柄
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
                logger.info(f"临时文件已被删除：{tmp_path}")
            except Exception as e:
                logger.error(f"Failed to delete tmp file: {e}")


@router.get("/file_list")
async def get_file_list(
    knowledge_id: str = None,
    page_num: int = 10,
    page_size: int = 1,
    current_user: User = Depends(get_current_user),
):
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
