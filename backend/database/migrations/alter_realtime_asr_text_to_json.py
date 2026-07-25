"""
迁移脚本：将 transcription 表的 realtime_asr_text 列从 TEXT 改为 JSON 类型
==========================================================

背景：
    SQLModel.metadata.create_all() 在项目中从未调用，所有表变更都依赖本迁移脚本
    通过 ALTER TABLE 完成，确保已部署的环境也能平滑升级。

变更：
    将 `realtime_asr_text` 列从 TEXT 改为 JSON 类型，用于存储转录文本行列表。

用法（在 backend 目录下执行）：
    python -m database.migrations.alter_realtime_asr_text_to_json

特性：
    - 幂等：执行前先查 information_schema 判断列类型，已是 JSON 则跳过。
"""
from loguru import logger
from sqlalchemy import text

from database.base import db_service

TABLE_NAME = "transcription"
COLUMN_NAME = "realtime_asr_text"


def _column_is_json(conn, table_name: str, column_name: str) -> bool:
    """查询 information_schema.COLUMNS 判断指定列是否为 JSON 类型。"""
    sql = text(
        "SELECT DATA_TYPE FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :table_name AND COLUMN_NAME = :column_name"
    )
    row = conn.execute(sql, {"table_name": table_name, "column_name": column_name}).fetchone()
    if not row:
        return False
    return row[0].lower() == "json"


def _column_exists(conn, table_name: str, column_name: str) -> bool:
    """查询 information_schema.COLUMNS 判断指定列是否存在。"""
    sql = text(
        "SELECT COUNT(*) FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :table_name AND COLUMN_NAME = :column_name"
    )
    return conn.scalar(sql, {"table_name": table_name, "column_name": column_name}) > 0


def migrate():
    logger.info(f"开始迁移：检查 {TABLE_NAME}.{COLUMN_NAME}")

    with db_service.engine.begin() as conn:
        if not _column_exists(conn, TABLE_NAME, COLUMN_NAME):
            # 列不存在，添加 JSON 列
            ddl = (
                f"ALTER TABLE `{TABLE_NAME}` "
                f"ADD COLUMN `{COLUMN_NAME}` JSON NULL "
                f"COMMENT '实时转录文本行列表'"
            )
            conn.execute(text(ddl))
            logger.info(f"列 `{TABLE_NAME}.{COLUMN_NAME}` 添加成功（JSON 类型）")
            return

        if _column_is_json(conn, TABLE_NAME, COLUMN_NAME):
            logger.info(f"列 `{TABLE_NAME}.{COLUMN_NAME}` 已是 JSON 类型，跳过")
            return

        # 列存在但不是 JSON 类型，修改列类型
        ddl = (
            f"ALTER TABLE `{TABLE_NAME}` "
            f"MODIFY COLUMN `{COLUMN_NAME}` JSON NULL "
            f"COMMENT '实时转录文本行列表'"
        )
        conn.execute(text(ddl))
        logger.info(f"列 `{TABLE_NAME}.{COLUMN_NAME}` 修改为 JSON 类型成功")

    logger.info(f"迁移完成：{TABLE_NAME}.{COLUMN_NAME}")


if __name__ == "__main__":
    migrate()
