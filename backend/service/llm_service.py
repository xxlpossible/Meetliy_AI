# backend/utils/llm_service.py
from langchain_core.prompts import PromptTemplate
from langchain_openai import ChatOpenAI
from settings import settings
import json
import asyncio
from typing import AsyncGenerator, List


class LLMService:
    """封装大语言模型调用逻辑（支持流式输出）"""

    def __init__(self, model_name: str = "gpt-4o-mini", temperature: float = 0.3):
        openai_config = settings.get_openai_config()
        self.model_name = model_name
        self.temperature = temperature
        self.base_url = openai_config["base_url"]
        self.api_key = openai_config["api_key"]

    def get_model(self) -> ChatOpenAI:
        """初始化流式模型实例"""
        return ChatOpenAI(
            model=self.model_name,
            temperature=self.temperature,
            base_url=self.base_url,
            api_key=self.api_key,
            streaming=True,
        )

    async def stream_answer(self, context: str, question: str, chat_history: List[str] = None) -> AsyncGenerator[str, None]:
        """
        传入会议上下文与问题，流式返回答案。
        """
        if chat_history is None:
            chat_history = []

        # 构建聊天历史字符串
        history_str = ""
        if chat_history:
            history_str = "【历史对话】\n"
            for i in range(0, len(chat_history), 2):
                if i < len(chat_history):
                    user_msg = chat_history[i]
                    history_str += f"助手: {user_msg}\n"
                if i + 1 < len(chat_history):
                    assistant_msg = chat_history[i + 1]
                    history_str += f"用户: {assistant_msg}\n"
            history_str += "\n"

        prompt_template = PromptTemplate.from_template(
            """
            你是一个会议智能助理，请基于以下会议记录内容和历史对话回答用户的问题。

            【会议内容】
            {context}

            {history_str}

            【当前问题】
            {question}

            请确保答案简明、准确，并基于会议内容进行回答。在回答时需要考虑历史对话的上下文，保持对话的连贯性。
            如果问题与历史对话相关，请结合历史信息给出一致的回答。
            """
        )
        prompt = prompt_template.format(context=context, question=question, history_str=history_str)

        llm = self.get_model()

        # 使用异步流式生成器
        async for chunk in llm.astream(prompt):
            delta = chunk.content
            if delta:
                yield json.dumps({"delta": delta}, ensure_ascii=False) + "\n"
            await asyncio.sleep(0)

        yield json.dumps({"event": "done"}) + "\n"


# 初始化单例
llm_service = LLMService()
