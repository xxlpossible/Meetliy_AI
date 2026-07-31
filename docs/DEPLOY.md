# Meetily 生产环境部署指南

> 从零开始，将 Meetily（智能会议纪要助手）部署到阿里云 ECS 云服务器。
> 适用配置：**2核4G**，操作系统 **Ubuntu 22.04**。

---

## 目录

- [1. 服务器申请（阿里云 ECS 免费试用）](#1-服务器申请阿里云-ecs-免费试用)
- [2. 服务器初始化配置](#2-服务器初始化配置)
- [3. Docker 基础概念（新手必读）](#3-docker-基础概念新手必读)
- [4. 安装 Docker 环境](#4-安装-docker-环境)
- [5. 上传项目代码](#5-上传项目代码)
- [6. 配置环境变量](#6-配置环境变量)
- [7. 启动服务](#7-启动服务)
- [8. 验证部署](#8-验证部署)
- [9. 运维管理](#9-运维管理)
- [10. 2核4G 内存优化说明](#10-2核4g-内存优化说明)
- [11. 故障排查 FAQ](#11-故障排查-faq)
- [12. 数据备份与迁移](#12-数据备份与迁移)

---

## 1. 服务器申请（阿里云 ECS 免费试用）

### 1.1 免费额度

阿里云为新用户提供 **300 元免费试用额度**，有效期 3 个月。2核4G 的 ECS 按量付费约 **0.3 元/小时**，300 元额度足够运行整个试用期。

**试用配置说明**：

| 配置项 | 内容 | 影响 |
|--------|------|------|
| **实例规格** | `ecs.e-c1m2.large`（2核4G） | 满足本项目 6 服务部署需求 |
| **系统盘** | 40GB ESSD | 足够代码 + Docker 镜像 + 数据卷 |
| **免费时长** | 1181 小时（约 49 天） | 足够毕业设计部署和演示 |
| **免费流量** | 中国内地地域 **20GB/月** | 毕业设计项目绰绰有余 |

> **流量预算评估**：本项目主要流量来自 AI 对话流式输出（每次会议约 35MB），50 次会议/月仅消耗 1.7GB，20GB 免费额度**绝对够用**，不会产生额外费用。
>
> 如果你对地域没有特殊偏好，建议选择 **华南3（广州）** 或 **华东2（上海）**，离用户近且都是 20GB 免费流量。

### 1.2 申请条件

- 阿里云新用户（未购买过任何产品的账号）
- 已完成**个人实名认证**（需身份证 + 人脸识别）

### 1.3 申请步骤

**Step 1：注册阿里云账号**

访问 [https://www.aliyun.com](https://www.aliyun.com)，点击右上角「免费注册」，使用手机号注册。

**Step 2：完成实名认证**

登录后进入「账号管理 → 实名认证」，选择「个人实名认证」：
1. 填写真实姓名、身份证号
2. 使用阿里云 APP 或支付宝扫码完成人脸识别
3. 认证通过后账号状态变为「已实名」

**Step 3：领取免费试用额度**

访问 [https://free.aliyun.com](https://free.aliyun.com)，在「计算」分类中找到「ECS 云服务器」，点击「立即试用」领取 300 元额度。

**Step 4：创建 ECS 实例**

进入 [ECS 控制台](https://ecs.console.aliyun.com)，点击「创建实例」：

| 配置项 | 推荐值 | 说明 |
|--------|--------|------|
| **计费方式** | 按量付费 | 用多少扣多少，300 元额度自动抵扣 |
| **地域** | 华北2（北京）/ 华东2（上海） | 离用户近即可 |
| **实例规格** | ecs.c7.large（2核4G） | 共享计算型，性价比高 |
| **镜像** | Ubuntu 22.04 64位 | 稳定性好，Docker 兼容性佳 |
| **系统盘** | ESSD 40GB | 默认即可，后续可扩容 |
| **公网带宽** | 按使用流量，峰值 10Mbps | 按流量计费更省 |
| **登录凭证** | 密钥对（推荐）或密码 | 密钥对更安全 |
| **预装应用** | ✅ 仅勾选 **Docker** | 见下方说明 |

> **预装应用选择说明**：
>
> | 选项 | 是否勾选 | 原因 |
> |------|---------|------|
> | **Docker** | ✅ 必选 | 本项目所有服务（FastAPI、Nginx、MySQL、Redis）都通过 Docker Compose 容器化部署 |
> | 宝塔 Linux 面板 | ❌ 不要选 | 会自带一套 LNMP，与容器内的 MySQL/Nginx 冲突，徒增复杂度 |
> | WordPress | ❌ 不要选 | 建站工具，与本项目无关 |
> | LNMP | ❌ 不要选 | 会在宿主机安装 MySQL/Nginx/PHP，与容器内的同名服务端口冲突 |
>
> **核心原则**：本项目用 Docker 部署一切，宿主机只需要装 Docker，其他都不要装，避免端口冲突和资源浪费。

**Step 5：配置安全组**

在「网络和安全组」中，确保安全组规则包含以下入方向规则：

| 端口 | 协议 | 来源 | 说明 |
|------|------|------|------|
| 22 | TCP | 0.0.0.0/0 | SSH 远程登录 |
| 80 | TCP | 0.0.0.0/0 | HTTP（Nginx） |
| 443 | TCP | 0.0.0.0/0 | HTTPS（如需） |

> ⚠️ **安全提示**：生产环境建议将 SSH（22）的源 IP 限制为你的办公/家庭 IP，避免被暴力破解。

**Step 6：确认并创建**

检查配置无误后，点击「确认下单」创建实例。约 1-2 分钟后实例进入「运行中」状态。

---

## 2. 服务器初始化配置

### 2.1 SSH 登录

在实例列表中找到你的实例，复制**公网 IP**，使用 SSH 连接：

```bash
# 密钥对方式登录
ssh -i /path/to/your-key.pem root@<你的公网IP>

# 密码方式登录
ssh root@<你的公网IP>
```

### 2.2 基础环境配置

```bash
# 更新系统包
apt update && apt upgrade -y

# 安装基础工具
apt install -y curl wget git vim htop net-tools

# 设置时区为中国标准时间
timedatectl set-timezone Asia/Shanghai

# 配置 swap（2核4G 建议 2GB swap，防止内存峰值 OOM）
fallocate -l 2G /swapfile
chmod 600 /swapfile
mkswap /swapfile
swapon /swapfile
echo '/swapfile none swap sw 0 0' | tee -a /etc/fstab

# 确认 swap 已启用
free -h
```

### 2.3 创建非 root 用户（可选但推荐）

```bash
# 创建用户
adduser meetily

# 添加 sudo 权限
usermod -aG sudo meetily

# 切换到新用户
su - meetily
```

---

## 3. Docker 基础概念（新手必读）

如果你不熟悉 Docker，先花 5 分钟理解这三个核心概念，后面的部署流程会非常顺畅。

### 3.1 一句话理解

```
┌─────────────────────────────────────────────────────────┐
│                                                         │
│   镜像 (Image)             容器 (Container)              │
│   ┌─────────────┐         ┌─────────────────┐          │
│   │  设计图纸    │   →     │  盖好的房子      │          │
│   │             │  创建    │                 │          │
│   │  只读的      │         │  可以住人、用东西  │          │
│   │  不会变的    │         │  用坏了可以拆掉    │          │
│   │             │         │  用图纸再盖一栋    │          │
│   └─────────────┘         └────────┬────────┘          │
│                                    │ 挂载               │
│                         ┌──────────▼──────────┐        │
│                         │  Volume (数据卷)     │        │
│                         │  ┌──────────────┐   │        │
│                         │  │  保险柜       │   │        │
│                         │  │              │   │        │
│                         │  │  独立存在     │   │        │
│                         │  │  房子拆了      │   │        │
│                         │  │  保险柜还在   │   │        │
│                         │  └──────────────┘   │        │
│                         └─────────────────────┘        │
│                                                         │
│  宿主机 (你的服务器)                                      │
│  /home/meetily/meetily/                                 │
└─────────────────────────────────────────────────────────┘
```

| 概念 | 类比 | 说明 |
|------|------|------|
| **镜像 (Image)** | 建筑图纸 | 只读模板，定义了程序运行需要的一切（系统、依赖、代码） |
| **容器 (Container)** | 盖好的房子 | 镜像的运行实例，程序在容器里运行，容器之间互相隔离 |
| **Volume (数据卷)** | 保险柜 | 独立于容器和镜像的持久化存储，数据存在宿主机硬盘上 |

### 3.2 镜像 (Image) = 设计图纸

**镜像是只读的、不可变的模板。** 由 `Dockerfile` 构建而来。

你的项目有两个自制镜像：

| 镜像 | 构建来源 | 包含内容 |
|------|---------|---------|
| `meetily-backend` | `backend/Dockerfile` | Python 3.11 + FastAPI + ChromaDB + 你的代码 |
| `meetily-nginx` | `frontend/Dockerfile` | Nginx + 前端编译好的 HTML/JS/CSS |

另外两个镜像直接从 Docker Hub 下载，不需要自己构建：

| 镜像 | 来源 |
|------|------|
| `mysql:8.0` | Docker Hub 官方 |
| `redis:7-alpine` | Docker Hub 官方 |

**特点**：图纸不能改，要改就得画新图纸（重新 `docker build`）。

```
backend/Dockerfile  →  docker build  →  meetily-backend 镜像
(设计图说明)                             (成品图纸)
```

### 3.3 容器 (Container) = 盖好的房子

**容器是镜像的运行实例。** 拿到图纸盖一栋房子，里面的程序开始运行。

```bash
docker compose up -d
# 效果：用镜像(图纸)创建容器(房子)，程序开始运行
```

**关键特点**：
- 从同一张图纸可以创建多个一模一样的容器
- 容器内部和外界是**隔离**的（有自己的文件系统、网络、进程）
- 容器可以随时删除重建，不会影响镜像

以 `meetily-backend` 容器为例，看看里面有什么：

```
┌──────────────────────────────────────┐
│  容器 meetily-backend (一座房子)       │
│                                      │
│  文件系统 (来自镜像 + Volume 挂载):     │
│    /app/main.py         ← 镜像自带    │
│    /app/config.yaml     ← 宿主机挂载   │
│    /app/chroma_db/      ← Volume 挂载 │
│                                      │
│  进程:                               │
│    uvicorn 正在运行，监听 31818 端口    │
│                                      │
│  网络:                               │
│    通过 meetily-net 网络              │
│    可以访问 mysql:3306                │
│    可以访问 redis:6379                │
└──────────────────────────────────────┘
```

### 3.4 Volume (数据卷) = 保险柜

**Volume 是独立于容器和镜像的持久化存储。** 容器删了，Volume 还在；镜像重构建了，Volume 还在。

```yaml
# docker-compose.yml 中定义
volumes:
  mysql_data:/var/lib/mysql
# ↑ 保险柜名字     ↑ 容器内的挂载点
```

**核心规则**：

```
容器删了        →  Volume 还在    ✅
镜像重构建了     →  Volume 还在    ✅
服务器重启了     →  Volume 还在    ✅
docker volume rm →  才真正删除     ❌ (需手动执行)
```

### 3.5 三者的关系：以本项目为例

```
一次完整的 docker compose up -d 过程：

Step 1: docker build (画图纸)
  backend/Dockerfile  ────► meetily-backend 镜像
  frontend/Dockerfile ────► meetily-nginx 镜像
  mysql:8.0           ────► 从 Docker Hub 下载现成图纸
  redis:7-alpine      ────► 从 Docker Hub 下载现成图纸

Step 2: 创建容器 (盖房子)
  用 meetily-backend 图纸 → 创建 meetily-backend 容器
  用 meetily-nginx 图纸   → 创建 meetily-nginx 容器
  用 mysql:8.0 图纸       → 创建 meetily-mysql 容器
  用 redis:7-alpine 图纸  → 创建 meetily-redis 容器

Step 3: 挂载 Volume (接保险柜)
  meetily-mysql-data 保险柜 ──接入── meetily-mysql 容器
  meetily-redis-data 保险柜 ──接入── meetily-redis 容器
  meetily-chroma-data 保险柜 ──接入── meetily-backend 容器
```

### 3.6 代码更新时发生了什么

```
git pull (代码变了)
    │
    ▼
docker compose up -d --build
    │
    ├── docker build → 画新图纸 (镜像更新)
    │
    ├── 拆掉旧房子 (删除旧容器)
    │       │
    │       └── 保险柜不受影响，留在原地
    │
    └── 用新图纸盖新房子 (创建新容器)
            │
            └── 新房子接上原来的保险柜，数据全在
```

**所以你完全不用担心数据丢失**。只要不手动敲 `docker volume rm`，数据永远在宿主机硬盘上。

### 3.7 你的服务器上最终的样子

```
你的服务器
│
├── /home/meetily/meetily/           ← 代码 + 配置文件 (宿主机)
│   ├── docker-compose.yml           ← 导演，定义整体架构
│   ├── .env                         ← 密钥，注入到容器
│   ├── backend/config.yaml          ← 挂载进容器，可随时改
│   └── ...
│
├── Docker 镜像 (/var/lib/docker/)
│   ├── meetily-backend:latest       ← 图纸
│   ├── meetily-nginx:latest         ← 图纸
│   ├── mysql:8.0                    ← 图纸 (官方)
│   └── redis:7-alpine               ← 图纸 (官方)
│
├── Docker 容器 (运行中的房子)
│   ├── meetily-backend    ← FastAPI 在运行
│   ├── meetily-celery     ← 后台任务在运行
│   ├── meetily-nginx      ← 网页在服务
│   ├── meetily-mysql      ← 数据库在运行
│   └── meetily-redis      ← 缓存在运行
│
└── Docker Volume (保险柜，数据持久化)
    ├── meetily-mysql-data/       ← MySQL 数据文件
    ├── meetily-redis-data/       ← Redis AOF 文件
    ├── meetily-chroma-data/      ← 向量数据库文件
    ├── meetily-checkpoints-data/ ← LangGraph 状态
    └── meetily-uploads-data/     ← 用户上传的文件
```

> **记住一句话**：镜像是图纸，容器是房子，Volume 是保险柜。房子可以拆了重盖，保险柜永远在。

---

## 4. 安装 Docker 环境

### 4.1 安装 Docker Engine

使用阿里云镜像加速安装（国内服务器推荐）：

```bash
# 使用阿里云 Docker CE 镜像源
curl -fsSL https://mirrors.aliyun.com/docker-ce/linux/ubuntu/gpg | sudo gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://mirrors.aliyun.com/docker-ce/linux/ubuntu \
  $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

### 4.2 配置 Docker（非 root 用户 + 镜像加速）

```bash
# 将当前用户加入 docker 组（免 sudo 运行 docker 命令）
sudo usermod -aG docker $USER
newgrp docker

# 配置 Docker 镜像加速（阿里云）
sudo mkdir -p /etc/docker
sudo tee /etc/docker/daemon.json <<-'EOF'
{
  "registry-mirrors": ["https://registry.cn-hangzhou.aliyuncs.com"],
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3"
  }
}
EOF

# 重启 Docker
sudo systemctl daemon-reload
sudo systemctl restart docker
sudo systemctl enable docker
```

### 4.3 验证安装

```bash
docker --version
# 输出：Docker version 24.x.x ...

docker compose version
# 输出：Docker Compose version v2.x.x ...

docker run hello-world
# 输出：Hello from Docker!
```

---

## 5. 上传项目代码

### 方式一：Git 克隆（推荐）

```bash
# 在服务器上克隆项目
cd /home/meetily
git clone https://github.com/你的用户名/the_graduation_project.git meetily
cd meetily
```

### 方式二：SCP 上传

```bash
# 在本地执行（将整个项目上传到服务器）
scp -r /path/to/the_graduation_project root@<公网IP>:/home/meetily/meetily
```

### 切换项目到正确的分支

```bash
cd /home/meetily/meetily
git checkout chain_update   # 或你的部署分支
```

---

## 6. 配置环境变量

### 5.1 复制并编辑生产环境变量

```bash
cd /home/meetily/meetily

# 复制模板
cp .env.production .env

# 编辑 .env，填入真实配置
vim .env
```

### 5.2 必填配置项

以下是**必须填写**的配置项（在 `.env` 中找到并替换）：

| 环境变量 | 说明 | 获取方式 |
|----------|------|----------|
| `MYSQL_ROOT_PASSWORD` | MySQL root 密码 | 自行设置强密码 |
| `JWT_SECRET_KEY` | JWT 签名密钥 | `openssl rand -hex 32` 生成 |
| `OSS_ACCESS_KEY_ID` | 阿里云 OSS AccessKey | [RAM 访问控制](https://ram.console.aliyun.com) |
| `OSS_ACCESS_KEY_SECRET` | 阿里云 OSS SecretKey | 同上 |
| `OSS_BUCKET_NAME` | OSS Bucket 名称 | [OSS 控制台](https://oss.console.aliyun.com) |
| `CHAT_MODEL_BASE_URL` | LLM API 端点 | 如通义千问、DeepSeek 等 |
| `CHAT_MODEL_API_KEY` | LLM API Key | 对应平台获取 |
| `DASHSCOPE_API_KEY` | 阿里云 DashScope API Key | [DashScope 控制台](https://dashscope.console.aliyun.com) |
| `EMBEDDINGS_API_KEY` | Embedding 模型 API Key | SiliconFlow 等平台获取 |
| `RERANK_API_KEY` | Rerank 模型 API Key | 同上 |

### 5.3 生产环境 CORS 配置

如果你的域名是 `meetily.example.com`，在 `.env` 中设置：

```bash
CORS_ORIGINS=http://meetily.example.com,https://meetily.example.com
```

### 5.4 config.yaml 说明

`config.yaml` 默认已配置为 Docker 地址，密码通过 `${MYSQL_ROOT_PASSWORD}` 从 `.env` 动态注入：

```yaml
database_url:
  "mysql+pymysql://root:${MYSQL_ROOT_PASSWORD:-123456}@mysql:3306/graduation_db?charset=utf8mb4"
redis_url: "redis://redis:6379/7"
celery_redis_url: "redis://redis:6379/9"
```

- **部署到服务器**：无需任何修改，`docker compose up -d` 即可
- **本地开发**：设置环境变量 `LOCAL_DEV=true`，`settings.py` 会自动将 `mysql`/`redis` 替换为 `127.0.0.1`

### 5.5 部署后如何修改 config.yaml

**config.yaml 通过 Volume 挂载，部署后可以直接在服务器上编辑：**

```bash
cd /home/meetily/meetily

# 直接编辑宿主机上的 config.yaml
vim backend/config.yaml

# 重启服务使修改生效
docker compose restart backend celery-worker
```

**原理**：docker-compose.yml 中配置了 `./backend/config.yaml:/app/config.yaml:ro`，这意味着：
- 宿主机的 `backend/config.yaml` 会覆盖容器内镜像自带的同名文件
- 你修改宿主机上的文件 → 容器内立即看到修改（因为是同一个文件）
- `:ro` 表示容器内只读，防止误操作

**一般你不需要改 config.yaml**，因为：
- 数据库/Redis 地址：部署后不会变
- 密码：通过 `.env` 中的 `MYSQL_ROOT_PASSWORD` 注入，改 `.env` 就行
- 所有 LLM 模型 API Key：已在 `.env` 中配置，不写在 config.yaml 里

### 5.6 部署后修改 .env 密钥

**修改 .env 也是编辑宿主机文件然后重启：**

```bash
cd /home/meetily/meetily

# 编辑 .env（改密钥、API Key 等）
vim .env

# 重启容器使新配置生效
docker compose down
docker compose up -d
```

> **原理**：`.env` 文件在宿主机上，docker-compose 通过 `env_file` 在每次启动容器时重新注入环境变量。容器内的 `config.yaml` 中的 `${MYSQL_ROOT_PASSWORD}` 占位符也会被新的环境变量值替换。**不需要进入容器内部改任何文件。**

---

## 7. 启动服务

### 6.1 构建并启动所有容器

```bash
cd /home/meetily/meetily

# 构建镜像并启动（首次需要 5-10 分钟）
docker compose up -d --build
```

构建过程中会：
1. 拉取基础镜像（python:3.11-slim、node:20-alpine、nginx:alpine、mysql:8.0、redis:7-alpine）
2. 安装 Python 依赖（uv sync）
3. 构建前端静态文件（npm ci + vite build）
4. 按依赖顺序启动容器

### 6.2 查看启动状态

```bash
# 查看所有容器状态
docker compose ps

# 期望输出（所有容器 STATUS 为 Up）：
# NAME               STATUS
# meetily-nginx      Up (healthy)
# meetily-backend    Up (healthy)
# meetily-celery     Up
# meetily-mysql      Up (healthy)
# meetily-redis      Up (healthy)
```

### 6.3 查看日志

```bash
# 查看所有服务日志
docker compose logs -f

# 只看后端日志
docker compose logs -f backend

# 只看 MySQL 日志
docker compose logs -f mysql

# 查看最近 50 行
docker compose logs --tail=50 backend
```

---

## 8. 验证部署

### 7.1 访问前端

在浏览器中访问：`http://<你的公网IP>`

应能看到 Meetily 的登录/注册页面。

### 7.2 验证 API

```bash
# 在服务器上测试 API
curl http://localhost/api/v1/health

# 或从本地测试
curl http://<公网IP>/api/v1/health
```

### 7.3 验证数据库连接

```bash
# 进入 MySQL 容器
docker compose exec mysql mysql -u root -p

# 查看数据库
SHOW DATABASES;
USE graduation_db;
SHOW TABLES;
EXIT;
```

### 7.4 验证 Redis

```bash
docker compose exec redis redis-cli PING
# 输出：PONG
```

---

## 9. 运维管理

### 8.1 常用命令

```bash
# ===== 服务管理 =====
docker compose up -d              # 启动所有服务
docker compose down               # 停止并删除所有容器
docker compose restart            # 重启所有服务
docker compose restart backend    # 只重启后端

# ===== 日志查看 =====
docker compose logs -f backend    # 实时查看后端日志
docker compose logs --tail=100    # 查看最近 100 行

# ===== 进入容器 =====
docker compose exec backend bash  # 进入后端容器
docker compose exec mysql bash    # 进入 MySQL 容器

# ===== 镜像更新 =====
docker compose pull               # 拉取最新基础镜像
docker compose up -d --build      # 重新构建并启动

# ===== 清理 =====
docker system prune -a            # 清理未使用的镜像/容器/网络
docker volume prune               # 清理未使用的数据卷
```

### 8.2 更新代码后重新部署

**重要**：不需要在本地打包镜像再上传！正确流程是「上传代码 → 服务器上构建」。

```bash
cd /home/meetily/meetily

# 拉取最新代码
git pull

# 重新构建并启动（Docker 会利用缓存加速，通常几秒到几十秒）
docker compose up -d --build
```

Docker 分层缓存机制：
- `pyproject.toml` / `package.json` 没变 → 依赖层直接复用缓存
- 只改了业务代码 → 仅重建源码层（很快）
- 改了依赖 → 自动重建依赖层（稍慢，约 2-5 分钟）

**零停机更新后端（不影响用户访问）**：
```bash
git pull
docker compose up -d --build --no-deps backend celery-worker
# --no-deps: 不重启 mysql/redis/nginx，只更新后端
```

### 8.3 修改密钥和配置信息

所有敏感信息通过 `.env` 文件管理，**不会被打包进 Docker 镜像**。

**修改 .env 中的密钥（推荐方式）：**

```bash
cd /home/meetily/meetily

# 编辑 .env 修改任意密钥（如 JWT、API Key、数据库密码）
vim .env

# 重启所有服务使新配置生效
docker compose down
docker compose up -d
```

**修改 config.yaml 中的地址/端口：**

config.yaml 通过 Volume 挂载到容器，可以直接在宿主机上编辑：

```bash
cd /home/meetily/meetily

# 编辑 config.yaml
vim backend/config.yaml

# 重启相关服务
docker compose restart backend celery-worker
```

> **完整原理**：
> 1. `.dockerignore` 排除了 `.env`，它永远不会进镜像
> 2. `docker-compose.yml` 通过 `env_file: - .env` 在启动时读取宿主机上的 `.env`，注入为容器环境变量
> 3. `./backend/config.yaml:/app/config.yaml:ro` 将宿主机文件挂载进容器，覆盖镜像自带版本
> 4. 容器内的 `config.yaml` 中有 `${MYSQL_ROOT_PASSWORD}` 占位符，`settings.py` 启动时自动用环境变量值替换
> 5. **你永远不需要进入容器内部改任何文件**，只需要改宿主机上的文件然后重启

### 8.4 MySQL 和 Redis 的服务地址

**部署后各服务在 Docker 内部网络中的地址：**

| 服务 | 容器内部地址 | 从宿主机访问 |
|------|-------------|-------------|
| MySQL | `mysql:3306` | `127.0.0.1:3306` |
| Redis | `redis:6379` | `127.0.0.1:6379` |
| 后端 API | `backend:31818` | `127.0.0.1:31818` |
| Nginx | `nginx:80` | `127.0.0.1:80` |

**自动接入机制**：Docker Compose 创建了一个名为 `meetily-net` 的虚拟网络，所有容器都在这个网络内，**直接用服务名（如 `mysql`、`redis`）即可互相访问**。config.yaml 中写的 `@mysql:3306` 就是这个原理。

```bash
# 验证：在后端容器内直接 ping mysql 服务名
docker compose exec backend ping -c 1 mysql
# 输出：PING mysql (172.18.0.x) → 自动解析为容器 IP

# 从宿主机用 mysql 客户端连接
mysql -h 127.0.0.1 -P 3306 -u root -p
```

### 8.5 代码更新是否会丢失数据？

**不会丢失任何数据！** 这是 Docker Volume 的核心设计。

**容器 vs 镜像 vs Volume 的关系：**

```
┌──────────────────────────────────────────────────────┐
│  Docker 镜像 (Image)                                   │
│  只读模板，包含代码 + 依赖 + 系统库                       │
│  更新代码 → 构建新镜像 → 旧镜像被替换                      │
│  ✗ 不存任何业务数据                                     │
└──────────────────────────────────────────────────────┘
                    ↓ 创建
┌──────────────────────────────────────────────────────┐
│  Docker 容器 (Container)                               │
│  镜像的运行实例，可被删除和重建                            │
│  docker compose up -d --build → 旧容器删除，新容器创建    │
│  ✗ 容器本身不存数据                                     │
└──────────────────────────────────────────────────────┘
                    ↓ 挂载
┌──────────────────────────────────────────────────────┐
│  Docker Volume (数据卷) ← 数据在这里！                   │
│  独立于容器和镜像，存储在宿主机磁盘上                       │
│  /var/lib/docker/volumes/meetily-mysql-data/_data/    │
│  /var/lib/docker/volumes/meetily-redis-data/_data/    │
│  /var/lib/docker/volumes/meetily-chroma-data/_data/   │
│  ✓ 容器删除 → Volume 还在                               │
│  ✓ 镜像更新 → Volume 还在                               │
│  ✓ 服务器重启 → Volume 还在                             │
│  ✗ 只有手动 docker volume rm 才会删除                   │
└──────────────────────────────────────────────────────┘
```

**各数据的存储位置：**

| 数据 | 存储方式 | 更新代码后 |
|------|---------|-----------|
| MySQL 数据库 | Volume `meetily-mysql-data` | ✅ 完好无损 |
| Redis 缓存 | Volume `meetily-redis-data` | ✅ 完好无损 |
| ChromaDB 向量库 | Volume `meetily-chroma-data` | ✅ 完好无损 |
| LangGraph 状态 | Volume `meetily-checkpoints-data` | ✅ 完好无损 |
| 用户上传文件 | Volume `meetily-uploads-data` | ✅ 完好无损 |
| 应用代码 | 镜像内 | 被新版本替换 |

**验证数据持久化：**

```bash
# 1. 停止并删除所有容器
docker compose down

# 2. 确认 Volume 还在
docker volume ls | grep meetily
# 输出：
# meetily-mysql-data
# meetily-redis-data
# meetily-chroma-data
# ...

# 3. 重新构建并启动
docker compose up -d --build

# 4. MySQL 数据完好无损
docker compose exec mysql mysql -u root -p -e "SHOW DATABASES;"
```

### 8.6 设置 Docker 开机自启

```bash
# Docker 本身已设置开机自启，确认一下
sudo systemctl enable docker

# 容器配置了 restart: unless-stopped，会自动重启
```

### 8.7 监控资源使用

```bash
# 查看容器资源占用
docker stats

# 查看系统内存
free -h

# 查看磁盘使用
df -h

# 实时进程监控
htop
```

---

## 10. 2核4G 内存优化说明

### 9.1 各服务内存分配

| 服务 | 内存上限 | 预留内存 | 实际占用（典型） |
|------|----------|----------|------------------|
| MySQL 8.0 | 1GB | 512MB | ~500-700MB |
| FastAPI 后端 | 1GB | 512MB | ~400-600MB |
| Celery Worker | 512MB | 256MB | ~200-300MB |
| Redis 7 | 256MB | 128MB | ~50-100MB |
| Nginx | 128MB | 64MB | ~20-40MB |
| 系统开销 | - | - | ~300MB |
| **总计** | **~2.9GB** | - | **~1.5-2.0GB** |

> 2核4G 配置下有约 2GB 余量，运行稳定，不会出现 OOM。

### 9.2 MySQL 优化

```yaml
# docker-compose.yml 中已配置：
--innodb-buffer-pool-size=512M   # InnoDB 缓冲池，提高查询性能
--innodb-log-file-size=128M      # 事务日志大小
--max-connections=200            # 最大连接数
--performance-schema=ON          # 开启性能监控（2核4G 内存充足）
```

### 9.3 Celery 并发

```yaml
# celery-worker 配置了 4 个并发 worker（eventlet 协程池）
--concurrency=4
--pool=eventlet
```

### 9.4 Redis 持久化

```yaml
# Redis 使用 AOF 持久化，每秒钟同步一次
--appendonly yes
--appendfsync everysec
--maxmemory 256mb
--maxmemory-policy allkeys-lru   # 内存满时淘汰最少使用的 key
```

### 9.5 系统级优化

已配置 2GB swap 空间（见第 2.2 节），极端情况下可防止 OOM。

---

## 11. 故障排查 FAQ

### Q1：`docker compose up -d` 后容器一直重启

```bash
# 查看具体错误日志
docker compose logs --tail=50 <容器名>

# 常见原因：
# 1. .env 文件未配置或配置错误
# 2. MySQL 未就绪时后端已启动（docker-entrypoint.sh 会等待 60 秒）
# 3. 端口冲突（80 或 3306 被占用）
```

### Q2：MySQL 连接失败

```bash
# 检查 MySQL 是否就绪
docker compose logs mysql | grep "ready for connections"

# 测试连接
docker compose exec mysql mysql -u root -p -e "SELECT 1"

# 如果密码不对，检查 .env 中的 MYSQL_ROOT_PASSWORD
```

### Q3：前端页面 502 Bad Gateway

```bash
# 后端未启动或崩溃
docker compose ps backend
docker compose logs --tail=50 backend

# 常见原因：
# 1. .env 中 LLM API Key 等配置错误导致启动失败
# 2. config.yaml 中 Docker 服务名未切换
```

### Q4：容器内无法访问外网

```bash
# 检查 Docker DNS
docker compose exec backend ping -c 1 baidu.com

# 如果失败，重启 Docker
sudo systemctl restart docker
docker compose up -d
```

### Q5：磁盘空间不足

```bash
# 查看磁盘使用
df -h

# 清理 Docker 垃圾
docker system prune -a --volumes

# 注意：这会删除未使用的镜像和数据卷，
# 请确保当前容器在运行中，否则会丢失数据！
```

### Q6：构建时 `uv sync` 失败

```bash
# 检查 PyPI 源连通性
docker compose exec backend pip config list

# 可能需要在 Dockerfile 中配置国内镜像源
# 编辑 backend/Dockerfile，在 uv sync 前添加：
# ENV UV_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
```

### Q7：内存不足导致容器被 Kill

虽然 2核4G 通常不会出现此问题，但如果遇到：

```bash
# 查看 OOM 事件
dmesg | grep -i oom

# 查看容器退出原因
docker inspect <容器名> | grep -A5 "State"

# 临时解决：增大 swap
sudo fallocate -l 4G /swapfile
# 或降低 docker-compose.yml 中各服务的 mem_limit
```

---

## 12. 数据备份与迁移

### 11.1 备份 MySQL 数据

```bash
# 导出整个数据库
docker compose exec mysql mysqldump -u root -p graduation_db > backup_$(date +%Y%m%d).sql

# 自动备份脚本（crontab 每日凌晨 2 点）
cat > /home/meetily/backup.sh << 'EOF'
#!/bin/bash
BACKUP_DIR="/home/meetily/backups"
mkdir -p $BACKUP_DIR
DATE=$(date +%Y%m%d_%H%M%S)
docker compose -f /home/meetily/meetily/docker-compose.yml exec -T mysql \
  mysqldump -u root -p${MYSQL_ROOT_PASSWORD} graduation_db > ${BACKUP_DIR}/mysql_${DATE}.sql
# 保留最近 7 天的备份
find ${BACKUP_DIR} -name "mysql_*.sql" -mtime +7 -delete
EOF

chmod +x /home/meetily/backup.sh

# 添加 crontab
(crontab -l 2>/dev/null; echo "0 2 * * * /home/meetily/backup.sh") | crontab -
```

### 11.2 备份 Docker 数据卷

```bash
# 备份所有数据卷
tar -czf meetily_volumes_$(date +%Y%m%d).tar.gz \
  /var/lib/docker/volumes/meetily-mysql-data \
  /var/lib/docker/volumes/meetily-redis-data \
  /var/lib/docker/volumes/meetily-chroma-data \
  /var/lib/docker/volumes/meetily-checkpoints-data \
  /var/lib/docker/volumes/meetily-uploads-data
```

### 11.3 迁移到新服务器

```bash
# 在旧服务器上
cd /home/meetily/meetily
docker compose down
tar -czf meetily_backup.tar.gz .env docker-compose.yml
# 备份数据卷（见上节）

# 将备份文件传输到新服务器
scp meetily_backup.tar.gz root@<新IP>:/home/meetily/
scp meetily_volumes_*.tar.gz root@<新IP>:/home/meetily/

# 在新服务器上
cd /home/meetily
tar -xzf meetily_backup.tar.gz -C meetily/
tar -xzf meetily_volumes_*.tar.gz -C /  # 恢复数据卷
cd meetily
docker compose up -d
```

### 11.4 免费试用到期前迁移

阿里云 300 元免费额度有效期 3 个月。到期前：

1. **备份所有数据**（按 11.1-11.2 节操作）
2. **下载备份到本地**：`scp root@<IP>:/home/meetily/backups/* ./`
3. **在新服务器上恢复**（或续费当前实例）
4. **验证服务正常运行**
5. **释放旧实例**（避免产生费用）

---

## 附录 A：项目架构图

```
┌──────────────────────────────────────────────────┐
│                   用户浏览器                        │
└─────────────────┬────────────────────────────────┘
                  │ HTTP :80
                  ▼
┌──────────────────────────────────────────────────┐
│              Nginx (meetily-nginx)                 │
│  ┌──────────────────┐  ┌────────────────────────┐ │
│  │ 静态文件 (dist/)  │  │ /api/* 反向代理          │ │
│  │ History 路由兜底   │  │ WebSocket Upgrade 头    │ │
│  └──────────────────┘  └───────────┬────────────┘ │
└────────────────────────────────────┼──────────────┘
                                     │
                  ┌──────────────────┼──────────────────┐
                  ▼                  ▼                  ▼
┌─────────────────────┐ ┌─────────────────────┐ ┌─────────────────────┐
│   backend :31818     │ │  celery-worker      │ │   mysql :3306       │
│  FastAPI + Uvicorn   │ │  Celery + Eventlet  │ │   MySQL 8.0         │
│  + ChromaDB (本地)   │ │  Concurrency=4      │ │   buffer_pool=512M  │
│  + LangGraph SQLite  │ └─────────┬───────────┘ └─────────────────────┘
└──────────┬──────────┘           │
           │                      │
           └──────────┬───────────┘
                      │
                      ▼
          ┌─────────────────────┐
          │   redis :6379       │
          │   Redis 7 (AOF)     │
          │   maxmemory=256MB   │
          └─────────────────────┘
```

## 附录 B：端口说明

| 端口 | 服务 | 对外暴露 | 说明 |
|------|------|----------|------|
| 80 | Nginx | ✅ | HTTP 入口 |
| 31818 | FastAPI | ✅ | 直接访问后端（调试用） |
| 3306 | MySQL | ✅ | 数据库连接（远程管理） |
| 6379 | Redis | ✅ | Redis 连接（调试用） |

> ⚠️ 生产环境建议通过安全组关闭 31818/3306/6379 的对外暴露，仅保留 80（和 443）。

## 附录 C：目录结构（部署相关）

```
meetily/
├── docker-compose.yml          # Docker Compose 编排文件
├── .dockerignore               # Docker 构建忽略规则
├── .env.production             # 生产环境变量模板
├── .env                        # 生产环境变量（需手动创建）
├── nginx/
│   └── nginx.conf              # Nginx 配置
├── backend/
│   ├── Dockerfile              # 后端镜像构建文件
│   ├── docker-entrypoint.sh    # 启动脚本（等待 MySQL + 初始化 + 启动）
│   ├── config.yaml             # 数据库/Redis 地址配置
│   ├── main.py                 # FastAPI 入口（dotenv 加载已修复）
│   └── ...
└── frontend/
    ├── Dockerfile              # 前端多阶段构建文件
    └── ...
```

---

> **文档维护**：如部署过程中遇到问题，请记录并更新本文档的 FAQ 部分。
