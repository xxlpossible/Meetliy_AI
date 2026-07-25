<script setup lang="ts">
// ============================================================
// MeetingRoomView — 实时会议室
// 功能：麦克风采集 → WS 实时转写 / AI 临时对话 / 结束&离开
// ============================================================
import { ref, reactive, computed, onMounted, onUnmounted, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useMeetingStore } from '@/stores'
import { useAuthStore } from '@/stores/auth'
import { meetingApi } from '@/api'
import { getAccessToken } from '@/api/request'
import { useAudioCapture } from '@/composables/useAudioCapture'
import { useMeetingWebSocket } from '@/composables/useMeetingWebSocket'
import { useWebRTC } from '@/composables/useWebRTC'
import { useTempChat } from '@/composables/useTempChat'
import type { Participant } from '@/api/types'

const route = useRoute()
const router = useRouter()
const meetingStore = useMeetingStore()
const authStore = useAuthStore()

// ---- 路由参数 ----
const meetingId = route.params.meetingId as string

// ---- 状态 ----
const meetingName = ref('')
const isHost = ref(false)
const micEnabled = ref(true)
const elapsedSeconds = ref(0)
const transcriptArea = ref<HTMLElement | null>(null)

// ---- 参与者 ----
const participants = reactive<Map<number, Participant>>(new Map())
const speakingSpeakers = reactive<Set<number>>(new Set())

// ---- 转写记录 ----
interface TranscriptEntry {
  speaker_id: number
  speaker_name: string
  text: string
  time: string
  is_final: boolean
}

const finalTranscripts = reactive<TranscriptEntry[]>([])
const interimTranscripts = reactive<Map<number, TranscriptEntry>>(new Map())

// ---- AI 对话 ----
interface ChatMsg {
  role: 'user' | 'assistant'
  content: string
  time: string
}

const chatMessages = reactive<ChatMsg[]>([
  {
    role: 'assistant',
    content:
      '你好！我是会议 AI 助手。你可以随时问我关于会议内容的问题，比如：\n\n• 总结当前讨论要点\n• 提取行动项\n• 解释某个术语或上下文',
    time: '',
  },
])
chatMessages[0].time = formatTime(new Date())

const chatInput = ref('')
const sidebarCollapsed = ref(false)

// ---- Composables ----
const { start: startAudio, stop: stopAudio, getStream, setTrackEnabled } = useAudioCapture()
const { connected, connect: connectWS, sendAudio, sendSignal, disconnect: disconnectWS } = useMeetingWebSocket()
const { isReady: webrtcReady, initialize: initWebRTC, connectToPeer, handleSignal: handleWebRTCSignal, closePeerConnection, closeAll: closeAllWebRTC } = useWebRTC()
const { streaming, ask: askTempChat } = useTempChat()

// ---- 计时器 ----
let timerInterval: ReturnType<typeof setInterval> | null = null
let pollParticipantsTimer: ReturnType<typeof setInterval> | null = null

