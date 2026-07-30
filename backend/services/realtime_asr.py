import asyncio
import json

import dashscope
from dashscope.audio.qwen_omni import OmniRealtimeCallback
from fastapi import WebSocket
from loguru import logger

from settings import settings

# 设置APIKEY
dashscope_config = settings.get_dashscope_config()
dashscope.api_key = dashscope_config.get("api_key")


class WebSocketCallback(OmniRealtimeCallback):
    """
    自定义回调类，用于将识别结果通过 WebSocket 发送给前端。
    使用新版 dashscope.audio.qwen_omni SDK，解析原始 JSON 事件。
    """

    def __init__(self, websocket: WebSocket, loop: asyncio.AbstractEventLoop):
        super().__init__()
        self.websocket = websocket
        self.loop = loop
        self.session_id = None

    def on_open(self) -> None:
        logger.info("DashScope Recognition Started.")

    def on_close(self, close_status_code, close_msg) -> None:
        logger.info(f"DashScope Recognition Closed. code={close_status_code}, msg={close_msg}")

    def on_event(self, message) -> None:
        """
        SDK 会在子线程调用此方法，接收事件。
        注：SDK 内部已将 JSON 字符串解析为 dict 后传入（尽管类型标注为 str），
        需兼容两种情况处理。
        """
        try:
            # SDK 实际上传入的是 dict（已 parsed），但类型标注是 str
            if isinstance(message, str):
                event = json.loads(message)
            elif isinstance(message, dict):
                event = message
            else:
                return
            event_type = event.get("type", "")

            # session.created → 记录 session ID
            if event_type == "session.created":
                self.session_id = event.get("session", {}).get("id")
                logger.info(f"Session created: {self.session_id}")
                return

            # conversation.item.input_audio_transcription.completed → 最终识别结果
            if event_type == "conversation.item.input_audio_transcription.completed":
                transcript = event.get("transcript", "")
                response_data = {
                    "type": "result",
                    "transcription": {
                        "text": transcript,
                        "is_final": True
                    }
                }
                asyncio.run_coroutine_threadsafe(
                    self.websocket.send_json(response_data),
                    self.loop
                )
                return

            # conversation.item.input_audio_transcription.text → 中间识别结果
            if event_type == "conversation.item.input_audio_transcription.text":
                text = event.get("text", "")
                stash = event.get("stash", "")
                full_text = text + stash
                response_data = {
                    "type": "result",
                    "transcription": {
                        "text": full_text,
                        "is_final": False
                    }
                }
                asyncio.run_coroutine_threadsafe(
                    self.websocket.send_json(response_data),
                    self.loop
                )
                return

            # input_audio_buffer.speech_started → 语音开始
            if event_type == "input_audio_buffer.speech_started":
                response_data = {
                    "type": "speech_started"
                }
                asyncio.run_coroutine_threadsafe(
                    self.websocket.send_json(response_data),
                    self.loop
                )
                return

            # input_audio_buffer.speech_stopped → 语音停止
            if event_type == "input_audio_buffer.speech_stopped":
                response_data = {
                    "type": "speech_stopped"
                }
                asyncio.run_coroutine_threadsafe(
                    self.websocket.send_json(response_data),
                    self.loop
                )
                return

        except json.JSONDecodeError:
            print(f"[Error] Failed to parse event as JSON: {message[:200]}")
        except Exception as e:
            print(f"[Error] Exception in on_event: {e}")
