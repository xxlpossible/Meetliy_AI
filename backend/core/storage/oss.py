import os

import alibabacloud_oss_v2 as oss
from loguru import logger

from utils.env import ENV_PATH, load_project_env


class OSSClientUtil:
    """
    阿里云 OSS 工具类
    - 自动加载项目根目录下的 .env 环境变量（统一本地与服务器）
    - 提供文件上传、公共访问 URL / 预签名 URL 生成等功能
    """

    def __init__(self, env_path: str | None = None):
        if env_path is None:
            # 统一使用项目根目录下的 .env（兼容本地和 Docker/服务器部署）
            load_project_env()
            env_path = str(ENV_PATH) if ENV_PATH.exists() else None
        # 1. 加载环境变量
        if env_path and os.path.exists(env_path):
            load_project_env()

        # 2. 读取配置（支持通过 .env 覆盖）
        self.bucket = os.getenv("OSS_BUCKET_NAME", "java-web-deng")
        self.endpoint = os.getenv("OSS_ENDPOINT", "oss-cn-beijing.aliyuncs.com")
        # 从 endpoint 中解析 region（如 oss-cn-beijing.aliyuncs.com -> cn-beijing）
        self.region = self.endpoint.split(".")[0].replace("oss-", "", 1) if self.endpoint.startswith("oss-") else "cn-beijing"

        # 3. 创建凭证提供者（从环境变量读取）
        self.credentials_provider = oss.credentials.EnvironmentVariableCredentialsProvider()

        # 4. 加载默认配置
        self.cfg = oss.config.load_default()
        self.cfg.credentials_provider = self.credentials_provider
        self.cfg.region = self.region
        self.cfg.endpoint = self.endpoint

        # 5. 创建客户端
        self.client = oss.Client(self.cfg)

    # -----------------------------
    # 公共访问 URL
    # -----------------------------
    def get_public_url(self, bucket: str | None = None, key: str | None = None) -> str:
        """
        生成 OSS 公共读访问 URL（需 bucket 开启公共读）。
        形如：https://java-web-deng.oss-cn-beijing.aliyuncs.com/avatar/xxx.png
        """
        bucket = bucket or self.bucket
        return f"https://{bucket}.{self.endpoint}/{key}"

    # -----------------------------
    # 从公共 URL 解析出 OSS key
    # -----------------------------
    def parse_key_from_url(self, url: str | None) -> str | None:
        """
        从公共访问 URL 中解析出 OSS key。
        形如：https://{bucket}.{endpoint}/avatar/xxx.png  ->  avatar/xxx.png
        若无法解析则返回 None。
        """
        if not url:
            return None
        prefix = f"https://{self.bucket}.{self.endpoint}/"
        if url.startswith(prefix):
            return url[len(prefix):].strip() or None
        return None

    # -----------------------------
    # 上传文件
    # -----------------------------
    def upload_file(self, bucket: str | None = None, key: str | None = None, file_path: str | None = None):
        """
        上传本地文件到 OSS
        :param bucket: OSS Bucket 名称（缺省时使用环境变量配置）
        :param key: OSS 对象名称
        :param file_path: 本地文件路径
        :return: 上传结果对象
        """
        bucket = bucket or self.bucket
        result = self.client.put_object_from_file(
            oss.PutObjectRequest(bucket=bucket, key=key),
            filepath=file_path
        )
        return result

    # -----------------------------
    # 删除文件
    # -----------------------------
    def delete_file(self, bucket: str | None = None, key: str | None = None):
        """
        删除 OSS 对象。
        :param bucket: OSS Bucket 名称（缺省时使用环境变量配置）
        :param key: OSS 对象名称
        """
        if not key:
            return
        bucket = bucket or self.bucket
        try:
            self.client.delete_object(oss.DeleteObjectRequest(bucket=bucket, key=key))
        except Exception:
            # 删除旧头像失败不阻断主流程，仅记录日志
            logger.warning(f"删除 OSS 对象失败：{bucket}/{key}")

    # -----------------------------
    # 生成预签名 URL
    # -----------------------------
    def generate_presigned_url(self, bucket: str | None = None, key: str | None = None):
        """
        生成 OSS GET 预签名 URL
        :param bucket: OSS Bucket 名称（缺省时使用环境变量配置）
        :param key: OSS 对象名称
        :return: URL 字符串
        """
        bucket = bucket or self.bucket
        pre_result = self.client.presign(
            oss.GetObjectRequest(
                bucket=bucket, key=key
            )
        )

        return pre_result.url


oss_client = OSSClientUtil()
