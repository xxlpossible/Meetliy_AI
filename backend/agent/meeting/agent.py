"""MeetingAgent —— 会议纪要生成 Agent。

工作流：语音 → ASR 识别 → 纠错润色 → 并行输出（会议纪要 / 行动项 / 主题分段）。
"""

import operator
from typing import Annotated, Literal

from langchain.chat_models import init_chat_model
from langchain.messages import AnyMessage
from langgraph.graph import END, START, StateGraph
from loguru import logger
from typing_extensions import TypedDict

from agent.base import BaseAgent
from agent.meeting.nodes.action_items import _make_action_items_node
from agent.meeting.nodes.llm_process import _make_llm_call_node
from agent.meeting.nodes.summary import _make_summary_node
from agent.meeting.nodes.theme_seg import _make_theme_seg_node
from agent.meeting.nodes.tool_exec import _make_tool_node
from agent.meeting.tools.asr import build_asr_tool
from settings import settings


class MeetingState(TypedDict):
    """MeetingAgent 专用 State，使用 operator.add 保证并行节点结果正确合并。"""
    messages: Annotated[list[AnyMessage], operator.add]
    result: Annotated[list[dict], operator.add]
    public_url: str
    llm_calls: int


class MeetingAgent(BaseAgent):

    def __init__(self):
        chat_model = settings.get_chat_model_config()
        self.model = init_chat_model(
            model=chat_model.get('model', "qwen3.5-flash"),
            model_provider="openai",
            api_key=chat_model.get('api_key', None),
            base_url=chat_model.get('base_url', "https://dashscope.aliyuncs.com/compatible-mode/v1")
        )
        self.tools = [build_asr_tool()]
        self.tools_by_name = {t.name: t for t in self.tools}
        self.model_with_tools = self.model.bind_tools(self.tools)

        self.agent = self._build_graph()

    def _should_continue(self, state: MeetingState) -> Literal["tool_node", list[str]]:
        last_message = state["messages"][-1]
        if last_message.tool_calls:
            return "tool_node"
        return ["summary", "get_action", "theme_segmentation"]

    def _build_graph(self) -> StateGraph:
        builder = StateGraph(MeetingState)

        builder.add_node("llm_call", _make_llm_call_node(self.model_with_tools))
        builder.add_node("tool_node", _make_tool_node(self.tools_by_name))
        builder.add_node("summary", _make_summary_node(self.model))
        builder.add_node("get_action", _make_action_items_node(self.model))
        builder.add_node("theme_segmentation", _make_theme_seg_node(self.model))

        builder.add_edge(START, "llm_call")

        builder.add_conditional_edges(
            "llm_call",
            self._should_continue,
            ["tool_node", "summary", "get_action", "theme_segmentation"]
        )

        builder.add_edge("tool_node", "llm_call")

        builder.add_edge(["summary", "get_action", "theme_segmentation"], END)

        return builder.compile()

    def run(self, public_url: str):
        """
        执行会议工作流：
        - 成功：合并 result 列表中的所有字典，并附加 state=SUCCESS
        - 失败：返回 state=ERROR
        """
        try:
            final_state = self.agent.invoke({
                "public_url": public_url
            })

            result_list = final_state.get("result", [])
            merged_result = {}

            if isinstance(result_list, list):
                for item in result_list:
                    if isinstance(item, dict):
                        merged_result.update(item)

            merged_result["status"] = "complete"
            return merged_result

        except Exception as e:
            return {
                "status": "complete_with_errors",
                "error_message": str(e)
            }
        finally:
            logger.info("✅ Agent工作流执行结束")
