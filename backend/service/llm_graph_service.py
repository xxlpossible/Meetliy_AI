"""
LangGraph 对话工作流

架构：
- START → Router 节点: 结构化输出判断用户问题类型、提取 keywords/speaker/topic
- Router → 三路并行检索（keywords 指导各检索节点）:
  - meeting_retrieval   (固定边)
  - memory_retrieval    (固定边)
  - knowledge_retrieval (条件边: need_kb=True 时进入)
- context_builder: 汇合三路检索结果，判定降级等级
- llm_call:  构建 SystemMessage + HumanMessage，流式生成回答
- 四级降级兜底代替硬错误返回
- 存储聊天记录
"""

import operator
from typing import Annotated, Literal

from langchain.chat_models import init_chat_model
from langchain_core.messages import AIMessageChunk
from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import END, START, StateGraph
from loguru import logger
from pydantic import BaseModel, Field
from typing_extensions import TypedDict

from service.context_builder import (
    append_history,
    build_context,
    get_next_turn_index,
    get_recent_history,
    persist_chat_message,
    retrieve_past_memory,
)
from service.retrieval_pipeline import RetrievalPipeline, expand_adjacent_chunks
from service.rerank import rerank
from settings import settings
from utils.siliconflow_embedding import db_manager


# ============================================================================
# Router 结构化输出模型
# ============================================================================
class RouterOutput(BaseModel):
    """Router 节点结构化输出 —— 分析用户提问的类型、检索目标和过滤条件。"""

    # 问题类型
    intent: Literal[
        "summary",    # 概括总结
        "action",     # 行动项 / 待办
        "topic",      # 主题 / 议题
        "detail",     # 细节 / 某人的观点 / 具体讨论
        "multi",      # 多类型混合
    ]

    # 检索过滤条件
    speaker: list[str] = Field(default_factory=list)      # 可能提到多个人
    topic: list[str] = Field(default_factory=list)         # 可能涉及多个话题
    keywords: list[str] = Field(default_factory=list)     # 关键检索词
    confidence: float = Field(ge=0, le=1)


# ============================================================================
# Router 系统提示
# ============================================================================
_ROUTER_SYSTEM_PROMPT = """你是会议分析系统的 Router，请以 JSON 格式输出分析结果。

你的职责：
1. 判断用户问题的主要意图（intent）
2. 提取过滤条件（speaker / topic / keywords）
3. 给出置信度（confidence）

## intent 定义
- "summary":    用户想了解会议整体内容、结论、关键决策
- "action":     用户想了解待办事项、任务分配、下一步计划
- "topic":      用户想了解会议讨论了哪些主题/议题
- "detail":     用户想知道某人说了什么、某个具体议题的讨论过程
- "multi":      问题涉及多个维度，需要综合检索

## 规则
- speaker:  用户提到的人名列表（如["张三", "李经理"]），如果没提到则为空列表 []
- topic:    用户涉及的话题列表（如["预算", "产品发布"]），如果没提到则为空列表 []
- keywords: 提取关键检索词（3-5个），用于后续向量检索
- confidence: 你对分类的把握程度（0-1）
- 所有列表字段即使为空也必须返回 []，不要返回 null
"""


# ============================================================================
# Router intent → 检索管道 query_type 映射
# ============================================================================
_INTENT_TO_QUERY_TYPE: dict[str, str] = {
    "summary":   "概括性",
    "action":    "行动项",
    "topic":     "概括性",
    "detail":    "细节性",
    "multi":     "细节性",
}


# ============================================================================
# State 定义
# ============================================================================
class ChatState(TypedDict):
    messages: Annotated[list, operator.add]
    question: str
    meeting_content: list[str]              # 会议检索结果
    kb_snippets: str                        # 知识库检索结果文本
    memory_content: list[str]               # 记忆库检索结果
    session_id: str
    user_id: int
    turn_index: int
    query_type: str                         # 会议检索用 query_type
    fallback_level: int                     # 降级等级 0-3
    need_kb: bool                           # 是否需要知识库检索（条件边）
    meeting_ids: list[str]                  # 会议 ID 列表
    knowledge_ids: list[str]                # 知识库 ID 列表
    router_result: dict | None              # Router 结构化输出（序列化为 dict）
    user_notice: str                        # 降级提示语


