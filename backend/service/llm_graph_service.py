"""
LangGraph 对话工作流

架构（重构版）：
- RetrievalPipeline 统一编排多路检索（含查询分类、改写、相邻扩展、rerank）
- context_builder 构建 SystemMessage + HumanMessage（角色分离，无 TAG 泄漏）
- LangGraph 流式生成回答
- 四级降级兜底代替硬错误返回
- 存储聊天记录
"""

import operator
from typing import Annotated

from fastapi import WebSocket
from langchain.chat_models import init_chat_model
from langchain_core.messages import AIMessageChunk
from langgraph.graph import END, START, StateGraph
from loguru import logger
from typing_extensions import TypedDict

from service.context_builder import (
    append_history,
    build_context,
    get_next_turn_index,
    get_recent_history,
    persist_chat_message,
    retrieve_past_memory,
)
from service.retrieval_pipeline import RetrievalPipeline
from settings import settings


# State 定义（扩展版）
class ChatState(TypedDict):
    messages: Annotated[list, operator.add]
    question: str
    meeting_content: list[str]                # 改为列表，直接来自 RetrievalPipeline
    kb_snippets: str                          # 知识库检索结果文本
    session_id: str
    user_id: int
    turn_index: int
    query_type: str                           # 新增：概括性/细节性/行动项/数据性/unknown
    fallback_level: int                       # 新增：降级等级 0-3


# Agent 封装
class ChatAgent:
    def __init__(self):
        chat_model = settings.get_chat_model_config()
        self.model = init_chat_model(
            model=chat_model.get('model', "qwen3.5-flash"),
            model_provider="openai",
            api_key=chat_model.get('api_key', None),
            base_url=chat_model.get('base_url', "https://dashscope.aliyuncs.com/compatible-mode/v1")
        )
        self._agent = None

    # =========================
    # Nodes
    # =========================
    async def _llm_call(self, state: dict):
        """
        LLM 调用节点（重构版）

        使用 context_builder.build_context() 构建 SystemMessage + HumanMessage 列表：
        - SystemMessage: 角色定位 + 防泄漏指令 + 降级引导
        - HumanMessage:  条件组装的用户上下文（会议/知识库/历史/问题）
        """
        question = state.get('question', '')
        session_id = state.get('session_id', '')
        user_id = state.get('user_id', 0)
        fallback_level = state.get('fallback_level', 0)

        # 会议内容片段（已经是列表，直接使用）
        meeting_content_list: list[str] = state.get('meeting_content', []) or []

        # 知识库片段
        kb_snippets_list: list[str] = []
        kb_snippets_str = state.get('kb_snippets', '')
        if kb_snippets_str:
            kb_snippets_list = [s.strip() for s in kb_snippets_str.split('\n') if s.strip()]

        # 获取最近 3 轮历史对话
        recent_history = get_recent_history(session_id)

        # 获取该会话的过往记忆（排除近 3 轮）
        past_memory = retrieve_past_memory(
            user_id=user_id,
            question=question,
            session_id=session_id,
            n_results=5,
            current_turn_index=state.get('turn_index', 0),
        )

        # 构建 SystemMessage + HumanMessage（返回值改为消息列表）
        messages = build_context(
            question=question,
            meeting_content=meeting_content_list,
            kb_snippets=kb_snippets_list,
            recent_history=recent_history,
            past_memory=past_memory,
            fallback_level=fallback_level,
        )

        logger.info(
            f"✅ 构建上下文完成, session_id={session_id}, "
            f"user_id={user_id}, fallback_level={fallback_level}"
        )

        # 使用消息列表调用 LLM
        llm_message = await self.model.ainvoke(messages)
        logger.info("✅ 调用大模型完成")

        return {
            "messages": [llm_message]
        }

    # =========================
    # Graph 构建
    # =========================
    def _build_graph(self):
        builder = StateGraph(ChatState)

        builder.add_node("llm_call", self._llm_call)

        builder.add_edge(START, "llm_call")
        builder.add_edge("llm_call", END)

        graph = builder.compile()
        return graph

    async def get_agent(self):
        """惰性构建并缓存编译图。"""
        if self._agent is None:
            self._agent = self._build_graph()
        return self._agent

    # =========================
    # 对外调用方法
    # =========================
    async def stream_run(
        self,
        question: str,
        meeting_snippets: list[str],
        kb_text: str,
        session_id: str,
        user_id: int,
        turn_index: int = 0,
        query_type: str = "unknown",
        fallback_level: int = 0,
    ):
        """
        流式执行对话工作流，逐 token 产出大模型回答。
        """
        agent = await self.get_agent()
        try:
            async for chunk, metadata in agent.astream(
                {
                    "messages": [],
                    "question": question,
                    "meeting_content": meeting_snippets,
                    "kb_snippets": kb_text,
                    "session_id": session_id,
                    "user_id": user_id,
                    "turn_index": turn_index,
                    "query_type": query_type,
                    "fallback_level": fallback_level,
                },
                stream_mode="messages"
            ):
                # 仅保留主回答节点 llm_call 的 AI token
                node = metadata.get("langgraph_node") if isinstance(metadata, dict) else None
                if node != "llm_call":
                    continue
                if not isinstance(chunk, AIMessageChunk):
                    continue
                content = getattr(chunk, "content", None)
                if isinstance(content, str):
                    text = content
                elif isinstance(content, list):
                    text = "".join(
                        c.get("text", "") if isinstance(c, dict) else str(c)
                        for c in content
                    )
                else:
                    text = ""
                if text:
                    yield text
        except Exception as e:
            logger.error(f"❌ Graph 流式对话执行错误：{str(e)}", exc_info=True)
            raise
        finally:
            logger.info("✅ Agent 流式工作流执行结束")


