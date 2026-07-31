# ============================================================
# Meetily 后端 Docker 镜像
# 基于 python:3.11-slim，使用 uv 管理依赖
# ============================================================

FROM python:3.11-slim

LABEL maintainer="dbs"
LABEL description="Meetily FastAPI Backend"

# 系统依赖：gcc 用于编译某些 Python 包，libmagic 用于文件类型检测
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libmagic1 \
    && rm -rf /var/lib/apt/lists/*

# 安装 uv（快速 Python 包管理器）
RUN pip install --no-cache-dir uv

WORKDIR /app

# ---- 第一阶段：安装依赖（利用 Docker 缓存层） ----
COPY backend/pyproject.toml backend/uv.lock ./

# 安装 Python 依赖（不安装 dev 依赖）
RUN uv sync --frozen --no-dev

# ---- 第二阶段：复制源码 ----
COPY backend/ .

# 创建数据目录
RUN mkdir -p /app/chroma_db /app/uploads /app/temp

# 启动脚本
COPY backend/docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh

EXPOSE 31818

ENTRYPOINT ["/app/docker-entrypoint.sh"]