// ---- 计算属性 ----
const timerDisplay = computed(() => {
  const h = Math.floor(elapsedSeconds.value / 3600)
  const m = Math.floor((elapsedSeconds.value % 3600) / 60)
  const s = elapsedSeconds.value % 60
  return `${h > 0 ? h + ':' : ''}${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
})

const participantList = computed(() => {
  return Array.from(participants.values())
})

const transcriptContext = computed(() => {
  return finalTranscripts.map((t) => `${t.speaker_name}: ${t.text}`).join('\n')
})

// ---- 生命周期 ----
onMounted(async () => {
  try {
    // 1. 加入会议
    const data = await meetingApi.join(meetingId)
    meetingName.value = data.meeting_name
    isHost.value = data.is_host
    meetingStore.setCurrentMeeting(meetingId, data.meeting_name, data.is_host)

    // 初始化参与者（包含自己）
    participants.clear()
    data.participants.forEach((p) => {
      participants.set(p.id, p)
    })

    // 2. 启动麦克风
    await startAudio((pcm: ArrayBuffer) => {
      if (micEnabled.value) {
        sendAudio(pcm)
      }
    })

    // 2.5 初始化 WebRTC（仅注入依赖：麦克风流 + 信令函数）
    // 不在此处发起连接——等 WS 连上后由 handleParticipantsList 回调触发，
    // 确保 sendSignal 时 WS 已 open（参考 frontend_test/meeting.js 方案）
    const stream = getStream()
    if (stream && authStore.userId) {
      initWebRTC(stream, authStore.userId, sendSignal)
    }

    // 3. 连接 WebSocket
    connectWebSocket()

    // 4. 启动计时器
    startTimer()

    // 5. 启动参与者轮询（每 10s）
    pollParticipantsTimer = setInterval(pollParticipants, 10000)
  } catch (e: any) {
    ElMessage.error(e.message || '加入会议失败')
    router.push('/dashboard')
  }
})

onUnmounted(() => {
  cleanup()
})

// ---- WebSocket ----
function connectWebSocket() {
  const token = getAccessToken()
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
  const url = `${proto}//${location.host}/api/v1/meeting/ws/realtime?meeting_id=${encodeURIComponent(meetingId)}&token=${encodeURIComponent(token || '')}`

  connectWS(url, handleWsMessage, handleWsClose)
}

function handleWsMessage(msg: any) {
  switch (msg.type) {
    case 'transcript':
      handleTranscript(msg)
      break
    case 'participants_list':
      handleParticipantsList(msg.participants || [])
      break
    case 'participant_joined':
      handleParticipantJoined(msg.user)
      break
    case 'participant_left':
      handleParticipantLeft(msg.user)
      break
    case 'speech_started':
      speakingSpeakers.add(msg.speaker_id)
      break
    case 'speech_stopped':
      speakingSpeakers.delete(msg.speaker_id)
      break
    case 'meeting_ended':
      handleMeetingEnded(msg.meeting_id, msg.task_id)
      break
    case 'signal':
      handleWebRTCSignal(msg)
      break
  }
}

function handleWsClose(code: number) {
  if (code === 4401) {
    ElMessage.error('认证失败，请重新登录')
    router.push('/login')
  } else if (code === 1000) {
    // 正常关闭
  } else if (code !== 1006) {
    // 1006 是异常断开，后端主动关闭会议连接是正常流程
    console.warn(`WebSocket closed with code: ${code}`)
  }
}

// ---- 转写 ----
function handleTranscript(msg: any) {
  const { speaker_id, speaker_name, text, is_final } = msg
  const entry: TranscriptEntry = {
    speaker_id,
    speaker_name,
    text,
    time: formatTime(new Date()),
    is_final,
  }

  if (is_final) {
    finalTranscripts.push(entry)
    interimTranscripts.delete(speaker_id)
  } else {
    interimTranscripts.set(speaker_id, entry)
  }

  scrollTranscriptToBottom()
}

function scrollTranscriptToBottom() {
  nextTick(() => {
    if (transcriptArea.value) {
      transcriptArea.value.scrollTop = transcriptArea.value.scrollHeight
    }
  })
}

// ---- 参与者 ----
function handleParticipantsList(list: Participant[]) {
  list.forEach((p) => {
    participants.set(p.id, p)
    // WS 已连接，此时发起 WebRTC 连接（参考 meeting.js 方案）
    // connectToPeer 内部已去重（已存在连接则跳过）
    if (webrtcReady.value && p.id !== authStore.userId) {
      connectToPeer(p.id)
    }
  })
}

function handleParticipantJoined(user: Participant) {
  participants.set(user.id, user)
  // 与新人建立 WebRTC P2P 连接
  if (webrtcReady.value && user.id !== authStore.userId) {
    connectToPeer(user.id)
  }
}

function handleParticipantLeft(user: any) {
  participants.delete(user.id)
  speakingSpeakers.delete(user.id)
  // 关闭与该用户的 WebRTC 连接
  closePeerConnection(user.id)
}

async function pollParticipants() {
  try {
    const list = await meetingApi.getParticipants(meetingId)
    list.forEach((p) => {
      participants.set(p.id, p)
    })
  } catch {
    // 静默失败
  }
}

// ---- 麦克风 ----
function toggleMic() {
  micEnabled.value = !micEnabled.value
  // 真正禁用/启用音频轨道（控制 WebRTC 发送 + PCM 采集）
  setTrackEnabled(micEnabled.value)
}

// ---- 结束会议 ----
async function endMeeting() {
  try {
    await ElMessageBox.confirm('确定要结束会议吗？', '结束会议', {
      confirmButtonText: '结束',
      cancelButtonText: '取消',
      type: 'warning',
    })
    const result = await meetingApi.end(meetingId)
    if (result.need_summary) {
      ElMessage.success('会议已结束，正在生成纪要')
    } else {
      ElMessage.success('会议已结束')
    }
    cleanup()
    router.push('/dashboard')
  } catch {
    // 取消
  }
}

function handleMeetingEnded(_meetingId: string, _taskId: string | null) {
  // 立即停止采集和发送音频，确保后端不再接收数据
  cleanup()
  ElMessage.info('主持人结束会议')
  router.push('/dashboard')
}

// ---- 离开会议 ----
function leaveMeeting() {
  cleanup()
  meetingStore.reset()
  router.push('/dashboard')
}

// ---- 清理 ----
function cleanup() {
  stopAudio()
  disconnectWS()
  closeAllWebRTC()
  if (timerInterval) {
    clearInterval(timerInterval)
    timerInterval = null
  }
  if (pollParticipantsTimer) {
    clearInterval(pollParticipantsTimer)
    pollParticipantsTimer = null
  }
}

// ---- 计时器 ----
function startTimer() {
  timerInterval = setInterval(() => {
    elapsedSeconds.value++
  }, 1000)
}

// ---- AI 对话 ----
async function sendChat() {
  const question = chatInput.value.trim()
  if (!question || streaming.value) return

  // 添加用户消息
  chatMessages.push({
    role: 'user',
    content: question,
    time: formatTime(new Date()),
  })

  // 添加占位 AI 消息
  const aiMsg: ChatMsg = {
    role: 'assistant',
    content: '',
    time: formatTime(new Date()),
  }
  chatMessages.push(aiMsg)

  chatInput.value = ''

  try {
    await askTempChat(
      transcriptContext.value,
      question,
      chatMessages.slice(0, -2).map((m) => ({ role: m.role, content: m.content })),
      (token) => {
        aiMsg.content += token
        scrollTranscriptToBottom()
      },
      () => {
        // done
      },
    )
  } catch (e: any) {
    aiMsg.content = '抱歉，对话失败了。'
  }
}

async function handleQuickQuestion(question: string) {
  chatInput.value = question
  await sendChat()
}

// ---- 工具函数 ----
function formatTime(date: Date): string {
  return date.toLocaleTimeString('zh-CN', { hour12: false })
}

// ---- 侧边栏折叠 ----
function toggleSidebar() {
  sidebarCollapsed.value = !sidebarCollapsed.value
}
</script>

<template>
  <div class="meeting-layout" :class="{ 'sidebar-collapsed': sidebarCollapsed }">
    <!-- 左侧主区域 -->
    <div class="main-area">
      <!-- 会议室头部 -->
      <header class="room-header">
        <div class="room-title-block">
          <div class="room-icon">会</div>
          <div class="room-title-text">
            <h2>{{ meetingName || '会议中' }}</h2>
            <div class="room-title-meta">
              <span class="live-dot"></span>
              <span>实时转写中</span>
              <span>·</span>
              <span>会议ID: {{ meetingId.slice(0, 12) }}</span>
              <span v-if="!connected" class="ws-status ws-status-offline">· 离线</span>
              <span v-else class="ws-status ws-status-online">· 在线</span>
            </div>
          </div>
        </div>
        <div class="room-timer">{{ timerDisplay }}</div>
      </header>

      <!-- 参与者条 -->
      <div class="participants-bar">
        <span class="participants-label">参会者</span>
        <div
          v-for="p in participantList"
          :key="p.id"
          class="participant-pill"
          :class="{ speaking: speakingSpeakers.has(p.id) }"
        >
          <div class="pill-avatar" :class="`pill-avatar-${p.id % 4}`">
            {{ p.name?.charAt(0) || '?' }}
          </div>
          <span>{{ p.name }}</span>
          <span v-if="p.id === authStore.userId" class="pill-host">我</span>
          <div class="pill-dot"></div>
        </div>
        <div v-if="participantList.length === 0" class="no-participants">
          暂无参会者
        </div>
      </div>

      <!-- 转写内容区 -->
      <div ref="transcriptArea" class="transcript-area">
        <!-- 最终转写 -->
        <div
          v-for="(t, idx) in finalTranscripts"
          :key="'f' + idx"
          class="transcript-line"
        >
          <div class="tl-speaker">
            <div class="tl-avatar" :class="`tl-avatar-${t.speaker_id % 4}`">
              {{ t.speaker_name?.charAt(0) || '?' }}
            </div>
            <span class="tl-speaker-name">{{ t.speaker_name }}</span>
          </div>
          <div class="tl-content">
            <div class="tl-time">{{ t.time }}</div>
            <div class="tl-text">{{ t.text }}</div>
          </div>
        </div>

        <!-- 临时转写 -->
        <div
          v-for="[tid, t] in interimTranscripts"
          :key="'i' + tid"
          class="transcript-line interim"
        >
          <div class="tl-speaker">
            <div class="tl-avatar" :class="`tl-avatar-${t.speaker_id % 4}`">
              {{ t.speaker_name?.charAt(0) || '?' }}
            </div>
            <span class="tl-speaker-name">{{ t.speaker_name }}</span>
          </div>
          <div class="tl-content">
            <div class="tl-time">{{ t.time }}</div>
            <div class="tl-text">{{ t.text }}</div>
          </div>
        </div>

        <!-- 空状态 -->
        <div
          v-if="finalTranscripts.length === 0 && interimTranscripts.size === 0"
          class="transcript-empty"
        >
          <p>等待参会者发言...</p>
        </div>
      </div>

      <!-- 底部控制栏 -->
      <div class="room-controls">
        <button
          class="ctrl-btn ctrl-btn-mic"
          :class="{ muted: !micEnabled }"
          @click="toggleMic"
        >
          <span>{{ micEnabled ? '🎤' : '🔇' }}</span>
          {{ micEnabled ? '麦克风已开启' : '麦克风已静音' }}
        </button>
        <button class="ctrl-btn ctrl-btn-leave" @click="leaveMeeting">
          <span>🚪</span> 离开会议
        </button>
        <button v-if="isHost" class="ctrl-btn ctrl-btn-end" @click="endMeeting">
          <span>📴</span> 结束会议
        </button>
      </div>
    </div>

    <!-- 右侧 AI 对话侧边栏 -->
    <aside class="sidebar">
      <div class="sidebar-header">
        <div class="sidebar-title">
          <div class="sidebar-icon">AI</div>
          <span>AI 助手</span>
        </div>
        <button class="sidebar-toggle" @click="toggleSidebar">
          {{ sidebarCollapsed ? '⟨' : '⟩' }}
        </button>
      </div>

      <div class="sidebar-protocol">
        <span class="protocol-badge">SSE /temp/question</span>
        <span>基于当前实时转写内容</span>
      </div>

      <!-- 聊天消息 -->
      <div class="chat-messages">
        <div
          v-for="(msg, idx) in chatMessages"
          :key="idx"
          class="chat-msg"
          :class="msg.role === 'user' ? 'chat-msg-user' : 'chat-msg-ai'"
        >
          <div class="chat-bubble">
            <span v-if="msg.content">{{ msg.content }}</span>
            <span v-else class="streaming-cursor"></span>
          </div>
          <span class="chat-time">{{ msg.time }}</span>
        </div>
      </div>

      <!-- 快捷问题 -->
      <div class="quick-questions">
        <button class="qq-chip" @click="handleQuickQuestion('总结当前讨论')">
          总结当前讨论
        </button>
        <button class="qq-chip" @click="handleQuickQuestion('提取行动项')">
          提取行动项
        </button>
        <button class="qq-chip" @click="handleQuickQuestion('列出争议点')">
          列出争议点
        </button>
      </div>

      <!-- 输入区 -->
      <div class="chat-input-area">
        <div class="chat-input-wrapper">
          <textarea
            v-model="chatInput"
            class="chat-input"
            placeholder="向 AI 提问..."
            rows="1"
            :disabled="streaming"
            @keydown.enter.exact.prevent="sendChat"
          ></textarea>
          <button
            class="chat-send-btn"
            :disabled="streaming || !chatInput.trim()"
            @click="sendChat"
          >
            ↑
          </button>
        </div>
      </div>
    </aside>
  </div>
</template>

<style scoped lang="scss">
@use '@/styles/mixins.scss' as *;

// ---- 变量 ----
:host {
  --sb-w: 380px;
}

.meeting-layout {
  display: grid;
  grid-template-columns: 1fr 380px;
  height: 100vh;
  background: var(--color-stone-100);

  &.sidebar-collapsed {
    grid-template-columns: 1fr;

    .sidebar {
      display: none;
    }
  }
}

// ---- 左侧主区域 ----
.main-area {
  display: flex;
  flex-direction: column;
  height: 100vh;
  overflow: hidden;
}

// ---- 会议室头部 ----
.room-header {
  background: white;
  border-bottom: 1px solid var(--color-stone-200);
  padding: 16px 24px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-shrink: 0;
}

.room-title-block {
  display: flex;
  align-items: center;
  gap: 14px;
}

.room-icon {
  width: 40px;
  height: 40px;
  border-radius: 10px;
  background: linear-gradient(135deg, var(--color-amber-400), var(--color-amber-500));
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  color: white;
  font-weight: 700;
  font-family: var(--font-display);
}

.room-title-text h2 {
  font-size: 16px;
  font-weight: 600;
  color: var(--color-stone-800);
}

.room-title-meta {
  font-size: 12px;
  color: var(--color-stone-400);
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 2px;
}

.ws-status {
  font-weight: 600;
}

.ws-status-online {
  color: var(--color-success);
}

.ws-status-offline {
  color: var(--color-error);
}

.live-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--color-error);
  animation: pulse 1.2s infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.5; transform: scale(0.8); }
}

