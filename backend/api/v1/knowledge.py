import os
import tempfile
import uuid

import aiofiles
from fastapi import APIRouter, UploadFile, File, HTTPException, Form
from starlette.concurrency import run_in_threadpool

from api.schemas import resp_200
from database.models.knowledge_file import KnowledgeFileDao, KnowledgeFile
from utils.file_loader import FileLoader
from utils.siliconflow_embedding import db_manager
from utils.splitter import Splitter

router = APIRouter(prefix='/knowledge', tags=['knowledge'])


@router.post("/upload")
async def upload_file(file: UploadFile = File(...), knowledge_id: str = Form(default=None)):
    suffix = file.filename.split(".")[-1].lower()
    if suffix not in ["pdf", "doc", "docx", "xls", "xlsx"]:
        raise HTTPException(status_code=400, detail="Unsupported file type")

    tmp_path = None
    file_id = uuid.uuid4().hex

    try:
        # 1. 创建 Python 原生临时文件
        # 这里用的是同步的方法
        # tmp_file = tempfile.NamedTemporaryFile(suffix=f".{suffix}", delete=False)
        # tmp_file.write(await file.read())
        # tmp_file.flush()
        # tmp_file.close()

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
            loader = FileLoader()
            docs = loader.load_document(file_path=path, file_type=sfx)

            chunks = Splitter.split_documents(docs)

            metadata_list = []
            content_list = []
            for idx, chunk in enumerate(chunks):
                chunk.metadata.update({
                    "knowledge_id": k_id,
                    "file_id": f_id
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

            # 数据库记录
            KnowledgeFileDao.add(KnowledgeFile(
                knowledge_id=k_id,
                file_name=f_name,
                chunks_counts=len(content_list),
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
            except Exception as e:
                print(f"Failed to delete tmp file: {e}")


@router.get("/file_list")
async def get_file_list(knowledge_id: str = None, page_num: int = 10, page_size: int = 1):
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
async def get_file_chunks(file_id: str, knowledge_id: str):
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
async def delete_file(file_id: str, knowledge_id: str):
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
