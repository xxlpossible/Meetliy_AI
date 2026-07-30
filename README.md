# 智能会议纪要助手（基于 LangChain / LangGraph）

> 面向多人实时会议的 AI 纪要助手 —— 实时语音转写、多人 WebRTC 协作、LangGraph 自动生成结构化纪要、知识库 RAG 问答与 AI 对话。

## 项目简介

本项目为毕业设计课题，探索大语言模型（LLM）与实时语音技术在会议场景的落地应用。系统支持多人实时会议（WebRTC Mesh P2P 音频）、实时语音转写（DashScope ASR）、会后自动生成结构化会议纪要（LangGraph 编排），并内置知识库检索增强问答（RAG）与 AI 对话功能。

### 核心能力

- **多人实时会议**：基于 WebRTC Mesh 的浏览器端 P2P 音频传输（≤4 人），服务端 ffmpeg 混音
- **实时语音转写**：DashScope ASR WebSocket 流式识别，支持说话人标注
- **自动纪要生成**：LangGraph 编排多节点工作流，会后自动产出结构化会议纪要
- **知识库管理**：文件上传 → 异步分块解析 → ChromaDB 向量入库 → RAG 检索问答
- **AI 对话**：基于知识库的流式 SSE 对话，支持多会话管理
- **双 Token 鉴权**：Access Token（30 分钟）+ Refresh Token（7 天）JWT 机制

## 系统架构

```
┌─────────────────────────────────────────────────────────────────┐
│                         浏览器（前端）                            │
│   Vue3 + Vite + Element Plus + Pinia + WebRTC + WebSocket        │
└───────────────┬─────────────────────────────┬───────────────────┘
                │ HTTP /api                    │ WebSocket + WebRTC
                ▼                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    FastAPI 后端（:31818）                         │
│  ┌──────────┐ ┌───────────┐ ┌──────────┐ ┌──────────────────┐  │
│  │ REST API │ │ WS 实时   │ │ Celery   │ │ LangGraph 编排   │  │
│  │ 鉴权/会议│ │ 转写/信令 │ │ 异步任务 │ │ 纪要生成/RAG     │  │
│  └────┬─────┘ └─────┬─────┘ └────┬─────┘ └────────┬─────────┘  │
└───────┼─────────────┼────────────┼────────────────┼────────────┘
        │             │            │                │
        ▼             ▼            ▼                ▼
   ┌────────┐  ┌──────────┐  ┌─────────┐    ┌────────────┐
   │ MySQL  │  │DashScope │  │ Redis   │    │ ChromaDB   │
   │ 业务库 │  │  ASR/LLM │  │缓存/队列│    │ 向量检索   │
   └────────┘  └──────────┘  └─────────┘    └────────────┘
                                    │
                                    ▼
                          ┌──────────────────┐
                          │  阿里云 OSS      │
                          │  会议录音存储    │
                          └──────────────────┘
```

**核心数据流**：浏览器麦克风 → WebSocket → DashScope ASR 实时转写 → PCM 录音 → 会议结束 ffmpeg 合并 → OSS 上传 → Celery 异步转写任务 → LangGraph 生成结构化纪要

## 技术栈

### 后端（backend/）

| 类别 | 技术 | 版本 |
|---|---|---|
| Web 框架 | FastAPI | ≥0.121 |
| ASGI 服务器 | Uvicorn | ≥0.38 |
| ORM | SQLModel | ≥0.0.27 |
| 数据库 | MySQL（PyMySQL 驱动） | ≥8.x |
| 缓存/队列 | Redis | ≥7.0 |
| 异步任务 | Celery + eventlet | ≥5.5 |
| LLM 编排 | LangChain + LangGraph | ≥1.2.6 |
| 向量数据库 | ChromaDB | ≥1.3.4 |
| 语音识别/LLM | DashScope（阿里云通义） | ≥1.25 |
| 对象存储 | 阿里云 OSS（alibabacloud-oss-v2） | ≥1.2.1 |
| 鉴权 | PyJWT + passlib（双 Token） | - |
| 文档解析 | markitdown / docx2txt / pypdf / openpyxl | - |
| 依赖管理 | uv + pyproject.toml | - |

### 前端（frontend/）

