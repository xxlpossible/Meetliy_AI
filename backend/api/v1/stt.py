import asyncio
import os

import aiofiles
from loguru import logger
import tempfile
import uuid
from typing import Optional, List

from dashscope.audio.asr import TranslationRecognizerRealtime
from fastapi import APIRouter, HTTPException, Body, Response, UploadFile, File, Form

from api.schemas import resp_200
from database.models.transcription import Transcription, TranscriptionDao, Status, Delete
from database.schemas.schema import TranscriptionQueryVo, TransUpdate
from service.audio_transcription import audio_service
from service.realtime_asr import WebSocketCallback
from task.tasks import transcription
from fastapi import WebSocket, WebSocketDisconnect

from utils.uploader import TmpFilesUploader

router = APIRouter(prefix='/audio', tags=['audio'])


@router.post('/transcription', description="音频转文字")
async def audio_transcription(
        file_path: str = Body(..., embed=True, description="需要转换为文本的语音")
):
    """
    音频转文字接口
    - file_path: 音频文件路径或URL
    """
    try:
        # 调用服务层处理业务逻辑
        transcription_result = await audio_service.transcribe_audio(file_path)

        # 返回响应
        return Response(
            content=transcription_result,
            media_type="text/plain"
        )

    except HTTPException:
        # 重新抛出HTTP异常
        raise
    except Exception as e:
        # 处理其他未预期异常
        raise HTTPException(status_code=500, detail=f"内部服务器错误: {str(e)}")


@router.post('/start_task', description="上传语音文件")
async def upload_file(
        audio_file: UploadFile = File(...),
        task_name: Optional[str] = Form(None)
):
    # 将音频文件传入MinIO进行备份，然后获取其url地址
    # 因为已经使用了阿里云OSS的Buket服务，所以注释这一步操作

    # 语音文件统一采用mp3格式
    # file_bytes = await audio_file.read()
    # minio_client.upload_bytes(audio_file.filename, file_bytes, audio_file.content_type)
    # original_url = minio_client.get_presigned_url(
    #     bucket_name="original-audio",
    #     object_name=audio_file.filename
    # )

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

        # 创建任务对象
        t_id = uuid.uuid4().hex
        TranscriptionDao.add(Transcription(
            id=t_id,
            task_name=task_name,
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
        body: TranscriptionQueryVo
):
    results, total = TranscriptionDao.list(body=body)
    return resp_200(data={"data": results, "total": total})


@router.delete('/delete', description="删除指定的记录")
async def delete(task_id: str):
    try:
        TranscriptionDao.delete(task_id=task_id)
    except Exception:
        raise HTTPException(status_code=500, detail="删除失败")
    return resp_200()


@router.post('/update', description="更新记录")
async def update(body: TransUpdate):
    task_id = body.task_id
    task = TranscriptionDao.get_by_id(t_id=task_id)
    if task is None:
        raise HTTPException(status_code=500, detail="未找到该记录")
    task.task_name = body.task_name
    task.note = body.note
    TranscriptionDao.update(task)
    return resp_200()


@router.post("/getTask/status", summary="获取项目审核书任务状态", description="获取项目审核书任务状态")
def get_audio2text_task_status(
        task_ids: List[str] = Body(..., embed=True, description="需要转换为语音的文本")
):
    result = []
    for t_id in task_ids:
        one = TranscriptionDao.get_by_id(t_id=t_id)
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
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()

    # 获取当前事件循环，用于在回调中调度任务
    loop = asyncio.get_running_loop()

    # 初始化回调，传入 websocket 和 loop
    callback = WebSocketCallback(websocket, loop)

    # 初始化识别器
    translator = TranslationRecognizerRealtime(
        model="gummy-realtime-v1",
        format="pcm",
        sample_rate=16000,
        transcription_enabled=True,
        translation_enabled=True,
        translation_target_languages=["en"],
        callback=callback,
    )

    try:
        translator.start()
        print("Backend: Recognizer started, waiting for audio...")

        while True:
            # 接收前端发送的二进制音频帧 (bytes)
            data = await websocket.receive_bytes()

            # 如果接收到数据，发送给 DashScope
            if data:
                translator.send_audio_frame(data)
            else:
                break

    except WebSocketDisconnect:
        print("Frontend disconnected.")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        # 清理资源
        translator.stop()
        print("Recognizer stopped.")








