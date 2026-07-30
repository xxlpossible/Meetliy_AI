"""LLM 流式客户端（原 service/llm_service.py，临时对话接口仍在使用）。"""

import json

from openai import AsyncOpenAI

from settings import settings


class LLMService:
    """封装大语言模型调用逻辑（支持流式输出）。"""

    def __init__(self):
        chat_model = settings.get_chat_model_config()
        self.async_client = AsyncOpenAI(
            api_key=chat_model.get('api_key'),
            base_url=chat_model.get('base_url')
        )
        self.model_name = chat_model.get('model')

    async def stream_answer(self, context: str, question: str, chat_history: list[str] | None = None):
        """
        传入会议上下文与问题，流式返回答案。
        """
        if chat_history is None:
            chat_history = []

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

        user_content = (
            f"【会议内容与相关知识库文件片段】\n{context}\n\n"
            f"{history_str}"
            f"【当前问题】\n{question}"
        )

        completion = await self.async_client.chat.completions.create(
            model=self.model_name,
            messages=[{'role': 'system',
                       'content': '你是一个会议智能助理，需要基于给出的会议记录内容，相关知识库文件片段以及历史对话回答用户的问题。'
                                  '请确保答案简明、准确，并基于会议内容进行回答。在回答时需要考虑历史对话的上下文，保持对话的连贯性。'
                                  '如果问题与历史对话相关，请结合历史信息给出一致的回答'},
                      {'role': 'user', 'content': user_content}],
            stream=True,
            stream_options={"include_usage": True}
        )

        async for chunk in completion:
            if len(chunk.choices) > 0:
                delta = chunk.choices[0].delta.content
                if delta:
                    yield json.dumps({"delta": delta}, ensure_ascii=False) + "\n"

            if hasattr(chunk, 'usage') and chunk.usage is not None:
                pass

        yield json.dumps({"event": "done"}) + "\n"


# 初始化单例
llm_service = LLMService()
