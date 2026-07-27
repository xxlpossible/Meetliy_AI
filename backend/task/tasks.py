# task/tasks.py
import os
import re
import uuid
from typing import Any

from langchain_core.documents import Document
from loguru import logger

from database.models.knowledge_file import (
    FileState,
    KnowledgeFileDao,
    KnowledgeType,
)
from database.models.transcription import Status, TranscriptionDao
from langchain_pipeline.agent import MeetingAgent
from utils.file_loader import FileLoader
from utils.markitdown_converter import get_knowledge_type
from utils.siliconflow_embedding import db_manager
from utils.splitter import Splitter

from .celery_app import celery_app


# ---------------------------------------------------------------------------
# 辅助函数：解析主题分段文本
# ---------------------------------------------------------------------------
def _parse_theme_segmentation(theme_text: str) -> list[dict[str, str]]:
    """
    将 MeetingAgent 生成的主题分段文本按【主题名称】边界解析为列表。

    输入格式示例：
        【产品发布计划】
        讨论了Q3发布计划...
        【预算评审】
        张三提出预算需要...

    输出：
        [
            {"theme": "产品发布计划", "content": "讨论了Q3发布计划..."},
            {"theme": "预算评审", "content": "张三提出预算需要..."},
        ]
    """
    if not theme_text or not theme_text.strip():
        return []

    # 按【】边界拆分
    segments = re.split(r'(?=【)', theme_text.strip())
    result: list[dict[str, str]] = []

    for seg in segments:
        seg = seg.strip()
        if not seg:
            continue
        # 提取主题名称：第一个【...】之间的内容
        match = re.match(r'【(.+?)】\s*(.*)', seg, re.DOTALL)
        if match:
            theme_name = match.group(1).strip()
            content = match.group(2).strip()
            if theme_name and content:
                result.append({"theme": theme_name, "content": content})

    return result


