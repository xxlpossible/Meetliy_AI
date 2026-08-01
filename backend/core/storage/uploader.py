import os
import tempfile
import uuid

import requests
from loguru import logger

from core.storage.oss import oss_client


class TmpFilesUploader:
    """
    将文件上传到阿里云OSS
    """

    TMP_FILENAME = "temp_audio_file.mp3"

    @staticmethod
    def upload_from_temp_path(temp_path: str):
        logger.info("⬆️ 正在上传到阿里云OSS ...")
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


class AvatarUploader:
    """
    头像上传工具：接收图片文件字节，上传到 OSS，返回公共访问 URL。
    数据库只保存 avatar_url（OSS 公共 URL），不保存大段 base64 文本。
    """

    ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
    MAX_SIZE = 2 * 1024 * 1024  # 2MB

    @staticmethod
    def _ext_from_filename(filename: str) -> str:
        """从原始文件名提取扩展名，不在白名单时回退为 .png。"""
        ext = os.path.splitext(filename or "")[1].lower()
        if ext not in AvatarUploader.ALLOWED_EXTENSIONS:
            ext = ".png"
        return ext

    @staticmethod
    def upload_from_bytes(image_bytes: bytes, filename: str = "avatar.png") -> str:
        """
        将图片文件字节上传到 OSS，返回公共访问 URL。

        :param image_bytes: 图片文件字节内容
        :param filename: 原始文件名（用于推断扩展名）
        :return: 公共访问 URL（形如 https://bucket.oss-cn-beijing.aliyuncs.com/avatar/xxx.png）
        :raises ValueError: 文件过大或内容为空
        """
        if not image_bytes:
            raise ValueError("头像内容为空")
        if len(image_bytes) > AvatarUploader.MAX_SIZE:
            raise ValueError("头像图片过大（超过 2MB）")

        ext = AvatarUploader._ext_from_filename(filename)
        file_id = uuid.uuid4().hex
        tmp_path = os.path.join(tempfile.gettempdir(), f"avatar_{file_id}{ext}")
        try:
            with open(tmp_path, "wb") as f:
                f.write(image_bytes)

            # 上传到 OSS（avatar/ 目录）
            key = f"avatar/{file_id}{ext}"
            oss_client.upload_file(key=key, file_path=tmp_path)
            logger.info(f"✅ 头像上传成功：{key}")
            return oss_client.get_public_url(key=key)
        finally:
            # 清理临时文件
            try:
                os.remove(tmp_path)
            except Exception:
                pass

