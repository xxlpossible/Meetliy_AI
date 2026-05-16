# task/tasks.py
from loguru import logger

from database.models.transcription import TranscriptionDao, Status
from langchain_pipeline.agent import MeetingAgent
from utils.chroma_db import chromadb_client
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
        # 构建完成工作流
        # complete_workflow = CompleteWorkflow()
        # 执行工作流 进行语音和文本处理
        # result = complete_workflow.process(audio_url=original_url)

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
            chromadb_client.get_or_create_collection(name=collection_name)
            logger.info(f"集合创建成功，集合名称：{collection_name}")
            # 结果向量化
            complete_text = result.get('complete_text', "")
            sentences = result.get('sentences', [])

            # 这里使用的是手写函数
            # chunks = chunk_text(complete_text)

            # 这里使用LangChain的标点符号递归分割器
            chunks = Splitter.split_documents([Document(page_content=complete_text)])
            chunk_page_contents = [chunk.page_content for chunk in chunks]
            sentences.extend(chunk_page_contents)

            logger.info("开始将数据存入集合")
            db_manager.add_documents(
                collection_name=collection_name,
                documents=sentences
            )
            # chromadb_client.add_documents(
            #     collection_name=collection_name,
            #     documents=sentences
            # )
    except Exception as e:
        logger.error(f"后台任务执行过程发生错误，请检查：{e}")


# 这个函数暂时弃用
def chunk_text(text, max_length=200, lookahead=200):
    """
    按 max_length 切分文本，但在切分点只往后寻找句末标点。
    找到标点就切，没有就按 max_length 切。
    """
    punctuation = set("。！？.!?；;…\n")
    chunks = []
    n = len(text)
    i = 0

    while i < n:
        # 剩余不足 max_length
        if n - i <= max_length:
            chunks.append(text[i:].strip())
            break

        tentative = i + max_length  # 基准切分点
        end_limit = min(n, tentative + lookahead)

        cut_pos = None
        for j in range(tentative, end_limit):
            if text[j] in punctuation:
                cut_pos = j + 1
                break

        # 如果找到标点就用标点，否则固定按 max_length 切
        end = cut_pos if cut_pos else tentative

        chunks.append(text[i:end].strip())
        i = end

    return chunks