.room-timer {
  font-family: var(--font-mono);
  font-size: 14px;
  font-weight: 600;
  color: var(--color-stone-600);
  background: var(--color-stone-50);
  padding: 4px 10px;
  border-radius: 6px;
}

// ---- 参与者条 ----
.participants-bar {
  background: white;
  border-bottom: 1px solid var(--color-stone-200);
  padding: 12px 24px;
  display: flex;
  align-items: center;
  gap: 16px;
  flex-shrink: 0;
  flex-wrap: wrap;
}

.participants-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--color-stone-500);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.no-participants {
  font-size: 13px;
  color: var(--color-stone-400);
}

.participant-pill {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 12px;
  border-radius: 20px;
  background: var(--color-stone-50);
  border: 1px solid var(--color-stone-200);
  font-size: 13px;
  font-weight: 500;
  color: var(--color-stone-700);
  transition: all 0.2s;

  &.speaking {
    background: #ecfdf5;
    border-color: #a7f3d0;
    color: #065f46;

    .pill-dot {
      background: var(--color-success);
      animation: pulse 1s infinite;
    }
  }
}

.pill-avatar {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 10px;
  font-weight: 700;
  color: white;
}

.pill-avatar-0 { background: var(--color-info); }
.pill-avatar-1 { background: var(--color-success); }
.pill-avatar-2 { background: var(--color-warning); }
.pill-avatar-3 { background: var(--color-purple); }

