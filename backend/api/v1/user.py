import asyncio
import json

import httpx
from fastapi import APIRouter, Request
from starlette.responses import StreamingResponse, JSONResponse

from api.schemas import resp_200
from database.models.user import User, UserDao

router = APIRouter(prefix='/user', tags=['user'])


@router.post("/tts/relay")
async def relay_tts(request: Request):
    """
    中继接口：流式调用 TTS 服务并将语音流转发给前端
    """
    try:
        body = await request.json()
        body["stream"] = True  # 强制开启流式模式

        async def stream_generator():
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream(
                    "POST",
                    "http://192.168.100.150:32509/tts/sft",
                    headers={"Content-Type": "application/json"},
                    content=json.dumps(body),
                ) as response:

                    if response.status_code != 200:
                        detail = await response.aread()
                        yield detail
                        return

                    async for chunk in response.aiter_bytes():
                        if chunk:
                            print(chunk)
                            yield chunk
                            await asyncio.sleep(0)  # 让出事件循环

        return StreamingResponse(stream_generator(), media_type="audio/wav")

    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
