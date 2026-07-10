import asyncio
import base64
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
from database.models.transcription import Transcription, TranscriptionDao, Status, Delete
from database.models.user import User
from database.schemas.schema import TranscriptionQueryVo, TransUpdate
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
        token: Optional[str] = Query(None)
):
    # WebSocket 无法返回标准 401，采用自定义关闭码 4401 表示认证失败
    if not token:
        await websocket.accept()
        await websocket.close(code=4401)
        logger.warning("🔒 WebSocket 连接因未提供 Token 被拒绝")
        return
    try:
        decode_token(token, expected_type=TOKEN_TYPE_ACCESS)
    except HTTPException:
        await websocket.accept()
        await websocket.close(code=4401)
        logger.warning("🔒 WebSocket 连接因 Token 无效或过期被拒绝")
        return

    await websocket.accept()

    # 获取当前事件循环，用于在回调中调度任务
    loop = asyncio.get_running_loop()

    # 初始化回调，传入 websocket 和 loop
    callback = WebSocketCallback(websocket, loop)

    # 获取 DashScope 配置
    dashscope_config = settings.get_dashscope_config()
    workspace_id = dashscope_config.get("workspace_id", "")

    # 初始化新版 OmniRealtimeConversation
    # 使用私有端点（需 Workspace ID），无 workspace_id 时回退到默认公共端点
    ws_url = f'wss://{workspace_id}.cn-beijing.maas.aliyuncs.com/api-ws/v1/realtime' if workspace_id else None
    conversation = OmniRealtimeConversation(
        model='qwen3-asr-flash-realtime',
        callback=callback,
        api_key=dashscope_config.get("api_key"),
        url=ws_url,
    )

    try:
        # 建立 WebSocket 连接
        conversation.connect()
        print("Backend: Connected to DashScope, configuring session...")

        # 配置会话：启用转写 + VAD
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
            # 接收前端发送的二进制音频帧 (bytes)
            data = await websocket.receive_bytes()

            # 如果接收到数据，base64 编码后发送给 DashScope
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
        # 清理资源
        try:
            conversation.end_session()
        except Exception:
            pass
        conversation.close()
        print("Recognizer stopped.")