| 类别 | 技术 | 版本 |
|---|---|---|
| 框架 | Vue 3 | ^3.5.13 |
| 构建工具 | Vite 6 | ^6.0.5 |
| 语言 | TypeScript | ^5.7.2 |
| UI 组件库 | Element Plus | ^2.9.1 |
| 状态管理 | Pinia | ^2.3.0 |
| 路由 | Vue Router | ^4.5.0 |
| HTTP 客户端 | Axios | ^1.7.9 |
| Markdown 渲染 | markdown-it + highlight.js | ^14.1 / ^11.11 |
| 实时通信 | WebSocket + WebRTC（Mesh） | 原生 API |
| 代码规范 | ESLint + vue-tsc | - |

### 基础设施

- **ffmpeg**：会议多路音频合并（amix + adelay 对齐）
- **Python 3.11+**（要求 ≥3.11, <3.14）
- **Node.js 22+**
- **MySQL 8.x**
- **Redis 7.x**

## 目录结构

```
the_graduation_project/
├── .gitignore                         # 根级统一忽略规则
├── .editorconfig                      # 编辑器缩进/换行规范
├── README.md                          # 项目说明（本文件）
│
├── backend/                           # FastAPI 后端
│   ├── main.py                        # 应用入口，监听 :31818
│   ├── settings.py                    # 三层配置（.env → DB config 表 → config.yaml）
│   ├── .env.example                   # 环境变量模板（复制为 .env 使用）
│   ├── config.yaml                    # MySQL/Redis 连接配置
│   ├── pyproject.toml                 # uv 依赖管理（项目名 graduation_project）
│   ├── uv.lock                        # 依赖锁文件
│   ├── benchmark_graph.py             # LangGraph 性能基准测试
│   │
│   ├── api/                           # 路由层（/api/v1 前缀）
│   │   ├── router.py                  # 根路由，聚合所有子路由
│   │   ├── schemas.py                 # 通用响应模型 (resp_200, TokenData)
│   │   └── v1/                        # v1 子路由
│   │       ├── __init__.py            # 导出所有 router
│   │       ├── auth.py                # 注册 / 登录 / Token 刷新（JWT 双 Token）
│   │       ├── user.py                # 用户信息管理
│   │       ├── meeting.py             # 会议管理（创建/加入/结束/列表/上传录音）
│   │       ├── chat_message.py        # AI 对话（HTTP 摘要 + WebSocket 流式）
│   │       ├── session.py             # 聊天会话管理（CRUD + 临时会话）
│   │       ├── knowledge.py           # 知识库 CRUD + 权限控制
│   │       └── knowledge_file.py      # 知识库文件上传 / 状态追踪 / 删除
│   │
│   ├── database/                      # 数据层
│   │   ├── base.py                    # session_getter 异步上下文管理器
│   │   ├── service.py                 # DatabaseService（引擎创建）
│   │   ├── check_points.py            # LangGraph checkpoint SQLite 管理
│   │   ├── models/                    # SQLModel 数据模型（8 个）
│   │   │   ├── user.py                # 用户模型
│   │   │   ├── meeting.py             # 会议模型
│   │   │   ├── transcription.py       # 转录任务模型
│   │   │   ├── knowledge.py           # 知识库模型
│   │   │   ├── knowledge_file.py      # 知识库文件模型
│   │   │   ├── chatmessage.py         # 聊天消息模型
│   │   │   ├── chat_session.py        # 聊天会话模型
│   │   │   └── config.py              # 数据库配置表（API Key 等动态配置）
│   │   ├── schemas/                   # Pydantic 响应 Schema
│   │   │   └── schema.py              # 统一响应数据模型
│   │
│   ├── service/                       # 业务逻辑层
│   │   ├── base.py                    # 服务基类
│   │   ├── llm_graph_service.py       # LangGraph 纪要生成主流程（核心编排）
│   │   ├── llm_service.py             # LLM 调用封装
│   │   ├── meeting_manager.py         # 多人会议房间管理（WebSocket 信令）
│   │   ├── meeting_callback.py        # 会议结束回调处理
│   │   ├── audio_merger.py            # PCM → WAV → mp3 ffmpeg 音频合并
│   │   ├── realtime_asr.py            # DashScope 实时语音识别 WebSocket 客户端
│   │   ├── dashscope_file_asr.py      # DashScope 文件转写（异步）
│   │   ├── retrieval_pipeline.py      # RAG 检索管线（向量检索 + 重排序）
│   │   ├── context_builder.py         # 对话上下文构建
│   │   ├── query_optimizer.py         # 查询优化与改写
│   │   └── rerank.py                  # 结果重排序
│   │
│   ├── utils/                         # 工具模块
│   │   ├── security.py                # JWT 生成/验证、密码哈希
│   │   ├── dependencies.py            # FastAPI 依赖注入（get_current_user 等）
│   │   ├── oss.py                     # 阿里云 OSS 客户端封装
│   │   ├── minio_client.py            # MinIO 对象存储客户端
│   │   ├── uploader.py                # 文件上传工具
│   │   ├── file_loader.py             # 本地文件加载器
│   │   ├── markitdown_converter.py    # Markitdown 文档转换
│   │   ├── splitter.py                # 文档分块策略
│   │   ├── formatter.py               # 数据格式化工具
│   │   ├── siliconflow_embedding.py   # SiliconFlow 嵌入模型封装
│   │   └── siliconflow_media_parser.py # SiliconFlow 多模态解析
│   │
│   ├── cache/                         # 缓存层
│   │   └── redis.py                   # Redis 客户端封装
│   │
│   ├── task/                          # Celery 异步任务
│   │   ├── celery_app.py              # Celery 应用实例
│   │   └── tasks.py                   # 异步任务（转写 / 知识库文件解析）
│   │
│   ├── langchain_pipeline/            # 早期 LangGraph 原型（待清理，见下文）
│   │   ├── __init__.py
│   │   └── agent.py
│   │
│   ├── sql/                           # 数据库初始化
│   │   ├── graduation_db.sql          # Navicat 导出的完整建表脚本
│   │   └── init_db.py                 # 一键初始化脚本（自动建库 + 执行 SQL）
│
│
├── frontend/                          # Vue3 + Vite + TS 前端
│   ├── package.json                   # 依赖与脚本
│   ├── vite.config.ts                 # Vite 配置（proxy /api → :31818，含 WebSocket）
│   ├── tsconfig.json / tsconfig.node.json
│   ├── tsconfig.app.json
│   ├── index.html                     # Vite 入口 HTML
│   ├── .env.development               # VITE_API_TARGET=http://localhost:31818
│   ├── .env.production                # 生产环境（同源部署）
│   ├── TECH_STACK.md                  # 前端技术选型详述
│   └── src/
│       ├── main.ts                    # 应用入口（挂载 Vue、Pinia、Router）
│       ├── App.vue                    # 根组件
│       ├── api/                       # API 调用层
│       │   ├── index.ts               # API 模块聚合导出
│       │   ├── request.ts             # Axios 实例（拦截器、Token 注入、刷新）
│       │   ├── types.ts               # TypeScript 接口契约（对齐后端 Schema）
│       │   └── modules/               # API 模块（auth / user / meeting / chat / knowledge 等）
│       ├── stores/                    # Pinia 状态管理
│       │   ├── index.ts               # Pinia 实例创建
│       │   ├── auth.ts                # 认证状态（Token、用户信息）
│       │   ├── chat.ts                # 聊天状态（会话列表、消息、流式响应）
│       │   ├── knowledge.ts           # 知识库状态
│       │   └── meeting.ts             # 会议状态（房间、参与者、WebRTC 连接）
│       ├── router/                    # Vue Router 路由
│       │   └── index.ts               # 路由配置 + 导航守卫
│       ├── views/                     # 页面视图
│       │   ├── LoginView.vue          # 登录 / 注册页
│       │   ├── DashboardView.vue      # 仪表盘首页
│       │   ├── MeetingRoomView.vue    # 实时会议房间（WebRTC + 转写）
│       │   ├── MeetingDetailView.vue  # 历史会议详情（纪要查看）
│       │   ├── ChatView.vue           # AI 对话页（流式 SSE）
│       │   ├── KnowledgeView.vue      # 知识库管理页
│       │   └── NotFoundView.vue       # 404 页面
│       ├── layouts/                   # 布局组件
│       │   ├── DefaultLayout.vue      # 主布局（侧边栏 + 顶栏 + 内容区）
│       │   └── BlankLayout.vue        # 空白布局（登录页使用）
│       ├── components/                # 通用组件
│       │   ├── ConfirmDialog.vue      # 确认对话框
│       │   ├── EditContextModal.vue   # 编辑上下文弹窗
│       │   └── NewChatModal.vue       # 新建会话弹窗
│       ├── composables/               # 组合式函数
│       │   ├── useAudioCapture.ts     # 麦克风音频采集
│       │   ├── useChatSSE.ts          # SSE 流式对话
│       │   ├── useMeetingWebSocket.ts # 会议 WebSocket 通信
│       │   ├── useTempChat.ts         # 临时对话逻辑
│       │   └── useWebRTC.ts           # WebRTC Mesh 连接管理
│       ├── styles/                    # 全局样式
│       │   ├── design-tokens.scss     # 设计 Token（配色、间距、圆角等）
│       │   ├── element-theme.scss     # Element Plus 主题覆盖
│       │   ├── global.scss            # 全局样式
│       │   └── mixins.scss            # SCSS Mixins
│       └── utils/                     # 前端工具函数
│           └── markdown.ts            # Markdown 渲染（markdown-it + highlight.js）
│
├── design/                            # 共享设计资源
│   ├── design-system.md               # 温暖工作室设计系统规范
│   ├── overview.md                    # 设计概览与设计决策
│   ├── api-needs.md                   # 接口需求文档
│   └── mockups/                       # HTML 页面设计原型（6 个）
│       ├── login.html                 # 登录页原型
│       ├── dashboard.html             # 仪表盘原型
│       ├── meeting-room.html          # 会议房间原型
│       ├── meeting-detail.html        # 会议详情原型
│       ├── knowledge-base.html        # 知识库原型
│       └── ai-chat.html               # AI 对话原型
│
└── docs/                              # 项目文档
    ├── auth-implementation-overview.md    # 双 Token JWT 鉴权实现总结
    ├── websocket-self-check.md            # WebSocket 自检报告
    └── prototypes/                        # 早期原型归档
        └── frontend_test/                 # 原生 JS WebRTC 原型（已被 Vue3 版本替代）
```

