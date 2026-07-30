"""ChatAgent —— RAG 对话 Agent。

工作流：START → Router → [meeting_retrieval, memory_retrieval, (knowledge_retrieval)]
→ context_builder → llm_call → END。
"""

from langchain.chat_models import init_chat_model
from langchain_core.messages import AIMessageChunk
from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import END, START, StateGraph
from loguru import logger

from agent.base import BaseAgent
from agent.chat.nodes.context_builder import _context_builder_node
from agent.chat.nodes.knowledge_retrieval import _knowledge_retrieval_node
from agent.chat.nodes.llm_generate import _make_llm_generate_node
from agent.chat.nodes.meeting_retrieval import _meeting_retrieval_node
from agent.chat.nodes.memory_retrieval import _memory_retrieval_node
from agent.chat.nodes.router import _make_router_node
from agent.chat.prompts.router import ROUTER_SYSTEM_PROMPT
from agent.chat.schemas import RouterOutput
from agent.chat.state import ChatState
from rag.retrieval_pipeline import RetrievalPipeline
from settings import settings


class ChatAgent(BaseAgent):

    def __init__(self):
        chat_model = settings.get_chat_model_config()
        self.model = init_chat_model(
            model=chat_model.get('model', "qwen3.5-flash"),
            model_provider="openai",
            api_key=chat_model.get('api_key', None),
            base_url=chat_model.get('base_url', "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        )
        logger.info(f"CHAT_MODEL:{chat_model.get('model')}")

        _router_cfg = settings.get_router_model_config()
        self.router_model = init_chat_model(
            model=_router_cfg.get('model', "qwen3.5-flash"),
            model_provider="openai",
            api_key=_router_cfg.get('api_key') or chat_model.get('api_key'),
            base_url=_router_cfg.get('base_url') or chat_model.get('base_url', "https://dashscope.aliyuncs.com/compatible-mode/v1"),
            temperature=0.1,
        ).with_structured_output(RouterOutput, method="json_mode")
        logger.info(f"ROUTER_MODEL:{_router_cfg.get('model')}")

        self.router_prompt = ChatPromptTemplate.from_messages([
            ("system", ROUTER_SYSTEM_PROMPT),
            ("human", "{question}"),
        ])

        self._agent = None
        self._retrieval_pipeline = RetrievalPipeline(top_k=15)

    def _build_graph(self) -> StateGraph:
        builder = StateGraph(ChatState)

        # meeting_retrieval 需要多传一个 retrieval_pipeline 参数，
        # 必须用 async wrapper 来 await，sync lambda 会返回 coroutine 而非 dict
        async def _meeting_retrieval_wrapper(state: ChatState) -> dict:
            return await _meeting_retrieval_node(state, self._retrieval_pipeline)

        builder.add_node("router", _make_router_node(self.router_model, self.router_prompt))
        builder.add_node("knowledge_retrieval", _knowledge_retrieval_node)
        builder.add_node("memory_retrieval", _memory_retrieval_node)
        builder.add_node("meeting_retrieval", _meeting_retrieval_wrapper)
        builder.add_node("context_builder", _context_builder_node)
        builder.add_node("llm_call", _make_llm_generate_node(self.model))

        builder.add_edge(START, "router")

        def _route_from_router(state: ChatState) -> list[str]:
            targets: list[str] = ["meeting_retrieval", "memory_retrieval"]
            if state.get("need_kb", False):
                targets.append("knowledge_retrieval")
            return targets

        builder.add_conditional_edges("router", _route_from_router)

        builder.add_edge("knowledge_retrieval", "context_builder")
        builder.add_edge("memory_retrieval", "context_builder")
        builder.add_edge("meeting_retrieval", "context_builder")

        builder.add_edge("context_builder", "llm_call")
        builder.add_edge("llm_call", END)

        return builder.compile()

    async def get_agent(self):
        if self._agent is None:
            self._agent = self._build_graph()
        return self._agent

    async def stream_run(
        self,
        question: str,
        meeting_ids: list[str],
        knowledge_ids: list[str],
        session_id: str,
        user_id: int,
        need_kb: bool = False,
        turn_index: int = 0,
    ):
        """流式执行对话工作流，逐 token 产出大模型回答。"""
        agent = await self.get_agent()
        try:
            async for chunk, metadata in agent.astream(
                {
                    "messages": [],
                    "question": question,
                    "meeting_ids": meeting_ids or [],
                    "knowledge_ids": knowledge_ids or [],
                    "session_id": session_id,
                    "user_id": user_id,
                    "need_kb": need_kb,
                    "turn_index": turn_index,
                    "meeting_content": [],
                    "kb_snippets": "",
                    "memory_content": [],
                    "query_type": "细节性",
                    "fallback_level": 0,
                    "router_result": None,
                    "user_notice": "",
                },
                stream_mode="messages",
            ):
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
            logger.error(f"[ChatAgent] Graph 流式对话执行错误：{str(e)}", exc_info=True)
            raise
        finally:
            logger.info("[ChatAgent] Agent 流式工作流执行结束")


# 全局单例
chat_agent = ChatAgent()
retrieval_pipeline = RetrievalPipeline(top_k=15)