.pill-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--color-stone-300);
}

.pill-host {
  font-size: 10px;
  font-weight: 600;
  color: var(--color-amber-600);
  background: var(--color-amber-50);
  padding: 2px 6px;
  border-radius: 4px;
}

// ---- 转写内容区 ----
.transcript-area {
  flex: 1;
  overflow-y: auto;
  padding: 24px;
  display: flex;
  flex-direction: column;
  gap: 16px;
  align-items: flex-start;
}

.transcript-empty {
  text-align: center;
  color: var(--color-stone-400);
  padding: 60px 20px;
  font-size: 14px;
}

.transcript-line {
  display: inline-flex;
  gap: 14px;
  padding: 14px 18px;
  background: white;
  border-radius: var(--radius-lg);
  border: 1px solid var(--color-stone-200);
  animation: slideIn 0.3s ease-out;
  transition: all 0.2s;
  max-width: 85%;
  align-self: flex-start;

  &:hover {
    border-color: var(--color-stone-300);
    box-shadow: var(--shadow-sm);
  }

  &.interim {
    opacity: 0.7;
    border-style: dashed;
  }
}

@keyframes slideIn {
  from { opacity: 0; transform: translateY(10px); }
  to { opacity: 1; transform: translateY(0); }
}

.tl-speaker {
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
}

