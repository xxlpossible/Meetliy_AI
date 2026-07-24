import json
import re
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Depends
from api.schemas import resp_200
from database.models.chatmessage import ChatMessageDao, ChatMessage
from database.models.chat_session import ChatSession, ChatSessionDao
from database.models.user import User
from database.schemas.schema import (
    UserQA, ChatMessageQuery, ChatMessageAdd,
    ChatMessageUpdate, UserTempQA, ChatSSERequest
)
from service.llm_service import llm_service
from service.llm_graph_service import stream_chat_answer, stream_chat_messages
from fastapi.responses import StreamingResponse
from fastapi import WebSocket, WebSocketDisconnect, Query
from loguru import logger
from utils.dependencies import get_current_user
from utils.security import TOKEN_TYPE_ACCESS, decode_token
import asyncio

router = APIRouter(prefix='/chat', tags=['chat'])


def _generate_session_name(question: str) -> str:
    """
    根据用户第一条问题生成会话名称。
    
    规则：
    - 去除首尾空白
    - 过滤特殊字符，仅保留中文、英文、数字、空格
    - 截取前 20 个字符，超出部分加省略号
    """
    if not question:
        return "新会话"
    
    # 去除首尾空白
    cleaned = question.strip()
    # 过滤特殊字符（仅保留中文、英文、数字、空格）
    cleaned = re.sub(r'[^\u4e00-\u9fa5a-zA-Z0-9\s]', '', cleaned)
    # 去除多余空白
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    
    if not cleaned:
        return "新会话"
    
    # 截取前 20 个字符
    max_len = 20
    if len(cleaned) <= max_len:
        return cleaned
    return cleaned[:max_len] + "…"


# 该接口已经弃用，使用下面的WebSocket接口进行AI对话
@router.post('/question', summary="用户提问")
async def user_qa(body: UserQA, current_user: User = Depends(get_current_user)):
    task_id = body.task_id
    question = body.question
    collection_name = f"collection_{task_id}"
    history = body.history

    async def stream_response():
        """生成流式响应"""
        try:
            from utils.siliconflow_embedding import db_manager
            from service.rerank import rerank
            search_result = db_manager.search(
                collection_name=collection_name,
                query_text=question,
                n_results=40
            )
        except Exception as e:
            yield json.dumps({"error": f"ChromaDB 查询失败: {e}"}) + "\n"
            return

        context_docs = search_result.get("documents", [[]])
        reranked_docs = await rerank.rerank_context(question, context_docs, top_k=10)
        texts = [item['text'] for item in reranked_docs]
        context_text = "\n".join(texts) if texts else ""

        if not context_text.strip():
            yield json.dumps({"error": "未找到相关会议内容"}) + "\n"
            return

        async for chunk in llm_service.stream_answer(context_text, question, chat_history=history):
            yield chunk

    generator = stream_response()
    return StreamingResponse(generator, media_type="text/event-stream")


