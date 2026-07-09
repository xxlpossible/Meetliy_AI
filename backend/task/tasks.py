# task/tasks.py
from loguru import logger

from database.models.transcription import TranscriptionDao, Status
from database.models.knowledge import Knowledge, KnowledgeDao
from langchain_pipeline.agent import MeetingAgent
from utils.siliconflow_embedding import db_manager
from utils.splitter import Splitter
from .celery_app import celery_app
from langchain_core.documents import Document


@celery_app.task
def transcription(
        public_url: str = None,
        t_id: str = None
):
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
            logger.error(f"后台任务执失败，执行过程出错，报错信息：{result.get('error_message', 'ERROR')}")
            task.status = Status.ERROR.value

        # 对数据库进行更新
        TranscriptionDao.update(task)
        if result.get('status') == 'complete':
            # 将识别结果转换为向量 并创建集合 存入向量数据库
            collection_name = f"collection_{t_id}"
            db_manager.get_or_create_collection(name=collection_name)
            logger.info(f"集合创建成功，集合名称：{collection_name}")
            # 结果向量化
            complete_text = result.get('complete_text', "")
            sentences = result.get('sentences', [])

            # 转录结果为纯文本（非 Markdown），不经过 MarkItDown 转换，
            # 故使用通用递归分块（按标点符号切分），而非 Markdown 结构化分块
            chunks = Splitter.split_documents([Document(page_content=complete_text)])
            chunk_page_contents = [chunk.page_content for chunk in chunks]
            sentences.extend(chunk_page_contents)

            logger.info("开始将数据存入集合")
            db_manager.add_documents(
                collection_name=collection_name,
                documents=sentences
            )

            # 创建 Knowledge 知识库实体，使会议文本集合有元信息归属与权限控制。
            # knowledge_id 与 task_id 一致（collection_{t_id} 对应此知识库），
            # user_ids 继承自转录任务（会议参与者在 upload 时已绑定），保证有权用户可访问。
            if KnowledgeDao.get_by_id(k_id=t_id) is None:
                KnowledgeDao.add(Knowledge(
                    id=t_id,
                    name=task.task_name or f"会议转录-{t_id[:8]}",
                    description="语音转录任务完成后自动生成的会议知识库",
                    user_ids=list(task.user_ids or []),
                ))
                logger.info(f"Knowledge 知识库实体已创建，id={t_id}")
            else:
                # 已存在则同步更新 user_ids（转录任务可能后续放权）
                existing = KnowledgeDao.get_by_id(k_id=t_id)
                existing.user_ids = list(task.user_ids or [])
                existing.name = task.task_name or existing.name
                KnowledgeDao.update(existing)
                logger.info(f"Knowledge 知识库实体已更新，id={t_id}")
    except Exception as e:
        logger.error(f"后台任务执行过程发生错误，请检查：{e}")