.tl-avatar {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  font-weight: 700;
  color: white;
}

.tl-avatar-0 { background: var(--color-info); }
.tl-avatar-1 { background: var(--color-success); }
.tl-avatar-2 { background: var(--color-warning); }
.tl-avatar-3 { background: var(--color-purple); }

.tl-speaker-name {
  font-size: 11px;
  font-weight: 600;
  color: var(--color-stone-500);
}

.tl-content {
  min-width: 0;
  max-width: 100%;
}

.tl-time {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--color-stone-400);
  margin-bottom: 4px;
}

.tl-text {
  font-size: 15px;
  line-height: 1.6;
  color: var(--color-stone-800);
  white-space: pre-wrap;
  word-wrap: break-word;
  word-break: break-word;
}

.transcript-line.interim .tl-text {
  color: var(--color-stone-400);
  font-style: italic;
}

// ---- 底部控制栏 ----
.room-controls {
  background: white;
  border-top: 1px solid var(--color-stone-200);
  padding: 16px 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 16px;
  flex-shrink: 0;
}

.ctrl-btn {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 20px;
  border: 1.5px solid var(--color-stone-200);
  border-radius: var(--radius-md);
  background: white;
  color: var(--color-stone-700);
  font-size: 14px;
  font-weight: 500;
  font-family: var(--font-body);
  cursor: pointer;
  transition: all 0.15s;

  &:hover {
    background: var(--color-stone-50);
    border-color: var(--color-stone-300);
  }
}

