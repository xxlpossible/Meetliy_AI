// ============================================================
// API 类型定义 — 对齐后端 FastAPI 接口
// ============================================================

/** 后端统一响应格式 */
export interface ApiResponse<T = any> {
  status_code: number
  status_message: string
  data: T
}

/** 双 Token 数据 */
export interface TokenData {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in: number
}

/** 用户信息 */
export interface UserInfo {
  id: number
  username: string
}

// ---- 认证 ----
export interface LoginRequest {
  username: string
  password: string
}

export interface RegisterRequest {
  username: string
  password: string
  confirmPassword: string
}

// ---- 会议 ----
/** 会议状态枚举 */
export const MeetingStatus = {
  ACTIVE: 0,           // 会议正在进行中
  END_AND_ANALYZE: 1,  // 会议结束，后台解析中
  FINISH: 2,           // 内容解析完成
  ERROR: -1,           // 会议解析异常
} as const

export interface MeetingItem {
  id: string
  meeting_name: string
  host_user_id: number
  status: number // 0进行中 1结束解析中 2解析完成 -1异常
  task_id: string | null
  need_summary: boolean | null // 是否需要生成纪要（null 表示旧数据，默认为 true）
  create_time: string | null
}

export interface MeetingListData {
  data: MeetingItem[]
  total: number
}

export interface Participant {
  id: number
  name: string
}

export interface CreateMeetingData {
  meeting_id: string
  meeting_name: string
  host_user_id: number
  need_summary: boolean
}

export interface JoinMeetingData {
  meeting_id: string
  meeting_name: string
  host_user_id: number
  is_host: boolean
  participants: Participant[]
}

// ---- 转写/录音 ----
export interface TranscriptionItem {
  id: string
  task_name: string | null
  user_ids: number[]
  status: number // 0进行中 1完成 -1失败
  task_result: any
  file_url: string | null
  create_time: string | null
}

export interface TranscriptionListData {
  data: TranscriptionItem[]
  total: number
}

export interface TaskStatusItem {
  id: string
  status: number
  result: any
}

// ---- 会议状态轮询 ----
export interface MeetingStatusItem {
  meeting_id: string
  meeting_name: string
  status: number
  status_label: string
  task_id: string | null
  need_summary: boolean | null
}

// ---- 会议解析结果 ----
export interface MeetingResultData {
  meeting_id: string
  meeting_name: string
  task_id: string
  task_name: string | null
  status: number
  task_result: any
  file_url: string | null
  realtime_asr_text: string[] | null  // 实时转录文本行列表
  need_summary: boolean              // 是否需要生成纪要
  create_time: string | null
  update_time: string | null
}

// ---- 知识库 ----
export interface KnowledgeItem {
  id: string
  name: string
  description: string | null
  creater?: number
  user_ids?: number[]
  accept_users?: number[]
  create_time: string | null
  update_time: string | null
}

/** 知识库详情 */
export interface KnowledgeDetail {
  id: string
  name: string
  description: string | null
  creater: number
  accept_users: number[]
  create_time: string | null
  update_time: string | null
}

/** 用户列表项 */
export interface UserListItem {
  id: number
  username: string
}

/** 用户列表数据 */
export interface UserListData {
  items: UserListItem[]
  total: number
}

export interface KnowledgeListData {
  items: KnowledgeItem[]
  total: number
  page_num: number
  page_size: number
}

export interface KnowledgeFileItem {
  id: string
  knowledge_id: string
  file_name: string
  type: number // 0文本 1音频 2图片
  state: number // 0解析中 1成功 2失败
  fail_reason: string | null
  chunks_counts: number | null
  create_time: string | null
}

export interface FileStateData {
  file_id: string
  file_name: string
  knowledge_id: string
  state: number
  fail_reason: string | null
  chunks_counts: number | null
}

export interface UploadFileData {
  msg: string
  file_id: string
  knowledge_id: string
  state: number
}

// ---- AI 对话（Session-based）----

/** AI 对话会话 */
export interface ChatSession {
  session_id: string
  session_name: string | null
  task_ids: string[]
  knowledge_ids: string[]
  need_kb: boolean
  user_id: number
  create_time: string | null
  update_time: string | null
}

/** 会话列表响应 */
export interface SessionListData {
  items: ChatSession[]
  total: number
  page_num: number
  page_size: number
}

/** 聊天记录 */
export interface ChatMessageItem {
  chat_id: number
  session_id: string
  role: 'user' | 'assistant'
  content: string
  turn_index: number
  user_id: number
  create_time: string | null
}

/** 聊天记录列表响应 */
export interface ChatMessageListData {
  items: ChatMessageItem[]
  total: number
  session_id: string
}

/** WebSocket 流式对话消息（S→C） */
export interface ChatWSMessage {
  status: 'start' | 'streaming' | 'done' | 'error'
  text?: string
  question?: string
  message?: string
  partial?: string
}

/** 会议 WS 消息类型 */
export type MeetingWSMessageType =
  | 'transcript'
  | 'signal'
  | 'participants_list'
  | 'participant_joined'
  | 'participant_left'
  | 'speech_started'
  | 'speech_stopped'
  | 'meeting_ended'

export interface TranscriptMessage {
  type: 'transcript'
  speaker_id: number
  speaker_name: string
  text: string
  is_final: boolean
}

export interface SignalMessage {
  type: 'signal'
  from: number
  from_name?: string
  signal_type: 'offer' | 'answer' | 'ice'
  data: any
}

export interface ParticipantsListMessage {
  type: 'participants_list'
  participants: Participant[]
}

export interface ParticipantJoinedMessage {
  type: 'participant_joined'
  user: Participant
}

export interface ParticipantLeftMessage {
  type: 'participant_left'
  user: Participant
}

export interface SpeechMessage {
  type: 'speech_started' | 'speech_stopped'
  speaker_id: number
}

export interface MeetingEndedMessage {
  type: 'meeting_ended'
  meeting_id: string
  task_id: string | null
  need_summary?: boolean
}
