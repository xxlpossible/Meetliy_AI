import json
import requests
from typing import List, Dict, Tuple, Optional

from loguru import logger


class Formatter:

    @staticmethod
    def format_audio_transcript(json_url: str, merge_threshold: int = 3000) -> Tuple[List[str], Optional[str]]:
        """
        根据JSON文件的URL下载地址，读取音频识别信息并格式化为指定格式

        Args:
            json_url: JSON文件的URL下载地址
            merge_threshold: 合并间隔阈值，单位毫秒，默认3秒

        Returns:
            Tuple[List[str], Optional[str]]: 格式化后的对话列表和完整文本
        """
        data = Formatter._download_json(json_url)
        if not data:
            return [], None
        logger.info("正在进行转录结果格式化")
        sentences, complete_text = Formatter._extract_sentences_and_text(data)
        merged_sentences = Formatter._merge_consecutive_speakers(sentences, merge_threshold)
        formatted_output = Formatter._format_sentences(merged_sentences)
        logger.info("结果格式化完成，即将进入文本处理链")

        return formatted_output, complete_text

    @staticmethod
    def _download_json(json_url: str) -> Optional[Dict]:
        """
        下载并解析JSON文件

        Args:
            json_url: JSON文件的URL下载地址

        Returns:
            解析后的JSON数据，失败时返回None
        """
        try:
            response = requests.get(json_url)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"下载或解析JSON文件失败: {e}")
            return None

    @staticmethod
    def _extract_sentences_and_text(data: Dict) -> Tuple[List[Dict], Optional[str]]:
        """
        从JSON数据中提取句子和完整文本

        Args:
            data: 解析后的JSON数据

        Returns:
            包含句子列表和完整文本的元组
        """
        all_sentences = []
        complete_text = None

        for transcript in data.get('transcripts', []):
            complete_text = transcript.get('text')
            for sentence in transcript.get('sentences', []):
                speaker = f"Speaker_{sentence.get('speaker_id', 0)}"
                begin_time = sentence.get('begin_time', 0)
                end_time = sentence.get('end_time', 0)
                text = sentence.get('text', '').strip()

                if text:  # 跳过空文本
                    all_sentences.append({
                        'speaker': speaker,
                        'begin_time': begin_time,
                        'end_time': end_time,
                        'text': text
                    })

        return all_sentences, complete_text

    @staticmethod
    def _merge_consecutive_speakers(sentences: List[Dict], merge_threshold: int) -> List[Dict]:
        """
        合并连续说话人相同的句子

        Args:
            sentences: 原始句子列表
            merge_threshold: 合并间隔阈值（毫秒）

        Returns:
            合并后的句子列表
        """
        if not sentences:
            return []

        merged_sentences = []
        current = sentences[0]

        for i in range(1, len(sentences)):
            next_sentence = sentences[i]

            # 检查是否应该合并：同一个说话人且时间间隔很小
            if (current['speaker'] == next_sentence['speaker'] and
                    next_sentence['begin_time'] - current['end_time'] <= merge_threshold):
                # 合并句子
                current['end_time'] = next_sentence['end_time']
                current['text'] += " " + next_sentence['text']
            else:
                # 不满足合并条件，保存当前句子
                merged_sentences.append(current)
                current = next_sentence

        # 添加最后一个句子
        merged_sentences.append(current)

        return merged_sentences

    @staticmethod
    def _format_sentences(sentences: List[Dict]) -> List[str]:
        """
        将句子列表格式化为指定格式

        Args:
            sentences: 句子列表

        Returns:
            格式化后的字符串列表
        """
        formatted_output = []

        for sentence in sentences:
            start_formatted = Formatter._ms_to_min_sec(sentence['begin_time'])
            end_formatted = Formatter._ms_to_min_sec(sentence['end_time'])

            formatted_line = f"[ {start_formatted} ~ {end_formatted} ] {sentence['speaker']} : {sentence['text']}"
            formatted_output.append(formatted_line)

        return formatted_output

    @staticmethod
    def _ms_to_min_sec(milliseconds: int) -> str:
        """
        将毫秒转换为分钟:秒的格式

        Args:
            milliseconds: 毫秒数

        Returns:
            格式化后的时间字符串（MM:SS）
        """
        total_seconds = milliseconds // 1000
        minutes = total_seconds // 60
        seconds = total_seconds % 60
        return f"{minutes:02d}:{seconds:02d}"



