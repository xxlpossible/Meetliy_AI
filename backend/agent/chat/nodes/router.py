"""ChatAgent - Router 意图路由节点。"""

from loguru import logger

from agent.chat.prompts.router import INTENT_TO_QUERY_TYPE


def _make_router_node(router_model, router_prompt_template):
    """创建 Router 节点（闭包捕获 model 和 prompt）。"""

    async def _router_node(state: dict) -> dict:
        question = state.get('question', '')
        session_id = state.get('session_id', '')

        router_result: dict = {}
        try:
            messages = router_prompt_template.format_messages(question=question)
            result = await router_model.ainvoke(messages)

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
            router_result = _router_fallback(question)

        intent = router_result.get("intent", "detail")
        router_query_type = INTENT_TO_QUERY_TYPE.get(intent, "细节性")

        return {
            "router_result": router_result,
            "query_type": router_query_type,
        }

    return _router_node


def _router_fallback(question: str) -> dict:
    """Router 兜底：基于关键词规则做简单分类。"""
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
