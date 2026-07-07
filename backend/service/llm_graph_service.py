from typing import List

from langchain_core.messages import HumanMessage, AIMessage

from database.check_points import CheckpointerManager
from langchain.chat_models import init_chat_model
from langchain.messages import AnyMessage
from langchain_core.prompts import ChatPromptTemplate
from typing_extensions import TypedDict, Annotated
import operator
from loguru import logger
from langgraph.graph import StateGraph, START, END
from settings import settings


# State 定义
class ChatState(TypedDict):
    messages: Annotated[list[AnyMessage], operator.add]
    question: str
    meeting_content: str
    recent_messages: List[AnyMessage]
    summary: str


# Agent 封装
class ChatAgent:
    def __init__(self):
        qwen = settings.get_qwen_config()
        self.model = init_chat_model(
            model=qwen.get('model', "qwen3.5-flash"),
            model_provider="openai",
            api_key=qwen.get('api_key', None),
            base_url=qwen.get('base_url', "https://dashscope.aliyuncs.com/compatible-mode/v1")
        )
        self.sum_model = init_chat_model(
            model=qwen.get('model', "qwen3.5-flash"),
            model_provider="openai",
            api_key=qwen.get('api_key', None),
            base_url=qwen.get('base_url', "https://dashscope.aliyuncs.com/compatible-mode/v1")
        )
        self.agent = self._build_graph()

    # =========================
    # Nodes
    # =========================
    def _llm_call(self, state: dict):
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", "你是一个会议智能助理，需要基于给出的会议记录内容，相关知识库文件片段以及历史对话回答用户的问题."
                           "请确保答案简明、准确，并基于会议内容进行回答。在回答时需要考虑历史对话的上下文，保持对话的连贯性。"
                           "如果问题与历史对话相关，请结合历史信息给出一致的回答"),
                ("human", "用户问题: {question}"
                          "会议记录内容与知识库相关文件片段: {meeting_content}"
                          "最近的对话记录: {history}"
                          "过往的对话总结: {summary}")
            ]
        )

        prompt_value = prompt.invoke(
            {
                "question": state.get('question'),
                "history": state['recent_messages'],
                "meeting_content": state.get('meeting_content'),
                "summary": state.get('summary')
            }
        )
        llm_message = self.model.invoke(prompt_value)
        logger.info("✅ 调用大模型")
        return {
            "messages": [llm_message]
        }

    # TODO 后续可以更改为超过Token值才进行总结 用轮次判断总结情况不太合理
    def _summary(self, state: ChatState):
        recent_messages = state['messages']
        summary = AIMessage("暂无对话总结")

        # 如果历史对话超过3轮（也就是6条Message）超过6条的部分需要做总结
        if len(recent_messages) > 6:
            recent_messages = state['messages'][-6:]
            old_messages = state["messages"][:-6]
            summary = self.sum_model.invoke(f"""
                总结以下历史对话：

                {old_messages}

                当前summary:
                {state["summary"]}
                """)
            logger.info(f"✅ 触发总结，总结内容为：{summary}")

        return {
            "summary": summary.content,
            "recent_messages": recent_messages
        }

    # =========================
    # Graph 构建
    # =========================
    def _build_graph(self):
        builder = StateGraph(ChatState)

        builder.add_node("summary", self._summary)
        builder.add_node("llm_call", self._llm_call)

        builder.add_edge(START, "summary")
        builder.add_edge("summary", "llm_call")

        builder.add_edge("llm_call", END)
        checkpointer = CheckpointerManager.get_checkpointer()
        graph = builder.compile(
            checkpointer=checkpointer
        )
        return graph

    # =========================
    # 对外调用方法 ✅
    # =========================
    def run(self, question: str, meeting_text: str, thead_id: str):
        """
        执行对话工作流：
        """
        try:
            config = {
                "configurable": {
                    "thread_id": f"chat_{thead_id}"
                }
            }

            ans = self.agent.invoke(
                {
                    "messages": [
                        HumanMessage(content=question)
                    ],
                    "question": question,
                    "meeting_content": meeting_text
                },
                config=config
            )

            return ans["messages"][-1].content

        except Exception as e:
            logger.error(f"❌ Graph对话执行错误：{str(e)}")
        finally:
            logger.info("✅ Agent工作流执行结束")


# =========================
# Main 测试函数
# =========================
# if __name__ == "__main__":
#     # 1. 初始化 Agent
#     bot = ChatAgent()
#
#     tid = "meeting_002"
#     meeting_data = "本会议讨论了关于‘星际航行’项目的预算问题，预算总额为5000万，预计2025年启动。"
#
#     print("\n--- 第一轮对话 ---")
#     q1 = "这次会议的主题是什么？预算是多少？"
#     print(f"用户: {q1}")
#     res1 = bot.run(q1, meeting_data, tid)
#     print(f"AI: {res1}")
#
#     print("\n--- 第二轮对话 (测试记忆) ---")
#     q2 = "我刚才提到的项目什么时候启动？"
#     print(f"用户: {q2}")
#     # 注意：即便不传 meeting_data，LangGraph 也会从历史 state 中恢复
#     res2 = bot.run(q2, meeting_data, tid)
#     print(f"AI: {res2}")
#
#     print("\n--- 连续对话测试 (触发总结逻辑) ---")
#     # 模拟多轮对话以触发 len(messages) > 6 的总结逻辑
#     for i in range(3):
#         res = bot.run(f"重复说一遍数字 {i}", meeting_data, tid)
#         print(f"AI Round {i}: {res}")
#
#     print("\n✅ 测试结束")


