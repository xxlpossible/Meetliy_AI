"""
会议管理 REST 接口：创建 / 加入 / 参与者列表 / 结束 / 列表。

路由前缀 /api/v1/meeting（router.py 的 /api/v1 + 本文件 /meeting）。
"""
import asyncio
import base64
import json
import os
import tempfile
import time
import uuid

import aiofiles
from dashscope.audio.qwen_omni import MultiModality, OmniRealtimeConversation
from dashscope.audio.qwen_omni.omni_realtime import TranscriptionParams
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from loguru import logger
from pydantic import BaseModel

from api.schemas import resp_200
from database.models.meeting import Meeting, MeetingDao, MeetingDelete, MeetingStatus
from database.models.transcription import (
    Delete,
    Status,
    Transcription,
    TranscriptionDao,
)
from database.models.user import User, UserDao
from service import audio_merger
from service.meeting_callback import MeetingCallback
from service.meeting_manager import meeting_manager
from settings import settings
from task.tasks import transcription
from utils.dependencies import get_current_user
from utils.security import TOKEN_TYPE_ACCESS, decode_token
from utils.uploader import TmpFilesUploader

router = APIRouter(prefix="/meeting", tags=["会议"])


# ----------------------------- 请求体 ----------------------------- #

class CreateMeetingRequest(BaseModel):
    meeting_name: str | None = None
    need_summary: bool | None = True  # 会议结束后是否需要生成纪要，默认需要


class MeetingListRequest(BaseModel):
    page_num: int = 1
    page_size: int = 10
    meeting_name: str | None = None


class MeetingStatusRequest(BaseModel):
    meeting_ids: list[str]


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
        need_summary=body.need_summary,
    )
    MeetingDao.add(meeting)
    logger.info(f"创建会议: id={meeting_id} host={current_user.username} name={meeting.meeting_name}")
    return resp_200(data={
        "meeting_id": meeting_id,
        "meeting_name": meeting.meeting_name,
        "host_user_id": current_user.id,
        "need_summary": meeting.need_summary,
    })


@router.post("/list", summary="我的会议列表")
async def list_meetings(
        body: MeetingListRequest,
        current_user: User = Depends(get_current_user),
):
    """查询当前用户参加的会议列表（分页）。"""
    results, total = MeetingDao.list(
        user_id=current_user.id,
        page_num=body.page_num,
        page_size=body.page_size,
        meeting_name=body.meeting_name
    )
    data = []
    for m in results:
        data.append({
            "id": m.id,
            "meeting_name": m.meeting_name,
            "host_user_id": m.host_user_id,
            "status": m.status,
            "task_id": m.task_id,
            "need_summary": m.need_summary if m.need_summary is not None else True,
            "create_time": m.create_time.strftime("%Y-%m-%d %H:%M:%S") if m.create_time else None,
        })
    return resp_200(data={"data": data, "total": total})


