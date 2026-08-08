# ============================================================
# Meetily 后端 Docker 镜像
# 基于 python:3.11-slim，使用 uv 管理依赖
# ============================================================

FROM python:3.11-slim

LABEL maintainer="dbs"
LABEL description="Meetily FastAPI Backend"

# 系统依赖：gcc 用于编译某些 Python 包，libmagic 用于文件类型检测，
# ffmpeg 用于会议录音的多路音频合并/转码（audio_service.py 通过 subprocess 调用）
# 使用阿里云 Debian 镜像源加速
RUN sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libmagic1 \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# 安装 uv（快速 Python 包管理器，使用阿里云 PyPI 镜像）
RUN pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ uv

WORKDIR /app

# 设置虚拟环境路径，让 uv 和后续命令都能找到
ENV VIRTUAL_ENV=/app/.venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# ---- 第一阶段：安装依赖（利用 Docker 缓存层） ----
COPY backend/pyproject.toml backend/uv.lock ./

# 安装 Python 依赖到虚拟环境（不安装 dev 依赖）
# 使用阿里云 PyPI 镜像加速
RUN uv sync --frozen --no-dev --index-url https://mirrors.aliyun.com/pypi/simple/

# ---- 第二阶段：复制源码 ----
COPY backend/ .

# 创建数据目录
RUN mkdir -p /app/chroma_db /app/uploads /app/temp

# 启动脚本
COPY backend/docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh

EXPOSE 31818

ENTRYPOINT ["/app/docker-entrypoint.sh"]
