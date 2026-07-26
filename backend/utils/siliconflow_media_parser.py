"""
硅基流动多模态解析模块
======================

语音与图片不走 MarkItDown，直接调用硅基流动免费模型解析为文本：
    - 语音：FunAudioLLM/SenseVoiceSmall（/v1/audio/transcriptions 接口，multipart 上传）
    - 图片：PaddlePaddle/PaddleOCR-VL-1.5（chat completions，base64 + OCR prompt）

API Key 复用 settings.get_embeddings_config()['api_key']（硅基流动同一账号同一 Key），
无需额外配置。解析结果为纯文本（OCR 结果可能含 Markdown 表格），供下游分块向量化。

设计要点：
    1. 语音/图片是网络调用，耗时较长，调用方应放入线程池（knowledge.py 已用 run_in_threadpool）
    2. 语音转录超时设 300s（音频可能较长），图片 OCR 走 OpenAI SDK 默认超时
    3. 任何异常均捕获并返回空字符串，由上层决定是否降级
"""

import base64
import mimetypes
import os

from loguru import logger

from settings import settings


def _get_api_key() -> str | None:
    """获取硅基流动 API Key（复用 embeddings 配置，同一账号）。"""
    config = settings.get_embeddings_config()
    return config.get("api_key")


# ==========================================
# 语音转录
# ==========================================
def transcribe_audio(path: str, model: str = "FunAudioLLM/SenseVoiceSmall") -> str:
    """
    调用硅基流动 SenseVoiceSmall 将音频转录为文本。

    接口：POST https://api.siliconflow.cn/v1/audio/transcriptions（multipart/form-data）
    返回：{"text": "转录文本"}

    :param path: 音频文件路径（mp3/wav/m4a/flac）
    :param model: 转录模型，默认 FunAudioLLM/SenseVoiceSmall
    :return: 转录文本；失败返回空字符串
    """
    if not os.path.exists(path):
        logger.error(f"[MediaParser] 音频文件不存在: {path}")
        return ""

    api_key = _get_api_key()
    if not api_key:
        logger.error("[MediaParser] 未配置硅基流动 api_key，无法转录音频")
        return ""

    import requests

    url = "https://api.siliconflow.cn/v1/audio/transcriptions"
    headers = {"Authorization": f"Bearer {api_key}"}

    # 根据扩展名推断 MIME 类型，兜底 audio/mpeg
    mime = mimetypes.guess_type(path)[0] or "audio/mpeg"

    try:
        with open(path, "rb") as audio_file:
            files = {
                "file": (os.path.basename(path), audio_file, mime),
                "model": (None, model),
            }
            response = requests.post(url, headers=headers, files=files, timeout=300)
            response.raise_for_status()
            data = response.json()
            # 硅基流动 transcription 接口返回 {"text": "..."}
            text = (data.get("text") or "").strip()
            logger.info(f"[MediaParser] 音频转录成功: {path} -> {len(text)} chars")
            return text
    except Exception as e:
        logger.error(f"[MediaParser] 音频转录失败 {path}: {e}")
        return ""


# ==========================================
# 图片 OCR
# ==========================================
# OCR prompt：提取文字、保持阅读顺序、表格输出 Markdown、不补充解释
_OCR_PROMPT = (
    "请完成OCR识别：\n\n"
    "要求：\n"
    "1. 提取所有文字\n"
    "2. 保持阅读顺序\n"
    "3. 如果存在表格，请输出Markdown表格\n"
    "4. 不要补充解释"
)


def ocr_image(path: str, model: str = "deepseek-ai/DeepSeek-OCR") -> str:
    """
    调用硅基流动 deepseek-ai/DeepSeek-OCR 对图片进行 OCR，输出文本（含 Markdown 表格）。

    接口：chat completions（OpenAI 兼容），图片以 base64 data-uri 传入。

    :param path: 图片文件路径（jpg/png/gif/bmp/webp/tiff）
    :param model: OCR 模型，默认 PaddlePaddle/PaddleOCR-VL-1.5
    :return: OCR 文本（可能含 Markdown 表格）；失败返回空字符串
    """
    if not os.path.exists(path):
        logger.error(f"[MediaParser] 图片文件不存在: {path}")
        return ""

    api_key = _get_api_key()
    if not api_key:
        logger.error("[MediaParser] 未配置硅基流动 api_key，无法 OCR 图片")
        return ""

    # 读取图片并转 base64
    try:
        with open(path, "rb") as f:
            image_base64 = base64.b64encode(f.read()).decode("utf-8")
    except Exception as e:
        logger.error(f"[MediaParser] 图片读取失败 {path}: {e}")
        return ""

    # 推断 MIME 类型，兜底 image/png
    mime = mimetypes.guess_type(path)[0] or "image/png"
    data_uri = f"data:{mime};base64,{image_base64}"

    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key, base_url="https://api.siliconflow.cn/v1")
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": data_uri}},
                        {"type": "text", "text": _OCR_PROMPT},
                    ],
                }
            ],
        )
        text = (response.choices[0].message.content or "").strip()
        logger.info(f"[MediaParser] 图片 OCR 成功: {path} -> {len(text)} chars")
        return text
    except Exception as e:
        logger.error(f"[MediaParser] 图片 OCR 失败 {path}: {e}")
        return ""
