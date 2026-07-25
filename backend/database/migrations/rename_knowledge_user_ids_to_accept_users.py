"""
迁移脚本：knowledge 表结构变更
==========================================================

背景：
    SQLModel.metadata.create_all() 不会 ALTER 已有表结构。
    Knowledge 模型变更：
      1. 新增 creater 列（创建者用户ID）
      2. user_ids 列重命名为 accept_users

用法（在 backend 目录下执行）：
    python -m database.migrations.rename_knowledge_user_ids_to_accept_users

特性：
    - 幂等：执行前先查 information_schema 判断列是否已存在/需要重命名。
    - creater 列：INT NULL（兼容旧数据，旧数据 creater 为 NULL，后续代码需兼容）。
    - accept_users 列：原 user_ids 列重命名。
"""
from loguru import logger
from sqlalchemy import text

from database.base import db_service
from database.models.knowledge import Knowledge


def _column_exists(conn, table_name: str, column_name: str) -> bool:
    """查询 information_schema 判断列是否已存在。"""
    sql = text(
        "SELECT COUNT(*) FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() "
        "AND TABLE_NAME = :table_name AND COLUMN_NAME = :column_name"
    )
    return conn.scalar(sql, {"table_name": table_name, "column_name": column_name}) > 0


def _column_rename(conn, table_name: str, old_name: str, new_name: str, col_type: str):
    """重命名列（MySQL 8+ 支持 RENAME COLUMN，跨版本用 CHANGE COLUMN）。"""
    sql = text(
        f"ALTER TABLE `{table_name}` CHANGE COLUMN `{old_name}` `{new_name}` {col_type}"
    )
    conn.execute(sql)


def migrate():
    table_name = Knowledge.__tablename__
    logger.info(f"开始迁移表 {table_name}：新增 creater 列 + user_ids 重命名为 accept_users")

    with db_service.engine.begin() as conn:
        # 1. 新增 creater 列
        if _column_exists(conn, table_name, "creater"):
            logger.info("列 `creater` 已存在，跳过")
        else:
            conn.execute(text(
                f"ALTER TABLE `{table_name}` ADD COLUMN `creater` INT NULL "
                "COMMENT '知识库创建者用户ID'"
            ))
            logger.info("列 `creater` 新增成功")

        # 2. user_ids → accept_users 重命名（如果 user_ids 存在且 accept_users 不存在）
        has_user_ids = _column_exists(conn, table_name, "user_ids")
        has_accept_users = _column_exists(conn, table_name, "accept_users")

        if has_user_ids and not has_accept_users:
            # JSON 列重命名：需要指定完整类型
            _column_rename(conn, table_name, "user_ids", "accept_users", "JSON NOT NULL")
            logger.info("列 `user_ids` 重命名为 `accept_users` 成功")
        elif has_accept_users:
            logger.info("列 `accept_users` 已存在，跳过重命名")
        else:
            # 两个都不存在，直接加 accept_users 列
            conn.execute(text(
                f"ALTER TABLE `{table_name}` ADD COLUMN `accept_users` JSON NOT NULL "
                "COMMENT '有权访问的用户ID列表（不含创建者）'"
            ))
            logger.info("列 `accept_users` 新增成功")

    logger.info(f"表 {table_name} 迁移完成")


if __name__ == "__main__":
    migrate()
