from http import HTTPStatus
from dashscope.audio.asr import Transcription
import dashscope
import json
from typing import List, Optional, Dict
from settings import settings
from loguru import logger
from utils.uploader import TmpFilesUploader


class DashScopeASRService:
    """
    DashScope 语音识别服务封装
    支持异步调用 + 自动等待任务完成 + 错误处理
    """

    def __init__(self):
        dashscope_config = settings.get_dashscope_config()
        api_key = dashscope_config.get("api_key")
        if not api_key:
            raise ValueError("❌ 未配置 DashScope API Key！")

        dashscope.api_key = api_key

    def transcribe(
        self,
        file_urls: List[str],
        language_hints: Optional[List[str]] = None,
        diarization_enabled: bool = True,
        timestamp_alignment_enabled: bool = False,
        model: str = "paraformer-v2",
    ) -> Dict:
        """
        调用 DashScope 异步语音识别 API，返回识别结果字典

        :param file_urls: 语音文件的公网URL列表
        :param language_hints: 语言提示（如 ['zh', 'en']）
        :param diarization_enabled: 是否启用说话人分离
        :param timestamp_alignment_enabled: 是否返回时间戳
        :param model: 语音识别模型
        :return: 识别结果 dict
        """
        # Step 1. 提交任务
        task_response = Transcription.async_call(
            model=model,
            file_urls=file_urls,
            language_hints=language_hints,
            timestamp_alignment_enabled=timestamp_alignment_enabled,
            diarization_enabled=diarization_enabled,
        )

        # Step 2. 等待任务完成
        transcribe_response = Transcription.wait(task=task_response.output.task_id)

        # Step 3. 结果处理
        if transcribe_response.status_code == HTTPStatus.OK:
            logger.info("✅ 转录完成！")
            return transcribe_response.output
        else:
            raise Exception(
                f"❌ 转录失败: {transcribe_response.status_code}, {transcribe_response.message}"
            )


if __name__ == "__main__":
    # 示例使用
    service = DashScopeASRService()
    url = TmpFilesUploader.upload_from_url(
        file_url="http://127.0.0.1:9001/api/v1/download-shared-object/aHR0cDovLzEyNy4wLjAuMTo5MDAwL29yaWdpbmFsLWF1ZGlvL2F1ZGlvLTAud2F2P1gtQW16LUFsZ29yaXRobT1BV1M0LUhNQUMtU0hBMjU2JlgtQW16LUNyZWRlbnRpYWw9WjdIUEVFQlowOEdPQ0RCRVNIVlIlMkYyMDI1MTEwOSUyRnVzLWVhc3QtMSUyRnMzJTJGYXdzNF9yZXF1ZXN0JlgtQW16LURhdGU9MjAyNTExMDlUMDc0ODI3WiZYLUFtei1FeHBpcmVzPTQzMjAwJlgtQW16LVNlY3VyaXR5LVRva2VuPWV5SmhiR2NpT2lKSVV6VXhNaUlzSW5SNWNDSTZJa3BYVkNKOS5leUpoWTJObGMzTkxaWGtpT2lKYU4waFFSVVZDV2pBNFIwOURSRUpGVTBoV1VpSXNJbVY0Y0NJNk1UYzJNamN4TVRZek9Td2ljR0Z5Wlc1MElqb2liV2x1YVc5aFpHMXBiaUo5LkZFZlhqd0hfOWR2NG9Fd3czTldIMFAtQk5RbUVrZEcxVm5TWWJUd1ZFT1lZRVE5UHp0ZkIweXMtNEx2VnRENFJZbGR5TTZyb1VhLWVTa2FlTzJfTjd3JlgtQW16LVNpZ25lZEhlYWRlcnM9aG9zdCZ2ZXJzaW9uSWQ9bnVsbCZYLUFtei1TaWduYXR1cmU9ZjJmMDc0YmQyMzIxNmQ2NDgxNWJhZTA4NWQ5YTA0ZWZmZGIwOTVjNDM3ZDk4ZmE5MzhiZTczMmVhOWMxNGE4Yw"
    )

    result = service.transcribe(
        file_urls=[
            "http://tmpfiles.org/dl/7623294/temp_audio_file.wav"
        ],
        language_hints=["zh", "en"],
        diarization_enabled=True,
    )

    print(json.dumps(result, indent=4, ensure_ascii=False))
