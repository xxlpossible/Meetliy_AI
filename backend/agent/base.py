"""Agent 抽象基类。

定义统一的 Agent 接口模式：模型加载、Graph 构建/编译/运行。
ChatAgent（异步流式）和 MeetingAgent（同步批量）均继承此基类。
"""

from abc import ABC, abstractmethod

from langgraph.graph import StateGraph


class BaseAgent(ABC):
    """Agent 抽象基类 —— 约束子类实现 _build_graph 和对外调用方法。"""

    @abstractmethod
    def _build_graph(self) -> StateGraph:
        """构建并返回 LangGraph StateGraph 编译结果。"""
        ...

    def get_agent(self):
        """惰性构建并缓存编译图（同步/异步子类分别覆写）。"""
        if not hasattr(self, '_agent') or self._agent is None:
            self._agent = self._build_graph()
        return self._agent
