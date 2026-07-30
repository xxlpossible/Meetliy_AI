"""对话服务编排 —— ChatAgent 调用 + 消息持久化 + 流式输出。"""

from loguru import logger

from agent.chat.agent import chat_agent
from rag.memory import (
    append_history,
    get_next_turn_index,
    persist_chat_message,
)


async def stream_chat_messages(
    question: str,
    session_id: str,
    user_id: int = 0,
    meeting_ids: list[str] | None = None,
    need_kb: bool = False,
    knowledge_ids: list[str] | None = None,
):
    """
    产出消息协议（与 WebSocket / SSE 共用）：
        - {"status": "start",    "question": "..."}            开始生成
        - {"status": "streaming", "text": "token 片段"}        逐 token 推送
        - {"status": "done",      "text": "完整回答"}          生成完成
        - {"status": "error",     "message": "错误信息"}       异常
    """
    meeting_ids = meeting_ids or []
    knowledge_ids = knowledge_ids or []

    # === 0. 将用户输入写入上下文（内存 + MySQL + Chroma） ===
    user_turn_index = get_next_turn_index(session_id)
    append_history(session_id, "user", question)
    persist_chat_message(
        session_id=session_id,
        user_id=user_id,
        role="user",
        content=question,
        turn_index=user_turn_index,
    )

    # === 1. 通知前端开始流式回答 ===
    yield {"status": "start", "question": question}

    # === 2. LangGraph 工作流（检索 + Context_Builder + LLM） ===
    full_answer_parts: list[str] = []

    try:
        async for chunk in chat_agent.stream_run(
            question=question,
            meeting_ids=meeting_ids,
            knowledge_ids=knowledge_ids,
            session_id=session_id,
            user_id=user_id,
            need_kb=need_kb,
            turn_index=user_turn_index,
        ):
            full_answer_parts.append(chunk)
            yield {"status": "streaming", "text": chunk}

        full_answer = "".join(full_answer_parts)

        # === 3. 将助手回答写入上下文 ===
        assistant_turn_index = get_next_turn_index(session_id)
        append_history(session_id, "assistant", full_answer)
        persist_chat_message(
            session_id=session_id,
            user_id=user_id,
            role="assistant",
            content=full_answer,
            turn_index=assistant_turn_index,
        )

        yield {
            "status": "done",
            "text": full_answer,
        }
    except Exception as e:
        logger.error(f"[stream_chat_messages] 流式生成回答失败：{e}")
        yield {
            "status": "error",
            "message": f"模型回答生成失败: {e}",
            "partial": "".join(full_answer_parts),
        }
