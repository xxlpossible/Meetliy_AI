-- ============================================================
-- 迁移脚本：为现有数据库的 user 表增加 avatar 字段
-- 用途：已初始化过数据库的环境，无需重跑 graduation_db.sql
-- 用法：mysql -u<user> -p <database> < user_avatar_migration.sql
-- ============================================================

ALTER TABLE `user`
  ADD COLUMN `avatar` text CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NULL DEFAULT NULL COMMENT '头像 OSS 公共 URL'
  AFTER `phone_number`;
