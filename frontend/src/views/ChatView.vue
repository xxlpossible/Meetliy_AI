<script setup lang="ts">
// ============================================================
// ChatView — AI 对话主页面
// 基于 design/mockups ai-chat.html 设计稿实现
// ============================================================

import { ref, computed, onMounted, nextTick, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import DefaultLayout from '@/layouts/DefaultLayout.vue'
import NewChatModal from '@/components/NewChatModal.vue'
import EditContextModal from '@/components/EditContextModal.vue'
import { useChatStore } from '@/stores/chat'
import { useChatSSE } from '@/composables/useChatSSE'
import { renderMarkdown } from '@/utils/markdown'
import type { ChatSession } from '@/api/types'

const chatStore = useChatStore()
const chatSSE = useChatSSE()

// ===== DOM 引用 =====
const chatScrollRef = ref<HTMLElement>()
const inputTextareaRef = ref<HTMLTextAreaElement>()

// ===== 弹窗控制 =====
const showNewChatModal = ref(false)
const showEditContextModal = ref(false)

// ===== 计算属性 =====
const currentSession = computed(() => chatStore.currentSession)
const sessionName = computed(() => currentSession.value?.session_name || '新会话')
const selectedMeetings = computed(() => {
  if (!currentSession.value?.task_ids) return []
  return chatStore.availableMeetings.filter(m => currentSession.value!.task_ids.includes(m.id))
})
const selectedKnowledge = computed(() => {
  if (!currentSession.value?.knowledge_ids) return []
  return chatStore.availableKnowledge.filter(k => currentSession.value!.knowledge_ids.includes(k.id))
})

// ===== 会话列表操作 =====

async function loadSessions() {
  await chatStore.loadSessions()
}

function handleSearchSessions(keyword: string) {
  chatStore.searchSessions(keyword)
}

async function selectSession(session: ChatSession) {
  chatStore.setCurrentSession(session)
  await chatStore.loadHistory(session.session_id)
}

async function handleDeleteSession(sessionId: string) {
  try {
    await ElMessageBox.confirm('确定要删除这个会话吗？', '提示', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning',
    })
    await chatStore.deleteSession(sessionId)
    ElMessage.success('会话已删除')
  } catch (e: any) {
    if (e !== 'cancel') {
      // 用户取消
    }
  }
}

async function handlePageChange(page: number) {
  await chatStore.loadSessions(page)
}

// ===== 新建对话 =====

function openNewChatModal() {
  chatStore.clearSelection()
  showNewChatModal.value = true
}

function handleStartNewChat(data: { sessionId: string; taskIds: string[]; knowledgeIds: string[]; needKb: boolean }) {
  // 创建本地会话（不立即连接 WS，发消息时按需连接）
  chatStore.createLocalSession(data.sessionId, data.taskIds, data.knowledgeIds, data.needKb)
  showNewChatModal.value = false
}

// ===== 修改讨论范围 =====

function openEditContextModal() {
  if (!currentSession.value) return
  chatStore.restoreSelectionFromSession(currentSession.value)
  showEditContextModal.value = true
}

async function handleEditContextSaved(data: { taskIds: string[]; knowledgeIds: string[]; needKb: boolean }) {
  if (!currentSession.value) return
  await chatStore.syncSessionContext(currentSession.value.session_id, data.taskIds, data.knowledgeIds)
  showEditContextModal.value = false
  ElMessage.success('讨论范围已更新')
}

// ===== 消息发送 =====

const inputText = ref('')

async function handleSendMessage() {
  const text = inputText.value.trim()
  if (!text) return

  if (!currentSession.value) {
    ElMessage.warning('请先选择或创建一个会话')
    return
  }

  // 立即清空输入框，不等待 SSE 完成
  inputText.value = ''
  scrollToBottom()

  chatStore.addUserMessage(text)

  await chatSSE.sendQuestion(
    currentSession.value.session_id,
    text,
    currentSession.value.task_ids,
    currentSession.value.knowledge_ids,
    currentSession.value.need_kb
  )
}

function handleQuickQuestion(question: string) {
  inputText.value = question
  handleSendMessage()
}

