# Meetily 前端技术选型方案

> 基于 `design/` 设计系统、`backend/` 全部 API 接口、`frontend_test/` 测试页代码的综合分析，制定的前端技术栈选型。

---

## 一、项目需求总览

通过分析设计稿和后端接口，前端需要实现 **6 个核心页面** 和 **3 套实时通信机制**：

| 页面 | 核心功能 | 通信方式 |
|------|----------|----------|
| 登录/注册 | 双Token鉴权、表单校验 | HTTP REST |
| 会议仪表盘 | 会议列表、统计卡片、创建/加入/上传 | HTTP REST |
| 实时会议室 | 多人WebRTC互听、实时转写、AI临时对话 | WebSocket + WebRTC + SSE |
| 会议纪要详情 | Markdown渲染、行动项、时间戳转写 | HTTP REST |
| 知识库管理 | 文件上传、异步解析轮询、分块查看 | HTTP REST + 轮询 |
| AI深度对话 | WebSocket流式对话、知识库检索、引用来源 | WebSocket + HTTP REST |

**技术难点**：
1. WebRTC Mesh 网络（≤4人浏览器直连，信令通过 WS 传递，需处理 glare/ICE候选缓存/竞态）
2. 双 WebSocket 并发（STT实时转写 WS + AI对话 WS）
3. PCM 音频采集与传输（AudioContext + ScriptProcessor → Blob → WS）
4. 流式输出渲染（SSE 和 WebSocket 两种流式协议）
5. 高度定制化的"温暖工作室"设计系统（非通用UI框架默认风格）

---

## 二、技术栈总览

| 类别 | 选型 | 版本 |
|------|------|------|
| **框架** | Vue 3 (Composition API) | ^3.5 |
| **构建工具** | Vite | ^6.0 |
| **语言** | TypeScript | ^5.6 |
| **UI 组件库** | Element Plus | ^2.8 |
| **样式方案** | SCSS + CSS Variables + Element Plus 主题定制 | - |
| **状态管理** | Pinia | ^2.2 |
| **路由** | Vue Router 4 | ^4.4 |
| **HTTP 客户端** | Axios | ^1.7 |
| **包管理** | npm | ^10.8 |
| **Markdown 渲染** | markdown-it + highlight.js | - |
| **代码规范** | ESLint + Prettier + Stylelint | - |

---

## 三、逐项选型理由

### 1. 框架：Vue 3 (Composition API)

**选择理由**：

- **Composition API 天然适配复杂状态逻辑**：本项目有大量复杂的状态逻辑——WebRTC PeerConnection 管理（Map 存储、ICE候选缓存、连接状态追踪）、双 WebSocket 并发管理、实时转写缓冲区（finalTranscripts + interimBySpeaker）。用 Composition API 可以将这些逻辑封装为 `useWebRTC()`、`useMeetingWS()`、`useTranscription()` 等 composable，比 Options API 的 `data/methods/mixins` 组织方式清晰得多。

- **与测试页代码的延续性**：`frontend_test/meeting.js` 已经实现了完整的 WebRTC Mesh + WS 逻辑。Vue 3 的 Composition API 可以将这些命令式代码优雅地重构为响应式 composable，迁移成本最低。

- **TypeScript 原生支持**：Vue 3 从底层用 TS 重写，`<script setup lang="ts">` 提供完整的类型推断。后端接口的请求/响应类型可以统一定义，配合 Axios 拦截器实现端到端类型安全。

- **生态成熟、中文社区活跃**：Vue Router、Pinia、Vite 都是 Vue 团队官方维护，版本兼容性有保障；中文文档完善，毕设答辩时技术资料充足。

- **包体积小**：Vue 3 运行时仅 ~34KB (gzip)，配合 Vite 的 tree-shaking，首屏加载快。

**对比 React 的取舍**：React 的 Hooks 也能处理复杂逻辑，但 React 的生态碎片化严重（状态管理有 Redux/Zustand/Jotai/Recoil 多种选择），对毕设项目来说决策成本太高。Vue 3 的官方全家桶（Router + Pinia）省去了选型烦恼。

