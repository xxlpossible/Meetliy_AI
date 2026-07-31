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
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  app/         API 层 —— 路由 / 鉴权 / 中间件              │   │
│  ├──────────────────────────────────────────────────────────┤   │
│  │  agent/       Agent 核心 —— ChatAgent / MeetingAgent      │   │
│  │               LangGraph 编排 nodes / prompts / tools      │   │
│  ├──────────────────────────────────────────────────────────┤   │
│  │  rag/         RAG 检索 —— embedding / 检索 / 重排序 / 记忆│   │
│  ├──────────────────────────────────────────────────────────┤   │
│  │  services/    业务编排 —— 聊天 / 会议 / ASR / 音频 / 文档 │   │
│  ├──────────────────────────────────────────────────────────┤   │
│  │  core/        基础设施 —— database / cache / llm / storage │   │
│  ├──────────────────────────────────────────────────────────┤   │
│  │  tasks/       Celery 异步 —— 转录 / 知识库文件解析        │   │
│  └──────────────────────────────────────────────────────────┘   │
└───────┬─────────────┬────────────┬────────────────┬─────────────┘
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

**核心数据流**：浏览器麦克风 → WebSocket → DashScope ASR 实时转写 → PCM 录音 → 会议结束 ffmpeg 合并 → OSS 上传 → Celery 异步转写任务 → MeetingAgent (LangGraph) 生成结构化纪要

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
├── backend/                           # FastAPI 后端（Agent 标准架构）
│   ├── main.py                        # 应用入口，监听 :31818
│   ├── settings.py                    # 三层配置（.env → DB config 表 → config.yaml）
│   ├── .env.example                   # 环境变量模板（复制为 .env 使用）
│   ├── config.yaml                    # MySQL/Redis 连接配置
│   ├── pyproject.toml                 # uv 依赖管理（项目名 graduation_project）
│   ├── uv.lock                        # 依赖锁文件
│   ├── benchmark_graph.py             # LangGraph 性能基准测试
│   │
│   ├── app/                           # ★ 应用层 —— API 路由与中间件
│   │   ├── api/
│   │   │   ├── router.py              # 根路由，聚合所有子路由
│   │   │   ├── schemas.py             # 通用响应模型 (resp_200, TokenData)
│   │   │   ├── request.py             # 请求/响应 Pydantic Schema
│   │   │   ├── deps.py                # 鉴权依赖注入 (get_current_user)
│   │   │   └── v1/                    # v1 子路由
│   │   │       ├── auth.py            # 注册 / 登录 / Token 刷新
│   │   │       ├── user.py            # 用户信息管理
│   │   │       ├── meeting.py         # 会议管理（创建/加入/结束/列表/上传录音）
│   │   │       ├── chat.py            # AI 对话（SSE 流式）
│   │   │       ├── session.py         # 聊天会话管理
│   │   │       ├── knowledge.py       # 知识库 CRUD + 权限控制
│   │   │       └── knowledge_file.py  # 知识库文件上传 / 状态追踪
│   │   └── middleware/
│   │       └── cors.py                # CORS 中间件
│   │
│   ├── agent/                         # ★ Agent 核心层 —— LangGraph 编排
│   │   ├── base.py                    # Agent 抽象基类
│   │   ├── chat/                      # ChatAgent —— RAG 对话
│   │   │   ├── agent.py               # 主控：START→Router→三路检索→builder→LLM→END
│   │   │   ├── state.py               # ChatState (TypedDict)
│   │   │   ├── schemas.py             # RouterOutput 结构化输出
│   │   │   ├── nodes/                 # 图节点（6 个）
│   │   │   │   ├── router.py          # 意图路由（结构化输出 + 关键词兜底）
│   │   │   │   ├── meeting_retrieval.py  # 会议库多路检索
│   │   │   │   ├── memory_retrieval.py   # 历史记忆检索
│   │   │   │   ├── knowledge_retrieval.py # 知识库检索
│   │   │   │   ├── context_builder.py    # 上下文构建 + 降级判定
│   │   │   │   └── llm_generate.py       # LLM 流式生成
│   │   │   └── prompts/               # 提示词（3 个）
│   │   │       ├── system.py          # 系统角色 + 反泄露指令
│   │   │       ├── router.py          # 路由分类提示词
│   │   │       └── fallback.py        # 四级降级兜底提示词
│   │   └── meeting/                   # MeetingAgent —— 会议纪要生成
│   │       ├── agent.py               # 主控：LLM→ASR Tool→润色→[纪要/行动项/主题]
│   │       ├── state.py               # MeetingState (TypedDict, operator.add)
│   │       ├── nodes/                 # 图节点（5 个）
│   │       │   ├── llm_process.py     # LLM 纠错润色
│   │       │   ├── tool_exec.py       # ASR 工具执行
│   │       │   ├── summary.py         # 会议总结生成
│   │       │   ├── action_items.py    # 行动项提取
│   │       │   └── theme_seg.py       # 主题分段
│   │       ├── tools/                 # 工具（1 个）
│   │       │   └── asr.py             # DashScope 语音识别工具
│   │       └── prompts/               # 提示词（4 个）
│   │           ├── process.py         # 纠错润色提示词
│   │           ├── summary.py         # 会议总结提示词
│   │           ├── action.py          # 行动项提取提示词
│   │           └── theme.py           # 主题分段提示词
│   │
│   ├── rag/                           # ★ RAG 检索增强层
│   │   ├── embedding.py               # ChromaDB 向量库管理 + 嵌入
│   │   ├── retrieval_pipeline.py      # 多路检索编排 + 相邻块扩展
│   │   ├── rerank.py                  # BGE Reranker 重排序
│   │   ├── query_optimizer.py         # 查询分类与改写
│   │   ├── splitter.py                # 文档分块策略
│   │   └── memory.py                  # 对话记忆持久化与检索
│   │
│   ├── core/                          # ★ 核心基础设施
│   │   ├── database/
│   │   │   ├── session.py             # SQLModel 会话 + 引擎管理
│   │   │   ├── checkpoints.py         # LangGraph checkpoint 管理
│   │   │   └── models/                # ORM 模型（8 个）
│   │   │       ├── user.py / meeting.py / transcription.py
│   │   │       ├── knowledge.py / knowledge_file.py
│   │   │       ├── chatmessage.py / chat_session.py / config.py
│   │   ├── cache/
│   │   │   └── redis.py               # Redis 客户端封装
│   │   ├── llm/
│   │   │   ├── factory.py             # LLM 模型工厂（统一管理各模型初始化）
│   │   │   └── client.py              # 流式 LLM 客户端
│   │   └── storage/
│   │       ├── oss.py                 # 阿里云 OSS 客户端
│   │       ├── minio.py               # MinIO 对象存储
│   │       └── uploader.py            # 文件上传工具
│   │
│   ├── services/                      # ★ 业务服务层（薄封装）
│   │   ├── chat_service.py            # 对话服务编排（Agent 调用 + 流式输出）
│   │   ├── meeting_service.py         # 会议室生命周期管理
│   │   ├── meeting_callback.py        # 会议结束回调处理
│   │   ├── audio_service.py           # PCM → WAV → mp3 ffmpeg 音频合并
│   │   ├── realtime_asr.py            # DashScope 实时 ASR WebSocket
│   │   ├── dashscope_file_asr.py      # DashScope 文件级语音识别
│   │   ├── media_parser.py            # 硅基流式多模态解析（语音转录+图片OCR）
│   │   └── document_service.py        # 文档解析/转换
│   │
│   ├── task/                          # Celery 异步任务
│   │   ├── celery_app.py              # Celery 应用实例
│   │   └── tasks.py                   # 转录任务 + 知识库文件解析
│   │
│   ├── utils/                         # 通用工具
│   │   ├── security.py                # JWT 生成/验证、密码哈希
│   │   ├── file_loader.py             # 本地文件加载器
│   │   └── formatter.py               # ASR 转录结果格式化
│   │
│   ├── sql/                           # 数据库初始化
│   │   ├── graduation_db.sql          # Navicat 完整建表脚本
│   │   └── init_db.py                 # 一键初始化脚本
│   │
│   ├── chroma_db/                     # ChromaDB 向量库持久化目录（运行时生成）
│   └── data/                          # 本地音频数据（运行时生成）
│
│
├── frontend/                          # Vue3 + Vite + TS 前端
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

