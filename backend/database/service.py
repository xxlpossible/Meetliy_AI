from typing import TYPE_CHECKING

from loguru import logger
from sqlmodel import Session, create_engine

from service.base import Service

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine


class DatabaseService(Service):
    name: str = 'database_service'

    def __init__(self, database_url: str):
        self.database_url = database_url
        # This file is in langflow.services.database.manager.py
        # the ini is in langflow
        # langflow_dir = Path(__file__).parent.parent.parent
        # self.script_location = langflow_dir / "alembic"
        # self.alembic_cfg_path = langflow_dir / "alembic.ini"
        self.engine = self._create_engine()

    def _create_engine(self) -> 'Engine':
        """Create the engine for the database."""
        connect_args = {}
        return create_engine(
            self.database_url,
            connect_args=connect_args,
            pool_size=100,
            max_overflow=20,
            pool_pre_ping=True,
            echo=True
        )

    def __enter__(self):
        self._session = Session(self.engine)
        return self._session

    def __exit__(self, exc_type, exc_value, traceback):
        if exc_type is not None:  # If an exception has been raised
            logger.error(f'Session rollback because of exception: {exc_type.__name__} {exc_value}')
            self._session.rollback()
        else:
            self._session.commit()
        self._session.close()

