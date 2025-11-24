from fastapi import WebSocket
import dashscope
from dashscope.audio.asr import TranslationRecognizerCallback, TranscriptionResult, TranslationResult, RecognitionResult
import asyncio

# 设置 API Key
dashscope.api_key = "sk-0e8a5b51bbc34dc6afc3f45041640341"


class WebSocketCallback(TranslationRecognizerCallback):
    """
    自定义回调类，用于将识别结果通过 WebSocket 发送给前端
    """

    def __init__(self, websocket: WebSocket, loop: asyncio.AbstractEventLoop):
        super().__init__()
        self.websocket = websocket
        self.loop = loop

    def on_open(self) -> None:
        print("DashScope Recognition Started.")

    def on_close(self) -> None:
        print("DashScope Recognition Closed.")

    def on_event(
            self,
            request_id,
            transcription_result: TranscriptionResult,
            translation_result: TranslationResult,
            usage,
    ) -> None:
        """
        SDK会在子线程调用此方法，因此需要使用 threadsafe 方式调用 async 的 websocket 发送
        """
        response_data = {
            "type": "result",
            "transcription": None,
            "translation": None
        }

        # 处理识别结果（中文）
        if transcription_result:
            response_data["transcription"] = {
                "text": transcription_result.text,
                "sentence_id": transcription_result.sentence_id,
                "is_sentence_end": transcription_result.is_sentence_end
            }

        # 处理翻译结果（英文）
        if translation_result:
            # 假设我们只取第一个目标语言 'en'
            if translation_result.get_language_list():
                en_trans = translation_result.get_translation("en")
                if en_trans:
                    response_data["translation"] = {
                        "text": en_trans.text,
                        "sentence_id": en_trans.sentence_id,
                        "is_sentence_end": en_trans.is_sentence_end
                    }

        # 只有当有内容时才发送
        if response_data["transcription"] or response_data["translation"]:
            # 关键：将异步发送任务提交给主事件循环
            asyncio.run_coroutine_threadsafe(
                self.websocket.send_json(response_data),
                self.loop
            )

