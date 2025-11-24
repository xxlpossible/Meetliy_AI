from database.service import DatabaseService
import os
from contextlib import contextmanager
from sqlmodel import Session

from settings import settings

db_service: 'DatabaseService' = DatabaseService(settings.database_url)


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


def read_from_conf(file_path: str) -> str:
    if '/' not in file_path:
        # Get current path
        current_path = os.path.dirname(os.path.abspath(__file__))

        file_path = os.path.join(current_path, file_path)

    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    return content
