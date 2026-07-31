#!/bin/bash
# ============================================================
# Meetily 后端容器启动脚本
# 功能：
#   1. 等待 MySQL 就绪
#   2. 执行数据库初始化（建库 + 建表）
#   3. 启动 Uvicorn
# ============================================================

set -e

echo "========================================"
echo "  Meetily Backend - Starting..."
echo "========================================"

# ── 1. 等待 MySQL 就绪 ──
echo "[1/3] Waiting for MySQL to be ready..."

# 用 grep + sed 从 config.yaml 解析 host 和 port
# config.yaml 格式: "mysql+pymysql://root:xxx@mysql:3306/graduation_db?..."
DB_URL=$(grep 'database_url' /app/config.yaml | head -1 | sed 's/.*"\(.*\)".*/\1/')
DB_HOST=$(echo "$DB_URL" | sed 's/.*@\([^:]*\):.*/\1/')
DB_PORT=$(echo "$DB_URL" | sed 's/.*:\([0-9]*\)\/.*/\1/')

echo "  MySQL target: ${DB_HOST}:${DB_PORT}"

# 使用 /dev/tcp 或 Python 等待端口可用
for i in $(seq 1 60); do
    if python -c "
import socket
try:
    s = socket.create_connection(('$DB_HOST', int('$DB_PORT')), timeout=2)
    s.close()
    exit(0)
except:
    exit(1)
" 2>/dev/null; then
        echo "  ✓ MySQL is ready after ${i}s"
        break
    fi
    if [ "$i" -eq 60 ]; then
        echo "  ✗ MySQL did not become ready in 60s"
        exit 1
    fi
    sleep 1
done

# ── 2. 初始化数据库表结构 ──
echo "[2/3] Initializing database tables..."
python sql/init_db.py
echo "  ✓ Database tables initialized"

# ── 3. 启动 Uvicorn ──
echo "[3/3] Starting Uvicorn on 0.0.0.0:31818..."
echo "========================================"
exec python main.py
