"""ChatAgent - Router 结构化输出模型。"""

from pydantic import BaseModel, Field
from typing import Literal


class RouterOutput(BaseModel):
    """Router 节点结构化输出 —— 分析用户提问的类型、检索目标和过滤条件。"""

    intent: Literal[
        "summary",    # 概括总结
        "action",     # 行动项 / 待办
        "topic",      # 主题 / 议题
        "detail",     # 细节 / 某人的观点 / 具体讨论
        "multi",      # 多类型混合
    ]

    speaker: list[str] = Field(default_factory=list)
    topic: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
