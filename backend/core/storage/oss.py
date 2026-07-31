import os

import alibabacloud_oss_v2 as oss
import dotenv


class OSSClientUtil:
    """
    阿里云 OSS 工具类
    - 自动加载 .env 环境变量
    - 提供文件上传、预签名 URL 生成等功能
    """

    def __init__(self, env_path: str | None = None, region: str = "cn-beijing"):
        if env_path is None:
            env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env")
        # 1. 加载环境变量
        dotenv.load_dotenv(env_path)

        # 2. 创建凭证提供者（从环境变量读取）
        self.credentials_provider = oss.credentials.EnvironmentVariableCredentialsProvider()

        # 3. 加载默认配置
        self.cfg = oss.config.load_default()
        self.cfg.credentials_provider = self.credentials_provider
        self.cfg.region = region
        self.cfg.endpoint = f"oss-{region}.aliyuncs.com"

        # 4. 创建客户端
        self.client = oss.Client(self.cfg)

    # -----------------------------
    # 上传文件
    # -----------------------------
    def upload_file(self, bucket: str = "java-web-deng", key: str | None = None, file_path: str | None = None):
        """
        上传本地文件到 OSS
        :param bucket: OSS Bucket 名称
        :param key: OSS 对象名称
        :param file_path: 本地文件路径
        :return: 上传结果对象
        """
        result = self.client.put_object_from_file(
            oss.PutObjectRequest(bucket=bucket, key=key),
            filepath=file_path
        )
        return result

    # -----------------------------
    # 生成预签名 URL
    # -----------------------------
    def generate_presigned_url(self, bucket: str = "java-web-deng", key: str | None = None):
        """
        生成 OSS GET 预签名 URL
        :param bucket: OSS Bucket 名称
        :param key: OSS 对象名称
        :param expire_seconds: 预签名 URL 过期秒数
        :return: URL 字符串
        """
        pre_result = self.client.presign(
            oss.GetObjectRequest(
                bucket=bucket, key=key
            )
        )

        return pre_result.url


oss_client = OSSClientUtil()
