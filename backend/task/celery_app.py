# task/celery_app.py
from celery import Celery
from settings import settings

# 创建 Celery 应用实例
celery_app = Celery('tasks')

# 配置
celery_app.conf.broker_url = settings.celery_redis_url
celery_app.conf.result_backend = settings.celery_redis_url
celery_app.conf.timezone = 'Asia/Shanghai'
celery_app.conf.enable_utc = False

# 自动发现任务
celery_app.autodiscover_tasks(['task'])

# 启动命令
# 进入 backend 目录 执行 celery -A task worker -l info -P eventlet