# ============================================================================
# ChatAgent
# ============================================================================
class ChatAgent:
    def __init__(self):
        chat_model = settings.get_chat_model_config()
        self.model = init_chat_model(
            model=chat_model.get('model', "qwen3.5-flash"),
            model_provider="openai",
            api_key=chat_model.get('api_key', None),
            base_url=chat_model.get('base_url', "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        )
        logger.info(f"CHAT_MODEL:{chat_model.get('model')}")

        # Router 模型：低温度 + 结构化输出（独立配置，需支持 function calling 的模型）
        _router_cfg = settings.get_router_model_config()
        self.router_model = init_chat_model(
            model=_router_cfg.get('model', "qwen3.5-flash"),
            model_provider="openai",
            api_key=_router_cfg.get('api_key') or chat_model.get('api_key'),
            base_url=_router_cfg.get('base_url') or chat_model.get('base_url', "https://dashscope.aliyuncs.com/compatible-mode/v1"),
            temperature=0.1,
        ).with_structured_output(RouterOutput, method="json_mode")
        logger.info(f"ROUTER_MODEL:{_router_cfg.get('model')}")

        # Router prompt 模板
        self.router_prompt = ChatPromptTemplate.from_messages([
            ("system", _ROUTER_SYSTEM_PROMPT),
            ("human", "{question}"),
        ])

        self._agent = None

    # =========================================================================
    # Node: Router —— 判断用户问题类型 + 过滤条件
    # =========================================================================
    async def _router_node(self, state: dict) -> dict:
        """
        Router 节点：使用 structured output 分析用户问题，
        输出 intent、retrieve_sources 和过滤条件。
        """
        question = state.get('question', '')
        session_id = state.get('session_id', '')

        router_result: dict = {}
        try:
            messages = self.router_prompt.format_messages(question=question)
            result: RouterOutput = await self.router_model.ainvoke(messages)

            router_result = {
                "intent": result.intent,
                "speaker": result.speaker,
                "topic": result.topic,
                "keywords": result.keywords,
                "confidence": result.confidence,
            }

            logger.info(
                f"[Router] session={session_id}, "
                f"intent={result.intent}, "
                f"confidence={result.confidence:.2f}"
            )
        except Exception as e:
            logger.warning(f"[Router] structured output 失败: {e}，使用兜底分类")
            router_result = self._router_fallback(question)

        # 映射 intent → query_type（会议检索用）
        intent = router_result.get("intent", "detail")
        router_query_type = _INTENT_TO_QUERY_TYPE.get(intent, "细节性")

        return {
            "router_result": router_result,
            "query_type": router_query_type,
        }

    def _router_fallback(self, question: str) -> dict:
        """Router 兜底：基于关键词规则做简单分类。"""
        # 简单的关键词匹配
        summary_kw = ["总结", "概括", "主要内容", "说了什么", "讲了什么", "结论", "共识"]
        action_kw = ["待办", "行动项", "任务", "下一步", "要做"]
        topic_kw = ["主题", "议题", "讨论了哪些", "议程"]
        detail_kw = ["具体", "为什么", "怎么", "如何", "看法", "观点", "意见"]

        intent = "detail"
        if any(k in question for k in summary_kw):
            intent = "summary"
        elif any(k in question for k in action_kw):
            intent = "action"
        elif any(k in question for k in topic_kw):
            intent = "topic"
        elif any(k in question for k in detail_kw):
            intent = "detail"

        logger.info(f"[Router] 关键词兜底: intent={intent}")
        return {
            "intent": intent,
            "speaker": [],
            "topic": [],
            "keywords": [],
            "confidence": 0.5,
        }

    # =========================================================================
    # Node: knowledge_retrieval —— 知识库检索（条件边）
    # =========================================================================
    async def _knowledge_retrieval_node(self, state: dict) -> dict:
        """从知识库中检索相关文档，逐个 keyword 检索后合并重排序。"""
        question = state.get('question', '')
        knowledge_ids = state.get('knowledge_ids', []) or []
        session_id = state.get('session_id', '')
        router_result = state.get('router_result') or {}

        # Router 提取的 keywords，逐个检索
        keywords: list[str] = router_result.get("keywords", [])
        queries: list[str] = list(keywords) + [question] if keywords else [question]

        kb_text = ""
        if knowledge_ids:
            try:
                # 逐个 keyword 检索，按 collection 汇总
                collection_docs: dict[str, list[str]] = {}
                for q in queries:
                    for kb_id in knowledge_ids:
                        col_name = f"collection_kb_{kb_id}"
                        try:
                            result = db_manager.search(
                                collection_name=col_name,
                                query_text=q,
                                n_results=10,
                            )
                            docs = (result.get("documents") or [[]])[0]
                            filtered = [d.strip() for d in docs if d and isinstance(d, str) and d.strip()]
                            if filtered:
                                collection_docs.setdefault(col_name, []).extend(filtered)
                        except Exception as e:
                            logger.warning(f"[knowledge_retrieval] 检索 {col_name} 失败: {e}")

                if collection_docs:
                    # 批量去重
                    for col in collection_docs:
                        collection_docs[col] = list(dict.fromkeys(collection_docs[col]))

                    # 统一重排序
                    reranked, _ = await rerank.rerank_multi_collection(
                        question=question,
                        collection_docs=collection_docs,
                        top_k=5,
                    )
                    kb_text = "\n".join(reranked)

                logger.info(
                    f"[knowledge_retrieval] session={session_id}, "
                    f"kb_ids={len(knowledge_ids)}, queries={len(queries)}, "
                    f"result_len={len(kb_text)}"
                )
            except Exception as e:
                logger.error(f"[knowledge_retrieval] 检索失败: {e}")
        else:
            logger.info(f"[knowledge_retrieval] session={session_id}, 无知识库 ID，跳过")

        return {"kb_snippets": kb_text}

    # =========================================================================
    # Node: memory_retrieval —— 记忆库检索（固定边）
    # =========================================================================
    async def _memory_retrieval_node(self, state: dict) -> dict:
        """从 Chroma 记忆库中检索过往对话记忆，逐个 keyword 检索后合并去重。"""
        question = state.get('question', '')
        session_id = state.get('session_id', '')
        user_id = state.get('user_id', 0)
        turn_index = state.get('turn_index', 0)
        router_result = state.get('router_result') or {}

        # Router 提取的 keywords，逐个检索
        keywords: list[str] = router_result.get("keywords", [])
        queries: list[str] = list(keywords) + [question] if keywords else [question]

        memory_content: list[str] = []
        seen: set[str] = set()
        try:
            # 每个 keyword 单独检索，n_results 调小以免膨胀
            n_per_query = max(2, 6 // len(queries))
            for q in queries:
                results = retrieve_past_memory(
                    user_id=user_id,
                    question=q,
                    session_id=session_id,
                    n_results=n_per_query,
                    current_turn_index=turn_index,
                )
                for r in results:
                    if r.strip() not in seen:
                        seen.add(r.strip())
                        memory_content.append(r.strip())

            # 重排序
            if memory_content:
                try:
                    memory_content = await rerank.rerank_context(
                        question, [memory_content], top_k=5
                    )
                except Exception as e:
                    logger.warning(f"[memory_retrieval] rerank 失败: {e}")

            logger.info(
                f"[memory_retrieval] session={session_id}, "
                f"queries={len(queries)}, "
                f"results={len(memory_content)}"
            )
        except Exception as e:
            logger.error(f"[memory_retrieval] 检索失败: {e}")

        return {"memory_content": memory_content}

    # =========================================================================
    # Node: meeting_retrieval —— 会议库检索（Router→meeting_retrieval 固定边）
    # =========================================================================
    async def _meeting_retrieval_node(self, state: dict) -> dict:
        """
        会议库检索节点。

        利用 Router 的输出（intent→query_type, retrieve_sources→doc_types,
        keywords, speaker, topic）指导多路检索。
        """
        question = state.get('question', '')
        meeting_ids = state.get('meeting_ids', []) or []
        router_result = state.get('router_result') or {}
        query_type = state.get('query_type', '细节性')
        session_id = state.get('session_id', '')

        if not meeting_ids:
            logger.info(f"[meeting_retrieval] session={session_id}, 无会议 ID")
            return {"meeting_content": []}

        # 从 Router 结果中提取指导信息
        keywords: list[str] = router_result.get("keywords", [])
        speakers: list[str] = router_result.get("speaker", [])
        topics: list[str] = router_result.get("topics", [])

        # 确定检索用的查询列表：keywords + 原问题
        query_list: list[str] = list(keywords) + [question] if keywords else [question]
        # 如果有 speakers，为每个 speaker 生成扩展查询
        if speakers:
            for sp in speakers:
                query_list.extend([f"{sp} {q}" for q in query_list])

        # 按 query_type 分路检索
        all_meeting_docs: list[str] = []
        all_meeting_metas: list[dict] = []

        # 按 query_type 确定检索参数: (doc_types, loop_queries, n_primary, fallback)
        type_config = {
            "概括性": (["summary", "theme_seg", "fine_chunk"], True,  5, (10, 10)),
            "行动项": (["action_items", "fine_chunk"],          True,  5, (10, 10)),
            "细节性": (None,                                    True,  5, None),
        }
        doc_types, loop_queries, n_primary, fallback = type_config.get(
            query_type, (None, False, 20, None)
        )

        queries = query_list if loop_queries else [query_list[0] if query_list else question]

        # 主检索
        for q in queries:
            await RetrievalPipeline._retrieve(
                meeting_ids=meeting_ids,
                query_text=q,
                n_res_per_collection=n_primary,
                doc_list=all_meeting_docs,
                meta_list=all_meeting_metas,
                doc_types=doc_types,
            )

        # 兜底检索
        if fallback and len(all_meeting_docs) < fallback[0]:
            for q in queries:
                await RetrievalPipeline._retrieve(
                    meeting_ids=meeting_ids,
                    query_text=q,
                    n_res_per_collection=fallback[1],
                    doc_list=all_meeting_docs,
                    meta_list=all_meeting_metas,
                )

        # 相邻扩展
        if all_meeting_docs and meeting_ids:
            for m_id in meeting_ids:
                try:
                    expanded = await expand_adjacent_chunks(
                        retrieved_docs=all_meeting_docs,
                        metadatas_list=[all_meeting_metas],
                        collection_name=f"collection_meeting_{m_id}",
                    )
                    all_meeting_docs = expanded
                except Exception as e:
                    logger.warning(f"[meeting_retrieval] 相邻扩展失败 ({m_id}): {e}")

        # 重排序
        reranked_meeting: list[str] = []
        if all_meeting_docs:
            try:
                reranked_meeting = await rerank.rerank_context(
                    question, [all_meeting_docs], top_k=retrieval_pipeline.top_k
                )
            except Exception as e:
                logger.error(f"[meeting_retrieval] rerank 失败: {e}")
                reranked_meeting = all_meeting_docs[:retrieval_pipeline.top_k]

        logger.info(
            f"[meeting_retrieval] session={session_id}, "
            f"query_type={query_type}, "
            f"final_count={len(reranked_meeting)}"
        )

        return {"meeting_content": reranked_meeting}


    # =========================================================================
    # Node: context_builder —— 汇合检索结果，判定降级等级
    # =========================================================================
    async def _context_builder_node(self, state: dict) -> dict:
        """
        汇合三路检索结果，判定降级等级，生成用户提示语。
        """
        session_id = state.get('session_id', '')
        has_meeting = len(state.get('meeting_content', []) or []) > 0
        has_kb = bool(state.get('kb_snippets', ''))
        has_memory = len(state.get('memory_content', []) or []) > 0

        # 获取当前对话的历史轮次
        recent_history = get_recent_history(session_id)
        has_history = bool(recent_history)

        # 四级降级判定
        fallback_level, user_notice = _determine_fallback_level(
            has_meeting=has_meeting,
            has_kb=has_kb,
            has_memory=has_memory,
            has_history=has_history,
        )

        logger.info(
            f"[context_builder] session={session_id}, "
            f"fallback_level={fallback_level}, "
            f"meeting={has_meeting}, kb={has_kb}, "
            f"memory={has_memory}, history={has_history}"
        )

        return {
            "fallback_level": fallback_level,
            "user_notice": user_notice or "",
        }

    # =========================================================================
    # Node: llm_call —— LLM 调用（构建上下文 + 生成回答）
    # =========================================================================
    async def _llm_call(self, state: dict) -> dict:
        """
        LLM 调用节点：

        从 state 中读取三路检索结果 + 降级等级，
        使用 context_builder.build_context() 构建 SystemMessage + HumanMessage，
        调用 LLM 生成回答。
        """
        question = state.get('question', '')
        session_id = state.get('session_id', '')
        user_id = state.get('user_id', 0)
        fallback_level = state.get('fallback_level', 0)

        # 会议内容
        meeting_content_list: list[str] = state.get('meeting_content', []) or []

        # 知识库片段
        kb_snippets_list: list[str] = []
        kb_snippets_str = state.get('kb_snippets', '')
        if kb_snippets_str:
            kb_snippets_list = [s.strip() for s in kb_snippets_str.split('\n') if s.strip()]

        # 记忆库内容（memory_retrieval 节点已检索）
        memory_content: list[str] = state.get('memory_content', []) or []

        # 最近 3 轮历史对话
        recent_history = get_recent_history(session_id)

        # 构建 SystemMessage + HumanMessage
        messages = build_context(
            question=question,
            meeting_content=meeting_content_list,
            kb_snippets=kb_snippets_list,
            recent_history=recent_history,
            past_memory=memory_content,
            fallback_level=fallback_level,
        )

        logger.info(
            f"[llm_call] 构建上下文完成, session_id={session_id}, "
            f"user_id={user_id}, fallback_level={fallback_level}"
        )

        # 调用 LLM
        llm_message = await self.model.ainvoke(messages)
        logger.info("[llm_call] 大模型调用完成")

        return {"messages": [llm_message]}

    # =========================================================================
    # Graph 构建
    # =========================================================================
    def _build_graph(self) -> StateGraph:
        builder = StateGraph(ChatState)

        # 添加节点
        builder.add_node("router", self._router_node)
        builder.add_node("knowledge_retrieval", self._knowledge_retrieval_node)
        builder.add_node("memory_retrieval", self._memory_retrieval_node)
        builder.add_node("meeting_retrieval", self._meeting_retrieval_node)
        builder.add_node("context_builder", self._context_builder_node)
        builder.add_node("llm_call", self._llm_call)

        # ── START → Router ──
        builder.add_edge(START, "router")

        # ── Router → 三路并行检索（条件边 fan-out） ──
        def _route_from_router(state: ChatState) -> list[str]:
            """Router 之后扇出到 meeting / memory / knowledge（条件）检索。"""
            targets: list[str] = ["meeting_retrieval", "memory_retrieval"]
            if state.get("need_kb", False):
                targets.append("knowledge_retrieval")
            return targets

        builder.add_conditional_edges("router", _route_from_router)

        # ── 各分支边 ──
        # 知识库分支：router → knowledge_retrieval → context_builder
        builder.add_edge("knowledge_retrieval", "context_builder")
        # 记忆库分支：router → memory_retrieval → context_builder
        builder.add_edge("memory_retrieval", "context_builder")
        # 会议库分支：router → meeting_retrieval → context_builder
        builder.add_edge("meeting_retrieval", "context_builder")

        # ── 汇合：context_builder → llm_call → END ──
        builder.add_edge("context_builder", "llm_call")
        builder.add_edge("llm_call", END)

        return builder.compile()

    async def get_agent(self):
        """惰性构建并缓存编译图。"""
        if self._agent is None:
            self._agent = self._build_graph()
        return self._agent

    # =========================================================================
    # 对外调用方法
    # =========================================================================
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
        """
        流式执行对话工作流，逐 token 产出大模型回答。

        Args:
            question:     用户问题
            meeting_ids:  会议 ID 列表
            knowledge_ids: 知识库 ID 列表
            session_id:   会话 ID
            user_id:      用户 ID
            need_kb:      是否需要知识库检索
            turn_index:   当前轮次序号
        """
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
            logger.error(f"[ChatAgent] Graph 流式对话执行错误：{str(e)}", exc_info=True)
            raise
        finally:
            logger.info("[ChatAgent] Agent 流式工作流执行结束")


# ============================================================================
# 单例
# ============================================================================
chat_agent = ChatAgent()
retrieval_pipeline = RetrievalPipeline(top_k=15)


# ============================================================================
# 私有辅助：四级降级判定
# ============================================================================
def _determine_fallback_level(
    has_meeting: bool,
    has_kb: bool,
    has_history: bool,
    has_memory: bool = False,
) -> tuple[int, str | None]:
    """
    根据检索结果确定降级等级和用户提示语。

    Returns:
        (fallback_level, user_notice | None)
        fallback_level: 0=完整, 1=部分, 2=仅历史/记忆, 3=仅提示词
        user_notice: 需要告知用户的话（Level 0 时为 None）
    """
    if has_meeting or has_kb:
        if has_meeting and has_kb:
            return 0, None  # Level 0: 完整
        else:
            return 1, None  # Level 1: 部分（有其中一个就够）
    elif has_history or has_memory:
        return 2, "未检索到相关会议记录，以下基于已有对话记录为您作答："
    else:
        return 3, "当前没有会议记录可供查询，请先选择会议的录音或转录结果，我才能帮您分析。"


# ============================================================================
# 对外调用：stream_chat_messages
# ============================================================================
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
