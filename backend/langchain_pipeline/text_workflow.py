from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate
from langchain_core.runnables import RunnableParallel, RunnableLambda
from langchain_openai import ChatOpenAI
from typing import Dict, Any
from loguru import logger


def with_logging(step_name: str):
    """
    装饰一个节点，使其在执行后打印日志。
    适用于 Runnable.invoke() 的包装器
    """

    def wrapper(func):
        def inner(data):
            result = func(data)
            logger.info(f"🟢 [MeetingWorkflow] {step_name} 完成")
            # 如果是字符串，可以打印前 200 字做预览
            return result

        return inner

    return wrapper


class MeetingWorkflow:
    def __init__(self, model_name="gpt-4.1-mini", temperature=0.3):
        """会议语音转文字处理工作流（合并纠错+润色为一步，随后并行生成详细纪要/主题/行动项）"""
        from settings import settings
        openai_config = settings.get_openai_config()

        self.llm = ChatOpenAI(
            model=model_name,
            temperature=temperature,
            base_url=openai_config.get("base_url"),
            api_key=openai_config.get("api_key"),
        )

        # === Prompt: 纠错 + 润色（合并一步） ===
        # 明确要求：先纠错（不改变原意），然后在纠错结果上进行润色（提升流畅性和专业性），最终输出完整经过纠错并润色的文本
        self.prompt_correct_then_polish = PromptTemplate.from_template("""
            请对以下会议文本进行两步处理：
            1) 先对原文做**逻辑与语义纠错**（保持原意不变，修复语序混乱、逻辑断裂、语义重复或不连贯的问题），
            2) 在纠错结果上进行**语言润色**（提升表达流畅性与专业性），
            严格按照“先纠错再润色”的顺序执行，不能颠倒。**不要删减核心信息**，不要加入未出现的新事实。
            最终只输出完整的、经过纠错并润色后的文本（标记变量名为 processed_text）。

            原始会议文本：
            {text}
        """)

        # === Prompt: 详细会议纪要（基于 processed_text） ===
        # 要求：一定要详细，不得简短概括，不得出现错误概括
        self.prompt_detailed_minutes = PromptTemplate.from_template("""
            请基于下方已处理（纠错并润色）的会议文本生成**详细的会议纪要**：
            - 绝对不要写成简短概括；要涵盖会议目的、讨论背景、每个主要讨论点的细节、不同观点或争议点、达成的结论、必要时的后续建议或未解决的问题。
            - **不能出现错误概括或未在文本中出现的信息**，凡是有不确定性应当标注为“（原文不明确）”。
            - 输出形式可以用有序段落或带小标题的段落，内容越全面越好（只要不发明事实）。
            文本：
            {processed_text}
        """)

        # === Prompt: 主题分段（基于 processed_text） ===
        # 要求：若无明确分段则输出单一主题；若有多主题必须分段；每段以【主题名称】开头
        self.prompt_topic_split = PromptTemplate.from_template("""
            请根据以下已处理（纠错并润色）的会议文本进行**主题分段**：
            - 如果会议没有明确分开的主题，输出一个主题整段内容；
            - 如果有多个明确主题，请将内容按主题分段，每段以 "【主题名称】" 开头，后跟该主题的完整、连贯内容（保留原意）。
            - 每段应尽量详细，保留上下文与逻辑衔接，不要丢失讨论中的关键细节。
            文本：
            {processed_text}
        """)

        # === Prompt: 行动项提取（基于 processed_text） ===
        # 要求：只关注要做的事情（不需要负责人/时间），每行一个行动项
        self.prompt_action_items = PromptTemplate.from_template("""
            请从以下已处理（纠错并润色）的会议文本中**提取行动项**：
            - 只列出“要做的事情”（即会议中决定要执行或推进的具体任务），**不需要包含负责人或截止时间**。
            - 每行一个行动项，尽量简洁明了地描述要做的事情本身（例如：“准备项目需求文档并提交评审”）。
            - 若文本没有明确行动项，输出 "无明确行动项"。
            文本：
            {processed_text}
        """)

        # === Prompt: 基于行动项与 processed_text 的简短小结 ===
        # 要求：简短（2-4 句），基于前面提取的行动项与处理后文本做总结
        self.prompt_brief_summary = PromptTemplate.from_template("""
            请基于下面的两个输入生成一个**详细的小结**：
            - 输入 A: 已处理后的会议全文（processed_text）
            - 输入 B: 提取出的行动项（action_items）
            小结要求：概述核心要点与最重要的行动方向，语言精炼，不要引入新事实。

            processed_text:
            {processed_text}

            action_items:
            {action_items}
        """)

        # 构建工作流链
        self.workflow_chain = self._build_workflow_chain()

    # =====================
    # 构建工作流链
    # =====================
    def _build_workflow_chain(self):
        # 单条链：纠错+润色 -> 返回 processed_text
        correct_then_polish_chain = self.prompt_correct_then_polish | self.llm | StrOutputParser()

        # 并行阶段：详细纪要 / 主题分段 / 行动项 —— 都以 processed_text 为输入
        parallel_processing = RunnableParallel({
            "detailed_minutes": self.prompt_detailed_minutes | self.llm | StrOutputParser(),
            "topics": self.prompt_topic_split | self.llm | StrOutputParser(),
            "action_items": self.prompt_action_items | self.llm | StrOutputParser(),
        })

        # 完整链（逻辑）：
        # 1) 将输入包装为 {"text": original}
        # 2) 运行纠错+润色，得到 processed_text
        # 3) 并行运行详细纪要/主题分段/行动项（输入 processed_text）
        # 4) 基于 processed_text 与并行得到的 action_items 生成简短小结
        full_chain = (
                RunnableLambda(lambda x: {"text": x})

                # 1. combined correct + polish
                | RunnableLambda(
                    with_logging("纠错并润色")(lambda data: {
                        **data,
                        "processed_text": correct_then_polish_chain.invoke({"text": data["text"]})
                    })
                )

                # 2. 并行：详细纪要 / 主题分段 / 行动项
                | RunnableLambda(
                    with_logging("并行生成：详细纪要 / 主题分段 / 行动项")(lambda data: {
                        **data,
                        **parallel_processing.invoke({"processed_text": data["processed_text"]})
                    })
                )

                # 3. 基于 processed_text 与 action_items 生成简短小结
                | RunnableLambda(
                    with_logging("生成简短小结")(lambda data: {
                        **data,
                        "brief_summary": (self.prompt_brief_summary | self.llm | StrOutputParser()).invoke({
                            "processed_text": data["processed_text"],
                            "action_items": data.get("action_items", "")
                        })
                    })
                )
        )

        return full_chain

    def process(self, text: str) -> Dict[str, Any]:
        """执行完整工作流，返回包含各阶段结果的字典"""
        logger.info("🚀 [MeetingWorkflow] 工作流开始")
        result = self.workflow_chain.invoke(text)
        logger.info("🏁 [MeetingWorkflow] 全部处理完成")
        # 整理并返回常用字段
        return {
            "processed_text": result.get("processed_text"),
            "detailed_minutes": result.get("detailed_minutes"),
            "topics": result.get("topics"),
            "action_items": result.get("action_items"),
            "brief_summary": result.get("brief_summary"),
        }
