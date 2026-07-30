"""MeetingAgent - 行动项提取节点。"""

from langchain_core.prompts import PromptTemplate
from loguru import logger

from agent.meeting.prompts.action import ACTION_ITEMS_PROMPT


def _make_action_items_node(model):
    """创建行动项提取节点（闭包捕获 model）。"""

    def _get_action(state: dict):
        get_action_template = PromptTemplate.from_template(ACTION_ITEMS_PROMPT)
        prompt_value = get_action_template.invoke({
            "processed_text": state["messages"][-1].content
        })
        get_action_message = model.invoke(prompt_value)
        logger.info("✅ 行动项提取完毕")
        return {
            "messages": [get_action_message],
            "result": [{"action": get_action_message.content}]
        }

    return _get_action
