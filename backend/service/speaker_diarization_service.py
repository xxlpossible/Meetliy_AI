import os
import tempfile

import requests
import torch
import warnings
from pyannote.audio import Pipeline
import whisper_timestamped as whisper

from settings import settings

warnings.filterwarnings("ignore", category=UserWarning)


class SpeakerTranscriber:
    def __init__(self, whisper_model_name="base", merge_threshold: float = 0.5):
        """
        语音识别 + 说话人分离整合服务

        Args:
            whisper_model_name: Whisper 模型名 (tiny, base, small, medium, large-v3)
            merge_threshold: 合并同说话人片段的最大时间间隔（秒）
        """
        self.hf_config = settings.get_hugging_face_config()
        self.hf_token = self.hf_config.get('token')
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.merge_threshold = merge_threshold

        # 初始化 Whisper
        print(f"✅ Loading Whisper model: {whisper_model_name}")
        self.whisper_model = whisper.load_model(whisper_model_name, device=self.device)

        # 初始化 Pyannote
        print("✅ Loading Pyannote speaker diarization pipeline...")
        self.diar_pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1",
            use_auth_token=self.hf_token
        )
        self.diar_pipeline.to(torch.device(self.device))

    def transcribe(self, audio_path: str):
        """执行完整识别流程"""
        print(f"\n🎧 Processing audio: {audio_path}")

        # === 1️⃣ Whisper 识别 ===
        audio = whisper.load_audio(audio_path)
        audio = whisper.pad_or_trim(audio)
        options = {
            "language": "zh",
            "beam_size": 5,
            "best_of": 5
        }
        asr_result = whisper.transcribe(self.whisper_model, audio, **options)

        whisper_segments = [
            {"start": seg["start"], "end": seg["end"], "text": seg["text"].strip()}
            for seg in asr_result["segments"]
        ]
        self.print_whisper_results(asr_result)

        # === 2️⃣ Pyannote 说话人分离 ===
        # 创建临时文件
        with tempfile.NamedTemporaryFile(delete=False, suffix='.wav') as temp_file:
            # 下载文件
            response = requests.get(audio_path)
            temp_file.write(response.content)
            temp_file_path = temp_file.name
        try:
            diarization = self.diar_pipeline(temp_file_path)
        finally:
            # 清理临时文件
            os.unlink(temp_file_path)
        speaker_segments = []
        for turn, _, speaker in diarization.itertracks(yield_label=True):
            speaker_segments.append({
                "speaker": speaker,
                "start": round(turn.start, 2),
                "end": round(turn.end, 2)
            })
        # 打印说话人分离结果
        self.print_diarization_results(speaker_segments)

        # === 3️⃣ 对齐匹配 ===
        merged_segments = self._match_segments(whisper_segments, speaker_segments)

        # === 4️⃣ 合并短暂停顿 ===
        merged_segments = self._merge_short_pauses(merged_segments)

        # === 5️⃣ 输出结果 ===
        print("\n================= 最终输出 =================")
        for seg in merged_segments:
            print(f"[{seg['speaker']}] [{seg['start']:.2f}s - {seg['end']:.2f}s] {seg['text']}")
        print("===========================================")

        return merged_segments

    @staticmethod
    def _match_segments(whisper_segments, speaker_segments):
        """匹配 ASR 文本与说话人区间"""
        results = []
        for w in whisper_segments:
            # 找与 Whisper 片段重叠最多的 speaker 区间
            best_speaker = None
            max_overlap = 0.0
            for s in speaker_segments:
                overlap = min(w["end"], s["end"]) - max(w["start"], s["start"])
                if overlap > max_overlap:
                    max_overlap = overlap
                    best_speaker = s["speaker"]
            results.append({
                "speaker": best_speaker or "Unknown",
                "start": w["start"],
                "end": w["end"],
                "text": w["text"]
            })
        return results

    def _merge_short_pauses(self, segments):
        """合并同说话人短暂停顿"""
        if not segments:
            return []

        merged = [segments[0]]
        for seg in segments[1:]:
            last = merged[-1]
            # 若同一说话人且间隔小于阈值 -> 合并
            if seg["speaker"] == last["speaker"] and seg["start"] - last["end"] <= self.merge_threshold:
                last["end"] = seg["end"]
                last["text"] += " " + seg["text"]
            else:
                merged.append(seg)
        return merged

    @staticmethod
    def print_diarization_results(speaker_segments):
        """打印说话人分离结果"""
        print("\n================= Pyannote 说话人分离结果 =================")
        print(f"✅ Pyannote 输出 {len(speaker_segments)} 个说话片段")
        for seg in speaker_segments:
            print(f"[{seg['speaker']}] [{seg['start']:.2f}s - {seg['end']:.2f}s]")
        print("==========================================================")

    @staticmethod
    def print_whisper_results(asr_result):
        print("\n================= Whisper 语音识别结果 =================")
        print(f"✅ Whisper 输出 {len(asr_result)} 个片段")
        # 5️⃣ 输出每句话的时间戳结果
        for segment in asr_result["segments"]:
            start = segment["start"]
            end = segment["end"]
            text = segment["text"].strip()
            print(f"[{start:.2f}s - {end:.2f}s] {text}")
        print("==========================================================")


# ================== 使用示例 ==================
if __name__ == "__main__":
    service = SpeakerTranscriber(whisper_model_name="base", merge_threshold=0.5)

