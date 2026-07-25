"""
迁移脚本：给 meeting 表增加 is_delete 列（软删除标记）
==========================================================

背景：
    SQLModel.metadata.create_all() 在项目中从未调用，所有表变更都依赖本迁移脚本
    通过 ALTER TABLE 完成，确保已部署的环境也能平滑升级。

变更：
    新增 `is_delete` TINYINT(1) DEFAULT 0 列，用于软删除标记。
    默认 0（正常），设为 -1 时表示已删除，查询时过滤掉。

用法（在 backend 目录下执行）：
    python -m database.migrations.add_meeting_is_delete

特性：
    - 幂等：执行前先查 information_schema 判断列是否已存在，已存在则跳过。
    - 兼容：使用 TINYINT(1) 作为整数类型，与项目现有 Delete 枚举一致。
"""
from loguru import logger
from sqlalchemy import text

from database.base import db_service

TABLE_NAME = "meeting"
COLUMN_NAME = "is_delete"


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
            f"ADD COLUMN `{COLUMN_NAME}` TINYINT(1) NULL DEFAULT 0 "
            f"COMMENT '软删除标记 0正常 -1已删除'"
        )
        conn.execute(text(ddl))
        logger.info(f"列 `{TABLE_NAME}.{COLUMN_NAME}` 添加成功")

    logger.info(f"迁移完成：{TABLE_NAME}.{COLUMN_NAME}")


if __name__ == "__main__":
    migrate()
