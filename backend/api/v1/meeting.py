"""
会议管理 REST 接口：创建 / 加入 / 参与者列表 / 结束 / 列表。

路由前缀 /api/v1/meeting（router.py 的 /api/v1 + 本文件 /meeting）。
"""
import asyncio
import os
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends
from loguru import logger
from pydantic import BaseModel

from api.schemas import resp_200
from database.models.meeting import Meeting, MeetingDao, MeetingStatus
from database.models.transcription import Transcription, TranscriptionDao, Status, Delete
from database.models.user import User, UserDao
from service.meeting_manager import meeting_manager, AUDIO_DIR
from service import audio_merger
from task.tasks import transcription
from utils.dependencies import get_current_user
from utils.uploader import TmpFilesUploader

router = APIRouter(prefix="/meeting", tags=["会议"])


# ----------------------------- 请求体 ----------------------------- #

class CreateMeetingRequest(BaseModel):
    meeting_name: Optional[str] = None


# ----------------------------- 接口 ----------------------------- #

@router.post("/create", summary="创建会议")
async def create_meeting(
        body: CreateMeetingRequest,
        current_user: User = Depends(get_current_user),
):
    """会议发起人创建一场新会议，返回会议ID。"""
    meeting_id = uuid.uuid4().hex
    meeting = Meeting(
        id=meeting_id,
        meeting_name=body.meeting_name or f"{current_user.username}的会议",
        host_user_id=current_user.id,
        user_ids=[current_user.id],
        status=MeetingStatus.ACTIVE.value,
        task_id=None,
    )
    MeetingDao.add(meeting)
    logger.info(f"创建会议: id={meeting_id} host={current_user.username} name={meeting.meeting_name}")
    return resp_200(data={
        "meeting_id": meeting_id,
        "meeting_name": meeting.meeting_name,
        "host_user_id": current_user.id,
    })


@router.post("/{meeting_id}/join", summary="加入会议")
async def join_meeting(
        meeting_id: str,
        current_user: User = Depends(get_current_user),
):
    """参会者加入会议：写入 user_ids，返回当前活跃参会者列表（供 WebRTC mesh 建连）。"""
    meeting = MeetingDao.get_by_id(m_id=meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="会议不存在")
    if meeting.status != MeetingStatus.ACTIVE.value:
        raise HTTPException(status_code=400, detail="会议已结束")

    # 加入会议（追加到 user_ids）
    MeetingDao.add_participant(meeting_id, current_user.id)

    # 返回当前活跃参会者（含自己，前端据此发起 WebRTC mesh）
    active = meeting_manager.get_participants(meeting_id)
    if not active:
        # 房间尚未有人连入 WS，从 DB user_ids 查用户信息
        active = []
        for uid in meeting.user_ids:
            u = UserDao.get_by_id(uid)
            if u:
                active.append({"id": u.id, "name": u.username})

    return resp_200(data={
        "meeting_id": meeting_id,
        "meeting_name": meeting.meeting_name,
        "host_user_id": meeting.host_user_id,
        "is_host": meeting.host_user_id == current_user.id,
        "participants": active,
    })


@router.get("/{meeting_id}/participants", summary="获取会议活跃参会者")
async def get_participants(
        meeting_id: str,
        current_user: User = Depends(get_current_user),
):
    """获取会议当前活跃参会者列表。"""
    meeting = MeetingDao.get_by_id(m_id=meeting_id, user_id=current_user.id)
    if not meeting:
        raise HTTPException(status_code=403, detail="无权访问或会议不存在")

    active = meeting_manager.get_participants(meeting_id)
    return resp_200(data={"participants": active})


@router.post("/{meeting_id}/end", summary="结束会议（仅主持人）")
async def end_meeting(
        meeting_id: str,
        current_user: User = Depends(get_current_user),
):
    """
    主持人结束会议：
    1. 关闭所有参会者连接与 PCM 录音
    2. ffmpeg 合并多路音频为 MP3
    3. 上传 OSS 获取公网 URL
    4. 创建 Transcription 记录（user_ids = 全体参会者）
    5. 触发 Celery 转录任务（整段转写 + 说话人分离 + AI 纪要）
    6. 更新 Meeting 状态 + 关联 task_id
    7. 广播 meeting_ended 给全体参会者
    """
    meeting = MeetingDao.get_by_id(m_id=meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="会议不存在")
    if meeting.host_user_id != current_user.id:
        raise HTTPException(status_code=403, detail="仅主持人可结束会议")
    if meeting.status != MeetingStatus.ACTIVE.value:
        raise HTTPException(status_code=400, detail="会议已结束")

    # 1. 关闭所有连接，收集录音信息（从内存房间）
    participants_info = meeting_manager.end_meeting(meeting_id)
    logger.info(f"会议 {meeting_id} 收集到 {len(participants_info)} 路录音")

    if not participants_info:
        raise HTTPException(status_code=400, detail="会议无录音数据")

    # 执行共享的结束会议逻辑
    task_id = await _execute_end_meeting(meeting_id, participants_info, meeting)

    return resp_200(data={"task_id": task_id}, message="会议已结束，正在生成纪要")