// ===== 滚动控制 =====
function scrollToBottom() {
  nextTick(() => {
    if (chatScrollRef.value) {
      chatScrollRef.value.scrollTop = chatScrollRef.value.scrollHeight
    }
  })
}

// 消息变化时自动滚动
watch(() => chatStore.messages.length, () => {
  scrollToBottom()
})

watch(() => {
  const msgs = chatStore.messages
  return msgs.length > 0 ? msgs[msgs.length - 1].content : ''
}, () => {
  scrollToBottom()
})

// ===== 生命周期 =====
onMounted(async () => {
  await loadSessions()
})
</script>

<template>
  <DefaultLayout>
    <div class="chat-layout">
      <!-- 左侧会话列表 -->
      <aside class="chat-sidebar">
        <div class="sidebar-header">
          <h1 class="sidebar-title">AI 对话</h1>
          <button
            class="btn-new-chat"
            @click="openNewChatModal"
          >
            + 新建对话
          </button>
        </div>

        <div class="sidebar-search">
          <input
            type="text"
            class="search-input"
            placeholder="搜索对话..."
            :value="chatStore.sessionSearch"
            @input="handleSearchSessions(($event.target as HTMLInputElement).value)"
          />
        </div>

        <div class="chat-list">
          <div v-if="chatStore.sessionLoading" class="select-empty">
            <p>加载中...</p>
          </div>

          <template v-else-if="chatStore.sessionList.length === 0">
            <div class="select-empty">
              <div class="select-empty-icon">💬</div>
              <p>暂无会话，点击新建开始</p>
            </div>
          </template>

          <template v-else>
            <div
              v-for="session in chatStore.sessionList"
              :key="session.session_id"
              class="chat-item"
              :class="{ active: currentSession?.session_id === session.session_id }"
              @click="selectSession(session)"
            >
              <div class="chat-item-icon">AI</div>
              <div class="chat-item-info">
                <div class="chat-item-title">
                  {{ session.session_name || '新会话' }}
                </div>
                <div class="chat-item-meta">
                  {{ session.update_time || '刚刚' }}
                </div>
                <div class="chat-item-tags">
                  <span v-if="session.task_ids?.length" class="chat-item-tag meeting">
                    {{ session.task_ids.length }} 个会议
                  </span>
                  <span v-if="session.knowledge_ids?.length" class="chat-item-tag kb">
                    {{ session.knowledge_ids.length }} 个知识库
                  </span>
                </div>
              </div>
              <button
                class="chat-item-delete"
                @click.stop="handleDeleteSession(session.session_id)"
                title="删除会话"
              >
                ×
              </button>
            </div>
          </template>
        </div>

        <!-- 分页 -->
        <div v-if="chatStore.sessionTotal > chatStore.sessionPageSize" class="chat-pagination">
          <button
            class="chat-pagination-btn"
            :disabled="chatStore.sessionPage <= 1"
            @click="handlePageChange(chatStore.sessionPage - 1)"
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
              <path d="M15 18l-6-6 6-6"/>
            </svg>
          </button>
          <span class="chat-pagination-text">
            第 {{ chatStore.sessionPage }} 页 / 共 {{ Math.ceil(chatStore.sessionTotal / chatStore.sessionPageSize) }} 页
          </span>
          <button
            class="chat-pagination-btn"
            :disabled="chatStore.sessionPage >= Math.ceil(chatStore.sessionTotal / chatStore.sessionPageSize)"
            @click="handlePageChange(chatStore.sessionPage + 1)"
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
              <path d="M9 18l6-6-6-6"/>
            </svg>
          </button>
        </div>
      </aside>

      <!-- 右侧聊天区域 -->
      <main class="chat-main">
        <!-- 聊天头部 -->
        <header v-if="currentSession" class="chat-header">
          <div class="chat-header-left">
            <div class="chat-header-icon">AI</div>
            <div class="chat-header-info">
              <h2>{{ sessionName }}</h2>
              <p>基于会议内容和知识库的 AI 深度对话</p>
            </div>
          </div>
          <div class="chat-header-actions">
            <button class="btn-edit-context" @click="openEditContextModal">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
                <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
              </svg>
              修改讨论范围
            </button>
          </div>
        </header>

        <!-- 聊天滚动区 -->
        <div ref="chatScrollRef" class="chat-scroll" :class="{ 'no-session': !currentSession }">
          <!-- 未选择会话时的提示（垂直居中） -->
          <div v-if="!currentSession" class="chat-welcome">
            <div class="chat-welcome-icon">💬</div>
            <h2>欢迎使用 AI 对话</h2>
            <p>请从左侧选择一个会话开始，或点击"新建对话"创建新会话。</p>
          </div>

          <!-- 欢迎区域 -->
          <div v-if="chatStore.messages.length === 0 && currentSession" class="chat-welcome">
            <div class="chat-welcome-icon">AI</div>
            <h2>你好，我是 Meetily AI</h2>
            <p>我已了解选定的会议和知识库内容。你可以问我任何问题，也可以随时修改上下文。</p>
          </div>

          <!-- 上下文摘要 -->
          <div v-if="currentSession && (selectedMeetings.length > 0 || selectedKnowledge.length > 0)" class="context-summary">
            <div
              v-for="meeting in selectedMeetings"
              :key="meeting.id"
              class="context-pill meeting"
            >
              📋 {{ meeting.meeting_name }}
            </div>
            <div
              v-for="kb in selectedKnowledge"
              :key="kb.id"
              class="context-pill kb"
            >
              📚 {{ kb.name }}
            </div>
          </div>

          <!-- 消息列表 -->
          <div
            v-for="(msg, idx) in chatStore.messages"
            :key="idx"
            class="msg-row"
            :class="msg.role"
          >
            <div class="msg-content">
              <div
                class="msg-bubble"
                v-html="msg.role === 'assistant' ? renderMarkdown(msg.content) : msg.content"
              />
              <span v-if="msg.streaming" class="streaming-cursor" />
              <div class="msg-meta">{{ msg.timestamp }}</div>
            </div>
          </div>
        </div>

        <!-- 输入区域 -->
        <div v-if="currentSession" class="chat-input-area">
          <div class="chat-input-wrapper">
            <textarea
              ref="inputTextareaRef"
              v-model="inputText"
              class="chat-input"
              placeholder="向 AI 提问，按 Enter 发送..."
              rows="1"
              :disabled="!currentSession || chatStore.isStreaming"
              @keydown.enter.prevent="handleSendMessage"
            />
            <button
              class="chat-send-btn"
              :disabled="!inputText.trim() || !currentSession || chatStore.isStreaming"
              @click="handleSendMessage"
            >
              ↑
            </button>
          </div>
          <!-- need_kb 控制已移至新建对话/修改讨论范围弹窗 -->
          <div v-if="chatStore.messages.length === 0" class="quick-questions">
            <button class="qq-chip" @click="handleQuickQuestion('总结会议要点')">
              总结会议要点
            </button>
            <button class="qq-chip" @click="handleQuickQuestion('提取行动项')">
              提取行动项
            </button>
            <button class="qq-chip" @click="handleQuickQuestion('分析争议焦点')">
              分析争议焦点
            </button>
            <button class="qq-chip" @click="handleQuickQuestion('对比知识库内容')">
              对比知识库内容
            </button>
          </div>
        </div>
      </main>
    </div>

    <!-- 新建对话弹窗 -->
    <NewChatModal
      v-if="showNewChatModal"
      :visible="showNewChatModal"
      @close="showNewChatModal = false"
      @start="handleStartNewChat"
    />

    <!-- 修改讨论范围弹窗 -->
    <EditContextModal
      v-if="showEditContextModal && currentSession"
      :visible="showEditContextModal"
      :session="currentSession"
      @close="showEditContextModal = false"
      @save="handleEditContextSaved"
    />
  </DefaultLayout>
