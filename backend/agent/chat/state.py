"""ChatAgent State 定义。"""

import operator
from typing import Annotated

from typing_extensions import TypedDict


class ChatState(TypedDict):
    messages: Annotated[list, operator.add]
    question: str
    meeting_content: list[str]
    kb_snippets: str
    memory_content: list[str]
    session_id: str
    user_id: int
    turn_index: int
    query_type: str
    fallback_level: int
    need_kb: bool
    meeting_ids: list[str]
    knowledge_ids: list[str]
    router_result: dict | None
    user_notice: str
