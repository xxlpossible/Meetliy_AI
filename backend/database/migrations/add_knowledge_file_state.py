"""
迁移脚本：为 knowledgefile 表新增 state 与 fail_reason 列
==========================================================

背景：
    SQLModel.metadata.create_all() 不会 ALTER 已有表结构。
    KnowledgeFile 模型新增了 state（解析状态）与 fail_reason（失败原因）两个字段，
    需通过本脚本对已存在的表执行 ALTER TABLE 补列。

用法（在 backend 目录下执行）：
    python -m database.migrations.add_knowledge_file_state

特性：
    - 幂等：执行前先查 information_schema 判断列是否已存在，已存在则跳过。
    - state 列：INT NOT NULL DEFAULT 0（0=解析中 1=成功 2=失败）。
    - fail_reason 列：TEXT NULL（解析失败时写入原因）。
"""
from loguru import logger
from sqlalchemy import text

from database.base import db_service
from database.models.knowledge_file import KnowledgeFile


def _column_exists(conn, table_name: str, column_name: str) -> bool:
    """查询 information_schema 判断列是否已存在。"""
    sql = text(
        "SELECT COUNT(*) FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() "
        "AND TABLE_NAME = :table_name AND COLUMN_NAME = :column_name"
    )
    return conn.scalar(sql, {"table_name": table_name, "column_name": column_name}) > 0


def migrate():
    table_name = KnowledgeFile.__tablename__
    logger.info(f"开始迁移表 {table_name}：新增 state / fail_reason 列")

    with db_service.engine.begin() as conn:
        # state 列：解析状态 0解析中 1成功 2失败，默认0
        if _column_exists(conn, table_name, "state"):
            logger.info("列 `state` 已存在，跳过")
        else:
            conn.execute(text(
                f"ALTER TABLE `{table_name}` ADD COLUMN `state` INT NOT NULL DEFAULT 0 "
                "COMMENT '解析状态 0解析中 1成功 2失败'"
            ))
            logger.info("列 `state` 新增成功")

        # fail_reason 列：解析失败原因
        if _column_exists(conn, table_name, "fail_reason"):
            logger.info("列 `fail_reason` 已存在，跳过")
        else:
            conn.execute(text(
                f"ALTER TABLE `{table_name}` ADD COLUMN `fail_reason` TEXT NULL "
                "COMMENT '解析失败原因'"
            ))
            logger.info("列 `fail_reason` 新增成功")

    logger.info(f"表 {table_name} 迁移完成")


if __name__ == "__main__":
    migrate()
