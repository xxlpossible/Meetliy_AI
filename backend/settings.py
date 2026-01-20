import os
from typing import Optional, Union, Dict

import yaml


from loguru import logger
from pydantic_settings import BaseSettings


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

    def get_openai_config(self):
        all_config = self.get_all_config()
        return all_config.get('openai_config', {})

    def get_transcription_config(self):
        all_config = self.get_all_config()
        return all_config.get('transcription', {})

    def get_hugging_face_config(self):
        all_config = self.get_all_config()
        return all_config.get('hugging_face_config', {})

    def get_minio_config(self):
        all_config = self.get_all_config()
        return all_config.get('minio_config', {})

    def get_dashscope_config(self):
        all_config = self.get_all_config()
        return all_config.get('dashscope', {})

    def get_rerank_config(self):
        all_config = self.get_all_config()
        return all_config.get('rerank', {})

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