.ctrl-btn-mic {
  background: #f0fdf4;
  border-color: #a7f3d0;
  color: #065f46;

  &.muted {
    background: #fef2f2;
    border-color: #fecaca;
    color: #991b1b;
  }
}

.ctrl-btn-end {
  background: var(--color-error);
  border-color: var(--color-error);
  color: white;

  &:hover {
    background: #dc2626;
    border-color: #dc2626;
  }
}

.ctrl-btn-leave {
  background: white;
  border-color: var(--color-stone-300);
  color: var(--color-stone-600);

  &:hover {
    background: var(--color-stone-50);
    border-color: var(--color-stone-400);
  }
}

// ---- 右侧 AI 对话侧边栏 ----
.sidebar {
  background: white;
  border-left: 1px solid var(--color-stone-200);
  display: flex;
  flex-direction: column;
  height: 100vh;
  overflow: hidden;
}

.sidebar-header {
  padding: 16px 20px;
  border-bottom: 1px solid var(--color-stone-200);
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-shrink: 0;
}

.sidebar-title {
  font-family: var(--font-display);
  font-size: 16px;
  font-weight: 600;
  color: var(--color-stone-800);
  display: flex;
  align-items: center;
  gap: 8px;
}

.sidebar-icon {
  width: 28px;
  height: 28px;
  border-radius: 8px;
  background: linear-gradient(135deg, var(--color-amber-400), var(--color-amber-500));
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  color: white;
  font-weight: 700;
}

