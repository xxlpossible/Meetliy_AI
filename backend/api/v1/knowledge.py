import os
import tempfile
import uuid

from fastapi import APIRouter, UploadFile, File, HTTPException, Form

from api.schemas import resp_200
from database.models.knowledge_file import KnowledgeFileDao, KnowledgeFile
from utils.chroma_db import chromadb_client
from utils.file_loader import FileLoader
from utils.splitter import Splitter

router = APIRouter(prefix='/knowledge', tags=['knowledge'])

TEMP_DIR = "data/tmp"
os.makedirs(TEMP_DIR, exist_ok=True)


@router.post("/upload")
async def upload_file(file: UploadFile = File(...), knowledge_id: str = Form(default=None)):
    suffix = file.filename.split(".")[-1].lower()
    if suffix not in ["pdf", "doc", "docx", "xls", "xlsx"]:
        raise HTTPException(status_code=400, detail="Unsupported file type")

    tmp_file = None

    try:
        # 1. 创建 Python 原生临时文件
        tmp_file = tempfile.NamedTemporaryFile(suffix=f".{suffix}", delete=False)
        tmp_file.write(await file.read())
        tmp_file.flush()
        tmp_file.close()

        # 2. 文档解析
        file_loader = FileLoader()
        documents = file_loader.load_document(file_path=tmp_file.name, file_type=suffix)

        # 3. 文本切分（递归标点切分）
        chunks = Splitter.split_documents(documents)
        file_id = uuid.uuid4().hex

        # 4. 添加 metadata（非常关键）
        for idx, chunk in enumerate(chunks):
            chunk.metadata.update({
                "knowledge_id": knowledge_id,
                "file_id": file_id
            })
        # 提取页面内容与metadata
        metadata_list = [chunk.metadata for chunk in chunks]
        chunks = [chunk.page_content for chunk in chunks]

        # 5. 向量入库（向量 + 原文）
        vector_store = chromadb_client
        vector_store.add_documents(
            metadata=metadata_list,
            collection_name=f"collection_{knowledge_id}",
            documents=chunks,
            ids=[f"{file_id}_{i}" for i in range(len(chunks))]
        )

        # 将文件信息存入数据库
        KnowledgeFileDao.add(KnowledgeFile(
            knowledge_id=knowledge_id,
            file_name=file.filename,
            chunks_counts=len(chunks),
            id=file_id
        ))

        return resp_200(data={
            "msg": "Document indexed successfully",
            "file_id": file_id,
            "chunk_count": len(chunks)
        })

    finally:
        # 6. 临时文件兜底清理
        if tmp_file and os.path.exists(tmp_file.name):
            os.remove(tmp_file.name)


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
        results = chromadb_client.get_by_file_id_and_knowledge_id(
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
        chromadb_client.delete_by_file_id(
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
