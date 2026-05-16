from langchain.tools import tool
from langchain.chat_models import init_chat_model
from langchain.messages import AnyMessage, ToolMessage
from langchain_core.prompts import ChatPromptTemplate, PromptTemplate
from typing_extensions import TypedDict, Annotated
from typing import Literal, List
import operator
from loguru import logger
from langgraph.graph import StateGraph, START, END

from service.dashscope_asr import DashScopeASRService
from settings import settings
from utils.formatter import Formatter


# =========================
# State 定义
# =========================
class MessagesState(TypedDict):
    result: Annotated[list[dict], operator.add]
    public_url: str
    messages: Annotated[list[AnyMessage], operator.add]
    llm_calls: int


# =========================
# Agent 封装
# =========================
class MeetingAgent:

    def __init__(self):
        qwen = settings.get_qwen_config()
        self.model = init_chat_model(
            model=qwen.get('model', "qwen3.5-flash"),
            model_provider="openai",
            api_key=qwen.get('api_key', None),
            base_url=qwen.get('base_url', "https://dashscope.aliyuncs.com/compatible-mode/v1")
        )
        self.tools = [self._build_asr_tool()]
        self.tools_by_name = {t.name: t for t in self.tools}
        self.model_with_tools = self.model.bind_tools(self.tools)

        self.agent = self._build_graph()

    # =========================
    # Tool
    # =========================
    def _build_asr_tool(self):
        @tool
        def asr(url: str) -> dict:
            """一个可以将语音文件的url地址转换为文字识别结果的工具

            Args:
                url: 语音文件的url下载地址
            """
            result = DashScopeASRService().transcribe(
                file_urls=[url],
                language_hints=["zh", "en"],
                diarization_enabled=True
            )
            results = result.get('results', [])
            json_file_url = results[0].get('transcription_url')

            sentences_with_time, complete_text = Formatter.format_audio_transcript(
                json_url=json_file_url
            )

            return {
                "sentences_with_time": sentences_with_time,
                "complete_text": complete_text
            }

        return asr

    # =========================
    # Nodes
    # =========================
    def _llm_call(self, state: dict):
        url = state.get("public_url")

        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", """给你一个会议语音文件的url地址，你需要将url地址对应的语音文件转换为文本，并对会议文本进行两步处理：
                1) 先对原文做**逻辑与语义纠错**（保持原意不变，修复语序混乱、逻辑断裂、语义重复或不连贯的问题），
                2) 在纠错结果上进行**语言润色**（提升表达流畅性与专业性），
                严格按照“先纠错再润色”的顺序执行，不能颠倒。**不要删减核心信息**，不要加入未出现的新事实。
                最终只输出完整的、经过纠错并润色后的文本"""),
                ("human", "{url}")
            ] + state.get("messages", [])
        )

        prompt_value = prompt.invoke({"url": url})
        llm_message = self.model_with_tools.invoke(prompt_value)
        logger.info("✅ 调用大模型")
        return {
            "messages": [llm_message],
            "llm_calls": state.get("llm_calls", 0) + 1
        }

    def _tool_node(self, state: dict):
        result = []
        asr_res = {}

        for tool_call in state["messages"][-1].tool_calls:
            tool = self.tools_by_name[tool_call["name"]]
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

    def _summary(self, state: dict):
        """make summary"""

        asr_result = state['result'][0]
        sentences_with_time = asr_result.get('sentences_with_time')
        # 设置提示词模板
        summary_template = PromptTemplate.from_template(
            """请基于下方已处理（纠错并润色）的会议文本以及根据说话人和说话时间分割的会议内容生成**详细的会议纪要**：
                - 绝对不要写成简短概括；要涵盖会议目的、讨论背景、每个主要讨论点的细节、不同观点或争议点、达成的结论、必要时的后续建议或未解决的问题。
                - **不能出现错误概括或未在文本中出现的信息**，凡是有不确定性应当标注为“（原文不明确）”。
                - 输出形式可以用有序段落或带小标题的段落，内容越全面越好（只要不发明事实）。
                文本：
                {processed_text}
                根据说话人和说话时间进行时间分割的会议内容：
                {sentences_with_time}
                """
        )
        prompt_value = summary_template.invoke({
            "processed_text": state["messages"][-1].content,
            "sentences_with_time": sentences_with_time
        })
        # 调用模型获取回答
        summary_message = self.model.invoke(
            prompt_value
        )
        logger.info("✅ 会议总结生成完毕")
        return {
            "messages": [summary_message],
            "result": [{
                "summary": summary_message.content
            }]
        }

    def _get_action(self, state: dict):
        """get action"""

        # 设置提示词模板
        get_action_template = PromptTemplate.from_template(
            """请从以下已处理（纠错并润色）的会议文本中**提取行动项**：
                - 只列出“要做的事情”（即会议中决定要执行或推进的具体任务），**不需要包含负责人或截止时间**。
                - 每行一个行动项，尽量简洁明了地描述要做的事情本身（例如：“准备项目需求文档并提交评审”）。
                - 若文本没有明确行动项，输出 "无明确行动项"。
                文本：
                {processed_text}"""
        )
        prompt_value = get_action_template.invoke({
            "processed_text": state["messages"][-1].content
        })
        # 调用模型获取回答
        get_action_message = self.model.invoke(
            prompt_value
        )
        logger.info("✅ 行动项提取完毕")
        return {
            "messages": [get_action_message],
            "result": [{
                "action": get_action_message.content
            }]
        }

    def _theme_segmentation(self, state: dict):
        """Theme Segmentation"""

        # 获取提示词模板
        theme_segmentation_template = PromptTemplate.from_template(
            """请根据以下已处理（纠错并润色）的会议文本进行**主题分段**：
                - 如果会议没有明确分开的主题，输出一个主题整段内容；
                - 如果有多个明确主题，请将内容按主题分段，每段以 "【主题名称】" 开头，后跟该主题的完整、连贯内容（保留原意）。
                - 每段应尽量详细，保留上下文与逻辑衔接，不要丢失讨论中的关键细节。
                文本：
                {processed_text}"""
        )
        prompt_value = theme_segmentation_template.invoke({
            "processed_text": state["messages"][-1].content
        })
        # 调用模型获取回答
        theme_segmentation_template_message = self.model.invoke(
            prompt_value
        )
        logger.info("✅ 主题分段完成")
        return {
            "messages": [theme_segmentation_template_message],
            "result": [{
                "theme_segmentation": theme_segmentation_template_message.content
            }]
        }

    # =========================
    # 路由
    # =========================
    def _should_continue(
        self, state: MessagesState
    ) -> Literal["tool_node", List[str]]:

        last_message = state["messages"][-1]

        if last_message.tool_calls:
            return "tool_node"

        return ["summary", "get_action", "theme_segmentation"]

    # =========================
    # Graph 构建
    # =========================
    def _build_graph(self):
        builder = StateGraph(MessagesState)

        builder.add_node("llm_call", self._llm_call)
        builder.add_node("tool_node", self._tool_node)
        builder.add_node("summary", self._summary)
        builder.add_node("get_action", self._get_action)
        builder.add_node("theme_segmentation", self._theme_segmentation)

        builder.add_edge(START, "llm_call")

        builder.add_conditional_edges(
            "llm_call",
            self._should_continue,
            ["tool_node", "summary", "get_action", "theme_segmentation"]
        )

        builder.add_edge("tool_node", "llm_call")

        builder.add_edge(
            ["summary", "get_action", "theme_segmentation"],
            END
        )

        return builder.compile()

    # =========================
    # 对外调用方法 ✅
    # =========================
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

            # 将列表中的多个字典统一合并
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
