from langchain.tools import tool
from langchain.chat_models import init_chat_model
from langchain.messages import AnyMessage
from langchain_core.prompts import ChatPromptTemplate, PromptTemplate
from typing_extensions import TypedDict, Annotated
import operator
from service.dashscope_asr import DashScopeASRService
from utils.formatter import Formatter
from langchain.messages import ToolMessage
from typing import Literal, List
from langgraph.graph import StateGraph, START, END
from IPython.display import Image, display

# Step1. Define tools and model
model = init_chat_model(
    model="openai:qwen3.5-flash",
    api_key="sk-19fad8b8b620464b9b0406afcb7c811b",
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
)


# 语音文件转文字的操作
@tool
def asr(url: str) -> dict:
    """一个可以将语音文件的url地址转换为文字识别结果的工具

    Args:
        url: 语音文件的url下载地址
    """
    # 获取语音文件转文字服务的结果
    result = DashScopeASRService().transcribe(
        file_urls=[url],
        language_hints=["zh", "en"],
        diarization_enabled=True
    )
    # 因为可以上传多个语音文件 所以结果是一个数组 存储了多个语音文件的识别结果
    results = result.get('results', [])
    # 我们只上传一个语音文件 所以只取数组中的第0个结果 识别结果被存储在了url中的json文件当中
    json_file_url = results[0].get('transcription_url')
    sentences_with_time, complete_text = Formatter.format_audio_transcript(
        json_url=json_file_url
    )
    return {
        "sentences_with_time": sentences_with_time,
        "complete_text": complete_text
    }


# Augment the LLM with tools
tools = [asr]
tools_by_name = {tool.name: tool for tool in tools}
model_with_tools = model.bind_tools(tools)


# Step 2: Define state
class MessagesState(TypedDict):
    # 存储最终结果的字典
    result: Annotated[list[dict], operator.add]
    public_url: str
    messages: Annotated[list[AnyMessage], operator.add]
    llm_calls: int


# Step 3: Define model node
def llm_call(state: dict):
    """LLM decides whether to call a tool or not"""
    url = state.get('public_url', None)

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", """
            给你一个会议语音文件的url地址，你需要将url地址对应的语音文件转换为文本，并对会议文本进行两步处理：
                1) 先对原文做**逻辑与语义纠错**（保持原意不变，修复语序混乱、逻辑断裂、语义重复或不连贯的问题），
                2) 在纠错结果上进行**语言润色**（提升表达流畅性与专业性），
                严格按照“先纠错再润色”的顺序执行，不能颠倒。**不要删减核心信息**，不要加入未出现的新事实。
                最终只输出完整的、经过纠错并润色后的文本"""
             ),
            ("human", "{url}")
        ] + state.get('messages', [])
    )

    prompt_value = prompt.invoke({
        "url": url
    })

    llm_message = model_with_tools.invoke(prompt_value)

    return {
        "messages": [
            llm_message
        ],
        "llm_calls": state.get('llm_calls', 0) + 1
    }


# Step 4: Define tool node
def tool_node(state: dict):
    """Performs the tool call"""

    result = []
    asr_res = {}
    for tool_call in state["messages"][-1].tool_calls:
        tool = tools_by_name[tool_call["name"]]
        observation = tool.invoke(tool_call["args"])
        # 将语音转录的结果进行保存
        if tool_call["name"] == "asr":
            asr_res = observation
        result.append(ToolMessage(content=observation, tool_call_id=tool_call["id"]))
    return {"messages": result, "result": [asr_res]}


# Step 5: Define other node
def summary(state: dict):
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
    summary_message = model.invoke(
        prompt_value
    )

    return {
        "messages": [summary_message],
        "result": [{
            "summary": summary_message.content
        }]
    }


def get_action(state: dict):
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
    get_action_message = model.invoke(
        prompt_value
    )

    return {
        "messages": [get_action_message],
        "result": [{
            "action": get_action_message.content
        }]
    }


def theme_segmentation(state: dict):
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
    theme_segmentation_template_message = model.invoke(
        prompt_value
    )

    return {
        "messages": [theme_segmentation_template_message],
        "result": [{
            "theme_segmentation": theme_segmentation_template_message.content
        }]
    }


# Step 5: Define logic to determine whether to end
# Conditional edge function to route to the tool node or end based upon whether the LLM made a tool call
def should_continue(state: MessagesState) -> Literal["tool_node", List[str]]:
    """
    控制 LangGraph 节点走向：

    - 如果 LLM 产生 tool_calls，则优先进入 tool_node
    - 如果没有 tool_calls，则同时流向三个平级任务节点
    """

    state_messages = state["messages"]
    last_message = state_messages[-1]

    # If the LLM makes a tool call, then perform an action
    if last_message.tool_calls:
        return "tool_node"

    # Otherwise, we stop (reply to the user)
    return ["summary", "get_action", "theme_segmentation"]


# Step 6: Build agent

# Build workflow
agent_builder = StateGraph(MessagesState)

# Add nodes
agent_builder.add_node("llm_call", llm_call)
agent_builder.add_node("tool_node", tool_node)
agent_builder.add_node("summary", summary)
agent_builder.add_node("get_action", get_action)
agent_builder.add_node("theme_segmentation", theme_segmentation)

# Add edges to connect nodes
agent_builder.add_edge(START, "llm_call")
agent_builder.add_conditional_edges(
    "llm_call",
    should_continue,
    ["tool_node", "summary", "get_action", "theme_segmentation"]
)
agent_builder.add_edge("tool_node", "llm_call")
agent_builder.add_edge(["summary", "get_action", "theme_segmentation"], END)

# Compile the agent
agent = agent_builder.compile()

# Show the agent
display(Image(agent.get_graph(xray=True).draw_mermaid_png()))

# Invoke
public_url = "https://java-web-deng.oss-cn-beijing.aliyuncs.com/audio/19a43b63c33c4bcbbc074d878cb26bfa.mp3"
final_state = agent.invoke({"public_url": public_url})
print(final_state['result'])
