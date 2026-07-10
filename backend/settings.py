import os
from typing import Optional, Union, Dict

import yaml
from dotenv import load_dotenv


from loguru import logger
from pydantic_settings import BaseSettings

# 提前加载 .env，确保配置项可被环境变量覆盖（.env 优先于数据库 config 表）
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

# 各 section 的环境变量前缀与已知字段。
# known_fields 用于纯 .env 模式（数据库无配置）：即使 section_dict 为空，
# 也能按已知字段从环境变量发现配置。
_SECTION_META: Dict[str, tuple] = {
    'openai_config':      ('OPENAI',       ['base_url', 'api_key', 'model']),
    'transcription':      ('TRANSCRIPTION', ['base_url', 'api_key', 'model']),
    'hugging_face_config': ('HUGGINGFACE', ['token']),
    'minio_config':       ('',             ['MINIO_ENDPOINT', 'MINIO_ACCESS_KEY', 'MINIO_SECRET_KEY']),
    'dashscope':          ('DASHSCOPE',    ['api_key']),
    'rerank':             ('RERANK',       ['model', 'base_url', 'api_key']),
    'qwen':               ('QWEN',         ['model', 'base_url', 'api_key']),
    'embeddings':         ('EMBEDDINGS',   ['model', 'base_url', 'api_key']),
}


class Settings(BaseSettings):
    database_url: Optional[str] = None
    redis_url: Optional[Union[str, Dict]] = None
    celery_redis_url: Optional[Union[str, Dict]] = None

    @staticmethod
    def get_all_config():
        from cache.redis import redis_client
        from database.models.config import ConfigDao
        redis_key = 'config:initdb_config'
        cache = redis_client.get(redis_key)
        if cache:
            return yaml.safe_load(cache)
        else:

            initdb_config = ConfigDao.get_init_db_config()
            if initdb_config:
                redis_client.set(redis_key, initdb_config.value, 100)
                return yaml.safe_load(initdb_config.value)
            else:
                raise ConfigNotFoundError('initdb_config not found, please check your system config')

    @staticmethod
    def _merge_env(section_dict: dict, env_prefix: str, known_fields: list = None) -> dict:
        """
        用环境变量覆盖 section 配置项，实现「.env 优先、数据库兜底」。

        规则：对每个字段 field，检查环境变量
          - env_prefix 非空：{ENV_PREFIX}_{FIELD}（均大写），如 OPENAI_API_KEY 覆盖 openai_config.api_key
          - env_prefix 为空：直接以字段名（大写）作为环境变量名，适用于字段本身已是 env 风格的 section（如 minio_config）

        字段来源 = section_dict 的 keys ∪ known_fields，确保纯 .env 模式
        （section_dict 为空）时也能按已知字段从环境变量发现配置。
        仅当环境变量存在且非空时覆盖，否则保留数据库原值。
        """
        if not section_dict and not known_fields:
            return {}
        result = dict(section_dict) if section_dict else {}
        fields = set(result.keys())
        if known_fields:
            fields = fields.union(known_fields)
        for field in fields:
            env_name = f"{env_prefix}_{field}".upper() if env_prefix else str(field).upper()
            env_val = os.getenv(env_name)
            if env_val is not None and env_val != "":
                result[field] = env_val
        return result

    def _get_section(self, section_name: str) -> dict:
        """
        取某个 section 的配置字典。
        数据库无配置（ConfigNotFoundError）时返回空字典，此时可完全由 .env 接管。
        """
        try:
            return self.get_all_config().get(section_name, {}) or {}
        except ConfigNotFoundError:
            logger.debug(f"config 表无配置，{section_name} 完全使用环境变量")
            return {}

    def get_openai_config(self):
        prefix, fields = _SECTION_META['openai_config']
        return self._merge_env(self._get_section('openai_config'), prefix, fields)

    def get_transcription_config(self):
        prefix, fields = _SECTION_META['transcription']
        return self._merge_env(self._get_section('transcription'), prefix, fields)

    def get_hugging_face_config(self):
        prefix, fields = _SECTION_META['hugging_face_config']
        return self._merge_env(self._get_section('hugging_face_config'), prefix, fields)

    def get_minio_config(self):
        prefix, fields = _SECTION_META['minio_config']
        return self._merge_env(self._get_section('minio_config'), prefix, fields)

    def get_dashscope_config(self):
        prefix, fields = _SECTION_META['dashscope']
        return self._merge_env(self._get_section('dashscope'), prefix, fields)

    def get_rerank_config(self):
        prefix, fields = _SECTION_META['rerank']
        return self._merge_env(self._get_section('rerank'), prefix, fields)

    def get_qwen_config(self):
        prefix, fields = _SECTION_META['qwen']
        return self._merge_env(self._get_section('qwen'), prefix, fields)

    def get_embeddings_config(self):
        prefix, fields = _SECTION_META['embeddings']
        return self._merge_env(self._get_section('embeddings'), prefix, fields)


class ConfigNotFoundError(Exception):
    pass


def load_settings_from_yaml(file_path: str) -> Settings:
    # Get current path
    current_path = os.path.dirname(os.path.abspath(__file__))
    # Check if a string is a valid path or a file name
    if '/' not in file_path:
        file_path = os.path.join(current_path, file_path)

    with open(file_path, 'r', encoding='utf-8') as f:
        settings_dict = yaml.safe_load(f)

    for key in settings_dict:
        if key not in Settings.__fields__.keys():
            raise KeyError(f'Key {key} not found in settings')
        logger.debug(f'Loading {len(settings_dict[key])} {key} from {file_path}')

    return Settings(**settings_dict)


config_file = os.getenv('config', 'config.yaml')
settings = load_settings_from_yaml(config_file)

