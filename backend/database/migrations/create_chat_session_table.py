"""
迁移脚本：创建 chat_session 表
==========================================================

背景：
    chat_session 表用于存储 AI 对话会话元信息。
    session 在 WebSocket /ws/chat 中首次收到消息时自动创建。
    需要运行此脚本物理创建表（create_all 不会 ALTER 已有表）。

用法（在 backend 目录下执行）：
    python -m database.migrations.create_chat_session_table

"""
from loguru import logger
from sqlalchemy import text

from database.base import db_service
from database.models.chat_session import ChatSession


def _table_exists(conn, table_name: str) -> bool:
    """查询 information_schema 判断表是否已存在。"""
    sql = text(
        "SELECT COUNT(*) FROM information_schema.TABLES "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :table_name"
    )
    return conn.scalar(sql, {"table_name": table_name}) > 0


def migrate():
    table_name = ChatSession.__tablename__
    logger.info(f"开始创建表 {table_name}")

    with db_service.engine.begin() as conn:
        if _table_exists(conn, table_name):
            logger.info(f"表 {table_name} 已存在，跳过创建")
            return

        conn.execute(text(f"""
            CREATE TABLE `{table_name}` (
                `id` INT AUTO_INCREMENT PRIMARY KEY,
                `session_id` VARCHAR(255) NOT NULL,
                `session_name` VARCHAR(255) DEFAULT NULL,
                `user_id` INT NOT NULL,
                `meeting_ids` JSON NOT NULL COMMENT '关联的会议ID列表',
                `knowledge_ids` JSON NOT NULL COMMENT '关联的知识库ID列表',
                `create_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                `update_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                INDEX `ix_{table_name}_session_id` (`session_id`),
                INDEX `ix_{table_name}_user_id` (`user_id`),
                INDEX `ix_{table_name}_create_time` (`create_time`),
                INDEX `ix_{table_name}_update_time` (`update_time`)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
        """))
        logger.info(f"表 {table_name} 创建成功")


if __name__ == "__main__":
    migrate()
