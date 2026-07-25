# AI对话WebSocket连接逻辑自检报告

## 执行时间
2026-07-22

## 自检范围
- `frontend/src/views/ChatView.vue` — AI对话主页面
- `frontend/src/composables/useChatWebSocket.ts` — WebSocket连接管理
- `frontend/src/stores/chat.ts` — 会话状态管理

## 自检结果

### ✅ 核心逻辑已正确实现

| 要求 | 实现位置 | 状态 |
|------|---------|------|
| 新建对话不立即建WS连接 | `handleStartNewChat` (L86-90) | ✅ |
| 切换会话不立即建WS连接 | `selectSession` (L51-57) | ✅ |
| 发送消息时检测WS连接 | `handleSendMessage` (L120-132) | ✅ |
| 连接活跃则直接发消息 | `handleSendMessage` (L134) | ✅ |
| 离开页面主动断开 | `onBeforeRouteLeave` + `onUnmounted` | ✅ |

### ⚠️ 边界问题已修复

**问题1：切换会话时可能漏断连接**
- 原代码：`if (chatWs.connected.value) { chatWs.disconnect() }`
- 修复：直接调用 `chatWs.disconnect()`（CONNECTING状态下也要断开）

**问题2：会话删除时可能漏断连接**
- 原代码：`if (oldSession && !newSession && chatWs.connected.value)`
- 修复：去掉 `connected.value` 条件

**问题3：路由离开/组件卸载时可能漏断连接**
- 原代码：`if (chatWs.connected.value) { chatWs.disconnect() }`
- 修复：直接调用 `chatWs.disconnect()`

## 修改文件
- `frontend/src/views/ChatView.vue` — 4处修改

## 验证
- TypeScript 类型检查：通过（零错误）
- 逻辑闭环：disconnect() 内部有安全判断，多次调用无害