</template>

<style scoped lang="scss">
@use '@/styles/mixins.scss' as *;

.chat-layout {
  display: grid;
  grid-template-columns: 300px 1fr;
  height: calc(100vh - 64px);
}

// ===== 左侧会话列表 =====
.chat-sidebar {
  background: white;
  border-right: 1px solid var(--color-stone-200);
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
}

.sidebar-header {
  padding: 20px 20px 14px;
  border-bottom: 1px solid var(--color-stone-100);
  flex-shrink: 0;

  .sidebar-title {
    font-family: var(--font-display);
    font-size: 18px;
    font-weight: 700;
    color: var(--color-stone-800);
    margin-bottom: 14px;
  }
}

.btn-new-chat {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  width: 100%;
  padding: 11px 16px;
  border: 1.5px solid var(--color-stone-200);
  border-radius: var(--radius-lg);
  background: white;
  color: var(--color-stone-700);
  font-size: 13px;
  font-weight: 600;
  font-family: var(--font-body);
  cursor: pointer;
  transition: all 0.15s;

  &:hover {
    background: var(--color-amber-50);
    border-color: var(--color-amber-300);
    color: var(--color-amber-600);
  }
}

.sidebar-search {
  padding: 12px 20px;
  border-bottom: 1px solid var(--color-stone-100);
  flex-shrink: 0;
}

