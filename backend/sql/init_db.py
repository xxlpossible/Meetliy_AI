"""
一键初始化数据库脚本

用法:
    cd backend
    python sql/init_db.py

功能：
    1. 从 config.yaml 读取 MySQL 连接信息
    2. 自动创建数据库（如不存在）
    3. 执行 graduation_db.sql 建表脚本
"""

import os
import re
import sys
import time
from pathlib import Path

import pymysql
import yaml
from pymysql.cursors import DictCursor

# 当前脚本所在目录
SCRIPT_DIR = Path(__file__).resolve().parent
# backend 根目录
BACKEND_DIR = SCRIPT_DIR.parent
# SQL 文件路径
SQL_FILE = SCRIPT_DIR / "graduation_db.sql"
# config.yaml 路径
CONFIG_FILE = BACKEND_DIR / "config.yaml"


def parse_db_url(db_url: str) -> dict:
    """从 SQLAlchemy 连接字符串解析 MySQL 连接参数"""
    pattern = r"mysql\+pymysql://(?P<user>[^:]+):(?P<password>[^@]+)@(?P<host>[^:]+):(?P<port>\d+)/(?P<database>[^?]+)"
    match = re.match(pattern, db_url)
    if not match:
        print(f"✗ 无法解析 database_url: {db_url}")
        sys.exit(1)
    return match.groupdict()


def main():
    print("=" * 60)
    print("  数据库一键初始化脚本")
    print("=" * 60)

    # 1. 检查 SQL 文件是否存在
    if not SQL_FILE.exists():
        print(f"✗ SQL 文件不存在: {SQL_FILE}")
        sys.exit(1)

    # 2. 读取 config.yaml
    if not CONFIG_FILE.exists():
        print(f"✗ 配置文件不存在: {CONFIG_FILE}")
        sys.exit(1)

    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        raw = f.read()

    # 替换 ${ENV_VAR} 为环境变量值（与 settings.py 保持一致）
    raw = re.sub(r'\$\{(\w+)(?::-([^}]*))?\}', lambda m: os.getenv(m.group(1), m.group(2) or ''), raw)
    config = yaml.safe_load(raw)

    db_url = config.get("database_url")
    if not db_url:
        print("✗ config.yaml 中未找到 database_url")
        sys.exit(1)

    db_info = parse_db_url(db_url)
    host = db_info["host"]
    port = int(db_info["port"])
    user = db_info["user"]
    password = db_info["password"]
    database = db_info["database"]

    print(f"\n连接信息: {user}@{host}:{port}")
    print(f"目标数据库: {database}")

    # 3. 先连接 MySQL（不指定数据库），创建数据库
    print(f"\n[1/3] 检查并创建数据库 `{database}` ...")
    try:
        conn = pymysql.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            charset="utf8mb4",
            cursorclass=DictCursor,
        )
        with conn.cursor() as cursor:
            cursor.execute(
                f"CREATE DATABASE IF NOT EXISTS `{database}` "
                f"DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci"
            )
        conn.close()
        print(f"  ✓ 数据库 `{database}` 已就绪")
    except pymysql.Error as e:
        print(f"  ✗ 连接 MySQL 失败: {e}")
        sys.exit(1)

    # 4. 连接目标数据库，执行 SQL 建表脚本
    print(f"\n[2/3] 执行建表脚本 {SQL_FILE.name} ...")
    sql_content = SQL_FILE.read_text(encoding="utf-8")

    try:
        conn = pymysql.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            database=database,
            charset="utf8mb4",
            cursorclass=DictCursor,
        )
        with conn.cursor() as cursor:
            # 按分号拆分语句，过滤空语句
            statements = [s.strip() for s in sql_content.split(";") if s.strip()]
            executed = 0
            for stmt in statements:
                # 跳过纯注释或 SET/DROP 等非关键语句的单独处理
                # 直接逐条执行
                try:
                    cursor.execute(stmt)
                    executed += 1
                except pymysql.Error as e:
                    # 某些 SET/FOREIGN_KEY_CHECKS 可能受影响，打印警告但不中断
                    print(f"  ⚠ 语句执行警告: {e}")
        conn.commit()
        conn.close()
        print(f"  ✓ 成功执行 {executed} 条 SQL 语句")

        # 验证各表是否创建成功
        print(f"\n[3/3] 验证表结构 ...")
        conn = pymysql.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            database=database,
            charset="utf8mb4",
            cursorclass=DictCursor,
        )
        with conn.cursor() as cursor:
            cursor.execute("SHOW TABLES")
            tables = [row[f"Tables_in_{database}"] for row in cursor.fetchall()]
        conn.close()

        if tables:
            print(f"  ✓ 共 {len(tables)} 张表已创建: {', '.join(tables)}")
        else:
            print("  ✗ 未检测到任何表，请检查 SQL 执行日志")

    except pymysql.Error as e:
        print(f"  ✗ 执行 SQL 失败: {e}")
        sys.exit(1)

    print("\n" + "=" * 60)
    print(f"  ✓ 数据库 `{database}` 初始化完成！")
    print("=" * 60)


if __name__ == "__main__":
    main()