## 环境要求

| 组件 | 版本 | 说明 |
|---|---|---|
| Python | ≥3.11, <3.14 | 后端运行时 |
| Node.js | ≥22 | 前端构建 |
| MySQL | ≥8.x | 业务数据存储 |
| Redis | ≥7.x | 缓存 + Celery 消息队列 |
| ffmpeg | 任意版本 | 会议音频合并（需加入 PATH） |
| uv | 最新版 | Python 依赖管理（可选，也可用 pip） |

### 外部服务密钥

- **阿里云 DashScope API Key**：用于 ASR 语音识别与通义千问 LLM
- **阿里云 OSS**：会议录音文件存储（Bucket 配置见 `.env`）
- **MySQL / Redis 连接信息**

## 快速开始

### 1. 克隆仓库

```bash
git clone https://github.com/xxlpossible/graduation.git
cd graduation
git checkout chain_update   # 主开发分支
```

### 2. 后端启动（backend/）

```bash
cd backend

# (1) 创建并激活虚拟环境
python -m venv .venv
# Windows Git Bash:
source .venv/Scripts/activate
# Linux/macOS:
# source .venv/bin/activate

# (2) 安装依赖（推荐 uv）
pip install uv
uv sync
# 或使用 pip:
# pip install -e .

# (3) 配置环境变量
#    按实际 MySQL/Redis 地址修改 config.yaml
cp config.yaml config.yaml
# 复制 .env 模板并填写实际值
cp .env.example .env
# 至少需要填写以下配置（所有 LLM 模型均通过 CHAT_MODEL 节配置）：
#   CHAT_MODEL_BASE_URL / CHAT_MODEL_API_KEY / CHAT_MODEL_MODEL
#   ROUTER_MODEL_BASE_URL / ROUTER_MODEL_API_KEY / ROUTER_MODEL_MODEL
#   DASHSCOPE_API_KEY
#   EMBEDDINGS_BASE_URL / EMBEDDINGS_API_KEY / EMBEDDINGS_MODEL
#   RERANK_BASE_URL / RERANK_API_KEY / RERANK_MODEL
#   JWT_SECRET_KEY
#   OSS_ACCESS_KEY_ID / OSS_ACCESS_KEY_SECRET / OSS_BUCKET_NAME / OSS_ENDPOINT

# (4) 初始化数据库（推荐一键脚本）
python sql/init_db.py
#    或者手动导入: mysql -u root -p graduation_db < sql/graduation_db.sql

# (5) 启动 Celery Worker（异步转写 + 知识库解析，需单独终端）
celery -A task worker -l info -P eventlet

# (6) 启动 FastAPI 主服务
python main.py
# 服务监听 http://localhost:31818
# API 文档：http://localhost:31818/docs
```

