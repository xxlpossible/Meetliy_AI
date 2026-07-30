"""MeetingAgent State 定义 —— 由 agent.py 直接使用。

使用 operator.add 作为 list 字段的 reducer，保证并行节点
（summary / get_action / theme_segmentation）的结果能被正确合并，
而非互相覆盖。
"""

import operator
from typing import Annotated

from langchain.messages import AnyMessage
from typing_extensions import TypedDict


class MeetingState(TypedDict):
    """MeetingAgent 的图状态。

    - messages: 使用 operator.add 追加（LangGraph 核心约定）。
    - result:    使用 operator.add 追加，并行节点的输出得以合并。
    - public_url: 待处理的会议录音 URL。
    - llm_calls: LLM 调用计数。
    """
    messages: Annotated[list[AnyMessage], operator.add]
    result: Annotated[list[dict], operator.add]
    public_url: str
    llm_calls: int
