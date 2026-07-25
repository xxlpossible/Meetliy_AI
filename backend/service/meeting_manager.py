"""
会议房间内存管理器。

设计说明：
    DB 的 Meeting 表管会议的生命周期持久化，本类管会议进行中的实时连接状态：
    参会者的 WebSocket、DashScope 会话、PCM 录音文件、加入时间偏移等。
    DashScope 回调在子线程执行，广播转写结果时需通过各参会者自己的事件循环
    (asyncio.run_coroutine_threadsafe) 调度 send，保证线程安全。

线程安全：
    participants 字典的增删加 threading.Lock；遍历时取 list 快照避免
    "dict changed size during iteration"。
"""
import asyncio
import json
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional, Dict, List

from fastapi import WebSocket
from loguru import logger


# 录音文件存放目录
AUDIO_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "meeting_audio"
)


@dataclass
class ParticipantConnection:
    """单个参会者的实时连接状态。"""
    websocket: WebSocket
    user_id: int
    username: str
    conversation: object  # OmniRealtimeConversation
    audio_file: object  # 已打开的二进制写入句柄
    audio_file_path: str
    join_offset_seconds: float  # 相对会议开始的偏移(秒)，用于 ffmpeg adelay 对齐
    loop: asyncio.AbstractEventLoop  # 该参会者所在的事件循环


@dataclass
class MeetingRoom:
    """一个活跃的会议房间。"""
    meeting_id: str
    started_at: float  # time.time()，会议房间创建时刻
    participants: Dict[int, ParticipantConnection] = field(default_factory=dict)
    # 录音信息注册表：user_id -> {user_id, username, audio_file_path, join_offset_seconds}
    # 即使参会者离开（从 participants 移除），录音记录仍保留，供会议结束时合并使用
    recordings: Dict[int, dict] = field(default_factory=dict)
    # 实时转录文本行（会议结束后持久化到 DB，内存临时存储）
    transcript_lines: List[str] = field(default_factory=list)


