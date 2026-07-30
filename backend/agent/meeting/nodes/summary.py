"""MeetingAgent - 会议总结节点。"""

from langchain_core.prompts import PromptTemplate
from loguru import logger

from agent.meeting.prompts.summary import SUMMARY_PROMPT


def _make_summary_node(model):
    """创建会议总结节点（闭包捕获 model）。"""

    def _summary(state: dict):
        result_list = state.get('result', [])
        if not result_list:
            logger.warning("⚠️ state 中无 result 数据，跳过会议总结")
            return {"messages": [], "result": [{"summary": ""}]}
        asr_result = result_list[0]
        sentences_with_time = asr_result.get('sentences_with_time')

        summary_template = PromptTemplate.from_template(SUMMARY_PROMPT)
        prompt_value = summary_template.invoke({
            "processed_text": state["messages"][-1].content,
            "sentences_with_time": sentences_with_time
        })
        summary_message = model.invoke(prompt_value)
        logger.info("✅ 会议总结生成完毕")
        return {
            "messages": [summary_message],
            "result": [{"summary": summary_message.content}]
        }

    return _summary
