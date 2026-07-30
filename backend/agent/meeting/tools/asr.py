"""MeetingAgent - ASR 语音识别工具。"""

from langchain.tools import tool

from services.dashscope_file_asr import DashScopeASRService
from utils.formatter import Formatter


def build_asr_tool():
    """构建 ASR 工具 —— 将语音文件 URL 转为文字识别结果。"""

    @tool
    def asr(url: str) -> dict:
        """一个可以将语音文件的url地址转换为文字识别结果的工具

        Args:
            url: 语音文件的url下载地址
        """
        result = DashScopeASRService().transcribe(
            file_urls=[url],
            language_hints=["zh", "en"],
            diarization_enabled=True
        )
        results = result.get('results', [])
        json_file_url = results[0].get('transcription_url')

        sentences_with_time, complete_text = Formatter.format_audio_transcript(
            json_url=json_file_url
        )

        return {
            "sentences_with_time": sentences_with_time,
            "complete_text": complete_text
        }

    return asr
