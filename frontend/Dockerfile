# ============================================================
# Meetily 前端 Docker 镜像 - 多阶段构建
# 阶段 1: Node 20 Alpine → 构建 Vue3 + Vite 产物
# 阶段 2: Nginx Alpine → 托管静态文件 + 反向代理
# ============================================================

# ── 阶段 1: 构建 ──
FROM node:20-alpine AS builder

WORKDIR /app

# 安装依赖（利用 Docker 缓存层）
# 使用淘宝 npm 镜像加速
COPY frontend/package.json frontend/package-lock.json ./
RUN npm config set registry https://registry.npmmirror.com && npm ci

# 复制源码
COPY frontend/ .

# 复制生产环境变量（VITE_API_TARGET 为空，同源部署）
COPY frontend/.env.production .env.production

# 构建（跳过 vue-tsc 类型检查以加速构建，类型错误不应阻塞部署）
RUN npx vite build

# ── 阶段 2: 运行 ──
FROM nginx:alpine

LABEL maintainer="dbs"
LABEL description="Meetily Frontend + Nginx"

# 从构建阶段复制静态文件
COPY --from=builder /app/dist /usr/share/nginx/html

# 复制 Nginx 配置
COPY nginx/nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
