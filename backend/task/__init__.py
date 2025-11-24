# task/__init__.py
from .celery_app import celery_app

# 这行很重要：导入任务模块，确保任务被注册
from . import tasks

__all__ = ['celery_app']
