"""
迁移脚本：创建 meeting 表
==========================================================

背景：
    SQLModel.metadata.create_all() 在项目中从未调用，现有迁移脚本只做 ALTER TABLE。
    Meeting 是全新表，需通过本脚本执行原始 CREATE TABLE IF NOT EXISTS。

用法（在 backend 目录下执行）：
    python -m database.migrations.add_meeting_table

特性：
    - 幂等：执行前先查 information_schema 判断表是否已存在，已存在则跳过。
    - 列定义与 Meeting SQLModel 一致（user_ids 为 MySQL JSON 列）。
"""
from loguru import logger
from sqlalchemy import text

from database.base import db_service

TABLE_NAME = "meeting"

DDL = f"""
CREATE TABLE IF NOT EXISTS `{TABLE_NAME}` (
    `id` VARCHAR(32) NOT NULL,
    `meeting_name` VARCHAR(255) NULL COMMENT '会议名称',
    `host_user_id` INT NOT NULL COMMENT '会议发起人(主持人)ID',
    `user_ids` JSON NOT NULL COMMENT '参会者用户ID列表',
    `status` INT DEFAULT 0 COMMENT '会议状态 0进行中 1结束解析中 2解析完成 -1异常',
    `task_id` VARCHAR(32) NULL COMMENT '结束后关联的转录任务ID',
    `create_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `update_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    INDEX `ix_meeting_host_user_id` (`host_user_id`),
    INDEX `ix_meeting_create_time` (`create_time`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""


def _table_exists(conn, table_name: str) -> bool:
    """查询 information_schema 判断表是否已存在。"""
    sql = text(
        "SELECT COUNT(*) FROM information_schema.TABLES "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :table_name"
    )
    return conn.scalar(sql, {"table_name": table_name}) > 0


def migrate():
    logger.info(f"开始迁移：检查表 {TABLE_NAME}")

    with db_service.engine.begin() as conn:
        if _table_exists(conn, TABLE_NAME):
            logger.info(f"表 `{TABLE_NAME}` 已存在，跳过创建")
            return

        conn.execute(text(DDL))
        logger.info(f"表 `{TABLE_NAME}` 创建成功")

    logger.info(f"迁移完成：表 {TABLE_NAME}")


if __name__ == "__main__":
    migrate()