@router.websocket("/ws/chat")
async def chat_stream(
    websocket: WebSocket,
    session_id: str,
    task_ids: Optional[str] = Query(None),
    need_kb: Optional[bool] = Query(False),
    knowledge_ids: Optional[str] = Query(None),
    token: Optional[str] = Query(None)
):
    """
    WebSocket 聊天接口。
    
    每次调用代表开启一个新会话（由前端传入 session_id）。
    首次收到消息时，如果 session 不存在则自动创建 ChatSession 记录。
    
    参数：
    - task_ids: 多个会议任务ID，用逗号分隔（如 "id1,id2,id3"），对应会议内容集合 collection_meeting_{id}
    - need_kb: 是否需要查询知识库
    - knowledge_ids: 知识库ID列表，用逗号分隔（如 "kb1,kb2"），对应知识库集合 collection_kb_{id}
    - token: 认证 token
    
    集合命名规则：
    - 会议内容：collection_meeting_{task_id}
    - 知识库：collection_kb_{knowledge_id}
    - 记忆：chat_memory_{user_id}
    """
    # === 第一步：Token 认证 ===
    if not token:
        await websocket.accept()
        await websocket.close(code=4401)
        logger.warning("🔒 WebSocket 连接因未提供 Token 被拒绝")
        return
    try:
        payload = decode_token(token, expected_type=TOKEN_TYPE_ACCESS)
    except HTTPException:
        await websocket.accept()
        await websocket.close(code=4401)
        logger.warning("🔒 WebSocket 连接因 Token 无效或过期被拒绝")
        return
    
    user_id = payload.get("user_id")
    
    # 解析 task_ids 和 knowledge_ids
    task_id_list = [t.strip() for t in task_ids.split(",") if t.strip()] if task_ids else []
    knowledge_id_list = [k.strip() for k in knowledge_ids.split(",") if k.strip()] if knowledge_ids else []

    # === 第二步：接受连接 ===
    await websocket.accept()
    client_info = f"{websocket.client.host}:{websocket.client.port}"
    logger.info(f"🎧 WebSocket 连接已建立（客户端: {client_info}，session_id: {session_id}，task_ids: {task_id_list}，need_kb: {need_kb}，knowledge_ids: {knowledge_id_list}）")

    # === 第三步：设置超时和消息循环 ===
    session_created = False
    try:
        while True:
            try:
                data = await asyncio.wait_for(
                    websocket.receive_json(),
                    timeout=300
                )
            except asyncio.TimeoutError:
                logger.info(f"⏰ WebSocket 连接超时（{300} 秒无消息），自动关闭")
                await websocket.close(code=4000)
                break

            if isinstance(data, dict) and data.get("type") == "close":
                logger.info("👋 收到客户端主动关闭请求")
                break

            question = data.get('text') if isinstance(data, dict) else None
            if not question or not str(question).strip():
                await websocket.send_json({"status": "error", "message": "问题不能为空"})
                continue

            # 首次收到有效消息时，自动创建 Session
            if not session_created:
                existing = ChatSessionDao.get_by_session_id(session_id=session_id)
                if existing is None:
                    session_name = _generate_session_name(str(question).strip())
                    ChatSessionDao.add(ChatSession(
                        session_id=session_id,
                        session_name=session_name,
                        user_id=user_id,
                        task_ids=task_id_list,
                        knowledge_ids=knowledge_id_list,
                        need_kb=need_kb,
                    ))
                    logger.info(f"🎯 自动创建会话: session_id={session_id}, name={session_name}")
                session_created = True

            try:
                await stream_chat_answer(
                    websocket, str(question).strip(), 
                    session_id=session_id, user_id=user_id,
                    task_ids=task_id_list,
                    need_kb=need_kb,
                    knowledge_ids=knowledge_id_list
                )
            except WebSocketDisconnect:
                raise
            except Exception as e:
                logger.error("❌ 处理用户问题失败", exc_info=True)
                await websocket.send_json({"status": "error", "message": f"处理失败: {e}"})

    except WebSocketDisconnect:
        logger.info("❎ WebSocket 客户端主动断开连接")
    except Exception as e:
        logger.error("❌ WebSocket 异常", exc_info=True)
    finally:
        await websocket.close()
        logger.info("🧹 WebSocket 连接已清理关闭")


