"""
迁移脚本：给 chat_session 表增加 need_kb 列
==========================================================

背景：
    SQLModel.metadata.create_all() 在项目中从未调用，所有表变更都依赖本迁移脚本
    通过 ALTER TABLE 完成，确保已部署的环境也能平滑升级。

变更：
    新增 `need_kb` TINYINT(1) NOT NULL DEFAULT 0 列，用于标记该会话是否启用
    知识库检索。对应前端"新建对话"弹窗中"使用知识库"切换按钮（need_kb 参数）。

用法（在 backend 目录下执行）：
    python -m database.migrations.add_chat_session_need_kb

特性：
    - 幂等：执行前先查 information_schema 判断列是否已存在，已存在则跳过。
"""
from loguru import logger
from sqlalchemy import text

from database.base import db_service

TABLE_NAME = "chat_session"
COLUMN_NAME = "need_kb"


def _column_exists(conn, table_name: str, column_name: str) -> bool:
    """查询 information_schema.COLUMNS 判断指定列是否已存在。"""
    sql = text(
        "SELECT COUNT(*) FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :table_name AND COLUMN_NAME = :column_name"
    )
    return conn.scalar(sql, {"table_name": table_name, "column_name": column_name}) > 0


def migrate():
    logger.info(f"开始迁移：检查 {TABLE_NAME}.{COLUMN_NAME}")

    with db_service.engine.begin() as conn:
        if _column_exists(conn, TABLE_NAME, COLUMN_NAME):
            logger.info(f"列 `{TABLE_NAME}.{COLUMN_NAME}` 已存在，跳过添加")
            return

        ddl = (
            f"ALTER TABLE `{TABLE_NAME}` "
            f"ADD COLUMN `{COLUMN_NAME}` TINYINT(1) NOT NULL DEFAULT 0 "
            f"COMMENT '是否启用知识库检索'"
        )
        conn.execute(text(ddl))
        logger.info(f"列 `{TABLE_NAME}.{COLUMN_NAME}` 添加成功")

    logger.info(f"迁移完成：{TABLE_NAME}.{COLUMN_NAME}")


if __name__ == "__main__":
    migrate()
