from contextlib import contextmanager

from sqlmodel import Session

from database.service import DatabaseService
from settings import settings

db_service: 'DatabaseService' = DatabaseService(settings.database_url)

# @contextmanager 是一个装饰器，它让你可以用“写生成器函数”的方式，轻松创建一个支持 with 语句的上下文管理器
@contextmanager
def session_getter() -> Session:
    """轻量级session context"""
    try:
        session = Session(db_service.engine)
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

