# Meeting Agent UI 设计说明

## 设计理念：温暖工作室 (Warm Workspace)

告别冰冷的科技蓝，拥抱自然材质色调与编辑排版风格。为知识工作者打造的精致数字工作空间。

---

## 🎨 设计亮点

### 1. 独特的品牌色彩
- **暖石灰 (Warm Stone)**：替代纯灰，营造温柔、自然的工作氛围
- **琥珀暖光 (Amber Glow)**：替代通用蓝紫，象征智慧与洞察
- **深暖棕品牌区**：登录页左侧面板区别于传统的纯色

### 2. 编辑排版风格
- **中文衬线字体** (Noto Serif SC)：用于标题，赋予权威感与审美价值
- **Inter 无衬线字体**：用于正文，确保现代感与可读性
- **JetBrains Mono 等宽字体**：用于时间戳和技术数据

### 3. 温暖的交互细节
- 按钮 hover 上浮 + 琥珀色光晕
- 卡片悬停浮现琥珀色顶边
- 脉冲动画的说话指示点
- 实时转写行的滑入动画

---

## 📁 设计文件清单

| 文件 | 说明 |
|------|------|
| `design-system.md` | 设计系统完整规范（色彩、字体、间距、组件） |
| `mockups/login.html` | 登录/注册页面 |
| `mockups/dashboard.html` | 主仪表盘（会议列表） |
| `mockups/meeting-room.html` | 实时会议室（转写 + AI 面板） |
| `mockups/meeting-detail.html` | 会议纪要详情页 |
| `mockups/knowledge-base.html` | 知识库管理页 |
| `mockups/ai-chat.html` | AI 深度对话页 |

---

## 🔗 API 对接说明

所有页面均基于现有后端 API 设计，关键对接点：

### 认证
- 登录/注册：`POST /api/v1/auth/login` · `register`
- 鉴权：请求头 `Authorization: Bearer {access_token}`

### 会议流程
- 创建：`POST /api/v1/meeting/create`
- WS 连接：`/api/v1/audio/ws/realtime?token=xxx&meeting_id=xxx`
- 结束：`POST /api/v1/meeting/{id}/end`
- 状态轮询：`POST /api/v1/audio/getTask/status`

### 转写结果
- 列表：`POST /api/v1/audio/list`
- 详情：`POST /api/v1/audio/getTask/status`

### 知识库
- 上传：`POST /api/v1/knowledge/upload`
- 状态查询：`GET /api/v1/knowledge/file_state?file_id=xxx`
- 分块查看：`GET /api/v1/knowledge/get_file_chunks?file_id=xxx`

### AI 对话
- **会后对话**：`WS /api/v1/chat/ws/chat?task_id=xxx&token=xxx`（WebSocket 流式，替代已弃用的 SSE POST）
- **会中临时对话**：`POST /api/v1/chat/temp/question`（HTTP + SSE，基于实时转写内容，无知识库检索）
- WebSocket 消息协议：`start` → `streaming`×N → `done` / `error`
- 临时对话请求体：`{text: 转写内容, question: 用户问题, history: 对话历史}`
- 新增接口需求：`api-needs.md`（主动离开会议、获取会议上下文）

---

## ♿ 可访问性考虑

- 文字与背景对比度 ≥ 4.5:1（WCAG AA）
- 焦点状态有明显视觉指示
- 所有交互元素支持键盘操作
- 状态信息不仅依赖颜色（配合图标和文字）
- 触摸目标 ≥ 44px

---

## 📱 响应式策略

- 桌面端：完整双栏布局（转写 + AI 面板）
- 平板端：侧边栏收缩
- 移动端：单栏布局，侧边栏隐藏

---

*设计完成时间：2026-07-11*
*设计师：UI Designer - 像素君*
