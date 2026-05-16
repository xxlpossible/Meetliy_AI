import os
import tempfile
import uuid

import requests
from loguru import logger

from utils.oss import oss_client


class TmpFilesUploader:
    """
    将文件上传到阿里云OSS
    """

    TMP_FILENAME = "temp_audio_file.mp3"

    @staticmethod
    def upload_from_temp_path(temp_path: str):
        logger.info("⬆️ 正在上传到OSS ...")
        file_id = uuid.uuid4().hex
        # 将文件上传到 OSS
        oss_client.upload_file(key=f"audio/{file_id}.mp3", file_path=temp_path)
        # 生成临时下载链接
        download_url = oss_client.generate_presigned_url(key=f"audio/{file_id}.mp3")
        logger.info("✅ 上传成功！")
        return download_url

    @staticmethod
    def upload_from_url(file_url: str) -> str:
        """
        从指定 file_url 下载文件（mp3格式），上传到 OSS并返回公网下载URL。
        """
        tmp_path = os.path.join(tempfile.gettempdir(), TmpFilesUploader.TMP_FILENAME)

        # Step 1. 下载文件到临时路径
        logger.info(f"⬇️ 正在从 {file_url} 下载文件...")
        response = requests.get(file_url)
        if response.status_code != 200:
            raise Exception(f"❌ 文件下载失败：{response.status_code}, {response.text}")

        with open(tmp_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        logger.info(f"✅ 已下载到临时文件：{tmp_path}")

        try:
            # Step 2. 上传到 阿里云OSS
            logger.info("⬆️ 正在上传到OSS ...")
            file_id = uuid.uuid4().hex
            # 将文件上传到 OSS
            oss_client.upload_file(key=f"audio/{file_id}.mp3", file_path=tmp_path)
            # 生成临时下载链接
            download_url = oss_client.generate_presigned_url(key=f"audio/{file_id}.mp3")
            logger.info("✅ 上传成功！")
            return download_url

        finally:
            # Step 3. 删除临时文件
            try:
                os.remove(tmp_path)
                logger.info(f"🧹 已删除临时文件：{tmp_path}")
            except Exception as e:
                logger.warning(f"⚠️ 删除临时文件失败：{e}")