### 3. 前端启动（frontend/）

```bash
cd frontend

# (1) 安装依赖
npm install

# (2) 启动开发服务器
npm run dev
# 开发服务器：http://localhost:5173
# 已配置代理：/api → http://localhost:31818（含 WebSocket）

# (3) 生产构建
npm run build
# 输出到 dist/，可由 Nginx 或后端静态托管
```

### 4. 访问应用

- 前端界面：http://localhost:5173
- 后端 API 文档：http://localhost:31818/docs
- 默认注册登录后即可使用会议、知识库、AI 对话功能

## 核心模块说明

### 后端服务层 (service/)

| 模块 | 职责 |
|---|---|
| `llm_graph_service.py` | LangGraph 纪要生成主流程：ASR 文本 → 内容提炼 → 结构化纪要输出 |
| `llm_service.py` | 统一 LLM 调用封装，支持多模型切换（DashScope / OpenAI / SiliconFlow） |
| `meeting_manager.py` | 会议室生命周期管理：创建房间、加入/离开、WebSocket 信令转发 |
| `meeting_callback.py` | 会议结束后的回调链：触发音频合并 → OSS 上传 → Celery 转写任务 |
| `audio_merger.py` | 多路 PCM 音频合并为 mp3（ffmpeg amix + adelay） |
| `realtime_asr.py` | DashScope 实时语音识别 WebSocket 客户端，流式返回转写结果 |
| `dashscope_file_asr.py` | DashScope 文件级语音识别（异步提交 + 轮询结果） |
| `retrieval_pipeline.py` | RAG 检索管线：用户提问 → 向量检索 → 重排序 → 上下文构建 |
| `context_builder.py` | 对话历史与知识库上下文整合 |
| `query_optimizer.py` | 用户查询改写与优化（提升检索精度） |
| `rerank.py` | 检索结果重排序（提升召回相关性） |

