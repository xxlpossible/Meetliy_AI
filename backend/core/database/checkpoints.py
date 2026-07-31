# database/check_points.py
import os
from pathlib import Path

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from loguru import logger


class CheckpointerManager:
    """
    基于 AsyncSqliteSaver 的异步 checkpointer 管理器。

    LangGraph 的 async astream / ainvoke 要求 checkpointer 实现异步方法
    (aget_tuple / aput / aput_writes / alist)，同步 SqliteSaver 不满足
    （调用 astream 会抛 NotImplementedError），因此统一改用 AsyncSqliteSaver
    （依赖 aiosqlite）。

    生命周期：init() / close() 应在 FastAPI lifespan 中 await 调用；
    get_checkpointer() 在未初始化时会自动惰性初始化作为兜底。
    """
    _async_cm = None
    _checkpointer = None

    @classmethod
    async def init(cls):
        if cls._checkpointer is not None:
            return
        # Path(__file__) 获取当前文件 checkpoints.py 的路径
        # .parent 是 database/ 目录
        # .parent.parent 是 core/ 目录
        # .parent.parent.parent 是 /app/ 目录（backend 根目录）
        base_dir = Path(__file__).resolve().parent.parent.parent
        db_path = base_dir / "checkpoints_db" / "checkpoints.db"
        # 确保父目录存在（SQLite 不会自动创建）
        os.makedirs(db_path.parent, exist_ok=True)
        # 确保转换为字符串路径，并使用绝对路径以防万一
        db_path_str = str(db_path.absolute())
        # AsyncSqliteSaver.from_conn_string 返回一个异步上下文管理器
        cls._async_cm = AsyncSqliteSaver.from_conn_string(db_path_str)
        cls._checkpointer = await cls._async_cm.__aenter__()
        logger.info(f"AsyncSqliteSaver 初始化完成: {db_path_str}")

    @classmethod
    async def get_checkpointer(cls):
        if cls._checkpointer is None:
            logger.info("AsyncSqliteSaver 尚未初始化，已自动初始化")
            await cls.init()
        return cls._checkpointer

    @classmethod
    async def close(cls):
        if cls._async_cm is not None:
            await cls._async_cm.__aexit__(None, None, None)
            cls._async_cm = None
            cls._checkpointer = None
            logger.info("AsyncSqliteSaver 已关闭")
