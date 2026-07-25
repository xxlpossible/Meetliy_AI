"""
迁移脚本：重构 chatmessage 表
==========================================================

背景：
    原 ChatMessage 结构为 (task_id, chat_messages[JSON], user_id)，
    每次会话存储多条消息的 JSON 数组。

    新结构改为每条记录对应一条（一个输入或输出）：
    - session_id: 会话 ID（原 task_id 改名）
    - role: user / assistant
    - content: 消息内容
    - turn_index: 会话内轮次序号
    - user_id: 用户 ID（保留）

用法（在 backend 目录下执行）：
    python -m database.migrations.update_chatmessage_table

特性：
    - 幂等：先查 information_schema 判断列/索引是否存在，避免重复操作。
    - 旧数据保留：chat_messages 列不删除，仅新增/修改列。
    - 如果表不存在，直接通过原始 SQL 创建新结构的表。
"""

from loguru import logger
from sqlalchemy import text

from database.base import db_service
from database.models.chatmessage import ChatMessage


def _table_exists(conn, table_name: str) -> bool:
    sql = text(
        "SELECT COUNT(*) FROM information_schema.TABLES "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :table_name"
    )
    return conn.scalar(sql, {"table_name": table_name}) > 0


def _column_exists(conn, table_name: str, column_name: str) -> bool:
    sql = text(
        "SELECT COUNT(*) FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() "
        "AND TABLE_NAME = :table_name AND COLUMN_NAME = :column_name"
    )
    return conn.scalar(sql, {"table_name": table_name, "column_name": column_name}) > 0


def _index_exists(conn, table_name: str, index_name: str) -> bool:
    sql = text(
        "SELECT COUNT(*) FROM information_schema.STATISTICS "
        "WHERE TABLE_SCHEMA = DATABASE() "
        "AND TABLE_NAME = :table_name AND INDEX_NAME = :index_name"
    )
    return conn.scalar(sql, {"table_name": table_name, "index_name": index_name}) > 0


def _create_new_table(conn, table_name: str):
    """创建新结构的 chatmessage 表"""
    conn.execute(text(f"""
        CREATE TABLE IF NOT EXISTS `{table_name}` (
            `chat_id` INT NOT NULL AUTO_INCREMENT,
            `session_id` VARCHAR(64) NULL,
            `role` VARCHAR(16) NULL COMMENT '消息角色: user / assistant',
            `content` TEXT NULL COMMENT '消息内容',
            `turn_index` INT NULL DEFAULT 0 COMMENT '会话内轮次序号',
            `user_id` INT NULL,
            `create_time` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            `update_time` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            PRIMARY KEY (`chat_id`),
            INDEX `ix_chatmessage_session_id` (`session_id`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """))
    logger.info(f"表 {table_name} 已创建（新结构）")


def migrate():
    table_name = ChatMessage.__tablename__
    logger.info(f"开始迁移表 {table_name}")

    with db_service.engine.begin() as conn:
        if not _table_exists(conn, table_name):
            logger.info(f"表 {table_name} 不存在，创建新结构表")
            _create_new_table(conn, table_name)
            return

        # 1. task_id -> session_id 改名
        if _column_exists(conn, table_name, "task_id"):
            logger.info("重命名列 task_id -> session_id")
            conn.execute(text(
                f"ALTER TABLE `{table_name}` CHANGE COLUMN `task_id` `session_id` VARCHAR(64) NULL"
            ))
            logger.info("列 task_id 已重命名为 session_id")
        elif not _column_exists(conn, table_name, "session_id"):
            logger.info("新增列 session_id")
            conn.execute(text(
                f"ALTER TABLE `{table_name}` ADD COLUMN `session_id` VARCHAR(64) NULL"
            ))
        else:
            logger.info("列 session_id 已存在，跳过")

        # 2. 新增 role 列
        if not _column_exists(conn, table_name, "role"):
            conn.execute(text(
                f"ALTER TABLE `{table_name}` ADD COLUMN `role` VARCHAR(16) NULL "
                "COMMENT '消息角色: user / assistant'"
            ))
            logger.info("列 role 新增成功")
        else:
            logger.info("列 role 已存在，跳过")

        # 3. 新增 content 列（TEXT）
        if not _column_exists(conn, table_name, "content"):
            conn.execute(text(
                f"ALTER TABLE `{table_name}` ADD COLUMN `content` TEXT NULL "
                "COMMENT '消息内容'"
            ))
            logger.info("列 content 新增成功")
        else:
            logger.info("列 content 已存在，跳过")

        # 4. 新增 turn_index 列
        if not _column_exists(conn, table_name, "turn_index"):
            conn.execute(text(
                f"ALTER TABLE `{table_name}` ADD COLUMN `turn_index` INT NULL DEFAULT 0 "
                "COMMENT '会话内轮次序号'"
            ))
            logger.info("列 turn_index 新增成功")
        else:
            logger.info("列 turn_index 已存在，跳过")

        # 5. 添加 session_id 索引（用于按会话查询）
        if not _index_exists(conn, table_name, "ix_chatmessage_session_id"):
            try:
                conn.execute(text(
                    f"CREATE INDEX `ix_chatmessage_session_id` ON `{table_name}` (`session_id`)"
                ))
                logger.info("索引 ix_chatmessage_session_id 创建成功")
            except Exception as e:
                logger.warning(f"创建索引失败（可能已存在其他名称的索引）: {e}")
        else:
            logger.info("索引 ix_chatmessage_session_id 已存在，跳过")

        # 6. 移除旧的 chat_messages 列（如果存在且不再需要）
        # 注：旧数据保留，仅标记废弃。确认新代码稳定后再手动 DROP COLUMN。
        if _column_exists(conn, table_name, "chat_messages"):
            logger.info("列 chat_messages 仍然存在，暂不删除，等待确认后手动清理")
        else:
            logger.info("列 chat_messages 已不存在")

    logger.info(f"表 {table_name} 迁移完成")


if __name__ == "__main__":
    migrate()
