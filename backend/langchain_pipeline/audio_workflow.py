import time
from typing import Dict, Any, List, Tuple

from langchain_core.runnables import RunnableLambda

from service.dashscope_asr import DashScopeASRService
from service.noise_reduce_service import NoiseReductionService
from utils.formatter import Formatter
from utils.uploader import TmpFilesUploader


class AudioProcessingWorkflow:
    """音频处理工作流：从URL到格式化文本"""

    def __init__(self):
        """初始化工作流所需的服务"""

    def _build_audio_processing_chain(self):
        """构建音频处理链"""

        def download_and_noise_reduction(url: str) -> Dict[str, Any]:
            """步骤1: 噪声处理"""
            try:
                process_file_url = NoiseReductionService().process(input_url=url)
                return {
                    "original_url": url,
                    "processed_file_url": process_file_url,
                    "status": "noise_reduction_completed"
                }
            except Exception as e:
                return {
                    "original_url": url,
                    "error": f"噪声处理失败: {str(e)}",
                    "status": "error"
                }

        def upload_processed_file(data: Dict[str, Any]) -> Dict[str, Any]:
            """步骤2: 上传处理后的文件"""
            if data.get("status") == "error":
                return data

            try:
                public_url = TmpFilesUploader.upload_from_url(
                    file_url=data["processed_file_url"]
                )
                return {
                    **data,
                    "public_url": public_url,
                    "status": "upload_completed"
                }
            except Exception as e:
                return {
                    **data,
                    "error": f"文件上传失败: {str(e)}",
                    "status": "error"
                }

        def transcribe_audio(data: Dict[str, Any]) -> Dict[str, Any]:
            """步骤3: 语音转文字"""
            if data.get("status") == "error":
                return data

            time.sleep(6)

            try:
                result = DashScopeASRService().transcribe(
                    file_urls=[data["public_url"]],
                    language_hints=["zh", "en"],
                    diarization_enabled=True
                )
                results = result.get('results', [])
                if not results:
                    return {
                        **data,
                        "error": "语音识别无结果",
                        "status": "error"
                    }

                json_file_url = results[0].get('transcription_url')
                return {
                    **data,
                    "transcription_result": result,
                    "json_file_url": json_file_url,
                    "status": "transcription_completed"
                }
            except Exception as e:
                return {
                    **data,
                    "error": f"语音识别失败: {str(e)}",
                    "status": "error"
                }

        def format_transcription(data: Dict[str, Any]) -> Dict[str, Any]:
            """步骤4: 格式化转录结果"""
            if data.get("status") == "error":
                return data

            try:
                sentences, complete_text = Formatter.format_audio_transcript(
                    json_url=data["json_file_url"]
                )
                return {
                    **data,
                    "sentences": sentences,
                    "complete_text": complete_text,
                    "status": "formatting_completed"
                }
            except Exception as e:
                return {
                    **data,
                    "error": f"格式转换失败: {str(e)}",
                    "status": "error"
                }

        # 构建完整链
        audio_chain = (
                RunnableLambda(lambda url: {"input_url": url})
                | RunnableLambda(lambda data: {**data, **download_and_noise_reduction(data["input_url"])})
                | RunnableLambda(lambda data: {**data, **upload_processed_file(data)})
                | RunnableLambda(lambda data: {**data, **transcribe_audio(data)})
                | RunnableLambda(lambda data: {**data, **format_transcription(data)})
        )

        return audio_chain

    def process_audio(self, audio_url: str) -> Dict[str, Any]:
        """
        处理音频URL并返回格式化文本

        Args:
            audio_url: 音频文件的URL

        Returns:
            Dict包含处理结果和状态
        """
        chain = self._build_audio_processing_chain()
        return chain.invoke(audio_url)
