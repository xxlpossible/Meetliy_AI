import time
from langchain.schema.runnable import RunnableSequence, RunnableParallel, RunnableLambda
from typing import Dict, Any, List, Tuple

from langchain_pipeline.audio_workflow import AudioProcessingWorkflow
from langchain_pipeline.text_workflow import MeetingWorkflow


class CompleteWorkflow:
    """完整工作流：从音频URL到会议分析结果"""

    def __init__(self, model_name="gpt-4o-mini", temperature=0.3):
        """初始化完整工作流"""
        self.audio_processor = AudioProcessingWorkflow()
        self.meeting_analyzer = MeetingWorkflow(model_name, temperature)

    def _build_complete_chain(self):
        """构建完整工作链"""

        def process_audio_step(url: str) -> Dict[str, Any]:
            """音频处理步骤"""
            return self.audio_processor.process_audio(url)

        def analyze_meeting_step(data: Dict[str, Any]) -> Dict[str, Any]:
            """会议分析步骤"""
            if data.get("status") == "error":
                return {
                    **data,
                    "meeting_analysis_error": data.get("error"),
                    "status": "complete_with_errors"
                }

            try:
                # 使用音频处理得到的完整文本进行会议分析
                meeting_result = self.meeting_analyzer.process(data["complete_text"])
                return {
                    **data,
                    **meeting_result,
                    "status": "complete"
                }
            except Exception as e:
                return {
                    **data,
                    "meeting_analysis_error": f"会议分析失败: {str(e)}",
                    "status": "complete_with_errors"
                }

        # 构建完整链：音频处理 → 会议分析
        complete_chain = (
                RunnableLambda(lambda url: {"audio_url": url})
                | RunnableLambda(lambda data: {**data, **process_audio_step(data["audio_url"])})
                | RunnableLambda(lambda data: {**data, **analyze_meeting_step(data)})
        )

        return complete_chain

    def process(self, audio_url: str) -> Dict[str, Any]:
        """
        从音频URL开始完整处理流程

        Args:
            audio_url: 音频文件的URL

        Returns:
            Dict包含所有处理结果
        """
        chain = self._build_complete_chain()
        return chain.invoke(audio_url)

