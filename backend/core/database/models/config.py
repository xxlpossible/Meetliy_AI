from datetime import datetime

from sqlalchemy import Column, DateTime, Text, text
from sqlmodel import Field, SQLModel, select

from core.database.session import session_getter


class ConfigBase(SQLModel):
    key: str = Field(index=True, unique=True)
    value: str = Field(sa_column=Column(Text))
    comment: str | None = Field(index=False)
    create_time: datetime | None = Field(sa_column=Column(
        DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP')))
    update_time: datetime | None = Field(
        sa_column=Column(DateTime,
                         nullable=False,
                         server_default=text('CURRENT_TIMESTAMP'),
                         onupdate=text('CURRENT_TIMESTAMP')))


class Config(ConfigBase, table=True):
    id: int | None = Field(default=None, primary_key=True)


class ConfigDao(Config):
    @classmethod
    def get_init_db_config(cls):
        with session_getter() as session:
            statement = select(Config).where(Config.key == 'initdb_config')
            initdb_config = session.exec(statement).first()
            return initdb_config
