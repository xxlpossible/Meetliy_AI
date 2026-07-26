# task/__init__.py
# 这行很重要：导入任务模块，确保任务被注册
from . import tasks  # noqa: F401
from .celery_app import celery_app

__all__ = ['celery_app']
