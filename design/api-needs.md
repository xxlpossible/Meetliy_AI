# Meeting Agent 前端 — 新增接口需求文档

> 以下接口为前端 UI 设计所需但当前后端尚未实现，请在后续开发中补充。

---

## 1. 主动离开会议

### 当前现状
用户断开 WebSocket 后自动触发 `meeting_manager.remove_participant()`，仅最后一人离开会触发 `auto_end_meeting()`。但无法在不关闭浏览器的情况下主动、优雅地离开。

### 新增接口

```
POST /api/v1/meeting/{meeting_id}/leave
Authorization: Bearer {access_token}
```

**行为差异：**
- 如果离开者是主持人且会议仍有其他人 → 会议继续，主持人自动转移给下一位参会者
- 如果离开者是最后一人 → 会议自动结束（与当前 `auto_end_meeting` 逻辑相同）

**响应格式：**
```json
{
  "status_code": 200,
  "status_message": "ok",
  "data": {
    "action": "left" | "transfer_host" | "ended",
    "new_host_user_id": 42  // 仅在 transfer_host 时返回
  }
}
```

---

## 2. 获取会议当前转写上下文（用于临时对话）

### 当前现状
✅ `POST /api/v1/chat/temp/question` 已存在。前端需在本地维护转写缓冲区（累积拼接 WS transcript 消息），用户提问时作为 `text` 传入。

### 备选方案（可选实现）

如果前端不想维护本地缓冲区，可新增：

```
GET /api/v1/meeting/{meeting_id}/context
Authorization: Bearer {access_token}
```

**响应格式：**
```json
{
  "status_code": 200,
  "data": {
    "meeting_id": "xxx",
    "current_text": "Speaker_0: 今天讨论...\nSpeaker_1: ...",
    "duration_seconds": 1800
  }
}
```

> 📝 **当前方案**：前端直接拼接 WS transcript，无需此接口。

---

## 3. 参会者列表（已确认存在）

✅ `GET /api/v1/meeting/{meeting_id}/participants` 已实现，返回活跃参会者列表。

---

## 4. AI 对话 WebSocket（已确认存在）

✅ `WS /api/v1/chat/ws/chat?task_id=xxx&token=xxx` 已实现。

**消息协议：**
| 方向 | 格式 | 说明 |
|------|------|------|
| C→S | `{"text": "用户问题"}` | 发送问题 |
| C→S | `{"type": "close"}` | 主动断开 |
| S→C | `{"status": "start", "question": "问题"}` | 开始生成 |
| S→C | `{"status": "streaming", "text": "token片段"}` | 流式推送 |
| S→C | `{"status": "done", "text": "完整回答"}` | 生成完成 |
| S→C | `{"status": "error", "message": "...", "partial": "已生成"}` | 错误 |

---

## 5. 会议录音文件上传

### 当前现状
✅ `POST /api/v1/audio/start_task` 已存在，支持上传录音文件。

### 补充说明
dashboard 中"上传录音"按钮调用此接口，上传成功后跳转到会议详情页（status=解析中）。

---

## 6. 加入会议（UI 变更，接口已有）

### 当前现状
✅ `POST /api/v1/meeting/{meeting_id}/join` 已存在。

### UI 变更
dashboard 页面"创建会议"按钮旁新增"加入会议"按钮，点击后弹出模态框输入会议 ID。

---

## 总结

需要后端新增的接口：
- `POST /api/v1/meeting/{meeting_id}/leave` — 主动离开会议（支持主持人转移）

其余功能均已由现有接口覆盖：
- 临时对话 → `POST /temp/question`（前端拼接 text）
- 参会者列表 → `GET /meeting/{id}/participants`
- AI 流式对话 → `WS /ws/chat`
- 录音上传 → `POST /audio/start_task`
- 加入会议 → `POST /meeting/{id}/join`

📅 文档创建时间：2026-07-11 | 最后更新：2026-07-11
