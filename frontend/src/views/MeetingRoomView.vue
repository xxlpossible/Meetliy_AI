<script setup lang="ts">
// ============================================================
// MeetingRoomView — 实时会议室
// 功能：麦克风采集 → WS 实时转写 / 视频停靠区 / 结束&离开
// ============================================================
import { ref, reactive, computed, onMounted, onUnmounted, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useMeetingStore } from '@/stores'
import { useAuthStore } from '@/stores/auth'
import { meetingApi } from '@/api'
import { getAccessToken } from '@/api/request'
import { useAudioCapture } from '@/composables/useAudioCapture'
import { useMeetingWebSocket } from '@/composables/useMeetingWebSocket'
import { useWebRTC } from '@/composables/useWebRTC'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
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
const copyIdDone = ref(false)  // 复制 ID 成功反馈

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

// ---- 视频停靠区 ----
interface DockedVideo {
  userId: number
  userName: string
  stream: MediaStream | null
  minimizedAt: string
}

const dockedVideos = reactive<DockedVideo[]>([])

const sidebarCollapsed = ref(false)

// ---- Composables ----
const { start: startAudio, stop: stopAudio, getStream, setTrackEnabled } = useAudioCapture()
const { connected, connect: connectWS, sendAudio, sendSignal, disconnect: disconnectWS } = useMeetingWebSocket()
const { isReady: webrtcReady, initialize: initWebRTC, connectToPeer, handleSignal: handleWebRTCSignal, closePeerConnection, closeAll: closeAllWebRTC } = useWebRTC()

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

/** 当前用户是否为会议室内最后一人 */
const isLastParticipant = computed(() => {
  return participants.size <= 1
})

/** 根据用户 id 从参与者列表获取头像（transcript 中使用） */
function getAvatar(userId: number): string | null {
  return participants.get(userId)?.avatar || null
}

// ---- 复制会议 ID ----
async function copyMeetingId() {
  try {
    await navigator.clipboard.writeText(meetingId)
    copyIdDone.value = true
    ElMessage.success('会议 ID 已复制')
    setTimeout(() => { copyIdDone.value = false }, 1500)
  } catch {
    ElMessage.error('复制失败，请手动复制')
  }
}

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
const showEndConfirmDialog = ref(false)

function endMeeting() {
  showEndConfirmDialog.value = true
}

async function confirmEndMeeting() {
  showEndConfirmDialog.value = false
  try {
    const result = await meetingApi.end(meetingId)
    if (result.need_summary) {
      ElMessage.success('会议已结束，正在生成纪要')
    } else {
      ElMessage.success('会议已结束')
    }
  } catch (e: any) {
    ElMessage.error(e.message || '结束会议失败')
  }
  cleanup()
  router.push('/dashboard')
}

function handleMeetingEnded(_meetingId: string, _taskId: string | null) {
  // 立即停止采集和发送音频，确保后端不再接收数据
  cleanup()
  ElMessage.info('主持人结束会议')
  router.push('/dashboard')
}

// ---- 离开会议 ----
const showLeaveConfirmDialog = ref(false)

function leaveMeeting() {
  showLeaveConfirmDialog.value = true
}

