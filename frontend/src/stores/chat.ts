// ============================================================
// Chat Store — Session-based AI 对话状态管理
// 管理会话列表 / 当前会话消息 / 流式输出状态 / 新建会话选择
// ============================================================

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { chatApi, knowledgeApi, meetingApi } from '@/api'
import type { ChatSession, ChatMessageItem, KnowledgeItem, MeetingItem } from '@/api/types'

export interface ChatMessage {
  chat_id?: number
  role: 'user' | 'assistant'
  content: string
  timestamp: string
  streaming?: boolean
  sources?: string[]
}

export const useChatStore = defineStore('chat', () => {
  // ===== 会话列表 =====
  const sessionList = ref<ChatSession[]>([])
  const sessionTotal = ref(0)
  const sessionPage = ref(1)
  const sessionPageSize = ref(20)
  const sessionLoading = ref(false)
  const sessionSearch = ref('')

  // ===== 当前会话 =====
  const currentSession = ref<ChatSession | null>(null)
  const messages = ref<ChatMessage[]>([])
  const isStreaming = ref(false)

  // ===== 可用选项（新建会话弹窗用）=====
  const availableMeetings = ref<MeetingItem[]>([])
  const availableKnowledge = ref<KnowledgeItem[]>([])
  const meetingPage = ref(1)
  const knowledgePage = ref(1)
  const meetingTotal = ref(0)
  const knowledgeTotal = ref(0)
  const meetingSearch = ref('')
  const knowledgeSearch = ref('')
  const optionsLoading = ref(false)

  // ===== 已选项（新建/修改讨论范围）=====
  const selectedMeetingIds = ref<string[]>([])
  const selectedKnowledgeIds = ref<string[]>([])
  const needKb = ref(false)

  // ===== 计算属性 =====
  const currentSessionId = computed(() => currentSession.value?.session_id || null)
  const hasSelection = computed(() => selectedMeetingIds.value.length > 0 || selectedKnowledgeIds.value.length > 0 || needKb.value)

  // ===== Actions: 会话列表 =====

  /** 获取会话列表 */
  async function loadSessions(page = 1): Promise<void> {
    sessionLoading.value = true
    sessionPage.value = page
    try {
      const data = await chatApi.getSessionList(sessionPage.value, sessionPageSize.value)
      let items = data.items
      // 前端搜索过滤
      if (sessionSearch.value) {
        const keyword = sessionSearch.value.toLowerCase()
        items = items.filter(s => (s.session_name || '').toLowerCase().includes(keyword))
      }
      sessionList.value = items
      sessionTotal.value = data.total

      // 如果当前会话不在刷新后的列表中（例如本地创建但未发消息的会话被丢弃），清空当前会话
      if (currentSession.value) {
        const stillExists = items.some(s => s.session_id === currentSession.value!.session_id)
        if (!stillExists) {
          currentSession.value = null
          messages.value = []
        }
      }
    } finally {
      sessionLoading.value = false
    }
  }

  /** 搜索会话 */
  function searchSessions(keyword: string): void {
    sessionSearch.value = keyword
    loadSessions(1)
  }

  /** 选中会话 */
  function setCurrentSession(session: ChatSession): void {
    currentSession.value = session
    messages.value = []
  }

  /** 删除会话 */
  async function deleteSession(sessionId: string): Promise<void> {
    await chatApi.deleteSession(sessionId)
    sessionList.value = sessionList.value.filter(s => s.session_id !== sessionId)
    if (currentSession.value?.session_id === sessionId) {
      currentSession.value = null
      messages.value = []
    }
  }

  // ===== Actions: 可用选项 =====

  /** 加载可用会议列表（分页） */
  async function loadAvailableMeetings(page = 1, search = ''): Promise<void> {
    optionsLoading.value = true
    meetingPage.value = page
    meetingSearch.value = search
    try {
      // 调用后端分页接口 POST /meeting/list
      const data = await meetingApi.list(page, 5)
      let items = data.data || []
      // 前端搜索过滤
      if (search) {
        const keyword = search.toLowerCase()
        items = items.filter(m => (m.meeting_name || '').toLowerCase().includes(keyword))
      }
      availableMeetings.value = items
      meetingTotal.value = data.total
    } catch (error: any) {
      availableMeetings.value = []
      meetingTotal.value = 0
      console.error('[ChatStore] 加载会议列表失败:', error)
    } finally {
      optionsLoading.value = false
    }
  }

  /** 加载可用知识库列表 */
  async function loadAvailableKnowledge(page = 1, search = ''): Promise<void> {
    optionsLoading.value = true
    knowledgePage.value = page
    knowledgeSearch.value = search
    try {
      const data = await knowledgeApi.list(page, 5, search)
      availableKnowledge.value = data.items
      knowledgeTotal.value = data.total
    } catch (error: any) {
      availableKnowledge.value = []
      knowledgeTotal.value = 0
      console.error('[ChatStore] 加载知识库列表失败:', error)
    } finally {
      optionsLoading.value = false
    }
  }

  /** 加载所有可用选项（新建会话弹窗打开时调用） */
  async function loadAllOptions(): Promise<void> {
    await Promise.all([
      loadAvailableMeetings(),
      loadAvailableKnowledge(),
    ])
  }

  // ===== Actions: 选择管理 =====

  /** 切换会议选择 */
  function toggleMeeting(taskId: string): void {
    const idx = selectedMeetingIds.value.indexOf(taskId)
    if (idx === -1) {
      selectedMeetingIds.value.push(taskId)
    } else {
      selectedMeetingIds.value.splice(idx, 1)
    }
  }

  /** 切换知识库选择 */
  function toggleKnowledge(kbId: string): void {
    const idx = selectedKnowledgeIds.value.indexOf(kbId)
    if (idx === -1) {
      selectedKnowledgeIds.value.push(kbId)
    } else {
      selectedKnowledgeIds.value.splice(idx, 1)
    }
  }

  /** 从会话信息恢复已选项 */
  function restoreSelectionFromSession(session: ChatSession): void {
    selectedMeetingIds.value = [...(session.meeting_ids || [])]
    selectedKnowledgeIds.value = [...(session.knowledge_ids || [])]
    needKb.value = session.need_kb || false
  }

  /** 清除选择 */
  function clearSelection(): void {
    selectedMeetingIds.value = []
    selectedKnowledgeIds.value = []
    needKb.value = false
  }

  // ===== Actions: 会话 CRUD =====

  /** 创建新会话（本地预创建，WS 连接后在首次发消息时激活） */
  function createLocalSession(sessionId: string, meetingIds: string[] = [], knowledgeIds: string[] = [], needKb: boolean = false): void {
    const newSession: ChatSession = {
      session_id: sessionId,
      session_name: null,
      meeting_ids: [...meetingIds],
      knowledge_ids: [...knowledgeIds],
      need_kb: needKb,
      user_id: 0,
      create_time: null,
      update_time: null,
    }
    currentSession.value = newSession
    messages.value = []
    sessionList.value.unshift(newSession)
  }

  /** 更新会话名称 */
  function updateSessionName(sessionId: string, name: string): void {
    const session = sessionList.value.find(s => s.session_id === sessionId)
    if (session) {
      session.session_name = name
    }
    if (currentSession.value?.session_id === sessionId) {
      currentSession.value.session_name = name
    }
  }

  /** 同步修改到后端 */
  async function syncSessionContext(sessionId: string, meetingIds: string[], knowledgeIds: string[]): Promise<void> {
    await chatApi.updateSession(sessionId, undefined, meetingIds, knowledgeIds, needKb.value)
    // 更新本地状态
    const session = sessionList.value.find(s => s.session_id === sessionId)
    if (session) {
      session.meeting_ids = meetingIds
      session.knowledge_ids = knowledgeIds
      session.need_kb = needKb.value
    }
    if (currentSession.value?.session_id === sessionId) {
      currentSession.value.meeting_ids = meetingIds
      currentSession.value.knowledge_ids = knowledgeIds
      currentSession.value.need_kb = needKb.value
    }
  }

  // ===== Actions: 消息管理 =====

  /** 添加用户消息 */
  function addUserMessage(content: string): void {
    messages.value.push({
      role: 'user',
      content,
      timestamp: new Date().toLocaleTimeString('zh-CN', { hour12: false }),
    })
  }

  /** 添加 AI 消息（流式开始） */
  function startAiMessage(): void {
    isStreaming.value = true
    messages.value.push({
      role: 'assistant',
      content: '',
      timestamp: new Date().toLocaleTimeString('zh-CN', { hour12: false }),
      streaming: true,
    })
  }

  /** 追加流式文本 */
  function appendAiText(text: string): void {
    const lastMsg = messages.value[messages.value.length - 1]
    if (lastMsg && lastMsg.role === 'assistant') {
      lastMsg.content += text
    }
  }

  /** 完成流式输出 */
  function finishAiMessage(): void {
    isStreaming.value = false
    const lastMsg = messages.value[messages.value.length - 1]
    if (lastMsg && lastMsg.role === 'assistant') {
      lastMsg.streaming = false
    }
  }

  /** 加载历史消息 */
  async function loadHistory(sessionId: string): Promise<void> {
    const data = await chatApi.getChatList(sessionId, 1, 100)
    messages.value = data.items.map((item: ChatMessageItem) => ({
      chat_id: item.chat_id,
      role: item.role,
      content: item.content,
      timestamp: item.create_time || new Date().toLocaleTimeString('zh-CN', { hour12: false }),
    }))
  }

  /** 清空当前消息 */
  function clearMessages(): void {
    messages.value = []
    isStreaming.value = false
  }

  return {
    // State
    sessionList,
    sessionTotal,
    sessionPage,
    sessionPageSize,
    sessionLoading,
    sessionSearch,
    currentSession,
    messages,
    isStreaming,
    availableMeetings,
    availableKnowledge,
    meetingPage,
    knowledgePage,
    meetingTotal,
    knowledgeTotal,
    meetingSearch,
    knowledgeSearch,
    optionsLoading,
    selectedMeetingIds,
    selectedKnowledgeIds,
    needKb,

    // Computed
    currentSessionId,
    hasSelection,

    // Actions
    loadSessions,
    searchSessions,
    setCurrentSession,
    deleteSession,
    loadAvailableMeetings,
    loadAvailableKnowledge,
    loadAllOptions,
    toggleMeeting,
    toggleKnowledge,
    restoreSelectionFromSession,
    clearSelection,
    createLocalSession,
    updateSessionName,
    syncSessionContext,
    addUserMessage,
    startAiMessage,
    appendAiText,
    finishAiMessage,
    loadHistory,
    clearMessages,
  }
})