@router.post('/sse/chat', summary="SSE 流式聊天")
async def chat_sse(
    body: ChatSSERequest,
    current_user: User = Depends(get_current_user)
):
    """
    SSE 事件流：
    - event: start     data: {"question": "..."}
    - event: streaming data: {"text": "token 片段"}
    - event: done      data: {"text": "完整回答"}
    - event: error     data: {"message": "错误信息", "partial": "..."}
    """
    task_ids = body.task_ids or []
    knowledge_ids = body.knowledge_ids or []
    user_id = current_user.id
    
    # 首次收到消息时，自动创建 Session
    existing = ChatSessionDao.get_by_session_id(session_id=body.session_id)
    if existing is None:
        session_name = _generate_session_name(body.question)
        ChatSessionDao.add(ChatSession(
            session_id=body.session_id,
            session_name=session_name,
            user_id=user_id,
            task_ids=task_ids,
            knowledge_ids=knowledge_ids,
            need_kb=body.need_kb,
        ))
        logger.info(f"🎯会话开始 SSE自动创建会话: session_id={body.session_id}, name={session_name}")
    
    async def event_generator():
        """将核心对话逻辑的消息转换为 SSE 格式"""
        async for msg in stream_chat_messages(
            question=body.question,
            session_id=body.session_id,
            user_id=user_id,
            task_ids=task_ids,
            need_kb=body.need_kb,
            knowledge_ids=knowledge_ids,
        ):
            status = msg.get('status', 'unknown')
            yield f"event: {status}\ndata: {json.dumps(msg, ensure_ascii=False)}\n\n"
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 禁用 Nginx 缓冲
        }
    )


@router.post('/temp/question', description="临时对话")
async def temp_chat(body: UserTempQA, current_user: User = Depends(get_current_user)):
    async def stream_response():
        async for chunk in llm_service.stream_answer(body.text, body.question, chat_history=body.history):
            yield chunk

    generator = stream_response()
    return StreamingResponse(generator, media_type="text/event-stream")


@router.post('/list', summary="获取聊天记录列表")
async def get_chat_message_list(
    body: ChatMessageQuery,
    current_user: User = Depends(get_current_user)
):
    """
    分页查询指定会话的聊天记录。
    
    安全过滤：仅返回当前用户有权访问的消息（session_id + user_id 双重过滤）。
    排序方式：按 turn_index 升序（对话时间线），便于前端直接遍历渲染。
    
    前端回显建议：
    - 直接遍历 items 数组，根据 role 区分左右气泡（user 右侧，assistant 左侧）
    - turn_index 严格递增，前端无需二次排序
    - total 用于分页判断，is_last_page = (page_num * page_size >= total)
    """
    if not body.session_id:
        raise HTTPException(status_code=400, detail="session_id 不能为空")

    messages, total = ChatMessageDao.get_session_messages(
        session_id=body.session_id,
        user_id=current_user.id,
        page_num=body.page_num,
        page_size=body.page_size,
    )

    return resp_200(data={
        "items": messages,
        "total": total,
        "session_id": body.session_id,
    })


@router.post('/add', summary="添加单条聊天记录")
async def insert_chat_message(chat_message: ChatMessageAdd, current_user: User = Depends(get_current_user)):
    """
    添加一条聊天记录（用户输入或助手输出）。
    
    - session_id: 会话ID（由前端生成）
    - role: user / assistant
    - content: 消息内容
    - turn_index: 轮次序号
    """
    from service.context_builder import persist_chat_message
    
    # 写入 MySQL + Chroma（通过 context_builder 统一处理）
    persist_chat_message(
        session_id=chat_message.session_id,
        user_id=current_user.id,
        role=chat_message.role,
        content=chat_message.content,
        turn_index=chat_message.turn_index,
    )
    
    return resp_200()


@router.post('/update', summary="更新聊天记录")
async def update_message(chat_message: ChatMessageUpdate, current_user: User = Depends(get_current_user)):
    chat = ChatMessageDao.get_chat_by_chat_id(
        chat_id=chat_message.chat_id,
        user_id=current_user.id
    )
    if chat is None:
        raise HTTPException(status_code=403, detail="无权操作或未查询到该聊天")
    chat.content = chat_message.content
    ChatMessageDao.update(chat)
    return resp_200()


@router.delete('/delete', summary="删除聊天记录")
async def delete_message(chat_id: int, current_user: User = Depends(get_current_user)):
    deleted = ChatMessageDao.delete(chat_id=chat_id, user_id=current_user.id)
    if not deleted:
        raise HTTPException(status_code=403, detail="无权操作或未查询到该聊天")
    return resp_200(message="删除成功")
