from typing import List

from langchain_core.messages import HumanMessage, AIMessage, AIMessageChunk

from database.check_points import CheckpointerManager
from langchain.chat_models import init_chat_model
from langchain.messages import AnyMessage
from langchain_core.prompts import ChatPromptTemplate
from typing_extensions import TypedDict, Annotated
import operator
from loguru import logger
from langgraph.graph import StateGraph, START, END
from fastapi import WebSocket
from settings import settings
from utils.siliconflow_embedding import db_manager
from service.rerank import rerank


# State 定义
class ChatState(TypedDict):
    messages: Annotated[list[AnyMessage], operator.add]
    question: str
    meeting_content: str
    recent_messages: List[AnyMessage]
    summary: str


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
        self.sum_model = init_chat_model(
            model=qwen.get('model', "qwen3.5-flash"),
            model_provider="openai",
            api_key=qwen.get('api_key', None),
            base_url=qwen.get('base_url', "https://dashscope.aliyuncs.com/compatible-mode/v1")
        )
        # 编译图依赖异步 checkpointer（在 FastAPI lifespan 中初始化），
        # 故不能在模块导入时直接构建，延迟到首次调用（事件循环内）时完成
        self._agent = None

    # =========================
    # Nodes
    # =========================
    def _llm_call(self, state: dict):
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", "你是一个会议智能助理，需要基于给出的会议记录内容，相关知识库文件片段以及历史对话回答用户的问题."
                           "请确保答案简明、准确，并基于会议内容进行回答。在回答时需要考虑历史对话的上下文，保持对话的连贯性。"
                           "如果问题与历史对话相关，请结合历史信息给出一致的回答"),
                ("human", "用户问题: {question}"
                          "会议记录内容与知识库相关文件片段: {meeting_content}"
                          "最近的对话记录: {history}"
                          "过往的对话总结: {summary}")
            ]
        )

        prompt_value = prompt.invoke(
            {
                "question": state.get('question'),
                "history": state['recent_messages'],
                "meeting_content": state.get('meeting_content'),
                "summary": state.get('summary')
            }
        )
        llm_message = self.model.invoke(prompt_value)
        logger.info("✅ 调用大模型")
        return {
            "messages": [llm_message]
        }

    def _summary(self, state: ChatState):
        recent_messages = state['messages']
        summary = AIMessage("暂无对话总结")

        # 如果历史对话超过3轮（也就是6条Message）超过6条的部分需要做总结
        if len(recent_messages) > 6:
            recent_messages = state['messages'][-6:]
            old_messages = state["messages"][:-6]
            summary = self.sum_model.invoke(f"""
                总结以下历史对话：

                {old_messages}

                当前summary:
                {state["summary"]}
                """)
            logger.info(f"✅ 触发总结，总结内容为：{summary}")

        return {
            "summary": summary.content,
            "recent_messages": recent_messages
        }

    # =========================
    # Graph 构建
    # =========================
    def _build_graph(self, checkpointer):
        builder = StateGraph(ChatState)

        builder.add_node("summary", self._summary)
        builder.add_node("llm_call", self._llm_call)

        builder.add_edge(START, "summary")
        builder.add_edge("summary", "llm_call")

        builder.add_edge("llm_call", END)
        graph = builder.compile(
            checkpointer=checkpointer
        )
        return graph

    async def get_agent(self):
        """
        惰性构建并缓存编译图。

        编译图需绑定异步 checkpointer，而 checkpointer 在 FastAPI lifespan 中异步初始化，
        因此不能在模块导入时（__init__）直接构建，需在首次调用（事件循环内）时完成。
        """
        if self._agent is None:
            checkpointer = await CheckpointerManager.get_checkpointer()
            self._agent = self._build_graph(checkpointer)
        return self._agent

    # =========================
    # 对外调用方法 ✅
    # =========================
    async def stream_run(self, question: str, meeting_text: str, thread_id: str):
        """
        流式执行对话工作流，逐 token 产出大模型回答。

        基于 LangGraph 的 async astream + stream_mode="messages"：
        - stream_mode="messages" 拦截底层聊天模型的 token 流，逐 token 产出
          (AIMessageChunk, metadata) 元组；
        - 仅保留主回答节点 llm_call 的 AI token，过滤 summary 节点等中间产物，
          以及空内容（如思考模型的推理前导帧）；
        - 多轮记忆由 AsyncSqliteSaver checkpointer 基于 thread_id 自动维护。

        Args:
            question: 用户本轮问题
            meeting_text: 检索 + 重排后的会议内容 / 知识库片段上下文
            thread_id: 会话线程 ID（用于 checkpointer 隔离不同任务 / 会话的记忆）

        Yields:
            str: 模型回答的文本片段（token chunk）
        """
        config = {
            "configurable": {
                "thread_id": f"chat_{thread_id}"
            }
        }
        agent = await self.get_agent()
        try:
            async for chunk, metadata in agent.astream(
                {
                    "messages": [
                        HumanMessage(content=question)
                    ],
                    "question": question,
                    "meeting_content": meeting_text
                },
                config=config,
                stream_mode="messages"
            ):
                # stream_mode="messages" 产出 (MessageChunk, metadata) 元组
                # 仅保留主回答节点 llm_call 的 AI token，过滤 summary 节点等中间产物
                node = metadata.get("langgraph_node") if isinstance(metadata, dict) else None
                if node != "llm_call":
                    continue
                # 仅处理 AI 回复片段，跳过 HumanMessage 回显等
                if not isinstance(chunk, AIMessageChunk):
                    continue
                content = getattr(chunk, "content", None)
                if isinstance(content, str):
                    text = content
                elif isinstance(content, list):
                    # 兼容结构化 content（如带 tool_calls 的列表形式），拼接其中的文本部分
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
# 模块级单例：复用同一份模型客户端；编译图在首次 stream_run 时惰性构建（绑定异步 checkpointer）
chat_agent = ChatAgent()