---

### 2. 构建工具：Vite 6

**选择理由**：

- **闪电般的 HMR**：Vite 基于原生 ESM 的 dev server，冷启动 < 1秒，HMR 更新 < 50ms。开发实时会议室页面时，频繁修改 WS 消息处理逻辑能立即看到效果，不需要等 Webpack 重新编译。

- **Vue 官方推荐**：`@vitejs/plugin-vue` 是 Vue 团队维护的官方插件，`<script setup>`、`<style scoped>`、HMR 体验一流。

- **开箱即用的 TypeScript 支持**：不需要额外配置 `ts-loader`，Vite 内置 esbuild 处理 TS，编译速度比 tsc 快 10-100 倍。

- **生产构建优化**：Rollup 打包 + 自动代码分割，`build.rollupOptions.output.manualChunks` 可以将 Element Plus、Markdown 渲染库等第三方依赖单独打包，减少首屏加载体积。

- **环境变量管理**：`import.meta.env.VITE_API_BASE` 原生支持，开发/生产环境切换零配置。

---

### 3. 语言：TypeScript

**选择理由**：

- **后端接口类型对齐**：后端使用 FastAPI + Pydantic，响应格式统一为 `{ status_code, status_message, data }`。用 TS 定义对应的 `interface ApiResponse<T>` 和各接口的请求/响应类型，可以在编译期捕获参数不匹配的低级错误。

- **WebRTC 信令类型安全**：会议模式的 WS 消息有多种类型（transcript/signal/participant_joined/left/speech_started/stopped/participants_list/meeting_ended），用 TS 的字面量联合类型 + switch 判断，漏处理一种消息类型编辑器会直接报红。

- **重构安全**：毕设开发过程中需求可能变动，TS 的类型系统让重构时能立即发现影响范围，不用全局搜索担心遗漏。

---

### 4. UI 组件库：Element Plus + 主题定制

**这是最关键的选型决策**，我来说清楚为什么选 Element Plus 以及如何处理它与设计系统的冲突。

**选择 Element Plus 的理由**：

- **复杂表单组件开箱即用**：登录注册需要表单校验（用户名3-20位字母开头、密码6-20位含字母数字），知识库上传需要拖拽上传组件，会议详情需要对话框确认操作。Element Plus 的 `ElForm` + `ElFormItem` + 校验规则、`ElUpload` 拖拽上传、`ElDialog`、`ElMessageBox` 这些组件自己从零写至少多花 3 天。

- **数据展示组件成熟**：会议列表的分页、知识库文件列表的排序/筛选、AI对话历史的会话列表，这些用 `ElTable` + `ElPagination` + `ElScrollbar` 组合就能快速实现。

- **反馈组件完善**：`ElMessage`（操作提示）、`ElNotification`（会议结束通知）、`ElLoading`（文件上传/纪要生成中）覆盖了所有反馈场景。

- **中文生态最成熟**：Element Plus 是 Element UI 的 Vue 3 重写版，中文文档完整，国内使用率最高，毕设答辩时评委熟悉度高。

**与设计系统的冲突及解决方案**：

设计系统的"温暖工作室"风格（暖石灰 + 琥珀暖光 + Noto Serif SC 衬线标题）与 Element Plus 默认的蓝色科技风差异较大。处理方式：

```scss
// styles/element-theme.scss — 覆盖 Element Plus CSS 变量
:root {
  // 品牌色：琥珀暖光替代默认蓝色
  --el-color-primary: #F5B400;
  --el-color-primary-light-3: #FFD046;
  --el-color-primary-light-5: #FFE089;
  --el-color-primary-light-7: #FFF3D6;
  --el-color-primary-light-8: #FFFBF0;
  --el-color-primary-light-9: #FFFBF0;
  --el-color-primary-dark-2: #D99A00;

  // 语义色对齐设计系统
  --el-color-success: #10B981;
  --el-color-danger: #EF4444;
  --el-color-warning: #F59E0B;
  --el-color-info: #3B82F6;

  // 文字色对齐暖石灰色阶
  --el-text-color-primary: #292522;
  --el-text-color-regular: #44403A;
  --el-text-color-secondary: #787165;
  --el-text-color-placeholder: #A89F8C;

  // 边框/背景对齐
  --el-border-color: #E8E4DC;
  --el-border-color-light: #F3F1ED;
  --el-bg-color: #FFFFFF;
  --el-bg-color-page: #FAF9F7;
  --el-fill-color-light: #F3F1ED;

  // 圆角
  --el-border-radius-base: 8px;
  --el-border-radius-small: 6px;

  // 字体
  --el-font-family: 'Inter', 'PingFang SC', 'Microsoft YaHei', sans-serif;
}
```

