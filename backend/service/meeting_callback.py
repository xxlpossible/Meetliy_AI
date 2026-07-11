"""
会议感知的 DashScope 实时 ASR 回调。

设计说明：
    现有 realtime_asr.WebSocketCallback 将识别结果只发给当前 WebSocket（单用户）。
    会议场景下，每个参会者各自有一条 DashScope 会话，但识别结果需带说话人标签
    广播给房间内所有人。本回调在 on_event 中调用 MeetingManager.broadcast_transcript
    完成广播，而非直接 send_json。

    本类不改动现有 WebSocketCallback，单用户路径继续使用原回调。
"""
import json
from loguru import logger
import dashscope
from dashscope.audio.qwen_omni import OmniRealtimeCallback
from settings import settings


# 设置 APIKEY（与 realtime_asr.py 一致）
dashscope_config = settings.get_dashscope_config()
dashscope.api_key = dashscope_config.get("api_key")


class MeetingCallback(OmniRealtimeCallback):
    """
    会议模式回调：将 DashScope 识别事件转换为带说话人标签的房间广播消息。
    SDK 在子线程调用 on_event，广播通过 MeetingManager 内的
    asyncio.run_coroutine_threadsafe 跨线程调度。
    """

    def __init__(self, manager, meeting_id: str, user_id: int, username: str):
        super().__init__()
        self.manager = manager
        self.meeting_id = meeting_id
        self.user_id = user_id
        self.username = username
        self.session_id = None

    def on_open(self) -> None:
        logger.info(f"[Meeting] DashScope Recognition Started. user={self.username}")

    def on_close(self, close_status_code, close_msg) -> None:
        logger.info(f"[Meeting] DashScope Recognition Closed. user={self.username} code={close_status_code}")

    def on_event(self, message) -> None:
        try:
            if isinstance(message, str):
                event = json.loads(message)
            elif isinstance(message, dict):
                event = message
            else:
                return
            event_type = event.get("type", "")

            # session.created
            if event_type == "session.created":
                self.session_id = event.get("session", {}).get("id")
                logger.info(f"[Meeting] Session created: {self.session_id} user={self.username}")
                return

            # 最终识别结果 → 广播 is_final=True
            if event_type == "conversation.item.input_audio_transcription.completed":
                transcript = event.get("transcript", "")
                self.manager.broadcast_transcript(
                    self.meeting_id, self.user_id, self.username, transcript, is_final=True
                )
                return

            # 中间识别结果 → 广播 is_final=False
            if event_type == "conversation.item.input_audio_transcription.text":
                text = event.get("text", "")
                stash = event.get("stash", "")
                full_text = text + stash
                self.manager.broadcast_transcript(
                    self.meeting_id, self.user_id, self.username, full_text, is_final=False
                )
                return

            # VAD 语音开始
            if event_type == "input_audio_buffer.speech_started":
                self.manager.broadcast_speech_event(
                    self.meeting_id, self.user_id, started=True
                )
                return

            # VAD 语音停止
            if event_type == "input_audio_buffer.speech_stopped":
                self.manager.broadcast_speech_event(
                    self.meeting_id, self.user_id, started=False
                )
                return

        except json.JSONDecodeError:
            logger.error(f"[Meeting] Failed to parse event: {str(message)[:200]}")
        except Exception as e:
            logger.error(f"[Meeting] Exception in on_event: {e}")