.sidebar-toggle {
  width: 32px;
  height: 32px;
  border: none;
  background: var(--color-stone-100);
  border-radius: 6px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--color-stone-500);
  transition: all 0.15s;
  font-size: 18px;

  &:hover {
    background: var(--color-stone-200);
    color: var(--color-stone-700);
  }
}

// ---- 协议提示 ----
.sidebar-protocol {
  padding: 8px 20px;
  border-bottom: 1px solid var(--color-stone-100);
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
  color: var(--color-stone-400);
}

.protocol-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 8px;
  background: var(--color-amber-50);
  border: 1px solid var(--color-amber-200);
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
  color: var(--color-amber-600);
}

// ---- 聊天消息 ----
.chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.chat-msg {
  display: flex;
  flex-direction: column;
  gap: 6px;
  animation: slideIn 0.25s ease-out;
}

.chat-msg-user { align-items: flex-end; }
.chat-msg-ai { align-items: flex-start; }

.chat-bubble {
  max-width: 100%;
  padding: 12px 16px;
  border-radius: var(--radius-lg);
  font-size: 14px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-wrap: break-word;
}

.chat-msg-user .chat-bubble {
  background: var(--color-amber-400);
  color: var(--color-stone-900);
  border-bottom-right-radius: 4px;
}

.chat-msg-ai .chat-bubble {
  background: var(--color-stone-100);
  color: var(--color-stone-800);
  border-bottom-left-radius: 4px;
}

.chat-time {
  font-size: 11px;
  color: var(--color-stone-400);
  padding: 0 4px;
}

// ---- 流式光标 ----
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

// ---- 快捷问题 ----
.quick-questions {
  padding: 0 20px 12px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.qq-chip {
  padding: 6px 12px;
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

// ---- 输入区 ----
.chat-input-area {
  padding: 16px 20px;
  border-top: 1px solid var(--color-stone-200);
  flex-shrink: 0;
}

.chat-input-wrapper {
  display: flex;
  gap: 10px;
  align-items: flex-end;
}

.chat-input {
  flex: 1;
  padding: 12px 16px;
  border: 1.5px solid var(--color-stone-200);
  border-radius: var(--radius-md);
  font-size: 14px;
  font-family: var(--font-body);
  color: var(--color-stone-800);
  background: var(--color-stone-50);
  outline: none;
  resize: none;
  min-height: 44px;
  max-height: 120px;
  line-height: 1.5;
  transition: all 0.2s;

  &:focus {
    border-color: var(--color-amber-400);
    background: white;
    box-shadow: 0 0 0 3px rgba(245, 180, 0, 0.08);
  }

  &:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }
}

.chat-send-btn {
  width: 44px;
  height: 44px;
  border: none;
  border-radius: var(--radius-md);
  background: var(--color-amber-400);
  color: var(--color-stone-900);
  font-size: 18px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.15s;
  flex-shrink: 0;

  &:hover:not(:disabled) {
    background: var(--color-amber-500);
    transform: translateY(-1px);
  }

  &:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }
}

// ---- 响应式 ----
@media (max-width: 1024px) {
  .meeting-layout {
    grid-template-columns: 1fr 320px;
  }
}

@media (max-width: 768px) {
  .meeting-layout {
    grid-template-columns: 1fr;

    .sidebar {
      display: none;
    }
  }
}
</style>
