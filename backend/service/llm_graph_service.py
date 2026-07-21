"""
LangGraph 对话工作流

架构：
- 从多集合收集数据：会议内容集合、知识库集合、记忆集合
- 统一重排序
- 拼接上下文提示词
- 流式生成回答
- 存储聊天记录
"""
from typing import List, Dict, Tuple

from langchain_core.messages import AIMessageChunk

from langchain.chat_models import init_chat_model
from langchain_core.prompts import ChatPromptTemplate
from typing_extensions import TypedDict, Annotated
import operator
from loguru import logger
from langgraph.graph import StateGraph, START, END
from fastapi import WebSocket
from settings import settings
from utils.siliconflow_embedding import db_manager
from service.rerank import rerank
from service.context_builder import (
    append_history,
    get_next_turn_index,
    get_recent_history,
    persist_chat_message,
    retrieve_past_memory,
    build_context,
)


# State 定义 - 移除了 summary 字段
class ChatState(TypedDict):
    messages: Annotated[list, operator.add]
    question: str
    meeting_content: str
    kb_snippets: str
    session_id: str
    user_id: int
    turn_index: int


# Agent 封装
class ChatAgent:
    def __init__(self):
        qwen = settings.get_qwen_config()
        self.model = init_chat_model(
            model=qwen.get('model', "qwen3.5-flash"),
            model_provider="openai",
            api_key=qwen.get('api_key', None),
            base_url=qwen.get('base_url', "https://dashscope.aliyuncs.com/compatible-mode/v1")
        )
        self._agent = None

    # =========================
    # Nodes
    # =========================
    def _llm_call(self, state: dict):
        """
        LLM 调用节点
        
        使用 context_builder 构建完整的上下文提示词：
        - [Role & Policies]: 系统初始提示词
        - [Task]: 用户当前问题
        - [MEETING_CONTENT]: 从多个会议内容集合检索并重排序后的片段
        - [Evidence]: 从多个知识库集合检索并重排序后的片段
        - [Context]: 最近 3 轮对话 + 过往记忆
        """
        question = state.get('question', '')
        session_id = state.get('session_id', '')
        user_id = state.get('user_id', 0)
        
        # 解析会议内容片段
        meeting_content_list = []
        meeting_content_str = state.get('meeting_content', '')
        if meeting_content_str:
            meeting_content_list = [s.strip() for s in meeting_content_str.split('\n') if s.strip()]
        
        # 解析知识库片段
        kb_snippets_list = []
        kb_snippets_str = state.get('kb_snippets', '')
        if kb_snippets_str:
            kb_snippets_list = [s.strip() for s in kb_snippets_str.split('\n') if s.strip()]

        # 获取最近 3 轮历史对话
        recent_history = get_recent_history(session_id)
        
        # 获取该会话的过往记忆（排除近 3 轮，避免与 SESSION_HISTORY 重复）
        past_memory = retrieve_past_memory(
            user_id=user_id,
            question=question,
            session_id=session_id,
            n_results=5,
            current_turn_index=state.get('turn_index', 0),
        )

        # 构建完整上下文提示词
        full_prompt = build_context(
            question=question,
            meeting_content=meeting_content_list,
            kb_snippets=kb_snippets_list,
            recent_history=recent_history,
            past_memory=past_memory,
        )
        
        logger.info(f"✅ 构建上下文完成，session_id={session_id}, user_id={user_id}")

        prompt = ChatPromptTemplate.from_messages([
            ("user", full_prompt)
        ])

        prompt_value = prompt.invoke({})
        llm_message = self.model.invoke(prompt_value)
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
    async def stream_run(self, question: str, meeting_text: str, kb_text: str, session_id: str, user_id: int, turn_index: int = 0):
        """
        流式执行对话工作流，逐 token 产出大模型回答。
        """
        agent = await self.get_agent()
        try:
            async for chunk, metadata in agent.astream(
                {
                    "messages": [],
                    "question": question,
                    "meeting_content": meeting_text,
                    "kb_snippets": kb_text,
                    "session_id": session_id,
                    "user_id": user_id,
                    "turn_index": turn_index,
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
# 单例 & WebSocket 业务编排
# =========================
chat_agent = ChatAgent()

# turn_index 管理已迁移到 context_builder._SESSION_TURN_COUNTERS
# 通过 get_next_turn_index(session_id) 获取下一个轮次序号


async def _search_and_rerank_meeting(
    question: str,
    task_ids: List[str],
    top_k: int = 5
) -> str:
    """
    从多个会议内容集合搜索并统一重排序
    
    Args:
        question: 用户问题
        task_ids: 会议任务ID列表
        top_k: 返回的 top k 条结果
        
    Returns:
        重排序后的会议内容，用换行符连接
    """
    if not task_ids:
        return ""
    
    # 从多个 meeting 集合收集文档
    all_meeting_docs = []
    for t_id in task_ids:
        collection_name = f"collection_meeting_{t_id}"
        try:
            result = db_manager.search(
                collection_name=collection_name,
                query_text=question,
                n_results=20
            )
            docs = (result.get("documents") or [[]])[0]
            all_meeting_docs.extend([d for d in docs if d and isinstance(d, str) and d.strip()])
        except Exception as e:
            logger.warning(f"搜索会议集合 {collection_name} 失败: {e}")
    
    if not all_meeting_docs:
        return ""
    
    # 统一重排序
    try:
        reranked = await rerank.rerank_context(question, [all_meeting_docs], top_k=top_k)
        return "\n".join(reranked)
    except Exception as e:
        logger.error(f"会议内容重排序失败: {e}")
        return "\n".join(all_meeting_docs[:top_k])


async def _search_and_rerank_knowledge_base(
    question: str,
    knowledge_ids: List[str],
    top_k: int = 5
) -> str:
    """
    从多个知识库集合搜索并统一重排序
    
    Args:
        question: 用户问题
        knowledge_ids: 知识库ID列表
        top_k: 返回的 top k 条结果
        
    Returns:
        重排序后的知识库内容，用换行符连接
    """
    if not knowledge_ids:
        return ""
    
    # 从多个 knowledge 集合收集文档
    collection_docs = {}
    for kb_id in knowledge_ids:
        collection_name = f"collection_kb_{kb_id}"
        try:
            result = db_manager.search(
                collection_name=collection_name,
                query_text=question,
                n_results=20
            )
            docs = (result.get("documents") or [[]])[0]
            filtered = [d.strip() for d in docs if d and isinstance(d, str) and d.strip()]
            if filtered:
                collection_docs[collection_name] = filtered
        except Exception as e:
            logger.warning(f"搜索知识库集合 {collection_name} 失败: {e}")
    
    if not collection_docs:
        return ""
    
    # 多集合统一重排序
    try:
        reranked, _ = await rerank.rerank_multi_collection(
            question=question,
            collection_docs=collection_docs,
            top_k=top_k
        )
        return "\n".join(reranked)
    except Exception as e:
        logger.error(f"知识库内容重排序失败: {e}")
        # 失败时返回所有文档的前 top_k 条
        all_docs = []
        for docs in collection_docs.values():
            all_docs.extend(docs)
        return "\n".join(all_docs[:top_k])


async def stream_chat_answer(
    websocket: WebSocket,
    question: str,
    session_id: str,
    user_id: int = 0,
    task_ids: List[str] = None,
    need_kb: bool = False,
    knowledge_ids: List[str] = None
):
    """
    WebSocket 对话业务编排：
    用户输入 -> 多集合搜索（会议/知识库/记忆） -> 统一重排 -> 构建上下文 -> 流式生成 -> 存储消息
    
    消息协议：
        - {"status": "start",    "question": "..."}           开始生成
        - {"status": "streaming", "text": "token 片段"}        逐 token 推送
        - {"status": "done",      "text": "完整回答"}          生成完成
        - {"status": "error",     "message": "错误信息"}        异常
    
    Args:
        websocket: FastAPI WebSocket 连接
        question:  用户本轮问题
        session_id: 会话 ID（用于聊天记录存储和上下文管理）
        user_id:   用户 ID
        task_ids:  会议任务ID列表（对应集合 collection_meeting_{id}）
        need_kb:   是否查询知识库
        knowledge_ids: 知识库ID列表（对应集合 collection_kb_{id}）
    """
    task_ids = task_ids or []
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

    # === 1. 从多集合收集会议内容并重排序 ===
    meeting_text = ""
    if task_ids:
        try:
            meeting_text = await _search_and_rerank_meeting(question, task_ids, top_k=5)
        except Exception as e:
            logger.error(f"搜索会议内容失败: {e}", exc_info=True)
            await websocket.send_json({"status": "error", "message": f"搜索会议内容失败: {e}"})
            return

    # === 2. 从多集合收集知识库内容并重排序 ===
    kb_text = ""
    if need_kb and knowledge_ids:
        try:
            kb_text = await _search_and_rerank_knowledge_base(question, knowledge_ids, top_k=5)
        except Exception as e:
            logger.error(f"搜索知识库内容失败: {e}", exc_info=True)
            await websocket.send_json({"status": "error", "message": f"搜索知识库内容失败: {e}"})
            return

    # 如果没有会议内容也没有知识库内容，返回提示
    if not meeting_text and not kb_text:
        await websocket.send_json({"status": "error", "message": "未找到相关会议内容或知识库片段"})
        return

    # === 3. 通知前端开始流式回答 ===
    await websocket.send_json({"status": "start", "question": question})

    # === 4. LangGraph 流式生成回答 ===
    full_answer_parts: List[str] = []
    try:
        async for chunk in chat_agent.stream_run(
            question, meeting_text, kb_text, session_id=session_id, user_id=user_id, turn_index=user_turn_index
        ):
            full_answer_parts.append(chunk)
            await websocket.send_json({"status": "streaming", "text": chunk})

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
        
        await websocket.send_json({
            "status": "done",
            "text": full_answer
        })
    except Exception as e:
        logger.error(f"❌ 流式生成回答失败: {e}", exc_info=True)
        await websocket.send_json({
            "status": "error",
            "message": f"模型回答生成失败: {e}",
            "partial": "".join(full_answer_parts)
        })