.search-input {
  width: 100%;
  padding: 10px 14px;
  border: 1.5px solid var(--color-stone-200);
  border-radius: var(--radius-lg);
  background: var(--color-stone-50);
  font-size: 13px;
  font-family: var(--font-body);
  color: var(--color-stone-800);
  outline: none;
  transition: all 0.2s;

  &:focus {
    border-color: var(--color-amber-400);
    background: white;
    box-shadow: 0 0 0 3px rgba(245,180,0,0.08);
  }

  &::placeholder {
    color: var(--color-stone-400);
  }
}

// 会话列表
.chat-list {
  flex: 1;
  overflow-y: auto;
  padding: 10px;
}

.chat-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 14px;
  border-radius: var(--radius-lg);
  cursor: pointer;
  transition: all 0.15s;
  margin-bottom: 2px;
  position: relative;

  &:hover {
    background: var(--color-stone-50);
  }

  &.active {
    background: var(--color-amber-50);
    border: 1px solid var(--color-amber-200);
  }

  &:hover .chat-item-delete {
    opacity: 1;
  }
}

.chat-item-icon {
  width: 38px;
  height: 38px;
  border-radius: 10px;
  background: var(--color-stone-100);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  font-weight: 700;
  color: var(--color-stone-600);
  flex-shrink: 0;
}

.chat-item-info {
  flex: 1;
  min-width: 0;
}

.chat-item-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--color-stone-800);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  margin-bottom: 3px;
}

.chat-item-meta {
  font-size: 11px;
  color: var(--color-stone-400);
}

.chat-item-tags {
  display: flex;
  gap: 4px;
  margin-top: 4px;
  flex-wrap: wrap;
}

.chat-item-tag {
  font-size: 10px;
  font-weight: 500;
  padding: 2px 6px;
  border-radius: 4px;
  background: var(--color-stone-100);
  color: var(--color-stone-500);

  &.meeting {
    background: #EFF6FF;
    color: var(--color-info);
  }

  &.kb {
    background: #ECFDF5;
    color: var(--color-success);
  }
}

.chat-item-delete {
  position: absolute;
  top: 8px;
  right: 8px;
  width: 20px;
  height: 20px;
  border: none;
  background: transparent;
  color: var(--color-stone-400);
  font-size: 16px;
  cursor: pointer;
  opacity: 0;
  transition: opacity 0.15s;
  display: flex;
  align-items: center;
  justify-content: center;

  &:hover {
    color: var(--color-error);
  }
}

// 会话列表分页
.chat-pagination {
  padding: 10px 20px 14px;
  border-top: 1px solid var(--color-stone-100);
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  flex-shrink: 0;
}

.chat-pagination-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  border: 1px solid var(--color-stone-200);
  border-radius: var(--radius-md);
  background: white;
  color: var(--color-stone-600);
  font-size: 12px;
  font-family: var(--font-body);
  cursor: pointer;
  transition: all 0.15s;

  &:hover:not(:disabled) {
    background: var(--color-stone-50);
    border-color: var(--color-stone-300);
    color: var(--color-stone-800);
  }

  &:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }
}

.chat-pagination-text {
  font-size: 11px;
  color: var(--color-stone-500);
  padding: 0 6px;
  white-space: nowrap;
}

// ===== 右侧聊天区域 =====
.chat-main {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
  background: var(--color-stone-50);
}

// 聊天头部
.chat-header {
  background: white;
  border-bottom: 1px solid var(--color-stone-200);
  padding: 16px 28px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-shrink: 0;
}

