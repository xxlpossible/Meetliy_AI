# task/tasks.py
from loguru import logger

from database.models.transcription import TranscriptionDao, Status
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
    except Exception as e:
        logger.error(f"后台任务执行过程发生错误，请检查：{e}")

