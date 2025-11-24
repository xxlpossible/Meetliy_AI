from minio import Minio
from datetime import timedelta
from io import BytesIO
import os

from settings import settings


class MinIOClient:
    def __init__(self, secure=False):
        """
        初始化 MinIO 客户端
        """
        self.minio_config = settings.get_minio_config()
        self.endpoint = self.minio_config.get('MINIO_ENDPOINT')
        self.access_key = self.minio_config.get('MINIO_ACCESS_KEY')
        self.secret_key = self.minio_config.get('MINIO_SECRET_KEY')

        self.client = Minio(
            endpoint=self.endpoint,
            access_key=self.access_key,
            secret_key=self.secret_key,
            secure=secure
        )

    # -------------------- Bucket 相关操作 --------------------
    def ensure_bucket(self, bucket_name: str):
        """
        如果 bucket 不存在则创建
        """
        if not self.client.bucket_exists(bucket_name):
            self.client.make_bucket(bucket_name)

    # -------------------- 上传文件 --------------------
    def upload_file(self, bucket_name: str, object_name: str, file_path: str):
        """
        上传本地文件
        """
        self.ensure_bucket(bucket_name)
        self.client.fput_object(bucket_name, object_name, file_path)
        return f"{bucket_name}/{object_name}"

    def upload_bytes(self, object_name: str, data: bytes,
                     content_type="application/octet-stream",
                     bucket_name: str = "original-audio"
                     ):
        """
        上传字节流（适用于上传音频、语音流）
        """
        self.ensure_bucket(bucket_name)
        data_stream = BytesIO(data)
        self.client.put_object(bucket_name, object_name, data_stream, length=len(data), content_type=content_type)
        return bucket_name, object_name

    # -------------------- 下载文件 --------------------
    def download_file(self, bucket_name: str, object_name: str, file_path: str):
        """
        下载文件到本地
        """
        self.client.fget_object(bucket_name, object_name, file_path)

    def get_file_bytes(self, bucket_name: str, object_name: str) -> bytes:
        """
        获取对象字节流（适合直接处理）
        """
        response = self.client.get_object(bucket_name, object_name)
        data = response.read()
        response.close()
        response.release_conn()
        return data

    # -------------------- 删除文件 --------------------
    def delete_file(self, bucket_name: str, object_name: str):
        """
        删除文件
        """
        self.client.remove_object(bucket_name, object_name)

    # -------------------- 获取预签名链接 --------------------
    def get_presigned_url(self, bucket_name: str, object_name: str, expire_hours: int = 1):
        """
        生成可访问链接，有效期 expire_hours 小时
        """
        url = self.client.presigned_get_object(
            bucket_name,
            object_name,
            expires=timedelta(hours=expire_hours)
        )
        return url


minio_client = MinIOClient()