.chat-header-left {
  display: flex;
  align-items: center;
  gap: 14px;
}

.chat-header-icon {
  width: 42px;
  height: 42px;
  border-radius: 12px;
  background: linear-gradient(135deg, var(--color-amber-400), var(--color-amber-500));
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  font-weight: 700;
  color: var(--color-stone-900);
  font-family: var(--font-display);
}

.chat-header-info h2 {
  font-size: 16px;
  font-weight: 600;
  color: var(--color-stone-800);
}

.chat-header-info p {
  font-size: 12px;
  color: var(--color-stone-500);
  margin-top: 2px;
}

.chat-header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.btn-edit-context {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 14px;
  border: 1.5px solid var(--color-stone-200);
  border-radius: var(--radius-lg);
  background: white;
  color: var(--color-stone-700);
  font-size: 13px;
  font-weight: 500;
  font-family: var(--font-body);
  cursor: pointer;
  transition: all 0.15s;

  &:hover {
    background: var(--color-amber-50);
    border-color: var(--color-amber-200);
    color: var(--color-amber-600);
  }
}

// 聊天滚动区
.chat-scroll {
  flex: 1;
  overflow-y: auto;
  padding: 24px 28px;

  &.no-session {
    display: flex;
    align-items: center;
    justify-content: center;
  }
}

// 欢迎区域
.chat-welcome {
  text-align: center;
  padding: 30px 20px 50px;
  animation: fadeSlideIn 0.4s ease-out;
}

@keyframes fadeSlideIn {
  from { opacity: 0; transform: translateY(10px); }
  to { opacity: 1; transform: translateY(0); }
}

.chat-welcome-icon {
  width: 60px;
  height: 60px;
  border-radius: 18px;
  background: linear-gradient(135deg, var(--color-amber-400), var(--color-amber-500));
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 26px;
  font-weight: 700;
  font-family: var(--font-display);
  color: var(--color-stone-900);
  margin: 0 auto 20px;
}

.chat-welcome h2 {
  font-family: var(--font-display);
  font-size: 22px;
  font-weight: 700;
  color: var(--color-stone-800);
  margin-bottom: 8px;
}

.chat-welcome p {
  font-size: 14px;
  color: var(--color-stone-500);
  max-width: 420px;
  margin: 0 auto;
  line-height: 1.6;
}

// 上下文摘要
.context-summary {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 8px;
  margin-top: 20px;
}

.context-pill {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  border-radius: 20px;
  font-size: 12px;
  font-weight: 500;

  &.meeting {
    background: #EFF6FF;
    color: var(--color-info);
    border: 1px solid #BFDBFE;
  }

  &.kb {
    background: #ECFDF5;
    color: #059669;
    border: 1px solid #A7F3D0;
  }
}

// 消息气泡
.msg-row {
  display: flex;
  margin-bottom: 20px;
  animation: fadeSlideIn 0.3s ease-out;

  &.user {
    justify-content: flex-end;
  }

  &.assistant {
    justify-content: flex-start;
  }
}

.msg-content {
  max-width: 75%;
  min-width: 0;
}

.msg-bubble {
  padding: 14px 18px;
  border-radius: var(--radius-lg);
  font-size: 14px;
  line-height: 1.7;
  word-break: break-word;
  /* 流式输出时气泡随内容自然伸缩，过渡平滑 */
  transition: padding 0.15s ease;

  .user & {
    background: var(--color-amber-400);
    color: var(--color-stone-900);
    border-bottom-right-radius: 4px;
    white-space: pre-wrap;
  }

  .assistant & {
    background: white;
    color: var(--color-stone-800);
    border: 1px solid var(--color-stone-200);
    border-bottom-left-radius: 4px;
  }

  // Markdown 样式（AI消息）
  .assistant & :deep(h1), .assistant & :deep(h2), .assistant & :deep(h3) {
    margin: 16px 0 8px;
    color: var(--color-stone-800);

    &:first-child { margin-top: 0; }
  }

  .assistant & :deep(p) { margin-bottom: 10px; }
  .assistant & :deep(p:last-child) { margin-bottom: 0; }

  .assistant & :deep(ul), .assistant & :deep(ol) {
    margin: 8px 0 12px;
    padding-left: 20px;
  }

  .assistant & :deep(li) { margin-bottom: 6px; }

  .assistant & :deep(code) {
    font-family: var(--font-mono);
    font-size: 12px;
    background: var(--color-stone-100);
    padding: 2px 6px;
    border-radius: 4px;
  }

  .assistant & :deep(pre) {
    background: var(--color-stone-900);
    color: var(--color-stone-100);
    padding: 14px 16px;
    border-radius: var(--radius-md);
    overflow-x: auto;
    margin: 12px 0;
    font-family: var(--font-mono);
    font-size: 12px;
    line-height: 1.6;
  }

  .assistant & :deep(pre code) {
    background: transparent;
    padding: 0;
    color: inherit;
  }

  .assistant & :deep(blockquote) {
    border-left: 3px solid var(--color-amber-300);
    background: var(--color-amber-50);
    padding: 10px 14px;
    margin: 12px 0;
    border-radius: 0 var(--radius-md) var(--radius-md) 0;
  }
}

