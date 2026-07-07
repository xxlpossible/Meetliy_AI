import json
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Body
from api.schemas import resp_200
from database.models.chatmessage import ChatMessageDao, ChatMessage
from database.schemas.schema import UserQA, ChatMessageQuery, ChatMessageAdd, ChatMessageUpdate, UserTempQA
from service.llm_service import llm_service
from service.rerank import rerank
from fastapi.responses import StreamingResponse
from fastapi import WebSocket, WebSocketDisconnect, Query
from loguru import logger
from utils.siliconflow_embedding import db_manager
import asyncio
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


@router.websocket("/ws/chat")
async def audio_to_text(
    websocket: WebSocket,
    task_id: str,
    token: Optional[str] = Query(None)
):
    # # === 第一步：认证 ===
    #     # if not verify_token(token):
    #     #     await websocket.close(code=4003)  # 自定义关闭码：认证失败
    #     #     logger.warning("🔒 WebSocket 连接因认证失败被拒绝")
    #     return

    # === 第二步：接受连接 ===
    await websocket.accept()
    client_info = f"{websocket.client.host}:{websocket.client.port}"
    logger.info(f"🎧 WebSocket 连接已建立（客户端: {client_info}）")

    # === 第三步：设置超时和消息循环 ===
    try:
        while True:
            try:
                # 设置对话超时 自动断开连接
                # TODO 这里需要判断一下 使用asyncio.wait_for进行异步函数的超时判断是否正确
                data = await asyncio.wait_for(
                    websocket.receive_json(),
                    timeout=30
                )
            except asyncio.TimeoutError:
                logger.info(f"⏰ WebSocket 连接超时（{30} 秒无消息），自动关闭")
                await websocket.close(code=4000)  # 自定义关闭码：超时
                break

            # 检查是否为关闭指令
            if isinstance(data, dict) and data.get("type") == "close":
                logger.info("👋 收到客户端主动关闭请求")
                break

            # === 你具体的业务逻辑===
            # 注意：这里应是非阻塞或异步处理，避免卡住 WebSocket 循环
            # TODO 这里需要调用 llm_graph_service.py 中的业务执行函数，接收websocket连接以及用户question后，调用大模型流式返回模型回答
            question = data.get('text')
            model_response_chunk = "模型流式回答的文本片段"

            # 发送响应
            await websocket.send_json({"status": "success", "text": model_response_chunk})

    except WebSocketDisconnect:
        logger.info("❎ WebSocket 客户端主动断开连接")
    except Exception as e:
        logger.error(f"❌ WebSocket 异常: {e}", exc_info=True)
    finally:
        # 确保连接关闭（幂等操作，重复调用安全）
        await websocket.close()
        logger.info("🧹 WebSocket 连接已清理关闭")


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