**策略**：Element Plus 负责交互复杂的基础组件（表单、上传、对话框、消息提示），设计系统中的特色组件（会议卡片、转写行、聊天气泡、参与者胶囊、状态徽章）用自定义 SCSS 组件实现。这样既利用了 Element Plus 的工程效率，又保证了设计稿的视觉还原度。

**对比其他方案**：
- *Naive UI*：TS 更友好、主题定制更灵活，但中文社区小、组件数量少（无 Upload 拖拽上传），毕设风险高。
- *Ant Design Vue*：组件丰富但包体积大（~1.2MB），且设计风格偏企业后台，与"温暖工作室"差异更大。
- *纯 Tailwind + Headless UI*：设计还原度最高，但表单校验、文件上传等复杂组件需要全部手写，开发周期至少多一倍。

---

### 5. 样式方案：SCSS + CSS Variables + Element Plus 主题定制

**选择理由**：

- **SCSS 管理设计 Token**：设计系统定义了完整的色彩/字体/间距/圆角/阴影体系，用 SCSS 变量统一管理，`@mixin` 封装复用样式（如卡片悬停效果、状态徽章）。

- **CSS Variables 运行时主题**：设计系统的色彩用 CSS Custom Properties 定义，方便未来扩展暗色模式（设计稿已预留响应式断点）。

- **`<style scoped>` 组件级样式隔离**：Vue SFC 的 scoped 样式避免全局污染，每个页面的特色组件样式独立管理。

- **设计 Token 双层架构**：
  ```
  design-system.md 定义的设计 Token
       ↓ 转换为
  SCSS 变量 ($color-amber-400 等)  ←  编译时使用（mixin/函数）
       ↓ 同时输出为
  CSS 变量 (--color-amber-400 等)  ←  运行时使用（组件内引用）
  ```

---

### 6. 状态管理：Pinia

**选择理由**：

- **Vue 官方推荐**：Pinia 是 Vue 3 的官方状态管理库，替代 Vuex，API 更简洁，TS 支持更好。

- **本项目的状态需求**：
  - `useAuthStore`：access_token / refresh_token / 用户信息 / 登录登出 / 自动刷新
  - `useMeetingStore`：当前会议信息 / 参与者列表 / 转写记录 / 会议状态
  - `useChatStore`：AI对话会话列表 / 当前会话消息 / 流式输出状态
  - `useKnowledgeStore`：知识库列表 / 文件列表 / 上传状态

- **Composition API 风格**：Pinia store 用 `defineStore('auth', () => { ... })` 定义，与组件内的 Composition API 写法完全一致，学习成本几乎为零。

- **DevTools 集成**：Pinia 与 Vue DevTools 深度集成，可以时间旅行调试状态变化，排查 WS 消息处理问题非常方便。

---

### 7. 路由：Vue Router 4

**选择理由**：

- **Vue 官方路由库**：与 Vue 3 深度集成，`<router-view>` + `<router-link>` 组件化路由。

- **路由守卫实现鉴权**：
  ```ts
  router.beforeEach((to) => {
    const auth = useAuthStore()
    if (to.meta.requiresAuth && !auth.isLoggedIn) {
      return { name: 'login', query: { redirect: to.fullPath } }
    }
  })
  ```

- **懒加载优化首屏**：6 个页面用动态 import 懒加载，首屏只加载登录页，会议室等重组件按需加载。

