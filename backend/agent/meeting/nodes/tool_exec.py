"""MeetingAgent - 工具执行节点。"""

from langchain.messages import ToolMessage
from loguru import logger


def _make_tool_node(tools_by_name: dict):
    """创建工具执行节点（闭包捕获 tools_by_name）。"""

    def _tool_node(state: dict):
        result = []
        asr_res = {}

        for tool_call in state["messages"][-1].tool_calls:
            tool = tools_by_name[tool_call["name"]]
            observation = tool.invoke(tool_call["args"])

            if tool_call["name"] == "asr":
                asr_res = observation

            result.append(
                ToolMessage(
                    content=observation,
                    tool_call_id=tool_call["id"]
                )
            )
        logger.info("✅ 大模型调用工具")
        return {
            "messages": result,
            "result": [asr_res]
        }

    return _tool_node