function confirmLeaveMeeting() {
  showLeaveConfirmDialog.value = false
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

// ---- 视频停靠区 ----
function addDockedVideo(userId: number, userName: string, stream: MediaStream) {
  // 避免重复添加
  if (dockedVideos.some((v) => v.userId === userId)) return
  dockedVideos.push({
    userId,
    userName,
    stream,
    minimizedAt: formatTime(new Date()),
  })
}

function removeDockedVideo(userId: number) {
  const idx = dockedVideos.findIndex((v) => v.userId === userId)
  if (idx !== -1) {
    dockedVideos.splice(idx, 1)
  }
}

function restoreVideo(userId: number) {
  // 预留：将最小化的视频恢复到主显示区域
  // 后续视频功能上架时实现
  removeDockedVideo(userId)
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
              <button
                class="copy-id-btn"
                :class="{ copied: copyIdDone }"
                title="复制会议 ID"
                @click="copyMeetingId"
              >
                <svg v-if="!copyIdDone" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <rect x="9" y="9" width="13" height="13" rx="2" ry="2"/>
                  <path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/>
                </svg>
                <svg v-else width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                  <polyline points="20 6 9 17 4 12"/>
                </svg>
              </button>
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
          <img v-if="p.avatar" :src="p.avatar" class="pill-avatar-img" alt="" />
          <div v-else class="pill-avatar" :class="`pill-avatar-${p.id % 4}`">
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
            <img v-if="getAvatar(t.speaker_id)" :src="getAvatar(t.speaker_id)" class="tl-avatar-img" alt="" />
            <div v-else class="tl-avatar" :class="`tl-avatar-${t.speaker_id % 4}`">
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
            <img v-if="getAvatar(t.speaker_id)" :src="getAvatar(t.speaker_id)" class="tl-avatar-img" alt="" />
            <div v-else class="tl-avatar" :class="`tl-avatar-${t.speaker_id % 4}`">
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
        <div class="ctrl-group">
          <button
            class="ctrl-btn ctrl-btn-mic"
            :class="{ muted: !micEnabled }"
            @click="toggleMic"
          >
            <span>{{ micEnabled ? '🎤' : '🔇' }}</span>
          </button>
          <span class="ctrl-label">关闭<br>麦克风</span>
        </div>
        <div class="ctrl-group">
          <button class="ctrl-btn ctrl-btn-leave" @click="leaveMeeting">
            <span>🚪</span>
          </button>
          <span class="ctrl-label">离开<br>会议</span>
        </div>
        <div v-if="isHost" class="ctrl-group">
          <button class="ctrl-btn ctrl-btn-end" @click="endMeeting">
            <span>⏹</span>
          </button>
          <span class="ctrl-label">结束<br>会议</span>
        </div>
      </div>
    </div>

    <!-- 侧边栏展开按钮（收起时显示） -->
    <button
      v-show="sidebarCollapsed"
      class="sidebar-expand-btn"
      @click="toggleSidebar"
      title="展开视频停靠区"
    >
      ⟨
    </button>

    <!-- 右侧视频停靠区 -->
    <aside class="sidebar">
      <div class="sidebar-header">
        <div class="sidebar-title">
          <div class="sidebar-icon">📹</div>
          <span>视频停靠区</span>
        </div>
        <button class="sidebar-toggle" @click="toggleSidebar">
          {{ sidebarCollapsed ? '⟨' : '⟩' }}
        </button>
      </div>

      <div class="sidebar-hint">
        <span class="hint-badge">视频停靠</span>
        <span>最小化的视频窗口将显示在此处</span>
      </div>

      <div class="sidebar-wip-banner">
        <span class="wip-icon">🚧</span>
        <span>视频功能开发中，敬请期待</span>
      </div>

      <!-- 停靠视频列表 -->
      <div class="docked-videos">
        <div
          v-for="video in dockedVideos"
          :key="video.userId"
          class="docked-video-card"
        >
          <div class="docked-video-preview">
            <video
              v-if="video.stream"
              :srcObject="video.stream"
              autoplay
              muted
              playsinline
              class="docked-video-element"
            ></video>
            <div v-else class="docked-video-placeholder">
              <div class="docked-video-avatar">{{ video.userName?.charAt(0) || '?' }}</div>
            </div>
          </div>
          <div class="docked-video-info">
            <span class="docked-video-name">{{ video.userName }}</span>
            <span class="docked-video-time">{{ video.minimizedAt }}</span>
          </div>
          <button
            class="docked-video-restore"
            title="恢复视频"
            @click="restoreVideo(video.userId)"
          >
            ↥
          </button>
          <button
            class="docked-video-close"
            title="关闭视频"
            @click="removeDockedVideo(video.userId)"
          >
            ✕
          </button>
        </div>

        <!-- 空状态 -->
        <div v-if="dockedVideos.length === 0" class="docked-videos-empty">
          <div class="empty-icon">🎥</div>
          <p>暂无停靠的视频</p>
          <p class="empty-hint">开启摄像头并最小化后，视频将出现在这里</p>
        </div>
      </div>
    </aside>

    <!-- 结束会议确认弹窗 -->
    <ConfirmDialog
      :visible="showEndConfirmDialog"
      title="结束会议"
      message="确定要结束会议吗？结束后所有参会者将被移出。"
      confirm-text="结束会议"
      cancel-text="取消"
      type="warning"
      @close="showEndConfirmDialog = false"
      @confirm="confirmEndMeeting"
    />

    <!-- 离开会议确认弹窗 -->
    <ConfirmDialog
      :visible="showLeaveConfirmDialog"
      title="离开会议室"
      :message="isLastParticipant
        ? '您离开后会议室将被销毁，会议自动结束。'
        : '确定要离开会议室吗？'"
      confirm-text="离开"
      cancel-text="取消"
      :type="isLastParticipant ? 'danger' : 'warning'"
      :subtitle="isLastParticipant ? '您是会议室内最后一人' : ''"
      @close="showLeaveConfirmDialog = false"
      @confirm="confirmLeaveMeeting"
    />
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

// ---- 侧边栏展开按钮（折叠时悬浮在右侧） ----
.sidebar-expand-btn {
  position: fixed;
  right: 12px;
  top: 50%;
  transform: translateY(-50%);
  width: 32px;
  height: 64px;
  border: 1px solid var(--color-stone-200);
  border-radius: 8px 0 0 8px;
  background: white;
  color: var(--color-stone-500);
  font-size: 16px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
  box-shadow: -2px 0 8px rgba(0, 0, 0, 0.06);
  transition: all 0.2s;

  &:hover {
    background: var(--color-stone-50);
    color: var(--color-stone-700);
    border-color: var(--color-stone-300);
    box-shadow: -2px 0 12px rgba(0, 0, 0, 0.1);
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

// 复制会议 ID 按钮
.copy-id-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border: none;
  border-radius: 5px;
  background: transparent;
  color: var(--color-stone-400);
  cursor: pointer;
  transition: all 0.15s;
  flex-shrink: 0;

  &:hover {
    background: var(--color-amber-50);
    color: var(--color-amber-500);
  }

  &:active {
    transform: scale(0.9);
  }

  &.copied {
    background: var(--color-amber-50);
    color: var(--color-amber-500);
  }
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

.pill-avatar-img {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  object-fit: cover;
  display: block;
  flex-shrink: 0;
}

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

.tl-avatar-img {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  object-fit: cover;
  display: block;
}

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
  padding: 12px 24px max(12px, var(--safe-area-bottom));
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 48px;
  flex-shrink: 0;
}

.ctrl-group {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
}

.ctrl-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 52px;
  height: 52px;
  border-radius: 50%;
  border: 1.5px solid var(--color-stone-200);
  background: white;
  color: var(--color-stone-700);
  font-size: 20px;
  cursor: pointer;
  transition: all 0.15s;

  span { line-height: 1; }

  &:active {
    transform: scale(0.92);
  }
}

.ctrl-label {
  font-size: 10px;
  color: var(--color-stone-500);
  text-align: center;
  line-height: 1.3;
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

  &:active {
    background: #dc2626;
  }
}

.ctrl-btn-leave {
  background: var(--color-warning);
  border-color: var(--color-warning);
  color: white;

  &:active {
    background: #d97706;
  }
}

// ---- 右侧视频停靠侧边栏 ----
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

// ---- 停靠区提示 ----
.sidebar-hint {
  padding: 8px 20px;
  border-bottom: 1px solid var(--color-stone-100);
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
  color: var(--color-stone-400);
}

.hint-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 8px;
  background: var(--color-info-light, #e0f2fe);
  border: 1px solid var(--color-info-border, #bae6fd);
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
  color: var(--color-info, #0284c7);
}

// ---- 视频功能未完提示 ----
.sidebar-wip-banner {
  margin: 8px 16px;
  padding: 8px 14px;
  background: var(--color-warning-light, #fef3c7);
  border: 1px solid var(--color-warning-border, #fcd34d);
  border-radius: var(--radius-md);
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  font-weight: 500;
  color: var(--color-warning, #b45309);

  .wip-icon {
    font-size: 14px;
    flex-shrink: 0;
  }
}

// ---- 停靠视频列表 ----
.docked-videos {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.docked-video-card {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  background: var(--color-stone-50);
  border: 1px solid var(--color-stone-200);
  border-radius: var(--radius-md);
  animation: slideIn 0.25s ease-out;
  transition: all 0.15s;

  &:hover {
    border-color: var(--color-stone-300);
    box-shadow: var(--shadow-sm);
  }
}

.docked-video-preview {
  width: 56px;
  height: 42px;
  border-radius: 6px;
  overflow: hidden;
  flex-shrink: 0;
  background: var(--color-stone-200);
  display: flex;
  align-items: center;
  justify-content: center;
}

.docked-video-element {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.docked-video-placeholder {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, var(--color-stone-300), var(--color-stone-400));
}

.docked-video-avatar {
  font-size: 16px;
  font-weight: 700;
  color: white;
}

.docked-video-info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.docked-video-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-stone-700);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.docked-video-time {
  font-size: 11px;
  color: var(--color-stone-400);
  font-family: var(--font-mono);
}

.docked-video-restore,
.docked-video-close {
  width: 28px;
  height: 28px;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  font-size: 14px;
  transition: all 0.15s;
}

.docked-video-restore {
  background: var(--color-info-light, #e0f2fe);
  color: var(--color-info, #0284c7);

  &:hover {
    background: var(--color-info, #0284c7);
    color: white;
  }
}

.docked-video-close {
  background: var(--color-stone-100);
  color: var(--color-stone-500);

  &:hover {
    background: var(--color-error);
    color: white;
  }
}

// ---- 停靠区空状态 ----
.docked-videos-empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: 40px 20px;
  color: var(--color-stone-400);

  .empty-icon {
    font-size: 36px;
    margin-bottom: 12px;
    opacity: 0.6;
  }

  p {
    font-size: 14px;
    margin: 0 0 4px;
    color: var(--color-stone-500);
  }

  .empty-hint {
    font-size: 12px;
    color: var(--color-stone-400);
    margin-top: 4px;
  }
}

// ---- 响应式 ----
@media (max-width: 1024px) {
  .meeting-layout {
    grid-template-columns: 1fr 320px;
  }
}

@include respond-to(md) {
  .meeting-layout {
    grid-template-columns: 1fr;

    .sidebar {
      display: none;
    }
  }

  .room-header {
    padding: 12px 16px;
    flex-wrap: wrap;
    gap: 10px;
  }

  .room-title-text h2 {
    font-size: 14px;
  }

  .room-title-meta {
    flex-wrap: wrap;
    gap: 6px;
    font-size: 11px;
  }

  .room-timer {
    font-size: 12px;
    padding: 3px 8px;
  }

  .participants-bar {
    padding: 10px 16px;
    gap: 10px;
  }

  .participants-label {
    font-size: 11px;
  }

  .participant-pill {
    padding: 4px 10px;
    font-size: 12px;
    gap: 6px;
  }

  .pill-avatar {
    width: 20px;
    height: 20px;
    font-size: 9px;
  }

  .transcript-area {
    padding: 16px;
    gap: 12px;
  }

  .transcript-line {
    max-width: 95%;
    padding: 12px 14px;
  }

  .tl-text {
    font-size: 14px;
  }

  .room-controls {
    padding: 12px 16px;
    gap: 32px;
    flex-wrap: wrap;
  }

  .ctrl-btn {
    padding: 8px 14px;
    font-size: 13px;
    gap: 4px;

    span {
      font-size: 14px;
    }
  }
}

@include respond-to(sm) {
  // 头部渐变背景（参照 mobile-responsive 设计 meeting-room-header）
  .room-header {
    background: linear-gradient(160deg, var(--color-amber-50) 0%, var(--color-stone-50) 100%);
    border-bottom: 1px solid var(--color-stone-100);
  }

  .room-title-block {
    gap: 8px;
  }

  .room-icon {
    width: 32px;
    height: 32px;
    font-size: 14px;
  }

  .participants-bar {
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
    flex-wrap: nowrap;

    &::-webkit-scrollbar { height: 0; }
    -ms-overflow-style: none;
    scrollbar-width: none;
  }

  // 参与者 chip：头像放大 + 说话时琥珀描边
  .participant-pill {
    flex-shrink: 0;

    &.speaking {
      background: white;
      border-color: var(--color-amber-400);

      .pill-avatar,
      .pill-avatar-img {
        box-shadow: 0 0 0 2px var(--color-amber-400);
      }
    }
  }

  .pill-avatar,
  .pill-avatar-img {
    width: 28px;
    height: 28px;
    font-size: 11px;
  }

  .transcript-area {
    padding: 12px;
    gap: 10px;
  }

  .transcript-line {
    max-width: 100%;
    padding: 10px 12px;
    gap: 10px;
  }

  .tl-avatar {
    width: 28px;
    height: 28px;
    font-size: 11px;
  }

  .tl-speaker-name {
    font-size: 10px;
  }

  .tl-text {
    font-size: 13px;
  }

  .room-controls {
    gap: 24px;
    padding: 10px 16px max(10px, var(--safe-area-bottom));
  }
}
</style>