### Agent 核心层 (agent/)

后端的核心是 **Agent 标准架构**，将 LLM 编排逻辑从业务层剥离，形成独立的 Agent 层。

| Agent | 图文件 | 节点数 | 说明 |
|---|---|---|---|
| **ChatAgent** | `agent/chat/agent.py` | 6 (router → 三路检索 → builder → llm) | RAG 对话，支持四级降级兜底，流式 SSE 输出 |
| **MeetingAgent** | `agent/meeting/agent.py` | 5 (llm → tool → llm → 并行三节点) | 语音→ASR识别→纠错润色→并行输出纪要/行动项/主题分段 |

每个 Agent 内部按 **state / nodes / prompts / tools** 独立拆分，节点通过闭包注入模型，提示词集中管理。

### RAG 检索层 (rag/)

| 模块 | 职责 |
|---|---|
| `embedding.py` | ChromaDB 向量库管理 + 硅基流动 Embedding 模型封装 |
| `retrieval_pipeline.py` | 多路检索编排：按意图类型切换检索策略 + 相邻块扩展 |
| `rerank.py` | BGE Reranker 重排序，提升召回相关性 |
| `query_optimizer.py` | 查询分类与改写 |
| `splitter.py` | 文档分块策略（文本/音频/图片） |
| `memory.py` | 对话记忆持久化（ChromaDB）+ 历史检索 |