async def stream_chat_answer(websocket: WebSocket, question: str, task_id: str):
    """
    WebSocket 对话业务编排：检索 -> 重排 -> LangGraph 流式对话 -> 通过 WebSocket 推送模型回答。

    该函数接收 WebSocket 连接与用户问题，按以下协议向前端推送 JSON 消息：
        - {"status": "start",    "question": "..."}           开始生成
        - {"status": "streaming", "text": "token 片段"}        逐 token 推送（多条）
        - {"status": "done",      "text": "完整回答"}          生成完成
        - {"status": "error",     "message": "错误信息"[, "partial": "..."]} 异常

    Args:
        websocket: FastAPI WebSocket 连接
        question:  用户本轮问题
        task_id:   任务 ID（用于定位知识库 collection_xxx 与 LangGraph 会话线程）
    """
    collection_name = f"collection_{task_id}"

    # === 1. 向量检索（ChromaDB） ===
    try:
        search_result = db_manager.search(
            collection_name=collection_name,
            query_text=question,
            n_results=20
        )
    except Exception as e:
        logger.error(f"❌ ChromaDB 检索失败: {e}", exc_info=True)
        await websocket.send_json({"status": "error", "message": f"知识库检索失败: {e}"})
        return

    context_docs = search_result.get("documents", [[]])

    # === 2. 重排序 ===
    try:
        reranked_docs = await rerank.rerank_context(question, context_docs, top_k=5)
    except Exception as e:
        logger.error(f"❌ 重排序失败: {e}", exc_info=True)
        await websocket.send_json({"status": "error", "message": f"重排序失败: {e}"})
        return

    reranked_docs = reranked_docs or []
    meeting_text = "\n".join(
        item.get("text", "") if isinstance(item, dict) else str(item)
        for item in reranked_docs
    ).strip()

    if not meeting_text:
        await websocket.send_json({"status": "error", "message": "未找到相关会议内容"})
        return

    # === 3. 通知前端开始流式回答 ===
    await websocket.send_json({"status": "start", "question": question})

    # === 4. LangGraph 流式生成回答，逐片段通过 WebSocket 推送 ===
    full_answer_parts: List[str] = []
    try:
        async for chunk in chat_agent.stream_run(question, meeting_text, thread_id=task_id):
            full_answer_parts.append(chunk)
            await websocket.send_json({"status": "streaming", "text": chunk})

        await websocket.send_json({
            "status": "done",
            "text": "".join(full_answer_parts)
        })
    except Exception as e:
        logger.error(f"❌ 流式生成回答失败: {e}", exc_info=True)
        # 已推送的内容保留在前端，这里补充一帧错误结束信息（含已生成部分便于前端兜底展示）
        await websocket.send_json({
            "status": "error",
            "message": f"模型回答生成失败: {e}",
            "partial": "".join(full_answer_parts)
        })