### 前端核心页面

| 页面 | 路由 | 说明 |
|---|---|---|
| `LoginView` | `/login` | 登录/注册页，支持表单切换 |
| `DashboardView` | `/` | 仪表盘首页，展示会议列表与快速入口 |
| `MeetingRoomView` | `/meeting/:id` | 实时会议房间，WebRTC 音视频 + 实时转写 |
| `MeetingDetailView` | `/meeting/:id/detail` | 历史会议详情，查看 AI 生成的结构化纪要 |
| `ChatView` | `/chat` | AI 对话页，流式 SSE 响应 + 知识库 RAG |
| `KnowledgeView` | `/knowledge` | 知识库管理，文件上传 / 状态追踪 / 检索 |
| `NotFoundView` | `/*` | 404 页面 |

### 数据库模型

| 模型 | 表名 | 说明 |
|---|---|---|
| `User` | `users` | 用户账户信息 |
| `Meeting` | `meetings` | 会议记录（标题、状态、参会者、录音 URL） |
| `Transcription` | `transcriptions` | 转录任务（状态、结果文本、文件 URL） |
| `Knowledge` | `knowledges` | 知识库元数据 |
| `KnowledgeFile` | `knowledge_files` | 知识库文件（上传状态、解析进度） |
| `ChatSession` | `chat_sessions` | 聊天会话 |
| `ChatMessage` | `chatmessages` | 聊天消息记录 |
| `Config` | `config` | 动态配置表（API Key 等运行时配置） |

## 设计资源

| 资源 | 路径 | 说明 |
|---|---|---|
| 设计系统 | `design/design-system.md` | 温暖工作室配色（暖石灰 + 琥珀暖光 #F5B400）、字体、组件规范 |
| 设计概览 | `design/overview.md` | 设计决策与页面规划 |
| 接口需求 | `design/api-needs.md` | 前后端接口需求文档 |
| 页面原型 | `design/mockups/*.html` | 6 个核心页面的 HTML 设计稿 |
| 鉴权文档 | `docs/auth-implementation-overview.md` | 双 Token JWT 鉴权实现总结 |
| WebSocket 文档 | `docs/websocket-self-check.md` | WebSocket 自检报告 |
| 早期原型 | `docs/prototypes/frontend_test/` | 原生 JS WebRTC 原型（已被 Vue3 版本替代，仅供历史参考） |
| 前端技术详述 | `frontend/TECH_STACK.md` | 前端技术选型与页面说明 |

## 项目文档

- **鉴权体系**：`docs/auth-implementation-overview.md`（双 Token、越权防护、配置获取）
- **前端技术栈**：`frontend/TECH_STACK.md`
- **设计规范**：`design/design-system.md`
- **API 契约**：`frontend/src/api/types.ts`（TypeScript 类型定义，对齐后端 FastAPI 模型）

## 分支说明

- `main`：稳定分支
- `chain_update`：主开发分支（当前活跃）

## License

毕业设计项目，仅供学习交流使用。

---

作者：xxlpossible (liang311818@163.com)