### 业务服务层 (services/)

| 模块 | 职责 |
|---|---|
| `chat_service.py` | 对话服务编排（Agent 调用 + 流式输出 + 消息持久化） |
| `meeting_service.py` | 会议室生命周期管理：创建/加入/离开/WebSocket 信令 |
| `meeting_callback.py` | 会议结束回调链：音频合并 → OSS 上传 → Celery 转写任务 |
| `audio_service.py` | 多路 PCM 音频合并为 mp3（ffmpeg amix + adelay） |
| `realtime_asr.py` | DashScope 实时语音识别 WebSocket 客户端 |
| `dashscope_file_asr.py` | DashScope 文件级语音识别（异步提交 + 轮询结果） |
| `media_parser.py` | 硅基流式多模态解析（语音转录 + 图片 OCR） |
| `document_service.py` | 文档格式转换（Markitdown + 多格式支持） |

### 核心基础设施 (core/)

| 子模块 | 说明 |
|---|---|
| `core/database/` | SQLModel ORM（8 个模型）+ 会话管理 + LangGraph checkpoint |
| `core/cache/` | Redis 客户端封装（缓存 + Celery 消息队列） |
| `core/llm/` | LLM 模型工厂 + 流式客户端统一管理 |
| `core/storage/` | OSS / MinIO / 文件上传 |

## LangGraph 工作流

后端两个 Agent 均使用 LangGraph `StateGraph` 构建，通过 TypedDict + `operator.add` 管理状态、条件边实现分支路由。

### ChatAgent —— RAG 对话图

```
                        ┌──────────────────────────┐
                        │          START            │
                        └────────────┬─────────────┘
                                     │
                                     ▼
                        ┌──────────────────────────┐
                        │        router             │
                        │  意图分类 (结构化输出)      │
                        │  summary/action/topic/    │
                        │  detail/multi             │
                        └────────────┬─────────────┘
                                     │ _route_from_router
                    ┌────────────────┼────────────────┐
                    ▼                ▼                ▼ (if need_kb)
        ┌──────────────────┐ ┌──────────────────┐ ┌──────────────────┐
        │ meeting_retrieval│ │ memory_retrieval │ │knowledge_retrieval│
        │ 会议库多路检索     │ │ 历史记忆检索      │ │ 知识库检索        │
        │ + 相邻块扩展      │ │ + keyword 多查    │ │ + 多collection    │
        │ + BGE rerank     │ │ + BGE rerank     │ │ + BGE rerank     │
        └────────┬─────────┘ └────────┬─────────┘ └────────┬─────────┘
                 │                    │                    │
                 └────────────────────┼────────────────────┘
                                      │
                                      ▼
                        ┌──────────────────────────┐
                        │    context_builder        │
                        │  汇合三路检索结果           │
                        │  四级降级判定 (L0~L3)      │
                        └────────────┬─────────────┘
                                     │
                                     ▼
                        ┌──────────────────────────┐
                        │        llm_call           │
                        │  System + 上下文 + 历史    │
                        │  流式 SSE 输出             │
                        └────────────┬─────────────┘
                                     │
                                     ▼
                        ┌──────────────────────────┐
                        │           END             │
                        └──────────────────────────┘
```