class MeetingManager:
    """单例：管理所有活跃会议房间。"""

    _instance = None
    _instance_lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    obj = super().__new__(cls)
                    obj._rooms: Dict[str, MeetingRoom] = {}
                    obj._rooms_lock = threading.Lock()
                    obj._ensure_audio_dir()
                    cls._instance = obj
        return cls._instance

    @staticmethod
    def _ensure_audio_dir():
        os.makedirs(AUDIO_DIR, exist_ok=True)

    # ------------------------------------------------------------------ #
    #  房间 / 参会者 生命周期
    # ------------------------------------------------------------------ #

    def create_room(self, meeting_id: str) -> MeetingRoom:
        """创建房间（若已存在则返回现有）。"""
        with self._rooms_lock:
            if meeting_id not in self._rooms:
                self._rooms[meeting_id] = MeetingRoom(
                    meeting_id=meeting_id,
                    started_at=time.time()
                )
                logger.info(f"创建会议房间: {meeting_id}")
            return self._rooms[meeting_id]

    def room_exists(self, meeting_id: str) -> bool:
        with self._rooms_lock:
            return meeting_id in self._rooms

    def get_room(self, meeting_id: str) -> Optional[MeetingRoom]:
        """获取房间引用（不移除）。"""
        with self._rooms_lock:
            return self._rooms.get(meeting_id)

    def add_participant(
        self,
        meeting_id: str,
        websocket: WebSocket,
        user_id: int,
        username: str,
        conversation: object,
        loop: asyncio.AbstractEventLoop,
    ) -> ParticipantConnection:
        """参会者加入房间：打开 PCM 录音文件，计算加入偏移。"""
        room = self.create_room(meeting_id)

        audio_file_path = os.path.join(AUDIO_DIR, f"{meeting_id}_{user_id}.pcm")
        audio_file = open(audio_file_path, "wb")
        join_offset = time.time() - room.started_at

        conn = ParticipantConnection(
            websocket=websocket,
            user_id=user_id,
            username=username,
            conversation=conversation,
            audio_file=audio_file,
            audio_file_path=audio_file_path,
            join_offset_seconds=join_offset,
            loop=loop,
        )

        with self._rooms_lock:
            room.participants[user_id] = conn
            # 注册录音信息（持久保留至房间销毁，供 end_meeting 收集）
            room.recordings[user_id] = {
                "user_id": user_id,
                "username": username,
                "audio_file_path": audio_file_path,
                "join_offset_seconds": join_offset,
            }

        logger.info(f"参会者加入会议 {meeting_id}: user_id={user_id} username={username} offset={join_offset:.2f}s")
        return conn

    def remove_participant(self, meeting_id: str, user_id: int):
        """
        参会者离开：关闭 PCM 文件与 DashScope 会话，从房间移除，广播离开事件。
        返回 (conn, is_last_participant)，is_last 表示该参会者离开后房间是否已空。
        """
        with self._rooms_lock:
            room = self._rooms.get(meeting_id)
            if not room:
                return None, False
            conn = room.participants.pop(user_id, None)
            is_last = len(room.participants) == 0

        if conn is None:
            return None, False

        # 关闭 PCM 录音文件
        try:
            conn.audio_file.close()
        except Exception as e:
            logger.warning(f"关闭 PCM 文件失败: {e}")

        # 关闭 DashScope 会话
        try:
            conn.conversation.end_session()
        except Exception:
            pass
        try:
            conn.conversation.close()
        except Exception:
            pass

        # 广播离开事件
        self.broadcast_participant_event(meeting_id, conn.user_id, conn.username, joined=False)

        logger.info(f"参会者离开会议 {meeting_id}: user_id={user_id}")

        # 房间空了不立即清理，由调用方（stt.py 的 _auto_end_meeting 或 end_meeting）
        # 在合并录音后通过 end_meeting 统一清理，确保不丢失录音信息
        return conn, is_last

    def get_participants(self, meeting_id: str) -> List[dict]:
        """返回房间内当前活跃参会者列表 [{id, name}]。"""
        with self._rooms_lock:
            room = self._rooms.get(meeting_id)
            if not room:
                return []
            return [{"id": c.user_id, "name": c.username}
                    for c in room.participants.values()]

    def write_audio_chunk(self, meeting_id: str, user_id: int, data: bytes):
        """将一段 PCM 写入参会者的录音文件。"""
        with self._rooms_lock:
            room = self._rooms.get(meeting_id)
            conn = room.participants.get(user_id) if room else None
        if conn and conn.audio_file and not conn.audio_file.closed:
            conn.audio_file.write(data)

    def add_transcript_line(self, meeting_id: str, text: str):
        """向指定会议的转录文本列表追加一行。"""
        with self._rooms_lock:
            room = self._rooms.get(meeting_id)
            if room:
                room.transcript_lines.append(text)

    def get_transcript_lines(self, meeting_id: str) -> List[str]:
        """获取转录文本行列表（原始列表，不拼接）。"""
        with self._rooms_lock:
            room = self._rooms.get(meeting_id)
            if room:
                return list(room.transcript_lines)
        return []

    # ------------------------------------------------------------------ #
    #  广播 / 信令路由（可被子线程回调调用）
    # ------------------------------------------------------------------ #

    def _send_to_participant(self, conn: ParticipantConnection, message: dict):
        """线程安全地向某个参会者的 WebSocket 发送 JSON。"""
        try:
            asyncio.run_coroutine_threadsafe(
                conn.websocket.send_json(message),
                conn.loop
            )
        except Exception as e:
            logger.warning(f"发送消息失败 (user_id={conn.user_id}): {e}")

    def broadcast_transcript(
        self,
        meeting_id: str,
        speaker_id: int,
        speaker_name: str,
        text: str,
        is_final: bool,
    ):
        """向房间内所有参会者广播转写结果（带说话人标签）。"""
        message = {
            "type": "transcript",
            "speaker_id": speaker_id,
            "speaker_name": speaker_name,
            "text": text,
            "is_final": is_final,
        }
        with self._rooms_lock:
            room = self._rooms.get(meeting_id)
            participants = list(room.participants.values()) if room else []
        for conn in participants:
            self._send_to_participant(conn, message)

    def broadcast_speech_event(self, meeting_id: str, speaker_id: int, started: bool):
        """广播 VAD 语音开始/停止事件（带说话人标签）。"""
        message = {
            "type": "speech_started" if started else "speech_stopped",
            "speaker_id": speaker_id,
        }
        with self._rooms_lock:
            room = self._rooms.get(meeting_id)
            participants = list(room.participants.values()) if room else []
        for conn in participants:
            self._send_to_participant(conn, message)

    def route_signal(
        self,
        meeting_id: str,
        from_user_id: int,
        from_username: str,
        to_user_id: int,
        signal_type: str,
        data,
    ):
        """将 WebRTC 信令路由给指定目标参会者。"""
        message = {
            "type": "signal",
            "from": from_user_id,
            "from_name": from_username,
            "signal_type": signal_type,
            "data": data,
        }
        with self._rooms_lock:
            room = self._rooms.get(meeting_id)
            conn = room.participants.get(to_user_id) if room else None
        if conn:
            self._send_to_participant(conn, message)

    def broadcast_participant_event(
        self, meeting_id: str, user_id: int, username: str, joined: bool
    ):
        """广播参会者加入/离开事件。"""
        message = {
            "type": "participant_joined" if joined else "participant_left",
            "user": {"id": user_id, "name": username},
        }
        with self._rooms_lock:
            room = self._rooms.get(meeting_id)
            participants = list(room.participants.values()) if room else []
        for conn in participants:
            # 不给刚加入/离开的自己发
            if conn.user_id == user_id:
                continue
            self._send_to_participant(conn, message)

    def broadcast_meeting_ended(self, meeting_id: str, task_id: str):
        """广播会议结束事件。"""
        message = {"type": "meeting_ended", "meeting_id": meeting_id, "task_id": task_id}
        with self._rooms_lock:
            room = self._rooms.get(meeting_id)
            participants = list(room.participants.values()) if room else []
        for conn in participants:
            self._send_to_participant(conn, message)

    # ------------------------------------------------------------------ #
    #  结束会议（收集录音信息）
    # ------------------------------------------------------------------ #

    def end_meeting(self, meeting_id: str) -> List[dict]:
        """
        结束会议：关闭所有参会者连接与 PCM 文件，返回录音信息供合并。
        返回所有已注册录音 [{user_id, audio_file_path, join_offset_seconds}]，
        包括已离会的参会者（录音文件已关闭，但仍参与合并）。
        """
        with self._rooms_lock:
            room = self._rooms.pop(meeting_id, None)

        if room is None:
            logger.warning(f"结束会议时房间不存在: {meeting_id}")
            return []

        # 关闭仍在房间的参会者的连接和 PCM 文件
        for conn in room.participants.values():
            try:
                if conn.audio_file and not conn.audio_file.closed:
                    conn.audio_file.close()
            except Exception as e:
                logger.warning(f"关闭 PCM 文件失败 (user_id={conn.user_id}): {e}")

            try:
                conn.conversation.end_session()
            except Exception:
                pass
            try:
                conn.conversation.close()
            except Exception:
                pass

        # 收集所有录音（含已离会者）
        participants_info = list(room.recordings.values())
        logger.info(f"会议 {meeting_id} 已结束，收集到 {len(participants_info)} 路录音（当前在线 {len(room.participants)} 人）")
        return participants_info


    def is_last_participant(self, meeting_id: str) -> bool:
        """检查房间内是否只剩一个参会者（用于判断最后一人离开时是否需要自动结束）。"""
        with self._rooms_lock:
            room = self._rooms.get(meeting_id)
            return room is not None and len(room.participants) == 1


# 全局单例
meeting_manager = MeetingManager()
