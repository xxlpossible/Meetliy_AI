#!/bin/bash
# ============================================================
# Meetily 后端容器启动脚本
# 功能：
#   1. 等待 MySQL 就绪
#   2. 执行数据库初始化（建库 + 建表）
#   3. 启动 Uvicorn
# ============================================================

echo "========================================"
echo "  Meetily Backend - Starting..."
echo "========================================"

# ── 1. 等待 MySQL 就绪 ──
echo "[1/3] Waiting for MySQL to be ready..."

# 用 grep + sed 从 config.yaml 解析 host 和 port
DB_URL=$(grep -A1 'database_url' /app/config.yaml | tail -1 | sed 's/.*"\(.*\)".*/\1/')
DB_HOST=$(echo "$DB_URL" | sed 's/.*@\([^:]*\):.*/\1/')
DB_PORT=$(echo "$DB_URL" | sed 's/.*:\([0-9]*\)\/.*/\1/')

echo "  MySQL target: ${DB_HOST}:${DB_PORT}"

# 等待 MySQL 端口可用
MAX_RETRIES=120
RETRY=0
while [ $RETRY -lt $MAX_RETRIES ]; do
    python -c "
import socket
try:
    s = socket.create_connection(('$DB_HOST', int('$DB_PORT')), timeout=5)
    s.close()
except Exception:
    exit(1)
" && break

    RETRY=$((RETRY + 1))
    if [ $RETRY -eq $MAX_RETRIES ]; then
        echo "  ✗ MySQL did not become ready in ${MAX_RETRIES}s"
        exit 1
    fi
    sleep 1
done

echo "  ✓ MySQL is ready after ${RETRY}s"

# ── 2. 初始化数据库表结构 ──
echo "[2/3] Initializing database tables..."
python sql/init_db.py
echo "  ✓ Database tables initialized"

# ── 3. 启动 Uvicorn ──
echo "[3/3] Starting Uvicorn on 0.0.0.0:31818..."
echo "========================================"
exec python main.py
