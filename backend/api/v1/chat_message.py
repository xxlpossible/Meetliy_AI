import json
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Body, Depends
from api.schemas import resp_200
from database.models.chatmessage import ChatMessageDao, ChatMessage
from database.models.user import User
from database.schemas.schema import UserQA, ChatMessageQuery, ChatMessageAdd, ChatMessageUpdate, UserTempQA
from service.llm_service import llm_service
from service.rerank import rerank
from service.llm_graph_service import stream_chat_answer
from fastapi.responses import StreamingResponse
from fastapi import WebSocket, WebSocketDisconnect, Query
from loguru import logger
from utils.dependencies import get_current_user
from utils.security import TOKEN_TYPE_ACCESS, decode_token
from utils.siliconflow_embedding import db_manager
import asyncio
router = APIRouter(prefix='/chat', tags=['chat'])


@router.post('/question', summary="用户提问")
async def user_qa(body: UserQA, current_user: User = Depends(get_current_user)):
    task_id = body.task_id
    question = body.question
    collection_name = f"collection_{task_id}"
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
async def chat_stream(
    websocket: WebSocket,
    task_id: str,
    token: Optional[str] = Query(None)
):
    # === 第一步：Token 认证 ===
    # WebSocket 无法返回标准 401，采用自定义关闭码 4401 表示认证失败
    if not token:
        await websocket.accept()
        await websocket.close(code=4401)
        logger.warning("🔒 WebSocket 连接因未提供 Token 被拒绝")
        return
    try:
        decode_token(token, expected_type=TOKEN_TYPE_ACCESS)
    except HTTPException:
        await websocket.accept()
        await websocket.close(code=4401)
        logger.warning("🔒 WebSocket 连接因 Token 无效或过期被拒绝")
        return

    # === 第二步：接受连接 ===
    await websocket.accept()
    client_info = f"{websocket.client.host}:{websocket.client.port}"
    logger.info(f"🎧 WebSocket 连接已建立（客户端: {client_info}，task_id: {task_id}）")

    # === 第三步：设置超时和消息循环 ===
    try:
        while True:
            try:
                # asyncio.wait_for 对 awaitable 进行超时控制是正确用法：
                # 超时会抛出 asyncio.TimeoutError，捕获后主动关闭连接
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

            # === 业务逻辑：调用 llm_graph_service 流式回答 ===
            # stream_chat_answer 内部完成：检索 -> 重排 -> LangGraph 流式对话，
            # 并通过 websocket 按协议推送 start / streaming / done / error 帧
            question = data.get('text') if isinstance(data, dict) else None
            if not question or not str(question).strip():
                await websocket.send_json({"status": "error", "message": "问题不能为空"})
                continue

            try:
                await stream_chat_answer(websocket, str(question).strip(), task_id)
            except WebSocketDisconnect:
                # 客户端在生成过程中断开，向上抛出以退出循环
                raise
            except Exception as e:
                logger.error(f"❌ 处理用户问题失败: {e}", exc_info=True)
                # 单轮失败不影响后续对话，继续等待下一条消息
                await websocket.send_json({"status": "error", "message": f"处理失败: {e}"})

    except WebSocketDisconnect:
        logger.info("❎ WebSocket 客户端主动断开连接")
    except Exception as e:
        logger.error(f"❌ WebSocket 异常: {e}", exc_info=True)
    finally:
        # 确保连接关闭（幂等操作，重复调用安全）
        await websocket.close()
        logger.info("🧹 WebSocket 连接已清理关闭")


@router.post('/temp/question', description="临时对话")
async def temp_chat(body: UserTempQA, current_user: User = Depends(get_current_user)):
    async def stream_response():
        """生成流式响应"""

        # 使用 llm_service 流式生成回答
        async for chunk in llm_service.stream_answer(body.text, body.question, chat_history=body.history):
            yield chunk

    # 流式输出
    generator = stream_response()
    return StreamingResponse(generator, media_type="text/event-stream")


@router.post('/list', summary="获取聊天记录列表")
async def get_chat_message_list(body: ChatMessageQuery, current_user: User = Depends(get_current_user)):
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
async def insert_chat_message(chat_message: ChatMessageAdd, current_user: User = Depends(get_current_user)):
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
async def update_message(chat_message: ChatMessageUpdate, current_user: User = Depends(get_current_user)):
    chat = ChatMessageDao.get_chat_by_chat_id(
        chat_id=chat_message.chat_id
    )
    if chat is None:
        raise HTTPException(status_code=500, detail="未查询到该聊天")
    chat.chat_messages = chat_message.chat_messages
    ChatMessageDao.update(chat)
    return resp_200()