**State: `ChatState`** (15 字段，`messages` 用 `operator.add` 追加)

| 节点 | 功能 |
|---|---|
| `router` | 用低温度 Router 模型做结构化意图分类，输出 intent/keywords/speaker/topic；异常时关键词兜底 |
| `meeting_retrieval` | 按 query_type 切换检索策略（概括性→summary/theme_seg，行动项→action_items，细节性→全量），BGE Reranker 重排序 |
| `memory_retrieval` | 从 ChromaDB 记忆库逐 keyword 检索 + 去重合并 |
| `knowledge_retrieval` | 逐 kb_id 多 collection 检索 + 重排序 |
| `context_builder` | 汇合三路结果，判定 fallback_level（L0 全命中 → L3 无回答），生成 user_notice |
| `llm_call` | 拼接 System 提示词 + 会议内容 + 知识库片段 + 历史记录 + 降级提示词，流式输出 |

### MeetingAgent —— 会议纪要生成图

```
                        ┌──────────────────────────┐
                        │          START            │
                        └────────────┬─────────────┘
                                     │
                                     ▼
                        ┌──────────────────────────┐
                        │        llm_call           │  ←──────┐
                        │  纠错润色 (with tools)     │         │
                        │  model.bind_tools([asr])  │         │
                        └────────────┬─────────────┘         │
                                     │ _should_continue      │
                          ┌──────────┴──────────┐            │
                          │ tool_calls?          │            │
                          └──────────┬──────────┘            │
                     Yes              │              No       │
                          ▼           │              ▼        │
          ┌──────────────────┐        │   ┌──────────────────┐│
          │    tool_node      │────────┘   │ [summary,        ││
          │  ASR 语音识别     │             │  get_action,     ││
          │  返回转录文本      │             │  theme_seg]      ││
          └──────────────────┘             │  并行三节点        ││
                                           └────────┬─────────┘│
                                                    │          │
                                     ┌──────────────┼──────┐   │
                                     ▼              ▼      ▼   │
                           ┌──────────┐  ┌──────────┐ ┌──────────┐
                           │ summary  │  │get_action│ │  theme   │
                           │ 会议总结  │  │ 行动项   │ │_seg      │
                           │          │  │ 提取     │ │ 主题分段 │
                           └────┬─────┘  └────┬─────┘ └────┬─────┘
                                │             │            │
                                └─────────────┼────────────┘
                                              │
                                              ▼
                                ┌──────────────────────────┐
                                │           END             │
                                └──────────────────────────┘
```

**State: `MeetingState`** (4 字段，`messages` 和 `result` 均用 `operator.add` 保证并行节点结果合并)

| 节点 | 功能 |
|---|---|
| `llm_call` | 模型绑定 ASR 工具，首轮输出 tool_calls 触发语音识别；二轮进行文本纠错润色 |
| `tool_node` | 执行 `asr` 工具：DashScope 文件级语音识别 → 转录文本格式化 |
| `summary` | 基于润色后文本 + 带时间戳的句子生成结构化会议总结 |
| `get_action` | 提取待办事项 / 行动项 / 责任人 |
| `theme_segmentation` | 按主题对会议内容进行分段，标注时间范围 |

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

- `main`：稳定分支（已并入最新重构）
- `chain_update`：主开发分支（活跃）

## License

毕业设计项目，仅供学习交流使用。

---

作者：xxlpossible (liang311818@163.com)
