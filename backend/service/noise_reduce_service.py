import os
import librosa
import soundfile as sf
import noisereduce as nr
import requests
import tempfile

from loguru import logger

from utils.minio_client import MinIOClient


class LoggingTemporaryDirectory(tempfile.TemporaryDirectory):
    def cleanup(self):
        logger.info(f"🗑 自动清理临时目录: {self.name}")
        super().cleanup()


class NoiseReductionService:
    """语音降噪服务"""

    def __init__(self, sample_rate: int = 16000):
        self.sample_rate = sample_rate
        self.minio_client = MinIOClient()  # 初始化 MinIO 客户端

    def process(self, input_url: str, output_bucket: str = "noise-reduce") -> str:
        """
        对输入音频URL进行降噪并上传到MinIO
        :param input_url: 原始音频URL地址
        :param output_bucket: 存储处理后音频的MinIO桶名
        :return: 处理后音频的URL地址
        """
        # 创建临时目录用于处理文件
        # 会自动删除临时文件 退出 with 块时 会自动删除临时文件
        with LoggingTemporaryDirectory() as temp_dir:
            # 1. 下载原始音频文件
            logger.info("⬇️ 正在下载原始音频")
            original_temp_path = os.path.join(temp_dir, "original_audio.mp3")
            self._download_audio(input_url, original_temp_path)

            # 2. 加载音频并进行降噪处理
            logger.info("🧹 正在进行噪声处理")
            y, sr = librosa.load(original_temp_path, sr=self.sample_rate)
            reduced = nr.reduce_noise(y=y, sr=sr)

            # 3. 保存降噪后的音频到临时文件
            logger.info("⬆️ 保存降噪后的文件")
            processed_temp_path = os.path.join(temp_dir, "processed_audio.mp3")
            sf.write(processed_temp_path, reduced, sr)

            # 4. 生成唯一的对象名
            import uuid
            object_name = f"denoised_{uuid.uuid4().hex}.mp3"

            # 5. 上传到MinIO
            self.minio_client.upload_file(
                bucket_name=output_bucket,
                object_name=object_name,
                file_path=processed_temp_path
            )

            # 6. 生成预签名URL
            presigned_url = self.minio_client.get_presigned_url(
                bucket_name=output_bucket,
                object_name=object_name,
                expire_hours=24  # 24小时有效期
            )

            return presigned_url

    def _download_audio(self, url: str, save_path: str):
        """下载音频文件到本地"""
        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()

            with open(save_path, 'wb') as f:
                f.write(response.content)

        except Exception as e:
            raise Exception(f"下载音频文件失败: {e}")