.msg-meta {
  font-size: 11px;
  color: var(--color-stone-400);
  margin-top: 6px;
  padding: 0 4px;

  .user & {
    text-align: right;
  }
}

// 流式输出光标
.streaming-cursor {
  display: inline-block;
  width: 2px;
  height: 14px;
  background: var(--color-amber-500);
  margin-left: 2px;
  animation: blink 0.8s infinite;
  vertical-align: middle;
}

@keyframes blink {
  0%, 50% { opacity: 1; }
  51%, 100% { opacity: 0; }
}

// 输入区域
.chat-input-area {
  padding: 16px 28px 20px;
  background: white;
  border-top: 1px solid var(--color-stone-200);
  flex-shrink: 0;
}

.chat-input-wrapper {
  display: flex;
  gap: 12px;
  align-items: flex-end;
}

.chat-input {
  flex: 1;
  padding: 14px 18px;
  border: 1.5px solid var(--color-stone-200);
  border-radius: var(--radius-lg);
  font-size: 14px;
  font-family: var(--font-body);
  color: var(--color-stone-800);
  background: var(--color-stone-50);
  outline: none;
  resize: none;
  min-height: 50px;
  max-height: 150px;
  line-height: 1.5;
  transition: all 0.2s;

  &:focus {
    border-color: var(--color-amber-400);
    background: white;
    box-shadow: 0 0 0 3px rgba(245,180,0,0.08);
  }

  &:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }

  &::placeholder {
    color: var(--color-stone-400);
  }
}

.chat-send-btn {
  width: 50px;
  height: 50px;
  border: none;
  border-radius: var(--radius-lg);
  background: var(--color-amber-400);
  color: var(--color-stone-900);
  font-size: 20px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.15s;
  flex-shrink: 0;

  &:hover:not(:disabled) {
    background: var(--color-amber-500);
    transform: translateY(-1px);
    box-shadow: 0 4px 12px rgba(245,180,0,0.25);
  }

  &:disabled {
    opacity: 0.5;
    cursor: not-allowed;
    transform: none;
    box-shadow: none;
  }
}

// 输入区域选项
.chat-input-options {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 8px;
}

// 快捷问题
.quick-questions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 10px;
}

.qq-chip {
  padding: 6px 14px;
  border: 1px solid var(--color-stone-200);
  border-radius: 20px;
  background: white;
  color: var(--color-stone-600);
  font-size: 12px;
  font-family: var(--font-body);
  cursor: pointer;
  transition: all 0.15s;

  &:hover {
    background: var(--color-amber-50);
    border-color: var(--color-amber-200);
    color: var(--color-amber-600);
  }
}

// 空状态
.select-empty {
  text-align: center;
  padding: 30px;
  color: var(--color-stone-400);

  .select-empty-icon {
    font-size: 32px;
    margin-bottom: 10px;
    opacity: 0.4;
  }

  p {
    font-size: 13px;
  }
}

// 滚动条美化
::-webkit-scrollbar {
  width: 6px;
}

::-webkit-scrollbar-track {
  background: transparent;
}

::-webkit-scrollbar-thumb {
  background: var(--color-stone-300);
  border-radius: 3px;

  &:hover {
    background: var(--color-stone-400);
  }
}
</style>
