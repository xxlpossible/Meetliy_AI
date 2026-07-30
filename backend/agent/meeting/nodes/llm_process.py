"""MeetingAgent - LLM 纠错润色节点。"""

from langchain_core.prompts import ChatPromptTemplate
from loguru import logger

from agent.meeting.prompts.process import PROCESS_PROMPT


def _make_llm_call_node(model_with_tools):
    """创建 LLM 调用节点（闭包捕获 model）。"""

    def _llm_call(state: dict):
        url = state.get("public_url")

        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", PROCESS_PROMPT),
                ("human", "{url}")
            ] + state.get("messages", [])
        )

        prompt_value = prompt.invoke({"url": url})
        llm_message = model_with_tools.invoke(prompt_value)
        logger.info("✅ 调用大模型")
        return {
            "messages": [llm_message],
            "llm_calls": state.get("llm_calls", 0) + 1
        }

    return _llm_call
