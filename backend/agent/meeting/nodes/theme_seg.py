"""MeetingAgent - 主题分段节点。"""

from langchain_core.prompts import PromptTemplate
from loguru import logger

from agent.meeting.prompts.theme import THEME_SEG_PROMPT


def _make_theme_seg_node(model):
    """创建主题分段节点（闭包捕获 model）。"""

    def _theme_segmentation(state: dict):
        theme_segmentation_template = PromptTemplate.from_template(THEME_SEG_PROMPT)
        prompt_value = theme_segmentation_template.invoke({
            "processed_text": state["messages"][-1].content
        })
        theme_segmentation_template_message = model.invoke(prompt_value)
        logger.info("✅ 主题分段完成")
        return {
            "messages": [theme_segmentation_template_message],
            "result": [{"theme_segmentation": theme_segmentation_template_message.content}]
        }

    return _theme_segmentation
