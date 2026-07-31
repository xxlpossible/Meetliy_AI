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
        # 自动检测 backend 根目录：向上查找包含 config.yaml 的目录
        # 兼容本地开发（__file__ 在 D:\...\backend\core\database\...）
        # 和 Docker 部署（__file__ 在 /app/core/database/...，多一层 /app/ 前缀）
        def _find_backend_dir():
            current = Path(__file__).resolve().parent
            for _ in range(6):
                if (current / "config.yaml").exists():
                    return current
                if current.parent == current:
                    break
                current = current.parent
            raise RuntimeError("无法定位 backend 根目录（未找到 config.yaml）")

        base_dir = _find_backend_dir()
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
