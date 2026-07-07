# database/check_points.py
import os
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver
from loguru import logger


class CheckpointerManager:
    _sqlite_cm = None
    _checkpointer = None

    @classmethod
    def init(cls):
        if cls._checkpointer is None:
            # Path(__file__) 获取当前文件 check_points.py 的路径
            # .parent 是 database/ 目录
            # .parent.parent 是 backend/ 目录（即上一级）
            base_dir = Path(__file__).parent.parent
            db_path = base_dir / "checkpoints.db"
            # 确保转换为字符串路径，并使用绝对路径以防万一
            db_path_str = str(db_path.absolute())
            cls._sqlite_cm = SqliteSaver.from_conn_string(db_path_str)
            # SqliteSaver.from_conn_string 返回的是一个上下文管理器
            cls._checkpointer = cls._sqlite_cm.__enter__()
            logger.info(f"SqliteSaver 初始化完成: {db_path_str}")

    @classmethod
    def get_checkpointer(cls):
        if cls._checkpointer is None:
            logger.info("FastAPI未初始化SQL-lite，已自动初始化")
            cls.init()
        return cls._checkpointer

    @classmethod
    def close(cls):
        if cls._sqlite_cm:
            cls._sqlite_cm.__exit__(None, None, None)
            cls._sqlite_cm = None
            cls._checkpointer = None
            logger.info("SqliteSaver 已关闭")