@celery_app.task
def transcription(
        public_url: str | None = None,
        t_id: str | None = None
):
    """语音转录后台任务"""
    try:
        # 取得对应任务
        task = TranscriptionDao.get_by_id(t_id=t_id)

        # 这里是新的工作流的执行结果
        agent = MeetingAgent()
        logger.info("Agent工作流开始执行")
        result = agent.run(public_url=public_url)
        if result.get('status') == 'complete':
            logger.info("后台任务执行成功")
            task.status = Status.COMPLETE.value
            task.task_result = result
        elif result.get('status') == 'complete_with_errors':
            logger.error(f"后台任务执行失败，执行过程出错，报错信息：{result.get('error_message', 'ERROR')}")
            task.status = Status.ERROR.value

        # 对数据库进行更新
        TranscriptionDao.update(task)

        # 转录任务完成后，同步更新关联的 Meeting 状态
        from database.models.meeting import MeetingDao, MeetingStatus
        meeting = MeetingDao.get_by_task_id(t_id)
        if meeting:
            if result.get('status') == 'complete':
                MeetingDao.update_status(meeting.id, MeetingStatus.FINISH.value)
                logger.info(f"会议 {meeting.id} 转录完成，状态更新为 FINISH")
            elif result.get('status') == 'complete_with_errors':
                MeetingDao.update_status(meeting.id, MeetingStatus.ERROR.value)
                logger.error(f"会议 {meeting.id} 转录异常，状态更新为 ERROR")
            else:
                # 未知状态也标为 ERROR
                MeetingDao.update_status(meeting.id, MeetingStatus.ERROR.value)
                logger.error(f"会议 {meeting.id} 转录返回未知状态，状态更新为 ERROR")
        else:
            logger.warning(f"task_id={t_id} 未找到关联的 Meeting 记录，跳过状态更新")

        if result.get('status') == 'complete':
            # 将识别结果转换为向量 并创建会议专用集合
            # 获取 meeting_id，用于集合命名和 metadata
            meeting_id = meeting.id if meeting else None
            # 集合命名为 collection_meeting_{meeting_id}
            collection_name = f"collection_meeting_{meeting_id}"
            db_manager.get_or_create_collection(name=collection_name)
            logger.info(f"会议内容集合创建成功，集合名称：{collection_name}")

            # —— 1. 细粒度分块（原有逻辑 + 增强 metadata） ——
            complete_text = result.get('complete_text', "")
            sentences = result.get('sentences', result.get('sentences_with_time', []))

            # 转录结果为纯文本（非 Markdown），使用通用递归分块
            chunks = Splitter.split_documents([Document(page_content=complete_text)])
            chunk_page_contents = [chunk.page_content for chunk in chunks]

            # 先存入带时间戳的原始句子（保持原逻辑不变，doc_type="sentence"）
            if sentences:
                db_manager.add_documents(
                    collection_name=collection_name,
                    documents=sentences,
                )
                logger.info(f"sentence入库: {len(sentences)} 条")

            # 再存入细粒度 chunk（带 chunk_index / meeting_id metadata）
            if chunk_page_contents:
                fine_metadatas: list[dict[str, Any]] = []
                for i, _content in enumerate(chunk_page_contents):
                    meta: dict[str, Any] = {"doc_type": "fine_chunk", "chunk_index": i}
                    if meeting_id:
                        meta["meeting_id"] = meeting_id
                    fine_metadatas.append(meta)
                db_manager.add_documents(
                    collection_name=collection_name,
                    documents=chunk_page_contents,
                    metadatas=fine_metadatas,
                    ids=[uuid.uuid4().hex for _ in chunk_page_contents],
                )
                logger.info(f"细粒度 chunk 入库: {len(chunk_page_contents)} 条 (doc_type=fine_chunk)")

            # —— 2. 摘要级内容入库 ——
            # 2.1 会议摘要
            summary_text = result.get('summary', '')
            if summary_text and summary_text.strip():
                db_manager.add_documents(
                    collection_name=collection_name,
                    documents=[summary_text.strip()],
                    metadatas=[{"doc_type": "summary"}],
                    ids=[uuid.uuid4().hex],
                )
                logger.info("会议摘要入库 (doc_type=summary)")

            # 2.2 行动项
            action_text = result.get('action', '')
            if action_text and action_text.strip():
                db_manager.add_documents(
                    collection_name=collection_name,
                    documents=[action_text.strip()],
                    metadatas=[{"doc_type": "action_items"}],
                    ids=[uuid.uuid4().hex],
                )
                logger.info("行动项入库 (doc_type=action_items)")

            # 2.3 主题分段（按【主题名称】拆分后逐段入库）
            theme_text = result.get('theme_segmentation', '')
            themes = _parse_theme_segmentation(theme_text)
            if themes:
                theme_docs: list[str] = []
                theme_metas: list[dict[str, Any]] = []
                for t in themes:
                    theme_docs.append(t["content"])
                    theme_metas.append({"doc_type": "theme_seg", "theme": t["theme"]})
                db_manager.add_documents(
                    collection_name=collection_name,
                    documents=theme_docs,
                    metadatas=theme_metas,
                    ids=[uuid.uuid4().hex for _ in theme_docs],
                )
                logger.info(f"主题分段入库: {len(themes)} 个主题 (doc_type=theme_seg)")
    except Exception as e:
        logger.error(f"后台任务执行过程发生错误，请检查：{e}")
        # 任务执行异常时，将 Transcription 和关联的 Meeting 都标为 ERROR
        try:
            task = TranscriptionDao.get_by_id(t_id=t_id)
            if task:
                task.status = Status.ERROR.value
                TranscriptionDao.update(task)
            from database.models.meeting import MeetingDao, MeetingStatus
            meeting = MeetingDao.get_by_task_id(t_id)
            if meeting:
                MeetingDao.update_status(meeting.id, MeetingStatus.ERROR.value)
                logger.info(f"会议 {meeting.id} 转录任务异常，状态更新为 ERROR")
        except Exception as update_err:
            logger.error(f"更新失败状态时出错: {update_err}")


