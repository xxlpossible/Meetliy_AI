import io
import json

import aiofiles
import httpx
from fastapi import HTTPException
from pydub import AudioSegment
from pydub.utils import make_chunks

from settings import settings


class AudioTranscriptionService:
    def __init__(self):
        self.stt_config = settings.get_transcription_config()
        self.api_url = self.stt_config.get('base_url')
        self.api_key = self.stt_config.get('api_key')

    async def transcribe_audio(self, file_path: str):
        """音频转文字服务"""
        # 下载音频文件内容
        if file_path.startswith("http"):
            async with httpx.AsyncClient() as client:
                download_resp = await client.get(file_path, timeout=300.0)
                content = download_resp.content
                if download_resp.status_code != 200:
                    raise HTTPException(status_code=400, detail=f"无法下载音频文件: {file_path}")
        else:
            async with aiofiles.open(file_path, 'rb') as file:
                content = await file.read()

        chunk_length_ms = 30000
        audio = AudioSegment.from_file(io.BytesIO(content))
        chunks = make_chunks(audio, chunk_length_ms)
        text_list = []

        # 调用语音转写API
        async with httpx.AsyncClient() as client:
            try:
                for i, chunk in enumerate(chunks):
                    with io.BytesIO() as buffer:
                        chunk.export(buffer, format="wav")
                        chunk_bytes = buffer.getvalue()
                        response = await client.post(
                            self.api_url,
                            headers={"Authorization": f"Bearer {self.api_key}"},
                            files={"file": ("audio.mp3", chunk_bytes, "audio/wav")},
                            data={
                                "model": "Whisper-large-v3",
                                "language": "auto",
                                "response_format": "json"
                            },
                            timeout=httpx.Timeout(3600.0)
                        )
                        if response.status_code != 200:
                            raise HTTPException(status_code=500, detail="转写失败")

                        result_dict = json.loads(response.text.replace('data:', ''))
                        text = result_dict.get('text')
                        text_list.append(text)
                        print(text + '\n')

                final_result = ''.join(text_list)
                return final_result

            except Exception as e:
                raise HTTPException(status_code=500, detail=f"转写服务异常: {str(e)}")


# 创建服务实例
audio_service = AudioTranscriptionService()
