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
# 从 config.yaml 解析数据库连接参数
DB_URL=$(python -c "
import yaml, re, os
raw = open('config.yaml').read()
raw = re.sub(r'\\$\\{(\\w+)(?::-([^}]*))?\\}', lambda m: os.getenv(m.group(1), m.group(2) or ''), raw)
cfg = yaml.safe_load(raw)
print(cfg.get('database_url', ''))
")

# 解析 host 和 port
DB_HOST=$(echo "$DB_URL" | sed -n 's/.*@\([^:]*\):.*/\1/p')
DB_PORT=$(echo "$DB_URL" | sed -n 's/.*:\([0-9]*\)\/.*/\1/p')

echo "  MySQL target: ${DB_HOST}:${DB_PORT}"

# 使用 Python 等待端口可用
python -c "
import socket, time, sys
host, port = '$DB_HOST', int('$DB_PORT')
for i in range(60):
    try:
        s = socket.create_connection((host, port), timeout=2)
        s.close()
        print(f'  ✓ MySQL is ready after {i+1}s')
        break
    except (socket.error, OSError):
        time.sleep(1)
else:
    print('  ✗ MySQL did not become ready in 60s')
    sys.exit(1)
"

# ── 2. 初始化数据库表结构 ──
echo "[2/3] Initializing database tables..."
python sql/init_db.py
echo "  ✓ Database tables initialized"

# ── 3. 启动 Uvicorn ──
echo "[3/3] Starting Uvicorn on 0.0.0.0:31818..."
echo "========================================"
exec python main.py
