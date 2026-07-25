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
├── backend/                           # FastAPI 后端
│   ├── main.py                        # 入口，监听 :31818
│   ├── settings.py                    # 三层配置（.env → DB config 表 → config.yaml）
│   ├── config.yaml                    # MySQL/Redis 连接配置
│   ├── pyproject.toml                 # uv 依赖管理
│   ├── uv.lock                        # 依赖锁文件
│   ├── api/                           # 路由层（/api/v1 前缀）
│   │   ├── router.py / schemas.py
│   │   └── v1/                        # auth / user / stt / chat_message / knowledge / meeting 等
│   ├── database/                      # 数据层
│   │   ├── models/                    # SQLModel 实体（User/Meeting/Transcription/Knowledge 等）
│   │   ├── schemas/                   # Pydantic 响应模型
│   │   ├── migrations/                # 数据库迁移脚本（幂等）
│   │   ├── base.py / service.py / check_points.py
│   ├── service/                       # 业务层
│   │   ├── llm_graph_service.py       # LangGraph 纪要生成主流程
│   │   ├── meeting_manager.py         # 多人会议房间管理
│   │   ├── audio_merger.py            # PCM→WAV→mp3 合并
│   │   ├── realtime_asr.py / rerank.py / ...
│   ├── utils/                         # 工具（JWT / OSS / MinIO / embedding / formatter 等）
│   ├── cache/                         # Redis 客户端封装
│   ├── task/                          # Celery 异步任务（转写/知识库解析）
│   ├── langchain_pipeline/            # 早期 LangGraph 原型（待清理，见下文）
│   └── test/                          # 端到端测试（auth / ownership / knowledge 等）
├── frontend/                          # Vue3 + Vite + TS 前端
│   ├── package.json                   # 依赖与脚本
│   ├── vite.config.ts                 # Vite 配置（proxy /api → :31818，含 ws）
│   ├── tsconfig.json / tsconfig.node.json
│   ├── index.html                     # Vite 入口
│   ├── .env.development               # VITE_API_TARGET=http://localhost:31818
│   ├── .env.production                # 生产环境（同源）
│   ├── TECH_STACK.md                  # 前端技术选型详述
│   └── src/
│       ├── api/                       # API 调用层（types.ts 为接口契约）
│       ├── stores/                    # Pinia 状态（auth / chat / knowledge / meeting）
│       ├── router/                    # Vue Router 路由配置
│       ├── views/                     # 页面（Login/Dashboard/Chat/MeetingRoom 等）
│       ├── layouts/                   # 布局（BlankLayout / DefaultLayout）
│       ├── components/                # 通用组件
│       ├── composables/               # 组合式函数（useWebRTC/useChatSSE 等）
│       ├── styles/                    # SCSS 设计 Token + Element Plus 主题
│       ├── utils/                     # 工具（markdown 渲染等）
│       ├── App.vue / main.ts
├── design/                            # 共享设计资源
│   ├── mockups/                       # 6 个页面 HTML 设计原型
│   │   ├── login.html / dashboard.html / meeting-room.html
│   │   ├── meeting-detail.html / knowledge-base.html / ai-chat.html
│   ├── api-needs.md                   # 接口需求
│   ├── design-system.md               # 温暖工作室设计系统
│   └── overview.md                    # 设计总览
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
#    复制示例配置并填写实际值（DashScope API Key、MySQL/Redis 连接、JWT 密钥、OSS 配置等）
cp config.yaml config.yaml   # 按实际 MySQL/Redis 地址修改
# 创建 .env 文件，至少包含：
#   DASHSCOPE_API_KEY=sk-xxx
#   JWT_SECRET_KEY=your-secret
#   OPENAI_API_KEY=sk-xxx（若使用 OpenAI 兼容接口）
#   EMBEDDINGS_API_KEY=xxx
#   MINIO_ENDPOINT / MINIO_ACCESS_KEY / MINIO_SECRET_KEY（如使用 MinIO）

# (4) 执行数据库迁移（幂等脚本，按需执行）
PYTHONPATH=. python -m database.migrations.add_meeting_table
PYTHONPATH=. python -m database.migrations.add_knowledge_file_state
# 其他迁移脚本见 database/migrations/ 目录

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

## 设计资源

| 资源 | 路径 | 说明 |
|---|---|---|
| 设计系统 | `design/design-system.md` | 温暖工作室配色（暖石灰 + 琥珀暖光 #F5B400）、字体、组件规范 |
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

## 待清理事项

- `backend/langchain_pipeline/`：早期 LangGraph 原型，已被 `service/llm_graph_service.py` 替代，待确认无引用后清理

## 分支说明

- `main`：稳定分支
- `chain_update`：主开发分支（当前活跃）

## License

毕业设计项目，仅供学习交流使用。

---

作者：邓炳山 (3260406958@qq.com)