**路由结构设计**：
```
/login                          → LoginView (公开)
/dashboard                      → DashboardView (需登录)
/meeting/room/:meetingId        → MeetingRoomView (需登录)
/meeting/detail/:taskId         → MeetingDetailView (需登录)
/knowledge                      → KnowledgeView (需登录)
/chat                           → ChatView (需登录)
/chat/:taskId                   → ChatView (需登录，指定会议)
```

---

### 8. HTTP 客户端：Axios

**选择理由**：

- **请求/响应拦截器实现双Token自动刷新**：
  ```ts
  // 请求拦截器：自动附加 access_token
  instance.interceptors.request.use(config => {
    const auth = useAuthStore()
    if (auth.accessToken) {
      config.headers.Authorization = `Bearer ${auth.accessToken}`
    }
    return config
  })

  // 响应拦截器：401 时自动用 refresh_token 换新 token 重试
  instance.interceptors.response.use(
    response => response,
    async error => {
      if (error.response?.status === 401 && !error.config._retry) {
        error.config._retry = true
        const auth = useAuthStore()
        await auth.refreshAccessToken()
        error.config.headers.Authorization = `Bearer ${auth.accessToken}`
        return instance(error.config)
      }
      return Promise.reject(error)
    }
  )
  ```
  这套逻辑在后端记忆中已明确要求（"401时用refresh_token调/auth/refresh换新token重试"），Axios 拦截器是最干净的实现方式。

- **取消请求**：`AbortController` 支持取消未完成的请求，切换页面时取消 pending 请求避免内存泄漏。

- **请求并发**：`Promise.all` + Axios 可以并行请求多个接口（如仪表盘同时加载会议列表和统计数据）。

---

### 9. 包管理：npm

**选择理由**：

- **Node.js 内置**：npm 随 Node.js 安装，无需额外安装包管理器，环境搭建最简单。

- **生态最广**：所有 npm 包都支持 npm 安装，不存在 pnpm/yarn 的兼容性问题。

- **package-lock.json 保证可重现构建**：锁定依赖版本，毕设答辩环境与开发环境一致。

- **与 Vite 无缝配合**：Vite 官方文档所有示例都基于 npm。

**对比 pnpm**：pnpm 的磁盘节省和速度优势在毕设这种中小项目中不明显，而 npm 的通用性更适合毕设评审环境。

---

### 10. Markdown 渲染：markdown-it + highlight.js

**选择理由**：

- 会议纪要详情页和 AI 对话气泡都需要渲染 Markdown 内容（后端返回的纪要是 Markdown 格式）。

- **markdown-it**：插件化架构，可以按需启用表格、代码高亮、链接等特性；比 marked 更安全（内置 XSS 防护）；比 vue-markdown 更轻量（不依赖完整 Vue 实例）。

- **highlight.js**：代码语法高亮，支持 190+ 语言，按需引入语言包减小体积。

- **流式渲染优化**：AI 对话的 WebSocket 流式输出需要边接收边渲染。markdown-it 的 `parse()` 是同步的，配合 `requestAnimationFrame` 节流渲染（每 100ms 渲染一次而非每个 token 都渲染），避免高频更新导致卡顿。

---

### 11. 代码规范：ESLint + Prettier + Stylelint

**选择理由**：

- **ESLint**：`@vue/eslint-config-typescript` 官方配置，检查 Vue SFC + TS 语法错误，强制 `no-unused-vars`、`no-explicit-any` 等规则。

- **Prettier**：统一代码格式化，团队协作（即使是单人毕设，也方便未来扩展）风格一致。

- **Stylelint**：SCSS 代码规范，禁止硬编码颜色（必须使用设计 Token 变量），保证设计系统一致性。

---

## 四、项目目录结构

