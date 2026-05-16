import json
import uuid
from fastapi import APIRouter, HTTPException
from api.schemas import resp_200
from database.models.chatmessage import ChatMessageDao, ChatMessage
from database.schemas.schema import UserQA, ChatMessageQuery, ChatMessageAdd, ChatMessageUpdate, UserTempQA
from service.llm_service import llm_service
from service.rerank import rerank
from fastapi.responses import StreamingResponse

from utils.siliconflow_embedding import db_manager

router = APIRouter(prefix='/chat', tags=['chat'])


@router.post('/question', summary="用户提问")
async def user_qa(body: UserQA):
    task_id = body.task_id
    question = body.question
    collection_name = f"collection_{task_id}"
    # TODO 后续可改为WebSocket接口 使用LangChain的ChatMessageHistory来管理记忆
    history = body.history

    async def stream_response():
        """生成流式响应"""
        try:
            # 进行初步检索
            search_result = db_manager.search(
                collection_name=collection_name,
                query_text=question,
                n_results=40
            )
        except Exception as e:
            yield json.dumps({"error": f"ChromaDB 查询失败: {e}"}) + "\n"
            return

        context_docs = search_result.get("documents", [[]])
        # 进行重排序
        reranked_docs = await rerank.rerank_context(question, context_docs, top_k=10)
        texts = [item['text'] for item in reranked_docs]
        context_text = "\n".join(texts) if texts else ""

        if not context_text.strip():
            yield json.dumps({"error": "未找到相关会议内容"}) + "\n"
            return

        # 使用 llm_service 流式生成回答
        async for chunk in llm_service.stream_answer(context_text, question, chat_history=history):
            yield chunk

    # 流式输出
    generator = stream_response()
    return StreamingResponse(generator, media_type="text/event-stream")


@router.post('/temp/question', description="临时对话")
async def temp_chat(body: UserTempQA):
    async def stream_response():
        """生成流式响应"""

        # 使用 llm_service 流式生成回答
        async for chunk in llm_service.stream_answer(body.text, body.question, chat_history=body.history):
            yield chunk

    # 流式输出
    generator = stream_response()
    return StreamingResponse(generator, media_type="text/event-stream")


@router.post('/list', summary="获取聊天记录列表")
async def get_chat_message_list(body: ChatMessageQuery):
    chat_messages, total = ChatMessageDao.get_list_by_task_id(
        task_id=body.task_id,
        page_size=body.page_size,
        page_num=body.page_num
    )
    data = {
        "items": chat_messages,
        "total": total
    }
    return resp_200(data=data)


@router.post('/add', summary="添加聊天记录")
async def insert_chat_message(chat_message: ChatMessageAdd):
    ChatMessageDao.add(
        ChatMessage(
            task_id=chat_message.task_id,
            user_id=chat_message.user_id,
            chat_messages=chat_message.chat_messages,
            chat_id=uuid.uuid4().hex
        )
    )
    return resp_200()


@router.post('/update', summary="更新聊天记录")
async def update_message(chat_message: ChatMessageUpdate):
    chat = ChatMessageDao.get_chat_by_chat_id(
        chat_id=chat_message.chat_id
    )
    if chat is None:
        raise HTTPException(status_code=500, detail="未查询到该聊天")
    chat.chat_messages = chat_message.chat_messages
    ChatMessageDao.update(chat)
    return resp_200()

