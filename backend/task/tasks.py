# task/tasks.py
import os

from loguru import logger

from database.models.transcription import TranscriptionDao, Status
from database.models.knowledge_file import KnowledgeFileDao, KnowledgeFile, FileState, KnowledgeType
from langchain_pipeline.agent import MeetingAgent
from utils.siliconflow_embedding import db_manager
from utils.splitter import Splitter
from utils.file_loader import FileLoader
from utils.markitdown_converter import get_knowledge_type
from .celery_app import celery_app
from langchain_core.documents import Document


@celery_app.task
def transcription(
        public_url: str = None,
        t_id: str = None
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
            # 集合命名为 collection_meeting_{t_id}，与知识库集合 collection_kb_{knowledge_id} 分开存储
            collection_name = f"collection_meeting_{t_id}"
            db_manager.get_or_create_collection(name=collection_name)
            logger.info(f"会议内容集合创建成功，集合名称：{collection_name}")
            # 结果向量化
            complete_text = result.get('complete_text', "")
            sentences = result.get('sentences', [])

            # 转录结果为纯文本（非 Markdown），不经过 MarkItDown 转换，
            # 故使用通用递归分块（按标点符号切分），而非 Markdown 结构化分块
            chunks = Splitter.split_documents([Document(page_content=complete_text)])
            chunk_page_contents = [chunk.page_content for chunk in chunks]
            sentences.extend(chunk_page_contents)

            logger.info("开始将会议内容存入集合")
            db_manager.add_documents(
                collection_name=collection_name,
                documents=sentences
            )
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