# =========================
# 单例
# =========================
chat_agent = ChatAgent()
retrieval_pipeline = RetrievalPipeline(top_k=5)

# turn_index 管理已迁移到 context_builder._SESSION_TURN_COUNTERS
# 通过 get_next_turn_index(session_id) 获取下一个轮次序号


# ---------------------------------------------------------------------------
# 私有辅助：四级降级判定
# ---------------------------------------------------------------------------
def _determine_fallback_level(
    has_meeting: bool,
    has_kb: bool,
    has_history: bool,
) -> tuple[int, str | None]:
    """
    根据检索结果确定降级等级和用户提示语。

    Returns:
        (fallback_level, user_notice | None)
        fallback_level: 0=完整, 1=部分, 2=仅历史, 3=仅提示词
        user_notice: 需要告知用户的话（Level 0 时为 None）
    """
    if has_meeting or has_kb:
        if has_meeting and has_kb:
            return 0, None  # Level 0: 完整
        else:
            return 1, None  # Level 1: 部分（有其中一个就够）
    elif has_history:
        return 2, "未检索到相关会议记录，以下基于已有对话为您作答："
    else:
        return 3, "当前没有会议记录可供查询，请先选择会议的录音或转录结果，我才能帮您分析。"


# ---------------------------------------------------------------------------
# 核心编排：stream_chat_messages
# ---------------------------------------------------------------------------
async def stream_chat_messages(
    question: str,
    session_id: str,
    user_id: int = 0,
    meeting_ids: list[str] | None = None,
    need_kb: bool = False,
    knowledge_ids: list[str] | None = None
):
    """
    产出消息协议（与 WebSocket / SSE 共用）：
        - {"status": "start",    "question": "..."}            开始生成
        - {"status": "streaming", "text": "token 片段"}         逐 token 推送
        - {"status": "done",      "text": "完整回答"}           生成完成
        - {"status": "error",     "message": "错误信息"}         异常
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

    # === 1. 使用 RetrievalPipeline 统一检索 ===
    kb_ids_for_pipeline = knowledge_ids if need_kb else []
    meeting_snippets: list[str] = []
    kb_text = ""
    query_type = "unknown"

    try:
        retrieval_result = await retrieval_pipeline.retrieve(
            question=question,
            meeting_ids=meeting_ids,
            knowledge_ids=kb_ids_for_pipeline,
        )
        meeting_snippets = retrieval_result.get("meeting", [])
        kb_text = retrieval_result.get("kb", "")
        query_type = retrieval_result.get("query_type", "unknown")
    except Exception as e:
        logger.error(f"[stream_chat_messages] 检索失败: {e}", exc_info=True)
        yield {"status": "error", "message": f"检索失败: {e}"}
        return

    # === 2. 四级降级判定 ===
    has_meeting = len(meeting_snippets) > 0
    has_kb = bool(kb_text)
    has_history = bool(get_recent_history(session_id))

    fallback_level, user_notice = _determine_fallback_level(
        has_meeting=has_meeting,
        has_kb=has_kb,
        has_history=has_history,
    )
    logger.info(
        f"[stream_chat_messages] 降级等级={fallback_level}, "
        f"meeting={has_meeting}, kb={has_kb}, history={has_history}, "
        f"query_type={query_type}"
    )

    # === 3. 通知前端开始流式回答 ===
    yield {"status": "start", "question": question}

    # === 4. LangGraph 流式生成回答 ===
    full_answer_parts: list[str] = []

    # 降级 Level 2/3 时，先输出用户提示语
    if user_notice:
        full_answer_parts.append(user_notice)
        yield {"status": "streaming", "text": user_notice}

    try:
        async for chunk in chat_agent.stream_run(
            question=question,
            meeting_snippets=meeting_snippets,
            kb_text=kb_text,
            session_id=session_id,
            user_id=user_id,
            turn_index=user_turn_index,
            query_type=query_type,
            fallback_level=fallback_level,
        ):
            full_answer_parts.append(chunk)
            yield {"status": "streaming", "text": chunk}

        full_answer = "".join(full_answer_parts)

        # === 5. 将助手回答写入上下文 ===
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
            "text": full_answer
        }
    except Exception as e:
        logger.error(f"❌ 流式生成回答失败，失败原因：{e}")
        yield {
            "status": "error",
            "message": f"模型回答生成失败: {e}",
            "partial": "".join(full_answer_parts)
        }


async def stream_chat_answer(
    websocket: WebSocket,
    question: str,
    session_id: str,
    user_id: int = 0,
    meeting_ids: list[str] | None = None,
    need_kb: bool = False,
    knowledge_ids: list[str] | None = None
):
    """
    WebSocket 对话业务编排 — 薄适配层。

    将 stream_chat_answer 核心逻辑委托给 stream_chat_messages()，
    仅负责将消息通过 WebSocket 发送给前端。
    """
    async for msg in stream_chat_messages(
        question=question,
        session_id=session_id,
        user_id=user_id,
        meeting_ids=meeting_ids,
        need_kb=need_kb,
        knowledge_ids=knowledge_ids,
    ):
        await websocket.send_json(msg)