```
frontend/
├── public/                     # 静态资源 (favicon 等)
├── src/
│   ├── api/                    # API 接口层
│   │   ├── modules/            # 按模块拆分
│   │   │   ├── auth.ts         # 登录/注册/刷新
│   │   │   ├── meeting.ts      # 会议 CRUD
│   │   │   ├── audio.ts        # 录音上传/转写列表/状态查询
│   │   │   ├── knowledge.ts    # 知识库上传/状态/分块
│   │   │   └── chat.ts         # AI 对话 CRUD
│   │   ├── types.ts            # 接口请求/响应类型定义
│   │   └── request.ts          # Axios 实例 + 拦截器
│   ├── assets/                 # 静态资源 (图片/字体)
│   ├── components/             # 通用组件
│   │   ├── common/             # 基础组件 (AppButton, StatusBadge...)
│   │   ├── meeting/            # 会议相关 (TranscriptLine, ParticipantPill...)
│   │   ├── chat/               # 对话相关 (ChatBubble, StreamingCursor...)
│   │   └── knowledge/          # 知识库相关 (FileCard, UploadZone...)
│   ├── composables/            # 组合式函数
│   │   ├── useAuth.ts          # 鉴权逻辑
│   │   ├── useWebRTC.ts        # WebRTC Mesh 管理
│   │   ├── useMeetingWS.ts     # 会议 WS 连接
│   │   ├── useChatWS.ts        # AI 对话 WS 连接
│   │   ├── useAudioCapture.ts  # 麦克风采集 + PCM 转换
│   │   ├── useTranscription.ts # 转写缓冲与渲染
│   │   └── useStreamingText.ts # SSE/WS 流式文本渲染
│   ├── layouts/                # 布局组件
│   │   ├── DefaultLayout.vue   # 带顶部导航的默认布局
│   │   └── BlankLayout.vue     # 空白布局 (登录页)
│   ├── router/                 # 路由配置
│   │   └── index.ts
│   ├── stores/                 # Pinia 状态管理
│   │   ├── auth.ts
│   │   ├── meeting.ts
│   │   ├── chat.ts
│   │   └── knowledge.ts
│   ├── styles/                 # 全局样式
│   │   ├── design-tokens.scss  # 设计系统 Token (SCSS 变量)
│   │   ├── element-theme.scss  # Element Plus 主题覆盖
│   │   ├── global.scss         # 全局重置 + 基础样式
│   │   └── mixins.scss         # SCSS mixins (卡片悬停等)
│   ├── views/                  # 页面组件
│   │   ├── LoginView.vue
│   │   ├── DashboardView.vue
│   │   ├── MeetingRoomView.vue
│   │   ├── MeetingDetailView.vue
│   │   ├── KnowledgeView.vue
│   │   └── ChatView.vue
│   ├── App.vue
│   └── main.ts
├── .eslintrc.cjs
├── .prettierrc
├── index.html
├── package.json
├── tsconfig.json
├── vite.config.ts
└── TECH_STACK.md               # 本文档
```

---

## 五、关键技术实现策略

### 5.1 WebRTC Mesh 迁移

`frontend_test/meeting.js` 中的 WebRTC 逻辑迁移为 `composables/useWebRTC.ts`：

- **响应式 PeerConnection 管理**：`reactive(new Map())` 存储 peer 连接，连接状态变化自动触发 UI 更新。
- **ICE 候选缓存**：保留原有 `pendingCandidates` 机制，处理 offer 到达前缓存的 ICE 候选。
- **glare 避免**：保留 `myUserId < targetUserId` 的发起方判断逻辑。
- **信令通道复用**：WebRTC 信令继续走 STT WS 的 `signal` 消息类型，不单独开 WS。

### 5.2 双 WebSocket 管理

- **STT WS**（`/audio/ws/realtime`）：会议模式，同时传输音频(bytes)和信令(text)。
- **AI 对话 WS**（`/chat/ws/chat`）：流式 AI 回答，`start → streaming×N → done`。
- **生命周期管理**：在 `onUnmounted` 中确保关闭连接，避免内存泄漏。Pinia store 中不直接持有 WS 实例（WS 不可序列化），用 composable 管理。

### 5.3 PCM 音频采集

