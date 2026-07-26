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
import time

import dashscope
from dashscope.audio.qwen_omni import OmniRealtimeCallback
from loguru import logger

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

    def __init__(self, manager, meeting_id: str, user_id: int, username: str, room_started_at: float):
        super().__init__()
        self.manager = manager
        self.meeting_id = meeting_id
        self.user_id = user_id
        self.username = username
        self.session_id = None
        # 会议房间创建时的 time.time()，用于计算相对时间戳
        self._room_started_at = room_started_at
        # 当前正在识别的句子开始时间（相对会议开始，秒）
        self._speech_start_elapsed: float | None = None

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

            # 最终识别结果 → 广播 is_final=True，同时存入内存
            if event_type == "conversation.item.input_audio_transcription.completed":
                transcript = event.get("transcript", "")
                self.manager.broadcast_transcript(
                    self.meeting_id, self.user_id, self.username, transcript, is_final=True
                )
                # 持久化完整文本到内存
                self._persist_transcript(transcript)
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
                # 记录句子开始时间（相对会议开始）
                self._speech_start_elapsed = time.time() - self._room_started_at
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

    def _persist_transcript(self, transcript: str) -> None:
        """将完整转录文本以 [MM:SS ~ MM:SS] [username]: text 格式存入内存。"""
        try:
            end_elapsed = time.time() - self._room_started_at
            start_elapsed = self._speech_start_elapsed if self._speech_start_elapsed else end_elapsed
            # 格式化为 [MM:SS]（从会议开始计算的经过时间）
            start_str = self._format_elapsed(start_elapsed)
            end_str = self._format_elapsed(end_elapsed)
            # 组装文本
            formatted = f"[{start_str} ~ {end_str}] [{self.username}]: {transcript}"
            # 存入 MeetingManager 的内存
            self.manager.add_transcript_line(self.meeting_id, formatted)
            logger.debug(f"[Meeting] 转录已持久化: {formatted[:80]}...")
        except Exception as e:
            logger.warning(f"[Meeting] 持久化转录失败: {e}")
        finally:
            # 重置句子开始时间
            self._speech_start_elapsed = None

    @staticmethod
    def _format_elapsed(seconds: float) -> str:
        """将秒数格式化为 MM:SS（从会议开始计算）。"""
        total = int(seconds)
        minutes = total // 60
        secs = total % 60
        return f"{minutes:02d}:{secs:02d}"
