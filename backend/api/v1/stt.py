import asyncio
import base64
import json
import os

import aiofiles
from loguru import logger
import tempfile
import uuid
from typing import Optional, List

from dashscope.audio.qwen_omni import OmniRealtimeConversation, MultiModality
from dashscope.audio.qwen_omni.omni_realtime import TranscriptionParams
from fastapi import APIRouter, HTTPException, Body, Response, UploadFile, File, Form, Depends, Query

from api.schemas import resp_200
from database.models.meeting import MeetingDao, MeetingStatus
from database.models.transcription import Transcription, TranscriptionDao, Status, Delete
from database.models.user import User, UserDao
from database.schemas.schema import TranscriptionQueryVo, TransUpdate
from service.meeting_callback import MeetingCallback
from service.meeting_manager import meeting_manager
from service.realtime_asr import WebSocketCallback
from task.tasks import transcription
from fastapi import WebSocket, WebSocketDisconnect
from utils.security import TOKEN_TYPE_ACCESS, decode_token
from utils.dependencies import get_current_user
from utils.uploader import TmpFilesUploader
from settings import settings

router = APIRouter(prefix='/audio', tags=['audio'])


@router.post('/start_task', description="上传语音文件")
async def upload_file(
        audio_file: UploadFile = File(...),
        task_name: Optional[str] = Form(None),
        # 这里后续需要加上一个参数 user_ids 代表参加会议的用户ID 但是目前还未实现联机会议 故ID只有current_user 不需要改参数
        # user_ids: Optional[List]
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
        # TODO 这里获取到公网的文件下载地址其实是非常耗时的，可以将此操作放到线程池当中完成，避免阻塞主线程
        # TODO 从获取公网下载地址 到下面的数据库读写操作其实都是同步操作，不应该出现在异步的接口当中，都需要放入线程池
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

        # Step 3. 将公网的地址传入工作流 交给AI执行任务
        transcription.delay(public_url, t_id)
        return resp_200(data=t_id, message="添加成功")

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


@router.post('/list', description="获取结果列表")
async def get_list(
        body: TranscriptionQueryVo,
        current_user: User = Depends(get_current_user)
):
    results, total = TranscriptionDao.list(body=body, user_id=current_user.id)
    return resp_200(data={"data": results, "total": total})


@router.post('/delete', description="删除指定的记录")
async def delete(
        task_id: str,
        current_user: User = Depends(get_current_user)
):
    try:
        TranscriptionDao.delete(task_id=task_id, user_id=current_user.id)
    except ValueError:
        # 记录不存在或当前用户无权操作
        raise HTTPException(status_code=403, detail="无权操作或记录不存在")
    except Exception:
        raise HTTPException(status_code=500, detail="删除失败")
    return resp_200()


@router.post('/update', description="更新记录")
async def update(
        body: TransUpdate,
        current_user: User = Depends(get_current_user)
):
    task_id = body.task_id
    # 带 user_id 校验权限：无权查询不到记录
    task = TranscriptionDao.get_by_id(t_id=task_id, user_id=current_user.id)
    if task is None:
        raise HTTPException(status_code=403, detail="无权操作或记录不存在")
    task.task_name = body.task_name
    task.note = body.note
    TranscriptionDao.update(task)
    return resp_200()


@router.post("/getTask/status", summary="获取项目审核书任务状态", description="获取项目审核书任务状态")
async def get_audio2text_task_status(
        task_ids: List[str] = Body(..., embed=True, description="需要转换为语音的文本"),
        current_user: User = Depends(get_current_user)
):
    result = []
    for t_id in task_ids:
        # 带 user_id 校验权限，且防御空值（修复原有 AttributeError）
        one = TranscriptionDao.get_by_id(t_id=t_id, user_id=current_user.id)
        if one is None:
            continue
        if one.status == Status.COMPLETE.value:
            result.append(
                {
                    "id": t_id,
                    "status": one.status,
                    "result": one.task_result
                }
            )
    return resp_200(data=result)


@router.websocket("/ws/realtime")
async def websocket_endpoint(
        websocket: WebSocket,
        token: Optional[str] = Query(None),
        meeting_id: Optional[str] = Query(None),
):
    """
    实时语音转写 WebSocket。
    - 无 meeting_id：单用户模式（向后兼容，消息格式不变）
    - 有 meeting_id：会议模式（解析 User、加入房间、广播带说话人标签的转写、
      服务端录制 PCM、路由 WebRTC 信令）
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

    # 分支：会议模式 vs 单用户模式
    if meeting_id:
        await _meeting_websocket_loop(websocket, meeting_id, payload)
    else:
        await _single_user_websocket_loop(websocket)


async def _single_user_websocket_loop(websocket: WebSocket):
    """单用户实时转写（向后兼容原有逻辑与消息格式）。"""
    loop = asyncio.get_running_loop()
    callback = WebSocketCallback(websocket, loop)

    dashscope_config = settings.get_dashscope_config()
    workspace_id = dashscope_config.get("workspace_id", "")
    ws_url = f'wss://{workspace_id}.cn-beijing.maas.aliyuncs.com/api-ws/v1/realtime' if workspace_id else None
    conversation = OmniRealtimeConversation(
        model='qwen3-asr-flash-realtime',
        callback=callback,
        api_key=dashscope_config.get("api_key"),
        url=ws_url,
    )

    try:
        conversation.connect()
        print("Backend: Connected to DashScope, configuring session...")
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
        print("Backend: Session configured, waiting for audio...")

        while True:
            data = await websocket.receive_bytes()
            if data:
                audio_b64 = base64.b64encode(data).decode('ascii')
                conversation.append_audio(audio_b64)
            else:
                break

    except WebSocketDisconnect:
        print("Frontend disconnected.")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        try:
            conversation.end_session()
        except Exception:
            pass
        conversation.close()
        print("Recognizer stopped.")


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
    callback = MeetingCallback(
        manager=meeting_manager,
        meeting_id=meeting_id,
        user_id=user_id,
        username=username,
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
        #    is_last 表示该参会者离开后房间是否已空
        # 注意：broadcast_participant_event 对已离开的参会者不生效，
        # 但仍有重要作用：告知剩余参会者有人离开。
        conn, is_last = meeting_manager.remove_participant(meeting_id, user_id)
        if is_last:
            # 最后一人离开：自动结束会议（合并录音 → OSS 上传 → 触发转录任务）
            logger.info(f"[Meeting] 最后一名参会者离开，自动结束会议: meeting={meeting_id}")
            try:
                # 延迟导入避免循环依赖（stt ↔ meeting 在 __init__.py 中互相依赖）
                from api.v1.meeting import auto_end_meeting
                await auto_end_meeting(meeting_id)
            except Exception:
                logger.exception(f"[Meeting] 自动结束会议失败: meeting={meeting_id}")
        else:
            logger.info(f"[Meeting] 参会者 {username} 离开，房间仍有其他参会者: meeting={meeting_id}")
