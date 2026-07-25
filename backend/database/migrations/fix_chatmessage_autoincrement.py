"""
迁移脚本：修复 chatmessage 表的 chat_id 自增问题
==========================================================

背景：
    原 chat_id 列缺少 AUTO_INCREMENT，导致插入时不传 chat_id 报错：
    (pymysql.err.OperationalError) (1364, "Field 'chat_id' doesn't have a default value")

修复：
    给 chat_id 列添加 AUTO_INCREMENT 属性。

用法（在 backend 目录下执行）：
    python -m database.migrations.fix_chatmessage_autoincrement

特性：
    - 幂等：先查 information_schema.COLUMNS 的 EXTRA 字段判断是否已有 auto_increment。
"""

from loguru import logger
from sqlalchemy import text

from database.base import db_service
from database.models.chatmessage import ChatMessage


def _has_auto_increment(conn, table_name: str, column_name: str) -> bool:
    """检查指定列是否已有 AUTO_INCREMENT"""
    sql = text(
        "SELECT EXTRA FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() "
        "AND TABLE_NAME = :table_name AND COLUMN_NAME = :column_name"
    )
    extra = conn.scalar(sql, {"table_name": table_name, "column_name": column_name})
    return extra and "auto_increment" in extra.lower()


def migrate():
    table_name = ChatMessage.__tablename__
    logger.info(f"开始检查表 {table_name} 的 chat_id 自增属性")

    with db_service.engine.begin() as conn:
        if _has_auto_increment(conn, table_name, "chat_id"):
            logger.info("列 chat_id 已有 AUTO_INCREMENT，无需修复")
            return

        logger.info("列 chat_id 缺少 AUTO_INCREMENT，正在修复...")
        conn.execute(text(
            f"ALTER TABLE `{table_name}` "
            f"MODIFY COLUMN `chat_id` INT NOT NULL AUTO_INCREMENT"
        ))
        logger.info("列 chat_id 已添加 AUTO_INCREMENT")

    logger.info(f"表 {table_name} 修复完成")


if __name__ == "__main__":
    migrate()