@celery_app.task
def parse_knowledge_file(
        file_path: str,
        file_suffix: str,
        knowledge_id: str,
        file_id: str,
):
    """
    知识库文件解析后台任务。

    由 knowledge.py 的 /upload 接口在创建 KnowledgeFile 记录（state=0）后通过
    parse_knowledge_file.delay(...) 触发。本任务在 Celery worker 中异步执行：
        1. 加载文档（MarkItDown / 语音转录 / 图片 OCR）；
        2. 按知识类型分块（语音走通用分块，文本/图片走 Markdown 分块）；
        3. 向量入库；
        4. 更新 KnowledgeFile.state 为成功(1) / 失败(2)；
        5. finally 清理临时文件。

    :param file_path: 持久化上传目录中的文件绝对路径，任务结束后由本任务删除
    :param file_suffix: 文件扩展名（不含点），如 pdf / docx / mp3
    :param knowledge_id: 知识库ID，对应 ChromaDB 集合名 collection_kb_{knowledge_id}
    :param file_id: 文件ID，KnowledgeFile 记录主键，用于回写解析状态
    """
    logger.info(f"[知识库解析] 开始 file_id={file_id}, knowledge_id={knowledge_id}, suffix={file_suffix}")
    try:
        # 防御：任务被消费前文件可能已被删除（如用户在解析中删除文件）
        kf = KnowledgeFileDao.get_by_id(file_id=file_id)
        if kf is None or kf.del_flag != 0:
            logger.warning(f"[知识库解析] 文件记录不存在或已删除，跳过解析 file_id={file_id}")
            return

        # 判断知识类型：0文本 1语音 2图片
        ktype = get_knowledge_type(f".{file_suffix}")

        loader = FileLoader()
        docs = loader.load_document(file_path=file_path, file_type=file_suffix)

        # 语音转录为纯文本，用通用递归分块；文本/图片（OCR 可能含 Markdown 表格）用 MD 分块
        if ktype == KnowledgeType.AUDIO.value:
            chunks = Splitter.split_documents(docs)
        else:
            chunks = Splitter.split_markdown_documents(docs)

        metadata_list = []
        content_list = []
        for chunk in chunks:
            chunk.metadata.update({
                "knowledge_id": knowledge_id,
                "file_id": file_id,
                "type": ktype,  # 知识类型写入 metadata，方便向量库查询过滤
            })
            metadata_list.append(chunk.metadata)
            content_list.append(chunk.page_content)

        # 向量入库
        db_manager.add_documents(
            metadatas=metadata_list,
            collection_name=f"collection_kb_{knowledge_id}",
            documents=content_list,
            ids=[f"{file_id}_{i}" for i in range(len(content_list))]
        )

        # 更新状态为成功，写入分块数
        KnowledgeFileDao.update_state(
            file_id=file_id,
            state=FileState.SUCCESS.value,
            chunks_counts=len(content_list),
        )
        logger.info(f"[知识库解析] 成功 file_id={file_id}, chunks={len(content_list)}")

    except Exception as e:
        logger.exception(f"[知识库解析] 失败 file_id={file_id}")
        # 更新状态为失败，保存失败原因供前端展示
        try:
            KnowledgeFileDao.update_state(
                file_id=file_id,
                state=FileState.FAILED.value,
                fail_reason=str(e)[:1000],  # 截断，避免超长异常信息撑爆字段
            )
        except Exception as update_err:
            logger.error(f"[知识库解析] 写入失败状态时再次出错 file_id={file_id}: {update_err}")

    finally:
        # 无论成功/失败，都清理临时上传文件
        try:
            if file_path and os.path.exists(file_path):
                os.remove(file_path)
                logger.info(f"[知识库解析] 已清理临时文件：{file_path}")
        except Exception as e:
            logger.warning(f"[知识库解析] 清理临时文件失败：{e}")