迁移 `float32ToInt16` 和 `ScriptProcessor` 逻辑到 `useAudioCapture.ts`：
- `getUserMedia` 获取麦克风流（16kHz、单声道、回声消除）。
- `AudioContext + ScriptProcessor` 采集 PCM 数据。
- 静音切换通过 `audioTrack.enabled = false` 实现（不发空数据）。

### 5.4 流式渲染优化

- **WebSocket 流式**（AI 对话）：每个 `streaming` 消息追加文本到响应式变量，`markdown-it` 渲染用 `requestAnimationFrame` 节流。
- **SSE 临时对话**：`fetch + ReadableStream` 消费 SSE 流（比 EventSource 更灵活，支持 POST 请求体）。

### 5.5 Token 自动刷新

Axios 响应拦截器统一处理 401：
1. 捕获 401 响应（排除 `/auth/refresh` 自身）。
2. 用 `refresh_token` 调 `/auth/refresh` 获取新双 Token。
3. 用新 `access_token` 重试原请求。
4. 刷新失败则跳转登录页。
5. 并发 401 时用 Promise 队列确保只刷新一次。

---

## 六、性能与可访问性

### 性能优化
- **路由懒加载**：`() => import('@/views/MeetingRoomView.vue')`，首屏只加载登录页。
- **组件按需引入**：Element Plus 用 `unplugin-vue-components` + `unplugin-auto-import` 自动按需导入，减小包体积。
- **Markdown 渲染节流**：流式输出用 `requestAnimationFrame` 节流，避免每个 token 都触发 DOM 更新。
- **虚拟滚动**：转写记录超长时用虚拟滚动（`@vueuse/core` 的 `useVirtualList`）。

### 可访问性
- 设计系统已定义 WCAG AA 对比度要求（≥ 4.5:1），暖石灰 + 琥珀色组合满足标准。
- 所有交互元素支持键盘操作（`tabindex` + `@keydown.enter`）。
- 状态信息配合图标和文字，不仅依赖颜色（如"解析中"用脉冲点 + 文字 + 黄色背景）。
- 触摸目标 ≥ 44px（设计系统已规范）。

---

## 七、开发环境配置

### 环境变量
```bash
# .env.development
VITE_API_BASE=http://localhost:31818
VITE_WS_BASE=ws://localhost:31818

# .env.production
VITE_API_BASE=          # 同源，空值
VITE_WS_BASE=           # 同源，空值
```

### Vite 代理配置
```ts
// vite.config.ts
export default defineConfig({
  plugins: [vue(), AutoImport({ resolvers: [ElementPlusResolver()] })],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:31818',
        changeOrigin: true,
        // WebSocket 代理
        ws: true,
      },
    },
  },
})
```

### 启动命令
```bash
npm install          # 安装依赖
npm run dev          # 开发服务器 (localhost:5173)
npm run build        # 生产构建
npm run preview      # 预览构建结果
npm run lint         # 代码检查
npm run type-check   # 类型检查
```

---

## 八、选型对比总结

| 决策点 | 选择 | 核心理由 | 放弃的方案 |
|--------|------|----------|------------|
| 框架 | Vue 3 | Composition API 适配复杂 WS/WebRTC 逻辑；官方全家桶减少选型成本 | React (生态碎片化) |
| 构建 | Vite 6 | HMR 极快；Vue 官方推荐；TS 零配置 | Webpack (启动慢) |
| UI库 | Element Plus | 表单/上传/对话框开箱即用；中文生态成熟 | Naive UI (组件少); 纯 Tailwind (开发慢) |
| 状态 | Pinia | Vue 官方推荐；Composition API 风格 | Vuex (API 过时) |
| HTTP | Axios | 拦截器实现双Token自动刷新最干净 | fetch (拦截器需手写) |
| 样式 | SCSS + CSS Variables | 设计 Token 双层管理；主题定制灵活 | Tailwind (与设计系统Token体系冲突) |
| 包管理 | npm | Node 内置；通用性最强 | pnpm (优势在中小项目不明显) |

---

**方案制定时间**：2026-07-12  
**制定人**：前端开发工程师 - 像素匠
