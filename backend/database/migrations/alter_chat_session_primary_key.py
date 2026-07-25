"""
迁移脚本：将 chat_session 表的主键从自增 id 改为 session_id
==========================================================

背景：
    ChatSession 模型中 id 字段从未被任何代码使用，所有 DAO 方法都用 session_id。
    将主键改为 session_id 简化表结构，移除冗余的自增 id 列。

    注意：此迁移脚本仅修改主键结构，不改变数据内容。
    执行前请确保 chat_session 表存在且有数据备份。

用法（在 backend 目录下执行）：
    python -m database.migrations.alter_chat_session_primary_key

"""
from loguru import logger
from sqlalchemy import text

from database.base import db_service


def _table_exists(conn, table_name: str) -> bool:
    """查询 information_schema 判断表是否已存在。"""
    sql = text(
        "SELECT COUNT(*) FROM information_schema.TABLES "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :table_name"
    )
    return conn.scalar(sql, {"table_name": table_name}) > 0


def _has_id_column(conn, table_name: str) -> bool:
    """检查表是否仍有 id 列（判断是否需要迁移）。"""
    sql = text(
        "SELECT COUNT(*) FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :table_name AND COLUMN_NAME = 'id'"
    )
    return conn.scalar(sql, {"table_name": table_name}) > 0


def migrate():
    table_name = "chat_session"
    logger.info(f"开始迁移表 {table_name} 主键")

    with db_service.engine.begin() as conn:
        if not _table_exists(conn, table_name):
            logger.error(f"表 {table_name} 不存在，请先运行 create_chat_session_table.py")
            return

        if not _has_id_column(conn, table_name):
            logger.info(f"表 {table_name} 已无 id 列，跳过迁移")
            return

        # 1. 删除自增 id 列，将 session_id 设为主键
        # 注意：需要先删除自增主键，再添加新主键
        conn.execute(text(f"""
            ALTER TABLE `{table_name}`
            DROP PRIMARY KEY,
            CHANGE COLUMN `id` `id` INT NULL,
            DROP COLUMN `id`,
            ADD PRIMARY KEY (`session_id`)
        """))

        logger.info(f"表 {table_name} 主键已改为 session_id")


if __name__ == "__main__":
    migrate()