async def auto_end_meeting(meeting_id: str) -> bool:
    """
    自动结束会议：当最后一名参会者离开房间时调用。
    
    与房主主动结束的区别：
    - 不做权限校验（非主动调用）
    - 会议状态和录音信息都已存在，只执行合并+上传+触发任务
    
    需要复用 _execute_end_meeting 的合并+上传逻辑。
    返回是否成功触发了转录任务。
    """
    # 查会议（不带 user_id 过滤，因为是系统内部调用）
    meeting = MeetingDao.get_by_id(m_id=meeting_id)
    if not meeting:
        logger.warning(f"[AutoEnd] 会议不存在: {meeting_id}")
        return False
    
    if meeting.status != MeetingStatus.ACTIVE.value:
        logger.info(f"[AutoEnd] 会议已结束或异常，跳过: {meeting_id} status={meeting.status}")
        return False
    
    # 安全校验：最后一人已离开，房间应为空（或不存在）
    if meeting_manager.room_exists(meeting_id):
        participants = meeting_manager.get_participants(meeting_id)
        if len(participants) > 0:
            logger.warning(f"[AutoEnd] 房间仍有参会者，不自动结束: {meeting_id}")
            return False
    
    # 收集录音信息（如果房间还存在，end_meeting 会清理房间录音）
    participants_info = meeting_manager.end_meeting(meeting_id)
    logger.info(f"[AutoEnd] 会议 {meeting_id} 自动结束，收集到 {len(participants_info)} 路录音")
    
    if not participants_info:
        logger.warning(f"[AutoEnd] 会议无录音数据，标为异常: {meeting_id}")
        MeetingDao.update_status(meeting_id, MeetingStatus.ERROR.value)
        return False
    
    # 复用 _execute_end_meeting 的合并+上传+任务逻辑
    task_id = await _execute_end_meeting(meeting_id, participants_info, meeting)
    logger.info(f"[AutoEnd] 会议 {meeting_id} 自动结束成功，task_id={task_id}")
    return True


async def _execute_end_meeting(
        meeting_id: str,
        participants_info: list,
        meeting: Meeting,
) -> str:
    """
    结束会议的核心逻辑：合并音频、OSS上传、创建Transcription、触发Celery、更新DB。
    供房主主动结束（end_meeting）和最后一人自动结束（auto_end）复用。
    返回 task_id。
    """
    # 2-3. ffmpeg 合并 + OSS 上传（耗时操作，放线程池避免阻塞事件循环）
    def _merge_and_upload():
        merged_path = audio_merger.merge(participants_info)
        public_url = TmpFilesUploader.upload_from_temp_path(temp_path=merged_path)
        # 清理合并后的 mp3（PCM 原始文件保留排查）
        try:
            os.remove(merged_path)
        except Exception:
            pass
        return public_url

    try:
        public_url = await asyncio.to_thread(_merge_and_upload)
    except Exception as e:
        logger.exception("音频合并/上传失败")
        MeetingDao.update_status(meeting_id, MeetingStatus.ERROR.value)
        raise HTTPException(status_code=500, detail=f"音频处理失败: {e}")

    # 上传成功后，删除所有 PCM 原始音频文件（mp3 已上传到 OSS 并保存 URL）
    _cleanup_pcm_files(meeting_id, participants_info)

    # 4. 创建 Transcription 记录（全体参会者有权访问）
    t_id = uuid.uuid4().hex
    TranscriptionDao.add(Transcription(
        id=t_id,
        task_name=meeting.meeting_name,
        user_ids=meeting.user_ids,
        status=Status.PENDING.value,
        task_result=None,
        is_delete=Delete.NOT.value,
        file_url=public_url,
    ))

    # 5. 触发 Celery 转录任务
    transcription.delay(public_url, t_id)
    logger.info(f"会议 {meeting_id} 转录任务已提交: task_id={t_id}")

    # 6. 更新 Meeting 状态
    MeetingDao.update_status(meeting_id, MeetingStatus.ENDED.value)
    MeetingDao.update_task_id(meeting_id, t_id)

    # 7. 广播会议结束（此时连接可能已被 end_meeting 关闭，尽力发送）
    meeting_manager.broadcast_meeting_ended(meeting_id, t_id)
    return t_id


def _cleanup_pcm_files(meeting_id: str, participants_info: list):
    """
    会议结束后清理本地 PCM 录音文件。
    合并后的 mp3 已上传 OSS（URL 保存在 Transcription.file_url），无需保留本地原始 PCM。
    audio_merger.merge 内部已清理其生成的临时 WAV 文件，此处只清理服务端录音的 PCM 文件。
    """
    for p in participants_info:
        pcm_path = p.get("audio_file_path")
        if pcm_path and os.path.exists(pcm_path):
            try:
                os.remove(pcm_path)
                logger.info(f"已删除 PCM 文件: {pcm_path}")
            except Exception as e:
                logger.warning(f"删除 PCM 文件失败: {pcm_path}, {e}")


@router.get("/list", summary="我的会议列表")
async def list_meetings(
        current_user: User = Depends(get_current_user),
):
    """查询当前用户参加的会议列表。"""
    results, total = MeetingDao.list(user_id=current_user.id)
    data = []
    for m in results:
        data.append({
            "id": m.id,
            "meeting_name": m.meeting_name,
            "host_user_id": m.host_user_id,
            "status": m.status,
            "task_id": m.task_id,
            "create_time": m.create_time.strftime("%Y-%m-%d %H:%M:%S") if m.create_time else None,
        })
    return resp_200(data={"data": data, "total": total})