@router.get("/statistics", summary="会议状态分布统计")
async def meeting_statistics(
        current_user: User = Depends(get_current_user),
):
    """
    统计所有会议的状态数量分布，供前端 DashBoard 数字仪表盘使用。
    返回会议总数，以及解析完成 / 解析中 / 解析异常（含会议进行中）的数量。
    """
    dist = MeetingDao.count_status_distribution(current_user.id)
    total = sum(dist.values())
    return resp_200(data={
        "total": total,
        # 会议进行中（尚未结束、未进入解析）
        "active": dist.get(MeetingStatus.ACTIVE.value, 0),
        # 解析中：会议已结束，正在后台解析（END_AND_ANALYZE）
        "analyzing": dist.get(MeetingStatus.END_AND_ANALYZE.value, 0),
        # 解析完成（FINISH）
        "finished": dist.get(MeetingStatus.FINISH.value, 0),
        # 解析异常（ERROR）
        "error": dist.get(MeetingStatus.ERROR.value, 0),
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


@router.post("/status", summary="批量查询会议状态（轮询）")
async def get_meeting_status(
        body: MeetingStatusRequest,
        current_user: User = Depends(get_current_user),
):
    """
    批量查询会议当前状态，供前端轮询后台解析进度。
    传入 meeting_ids 列表，返回每个会议的状态码、状态描述、关联 task_id。
    """
    meeting_ids = body.meeting_ids
    if not meeting_ids:
        raise HTTPException(status_code=400, detail="meeting_ids 不能为空")

    status_labels = {
        MeetingStatus.ACTIVE.value: "会议进行中",
        MeetingStatus.END_AND_ANALYZE.value: "后台解析中",
        MeetingStatus.FINISH.value: "解析完成",
        MeetingStatus.ERROR.value: "解析异常",
    }

    results = []
    for m_id in meeting_ids:
        meeting = MeetingDao.get_by_id(m_id=m_id, user_id=current_user.id)
        if not meeting:
            continue
        results.append({
            "meeting_id": meeting.id,
            "meeting_name": meeting.meeting_name,
            "status": meeting.status,
            "status_label": status_labels.get(meeting.status, "未知状态"),
            "task_id": meeting.task_id,
            "need_summary": meeting.need_summary if meeting.need_summary is not None else True,
        })

    return resp_200(data=results)


@router.get("/{meeting_id}/result", summary="查询会议解析结果")
async def get_meeting_result(
        meeting_id: str,
        task_id: str | None = Query(None),
        current_user: User = Depends(get_current_user),
):
    """
    根据 meeting_id 和 task_id 查询后台任务解析的详细结果。
    校验用户对 meeting 的访问权限后，通过 TranscriptionDao.get_by_id 获取完整结果。
    """
    meeting = MeetingDao.get_by_id(m_id=meeting_id, user_id=current_user.id)
    if not meeting:
        raise HTTPException(status_code=403, detail="无权访问或会议不存在")

    # 未传 task_id 则取 meeting 关联的 task_id
    query_task_id = task_id or meeting.task_id
    if not query_task_id:
        raise HTTPException(status_code=400, detail="会议暂无解析任务")

    # 若传了 task_id，校验与 meeting 绑定的 task_id 一致（防止越权）
    if task_id and task_id != meeting.task_id:
        raise HTTPException(status_code=403, detail="task_id 与会议不匹配")

    transcription = TranscriptionDao.get_by_id(t_id=query_task_id, user_id=current_user.id)
    if not transcription:
        raise HTTPException(status_code=404, detail="解析结果不存在")

    return resp_200(data={
        "meeting_id": meeting.id,
        "meeting_name": meeting.meeting_name,
        "task_id": transcription.id,
        "task_name": transcription.task_name,
        "status": transcription.status,
        "task_result": transcription.task_result,
        "file_url": transcription.file_url,
        "realtime_asr_text": transcription.realtime_asr_text,
        "need_summary": meeting.need_summary if meeting.need_summary is not None else True,
        "create_time": transcription.create_time.strftime("%Y-%m-%d %H:%M:%S") if transcription.create_time else None,
        "update_time": transcription.update_time.strftime("%Y-%m-%d %H:%M:%S") if transcription.update_time else None,
    })


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

    # 0. 先广播 meeting_ended（必须在 end_meeting pop 房间之前），
    #    确保剩余参会者收到通知立刻停止音频并退出会议室
    t_id = uuid.uuid4().hex
    meeting_manager.broadcast_meeting_ended(meeting_id, t_id)

    # 1. 读取实时转录文本（必须在 end_meeting 之前，因为 end_meeting 会 pop 掉房间）
    realtime_lines = meeting_manager.get_transcript_lines(meeting_id)
    logger.info(f"会议 {meeting_id} 读取到 {len(realtime_lines)} 行实时转录文本")

    # 2. 关闭所有连接，收集录音信息（从内存房间）
    participants_info = meeting_manager.end_meeting(meeting_id)
    logger.info(f"会议 {meeting_id} 收集到 {len(participants_info)} 路录音")

    if not participants_info:
        raise HTTPException(status_code=400, detail="会议无录音数据")

    # 执行共享的结束会议逻辑（使用预生成的 t_id）
    task_id = await _execute_end_meeting(meeting_id, participants_info, meeting, realtime_lines, t_id)

    if task_id:
        if meeting.need_summary:
            return resp_200(data={"task_id": task_id, "need_summary": True}, message="会议已结束，正在生成纪要")
        else:
            return resp_200(data={"task_id": task_id, "need_summary": False}, message="会议已结束")
    else:
        return resp_200(data={"task_id": None, "need_summary": meeting.need_summary}, message="会议已结束")


@router.delete("/{meeting_id}", summary="软删除会议（仅主持人）")
async def delete_meeting(
        meeting_id: str,
        current_user: User = Depends(get_current_user),
):
    """
    软删除会议：将 is_delete 设为 -1，同时联动软删除关联的 Transcription。
    仅主持人可操作。
    """
    meeting = MeetingDao.get_by_id(m_id=meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="会议不存在")
    if meeting.host_user_id != current_user.id:
        raise HTTPException(status_code=403, detail="仅主持人可删除会议")
    if meeting.is_delete == MeetingDelete.DELETED.value:
        raise HTTPException(status_code=400, detail="会议已被删除")

    # 软删除 Meeting
    success = MeetingDao.soft_delete(meeting_id, user_id=current_user.id)
    if not success:
        raise HTTPException(status_code=500, detail="删除会议失败")

    # 联动软删除关联的 Transcription
    if meeting.task_id:
        TranscriptionDao.soft_delete_by_task_id(meeting.task_id)
        logger.info(f"会议 {meeting_id} 已软删除，联动删除转录记录 {meeting.task_id}")
    else:
        logger.info(f"会议 {meeting_id} 已软删除（无关联转录记录）")

    return resp_200(message="会议已删除")


@router.post('/start_task', description="上传语音文件")
async def upload_file(
        audio_file: UploadFile = File(...),
        task_name: str | None = Form(None),
        current_user: User = Depends(get_current_user)
):
    # 获取原始文件扩展名（如 .mp3 / .wav）
    file_ext = os.path.splitext(audio_file.filename)[1] or ".mp3"

    # 生成唯一临时文件名
    temp_filename = f"{uuid.uuid4().hex}{file_ext}"

    # 创建完整临时文件路径
    tmp_path = os.path.join(tempfile.gettempdir(), temp_filename)

    logger.info(f"⬇️ 接口调用成功，开始接收上传语音文件: {audio_file.filename}")
    logger.info(f"📁 临时文件路径: {tmp_path}")

    try:
        # Step 1. 异步写入临时文件
        async with aiofiles.open(tmp_path, "wb") as f:
            while chunk := await audio_file.read(8192):
                await f.write(chunk)

        logger.info(f"✅ 文件已保存到临时路径: {tmp_path}")

        # Step 2. 根据临时文件的保存路径 获取公网的文件地址 public_url
        public_url = TmpFilesUploader.upload_from_temp_path(temp_path=tmp_path)

        # 创建任务对象（绑定当前用户为首个有权用户）
        t_id = uuid.uuid4().hex
        TranscriptionDao.add(Transcription(
            id=t_id,
            task_name=task_name,
            user_ids=[current_user.id],
            status=Status.PENDING.value,
            task_result=None,
            is_delete=Delete.NOT.value
        ))

        # 同步创建 Meeting 记录，状态为 END_AND_ANALYZE
        # 上传语音文件场景下，无需实时会议流程，直接进入后台解析
        meeting_id = uuid.uuid4().hex
        MeetingDao.add(Meeting(
            id=meeting_id,
            meeting_name=task_name or f"{current_user.username}的语音会议",
            host_user_id=current_user.id,
            user_ids=[current_user.id],
            status=MeetingStatus.END_AND_ANALYZE.value,
            task_id=t_id,
            need_summary=True,
        ))
        logger.info(f"上传语音文件，创建 Meeting 记录: id={meeting_id} task_id={t_id}")

        # Step 3. 将公网的地址传入工作流 交给AI执行任务
        transcription.delay(public_url, t_id)
        return resp_200(data=meeting_id, message="添加成功")

    except Exception as e:
        logger.exception("❌ 文件上传处理失败")
        return {
            "success": False,
            "message": str(e),
        }
    finally:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
                logger.info(f"🧹 已删除临时文件: {tmp_path}")
        except Exception as e:
            logger.warning(f"⚠️ 删除临时文件失败: {e}")


@router.websocket("/ws/realtime")
async def websocket_endpoint(
        websocket: WebSocket,
        token: str | None = Query(None),
        meeting_id: str | None = Query(None),
):
    """
    实时语音转写 WebSocket（会议模式）。
    - 解析 User、加入房间、广播带说话人标签的转写、服务端录制 PCM、路由 WebRTC 信令
    """
    # WebSocket 无法返回标准 401，采用自定义关闭码 4401 表示认证失败
    if not token:
        await websocket.accept()
        await websocket.close(code=4401)
        logger.warning("🔒 WebSocket 连接因未提供 Token 被拒绝")
        return
    try:
        payload = decode_token(token, expected_type=TOKEN_TYPE_ACCESS)
    except HTTPException:
        await websocket.accept()
        await websocket.close(code=4401)
        logger.warning("🔒 WebSocket 连接因 Token 无效或过期被拒绝")
        return

    await websocket.accept()

    if not meeting_id:
        await websocket.close(code=4400)
        logger.warning("🔒 WebSocket 连接因未提供 meeting_id 被拒绝（仅支持会议模式）")
        return

    await _meeting_websocket_loop(websocket, meeting_id, payload)


async def _meeting_websocket_loop(websocket: WebSocket, meeting_id: str, token_payload: dict):
    """会议模式实时转写：加入房间、广播带说话人标签的转写、录制 PCM、路由 WebRTC 信令。"""
    # 1. 从 token 解析用户身份
    user_id = token_payload.get("user_id")
    if user_id is None:
        await websocket.close(code=4401)
        logger.warning("🔒 会议 WS: token 中无 user_id")
        return
    user = UserDao.get_by_id(user_id)
    if not user:
        await websocket.close(code=4401)
        logger.warning(f"🔒 会议 WS: 用户不存在 user_id={user_id}")
        return

    # 2. 校验会议存在且进行中
    meeting = MeetingDao.get_by_id(m_id=meeting_id, user_id=user_id)
    if not meeting:
        # 用户不在 user_ids 中，尝试自动加入（主持人创建时已含，此处兜底）
        meeting = MeetingDao.get_by_id(m_id=meeting_id)
        if not meeting:
            await websocket.close(code=4404)
            logger.warning(f"🔒 会议 WS: 会议不存在 meeting_id={meeting_id}")
            return
        MeetingDao.add_participant(meeting_id, user_id)
        meeting = MeetingDao.get_by_id(m_id=meeting_id, user_id=user_id)

    if meeting.status != MeetingStatus.ACTIVE.value:
        await websocket.close(code=4403)
        logger.warning(f"🔒 会议 WS: 会议已结束 meeting_id={meeting_id}")
        return

    loop = asyncio.get_running_loop()
    username = user.username

    # 3. 创建 DashScope 会话 + 会议回调
    dashscope_config = settings.get_dashscope_config()
    workspace_id = dashscope_config.get("workspace_id", "")
    ws_url = f'wss://{workspace_id}.cn-beijing.maas.aliyuncs.com/api-ws/v1/realtime' if workspace_id else None
    # 获取会议房间创建时间，用于回调计算相对时间戳
    room = meeting_manager.get_room(meeting_id)
    room_started_at = room.started_at if room else time.time()
    callback = MeetingCallback(
        manager=meeting_manager,
        meeting_id=meeting_id,
        user_id=user_id,
        username=username,
        room_started_at=room_started_at,
    )
    conversation = OmniRealtimeConversation(
        model='qwen3-asr-flash-realtime',
        callback=callback,
        api_key=dashscope_config.get("api_key"),
        url=ws_url,
    )

    try:
        conversation.connect()
        conversation.update_session(
            output_modalities=[MultiModality.TEXT],
            enable_input_audio_transcription=True,
            transcription_params=TranscriptionParams(
                language='zh',
                sample_rate=16000,
                input_audio_format="pcm"
            ),
            enable_turn_detection=True,
            turn_detection_type='server_vad'
        )
        logger.info(f"[Meeting] DashScope 会话已就绪: meeting={meeting_id} user={username}")

        # 4. 加入房间（开 PCM 录音文件、记 join_offset）
        meeting_manager.add_participant(
            meeting_id=meeting_id,
            websocket=websocket,
            user_id=user_id,
            username=username,
            conversation=conversation,
            loop=loop,
        )

        # 向新加入者发送当前房间已有参与者列表
        # （解决竞态：后加入者可能错过之前的 participant_joined 广播）
        current_participants = meeting_manager.get_participants(meeting_id)
        await websocket.send_json({
            "type": "participants_list",
            "participants": current_participants,
        })

        # 广播加入事件给其他参会者
        meeting_manager.broadcast_participant_event(meeting_id, user_id, username, joined=True)

        # 5. 接收循环：同时处理二进制(音频)和文本(信令)
        while True:
            msg = await websocket.receive()

            # 处理断连消息（前端 ws.close() 触发），避免下次 receive() 抛 RuntimeError
            if msg.get("type") == "websocket.disconnect":
                break

            if "bytes" in msg:
                data = msg["bytes"]
                if data:
                    audio_b64 = base64.b64encode(data).decode('ascii')
                    conversation.append_audio(audio_b64)
                    # 同时写入 PCM 录音文件
                    meeting_manager.write_audio_chunk(meeting_id, user_id, data)
                else:
                    break

            elif "text" in msg:
                text_msg = msg["text"]
                try:
                    signal = json.loads(text_msg)
                    to_user_id = signal.get("to_user_id")
                    signal_type = signal.get("signal_type")  # offer / answer / ice
                    signal_data = signal.get("data")
                    if to_user_id is not None and signal_type:
                        meeting_manager.route_signal(
                            meeting_id, user_id, username,
                            to_user_id, signal_type, signal_data
                        )
                except json.JSONDecodeError:
                    logger.warning(f"[Meeting] 无效信令消息: {text_msg[:200]}")

    except WebSocketDisconnect:
        logger.info(f"[Meeting] 参会者断开: meeting={meeting_id} user={username}")
    except RuntimeError as e:
        # Starlette: 前端正常 ws.close() 后，下一次 receive() 抛出 RuntimeError，属正常断连
        logger.info(f"[Meeting] 参会者断开 (Normal close): meeting={meeting_id} user={username}, {e}")
    except Exception as e:
        logger.error(f"[Meeting] WS 异常: meeting={meeting_id} user={username}, {e!r}")
    finally:
        # 6. 清理：移除参会者、关 PCM、关 DashScope、广播离开
        _conn, is_last = meeting_manager.remove_participant(meeting_id, user_id)
        if is_last:
            # 最后一人离开：自动结束会议（合并录音 → OSS 上传 → 触发转录任务）
            logger.info(f"[Meeting] 最后一名参会者离开，自动结束会议: meeting={meeting_id}")
            try:
                from api.v1.meeting import auto_end_meeting
                await auto_end_meeting(meeting_id)
            except Exception:
                logger.exception(f"[Meeting] 自动结束会议失败: meeting={meeting_id}")
        else:
            logger.info(f"[Meeting] 参会者 {username} 离开，房间仍有其他参会者: meeting={meeting_id}")


async def auto_end_meeting(meeting_id: str) -> bool:
    """
    自动结束会议：当最后一名参会者离开房间时调用。

    与房主主动结束的区别：
    - 不做权限校验（非主动调用）

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
    
    # 安全校验：最后一人已离开，房间应为空
    if meeting_manager.room_exists(meeting_id):
        participants = meeting_manager.get_participants(meeting_id)
        if len(participants) > 0:
            logger.warning(f"[AutoEnd] 房间仍有参会者，不自动结束: {meeting_id}")
            return False
    
    # 读取实时转录文本（必须在 end_meeting 之前，因为 end_meeting 会 pop 掉房间）
    realtime_lines = meeting_manager.get_transcript_lines(meeting_id)
    logger.info(f"[AutoEnd] 会议 {meeting_id} 读取到 {len(realtime_lines)} 行实时转录文本")

    # 收集录音信息（如果房间还存在，end_meeting 会清理房间录音）
    participants_info = meeting_manager.end_meeting(meeting_id)
    logger.info(f"[AutoEnd] 会议 {meeting_id} 自动结束，收集到 {len(participants_info)} 路录音")
    
    if not participants_info:
        logger.warning(f"[AutoEnd] 会议无录音数据，标为异常: {meeting_id}")
        MeetingDao.update_status(meeting_id, MeetingStatus.ERROR.value)
        return False
    
    # 复用 _execute_end_meeting 的合并+上传+任务逻辑
    task_id = await _execute_end_meeting(meeting_id, participants_info, meeting, realtime_lines)
    logger.info(f"[AutoEnd] 会议 {meeting_id} 自动结束成功，task_id={task_id}, need_summary={meeting.need_summary}")
    return True


async def _execute_end_meeting(
        meeting_id: str,
        participants_info: list,
        meeting: Meeting,
        realtime_lines: list | None = None,
        task_id: str | None = None,
) -> str | None:
    """
    结束会议的核心逻辑：合并音频、OSS上传、创建Transcription、触发Celery、更新DB。
    供房主主动结束（end_meeting）和最后一人自动结束（auto_end）复用。
    返回 task_id（无需生成纪要时也返回 task_id，但不执行后台任务）。
    """
    # 如果调用方没有传入 realtime_lines（向后兼容），再从内存中读取
    if realtime_lines is None:
        realtime_lines = _get_realtime_transcript(meeting_id)

    # 检查是否需要生成纪要
    if not meeting.need_summary:
        # 无需生成纪要：清理 PCM 文件，创建 Transcription 记录保存实时转录文本，不执行后台任务
        logger.info(f"会议 {meeting_id} 无需生成纪要，跳过转录任务")
        _cleanup_pcm_files(meeting_id, participants_info)
        # 创建 Transcription 记录，保存实时转录文本
        t_id = task_id or uuid.uuid4().hex
        TranscriptionDao.add(Transcription(
            id=t_id,
            task_name=meeting.meeting_name,
            user_ids=meeting.user_ids,
            status=Status.COMPLETE.value,
            task_result=None,
            is_delete=Delete.NOT.value,
            realtime_asr_text=realtime_lines,
        ))
        MeetingDao.update_status(meeting_id, MeetingStatus.FINISH.value)
        MeetingDao.update_task_id(meeting_id, t_id)
        return t_id

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
    t_id = task_id or uuid.uuid4().hex
    TranscriptionDao.add(Transcription(
        id=t_id,
        task_name=meeting.meeting_name,
        user_ids=meeting.user_ids,
        status=Status.PENDING.value,
        task_result=None,
        is_delete=Delete.NOT.value,
        file_url=public_url,
        realtime_asr_text=realtime_lines,
    ))

    # 更新 Meeting 状态为 END_AND_ANALYZE，关联 task_id
    MeetingDao.update_status(meeting_id, MeetingStatus.END_AND_ANALYZE.value)
    MeetingDao.update_task_id(meeting_id, t_id)

    # 5. 触发 Celery 转录任务
    transcription.delay(public_url, t_id)
    logger.info(f"会议 {meeting_id} 转录任务已提交: task_id={t_id}")

    return t_id


def _get_realtime_transcript(meeting_id: str) -> list:
    """从内存中读取实时转录文本行列表。"""
    try:
        return meeting_manager.get_transcript_lines(meeting_id)
    except Exception as e:
        logger.warning(f"读取实时转录文本失败: {e}")
        return []


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
