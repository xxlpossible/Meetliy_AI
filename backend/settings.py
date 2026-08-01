import os
import re

import yaml
from loguru import logger
from pydantic_settings import BaseSettings

from utils.env import load_project_env

# 提前加载项目根目录下的 .env（统一本地与服务器），确保配置项可被环境变量覆盖
load_project_env()

# 各 section 的环境变量前缀与已知字段。
# known_fields 用于纯 .env 模式（数据库无配置）：即使 section_dict 为空，
# 也能按已知字段从环境变量发现配置。
_SECTION_META: dict[str, tuple] = {
    'openai_config':      ('OPENAI',       ['base_url', 'api_key', 'model']),
    'transcription':      ('TRANSCRIPTION', ['base_url', 'api_key', 'model']),
    'hugging_face_config': ('HUGGINGFACE', ['token']),
    'minio_config':       ('',             ['MINIO_ENDPOINT', 'MINIO_ACCESS_KEY', 'MINIO_SECRET_KEY']),
    'dashscope':          ('DASHSCOPE',    ['api_key', 'workspace_id', 'base_url']),
    'rerank':             ('RERANK',       ['model', 'base_url', 'api_key']),
    'chat_model':         ('CHAT_MODEL',    ['model', 'base_url', 'api_key']),
    'rewrite_model':      ('REWRITE_MODEL', ['model', 'base_url', 'api_key']),
    'router_model':       ('ROUTER_MODEL',  ['model', 'base_url', 'api_key']),
    'embeddings':         ('EMBEDDINGS',    ['model', 'base_url', 'api_key']),
}


class Settings(BaseSettings):
    database_url: str | None = None
    redis_url: str | dict | None = None
    celery_redis_url: str | dict | None = None

    @staticmethod
    def get_all_config():
        from core.cache.redis import redis_client
        from core.database.models.config import ConfigDao
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
    def _merge_env(section_dict: dict, env_prefix: str, known_fields: list | None = None) -> dict:
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

    def get_chat_model_config(self):
        prefix, fields = _SECTION_META['chat_model']
        return self._merge_env(self._get_section('chat_model'), prefix, fields)

    def get_rewrite_model_config(self):
        prefix, fields = _SECTION_META['rewrite_model']
        return self._merge_env(self._get_section('rewrite_model'), prefix, fields)

    def get_router_model_config(self):
        prefix, fields = _SECTION_META['router_model']
        return self._merge_env(self._get_section('router_model'), prefix, fields)

    def get_embeddings_config(self):
        prefix, fields = _SECTION_META['embeddings']
        return self._merge_env(self._get_section('embeddings'), prefix, fields)


class ConfigNotFoundError(Exception):
    pass


def _substitute_env_vars(value):
    """递归替换字符串中的 ${VAR_NAME} 或 ${VAR_NAME:-default} 为环境变量值。"""
    if isinstance(value, str):
        def _replacer(m):
            var_name = m.group(1)
            default = m.group(2)
            return os.getenv(var_name, default)
        return re.sub(r'\$\{(\w+)(?::-([^}]*))?\}', _replacer, value)
    elif isinstance(value, dict):
        return {k: _substitute_env_vars(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [_substitute_env_vars(v) for v in value]
    return value


def load_settings_from_yaml(file_path: str) -> Settings:
    # Get current path
    current_path = os.path.dirname(os.path.abspath(__file__))
    # Check if a string is a valid path or a file name
    if '/' not in file_path:
        file_path = os.path.join(current_path, file_path)

    with open(file_path, 'r', encoding='utf-8') as f:
        raw = f.read()

    # 替换 ${ENV_VAR} 语法为实际环境变量值
    raw = re.sub(r'\$\{(\w+)(?::-([^}]*))?\}', lambda m: os.getenv(m.group(1), m.group(2) or ''), raw)

    settings_dict = yaml.safe_load(raw)

    # 本地开发模式：自动将 Docker 服务名换回 127.0.0.1
    if os.getenv('LOCAL_DEV', '').lower() in ('true', '1', 'yes'):
        for key in ('database_url', 'redis_url', 'celery_redis_url'):
            if key in settings_dict and isinstance(settings_dict[key], str):
                settings_dict[key] = settings_dict[key].replace('@mysql:', '@127.0.0.1:')
                settings_dict[key] = settings_dict[key].replace('@redis:', '@127.0.0.1:')
                settings_dict[key] = settings_dict[key].replace('redis://redis:', 'redis://127.0.0.1:')

    for key in settings_dict:
        if key not in Settings.__fields__.keys():
            raise KeyError(f'Key {key} not found in settings')
        logger.debug(f'Loading {len(settings_dict[key])} {key} from {file_path}')

    return Settings(**settings_dict)


config_file = os.getenv('config', 'config.yaml')
settings = load_settings_from_yaml(config_file)

