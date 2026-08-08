<script setup lang="ts">
// ============================================================
// DashboardView — 会议工作空间
// 功能：仪表盘统计卡 / 会议列表 / 状态门控 / 自动轮询
// ============================================================
import { ref, reactive, onMounted, onUnmounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import DefaultLayout from '@/layouts/DefaultLayout.vue'
import { meetingApi } from '@/api'
import type { MeetingItem, MeetingStatusItem, MeetingStatisticsData } from '@/api/types'
import { MeetingStatus } from '@/api/types'
import { useAuthStore } from '@/stores'

const router = useRouter()
const auth = useAuthStore()

// ---- 状态 ----
const loading = ref(false)     // 首次加载（无数据时的全屏骨架）
const isFetching = ref(false)  // 翻页/搜索中的数据请求（不遮挡现有内容）
const meetingList = ref<MeetingItem[]>([])
const meetingStatusMap = reactive<Map<string, MeetingStatusItem>>(new Map())
const activeFilter = ref('all') // all | active | analyzing | finish | error
const joinDialogVisible = ref(false)
const joinMeetingId = ref('')
const currentPage = ref(1)
const pageSize = ref(6)
const totalCount = ref(0)
const searchKeyword = ref('')
const searchInput = ref('')

// ---- 删除会议弹窗 ----
const deleteDialogVisible = ref(false)
const deleteTarget = ref<MeetingItem | null>(null)

// ---- 创建会议弹窗 ----
const createDialogVisible = ref(false)
const createMeetingName = ref('')
const createNeedSummary = ref(false)
const createLoading = ref(false)

// ---- 自动轮询 ----
const POLL_INTERVAL = 10000 // 10 秒
let pollTimer: ReturnType<typeof setInterval> | null = null

// ---- 仪表盘统计 ----
const stats = reactive({
  total: 0,
  finish: 0,
  analyzing: 0,
  active: 0,
  error: 0,
})

// ---- 计算属性 ----
const filteredMeetings = computed(() => {
  if (activeFilter.value === 'all') return meetingList.value
  return meetingList.value.filter((m) => {
    const statusCode = resolveStatus(m)
    if (activeFilter.value === 'active') return statusCode === MeetingStatus.ACTIVE
    if (activeFilter.value === 'analyzing') return statusCode === MeetingStatus.END_AND_ANALYZE
    if (activeFilter.value === 'finish') return statusCode === MeetingStatus.FINISH
    if (activeFilter.value === 'error') return statusCode === MeetingStatus.ERROR
    return true
  })
})

/** 当前页是否有解析中/进行中的会议（决定是否启动轮询） */
const hasCurrentPageProcessing = computed(
  () => meetingList.value.some((m) => {
    const s = resolveStatus(m)
    return s === MeetingStatus.ACTIVE || s === MeetingStatus.END_AND_ANALYZE
  })
)

/**
 * 解析会议状态：优先使用 meetingStatusMap 中最新状态，否则用列表中的 status
 */
function resolveStatus(m: MeetingItem): number {
  const latest = meetingStatusMap.get(m.id)
  if (latest !== undefined) return latest.status
  return m.status
}

function getStatusInfo(
  m: MeetingItem
): { label: string; type: 'active' | 'analyzing' | 'finish' | 'error' } {
  const s = resolveStatus(m)
  if (s === MeetingStatus.FINISH) return { label: '解析完成', type: 'finish' }
  if (s === MeetingStatus.ERROR) return { label: '解析异常', type: 'error' }
  if (s === MeetingStatus.END_AND_ANALYZE) return { label: '解析中', type: 'analyzing' }
  if (s === MeetingStatus.ACTIVE) return { label: '进行中', type: 'active' }
  return { label: '未知', type: 'active' }
}

// ---- 数据加载 ----
async function loadData() {
  // 首次加载：显示骨架屏；翻页/搜索：仅显示顶部加载条，保留旧数据
  if (meetingList.value.length === 0) {
    loading.value = true
  } else {
    isFetching.value = true
  }

  try {
    // 将前端筛选映射为后端 status 参数
    const statusParam = filterToStatus(activeFilter.value)
    const listData = await meetingApi.list(currentPage.value, pageSize.value, searchKeyword.value || undefined, statusParam)

    // 先赋值列表，确保 refreshStatuses 读取的是新 ID
    meetingList.value = listData.data
    totalCount.value = listData.total

    // 批量查询所有会议最新状态
    const meetingIds = listData.data.map((m) => m.id)
    if (meetingIds.length > 0) {
      await refreshStatuses(meetingIds)
    }

    // 用后端统计接口刷新仪表盘
    await loadStatistics()
  } catch (e: any) {
    ElMessage.error(e.message || '加载失败，请稍后重试')
  } finally {
    loading.value = false
    isFetching.value = false
    // 启动/停止轮询
    togglePolling()
  }
}

/** 搜索 */
function handleSearch() {
  searchKeyword.value = searchInput.value.trim()
  currentPage.value = 1
  loadData()
}

/** 将前端筛选映射为后端 status 参数 */
function filterToStatus(filter: string): number | undefined {
  if (filter === 'active') return MeetingStatus.ACTIVE         // 0
  if (filter === 'analyzing') return MeetingStatus.END_AND_ANALYZE // 1
  if (filter === 'finish') return MeetingStatus.FINISH          // 2
  if (filter === 'error') return MeetingStatus.ERROR            // -1
  return undefined // 'all' → 不传 status，由后端返回全部
}

/** 切换筛选并重新加载 */
function setActiveFilter(filter: string) {
  activeFilter.value = filter
  currentPage.value = 1
  loadData()
}

/** 删除会议 */
async function handleDeleteMeeting(meeting: MeetingItem, event: Event) {
  event.stopPropagation()
  deleteTarget.value = meeting
  deleteDialogVisible.value = true
}

function confirmDelete() {
  if (!deleteTarget.value) return
  const meeting = deleteTarget.value
  deleteDialogVisible.value = false
  deleteTarget.value = null
  
  meetingApi.deleteMeeting(meeting.id).then(() => {
    ElMessage.success('会议已删除')
    loadData()
  }).catch((e: any) => {
    ElMessage.error(e.message || '删除失败')
  })
}

/** 刷新会议状态（不加载列表，仅查询状态并更新 map） */
async function refreshStatuses(ids?: string[]) {
  let meetingIds = ids || meetingList.value.map((m) => m.id)

  // 只轮询未完成解析的会议（进行中或解析中）
  meetingIds = meetingIds.filter((id) => {
    const m = meetingList.value.find((item) => item.id === id)
    if (m) {
      const statusCode = resolveStatus(m)
      return statusCode === MeetingStatus.ACTIVE || statusCode === MeetingStatus.END_AND_ANALYZE
    }
    // 如果不在列表中（外部传入的 ID），也包含进来
    return true
  })

  if (meetingIds.length === 0) return

  const statusList = await meetingApi.getStatus(meetingIds)
  statusList.forEach((s) => meetingStatusMap.set(s.meeting_id, s))

  // 状态可能已变化，重新拉取统计（用于仪表盘数字实时更新）
  loadStatistics()
}

/**
 * 从后端统计接口拉取会议状态分布，填充仪表盘数字。
 * 取代原先基于列表前端统计的方式，避免只统计到当前分页的会议。
 */
async function loadStatistics() {
  try {
    const data: MeetingStatisticsData = await meetingApi.statistics()
    stats.total = data.total
    stats.active = data.active
    stats.analyzing = data.analyzing
    stats.finish = data.finished
    stats.error = data.error
  } catch {
    // 统计失败不应阻断会议列表展示，静默忽略
  }
}

// ---- 自动轮询 ----
function togglePolling() {
  if (hasCurrentPageProcessing.value && !pollTimer) {
    pollTimer = setInterval(() => {
      // 每次轮询前重新检查当前页是否有处理中的会议
      if (hasCurrentPageProcessing.value) {
        refreshStatuses()
      } else {
        // 停止轮询
        clearInterval(pollTimer!)
        pollTimer = null
      }
    }, POLL_INTERVAL)
  } else if (!hasCurrentPageProcessing.value && pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

// ---- 状态门控 ----
function handleCardClick(m: MeetingItem) {
  const statusInfo = getStatusInfo(m)
  if (statusInfo.type === 'active') {
    // 会议进行中，允许中途重新进入
    router.push(`/meeting/room/${m.id}`)
    return
  }
  if (statusInfo.type === 'analyzing') {
    ElMessage.warning('会议正在解析中，请稍后再试')
    return
  }
  if (statusInfo.type === 'error') {
    ElMessage.error('会议解析出错，无法查看详情')
    return
  }
  // 解析完成 → 跳转详情页（need_summary=false 显示实时转录，need_summary=true 显示 AI 纪要）
  router.push(`/meeting/detail/${m.id}`)
}

// ---- 快速操作 ----
function handleCreateMeeting() {
  createMeetingName.value = ''
  createNeedSummary.value = false
  createDialogVisible.value = true
}

async function handleCreateConfirm() {
  try {
    createLoading.value = true
    const data = await meetingApi.create(createMeetingName.value.trim() || undefined, createNeedSummary.value)
    createDialogVisible.value = false
    ElMessage.success('会议已创建')
    router.push(`/meeting/room/${data.meeting_id}`)
  } catch (e: any) {
    ElMessage.error(e.message || '创建会议失败')
  } finally {
    createLoading.value = false
  }
}

async function handleJoinMeeting() {
  if (!joinMeetingId.value.trim()) {
    ElMessage.warning('请输入会议 ID')
    return
  }
  const id = joinMeetingId.value.trim()
  joinDialogVisible.value = false
  router.push(`/meeting/room/${id}`)
}

async function handleUploadAudio(uploadFile: File) {
  try {
    loading.value = true
    await meetingApi.uploadFile(uploadFile, uploadFile.name)
    ElMessage.success('录音已上传，正在解析中...')
    // 上传成功后刷新列表，不跳转到详情页（任务尚未解析完成）
    loadData()
  } catch (e: any) {
    ElMessage.error(e.message || '上传失败')
  } finally {
    loading.value = false
  }
}

onMounted(loadData)
onUnmounted(stopPolling)
</script>

<template>
  <DefaultLayout>
    <div class="dashboard">
      <!-- ========== 移动端英雄区（仅小屏显示，参照 mobile-responsive 设计） ========== -->
      <div class="mobile-hero">
        <div class="dashboard-greeting">
          早上好<span v-if="auth.username">，{{ auth.username }}</span>
        </div>
        <div class="dashboard-subtitle">今天有 {{ stats.active }} 场会议待处理</div>
        <div class="dashboard-quick-actions">
          <button type="button" class="quick-action-btn quick-action-primary" @click="handleCreateMeeting">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
            新建会议
          </button>
          <button type="button" class="quick-action-btn quick-action-secondary" @click="joinDialogVisible = true">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4"/><polyline points="10 17 15 12 10 7"/></svg>
            加入
          </button>
          <el-upload
            class="quick-action-upload"
            :show-file-list="false"
            :before-upload="handleUploadAudio"
            accept=".mp3,.wav,.m4a,.ogg,.flac"
          >
            <button type="button" class="quick-action-btn quick-action-secondary" :disabled="loading">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M12 19V5"/><polyline points="5 12 12 5 19 12"/></svg>
              上传
            </button>
          </el-upload>
        </div>
      </div>

      <!-- ========== 页头（桌面/平板显示） ========== -->
      <div class="page-header desktop-only">
        <div>
          <h1 class="page-title">会议工作空间</h1>
          <p class="page-subtitle">管理您的会议记录、追踪处理进度</p>
        </div>
        <div class="quick-actions">
          <el-upload
            :show-file-list="false"
            :before-upload="handleUploadAudio"
            accept=".mp3,.wav,.m4a,.ogg,.flac"
          >
            <el-button size="large" :disabled="loading">⬆ 上传录音</el-button>
          </el-upload>
          <el-button type="primary" size="large" @click="handleCreateMeeting"
            >+ 创建会议</el-button
          >
          <el-button type="success" size="large" @click="joinDialogVisible = true"
            >↗ 加入会议</el-button
          >
        </div>
      </div>

      <!-- ========== 仪表盘统计 ========== -->
      <div class="stats-row">
        <div class="stat-card stat-card-total" @click="setActiveFilter('all')">
          <div class="stat-icon stat-icon-amber">📋</div>
          <div class="stat-value">{{ stats.total }}</div>
          <div class="stat-label">全部会议</div>
        </div>
        <div class="stat-card stat-card-finish" @click="setActiveFilter('finish')">
          <div class="stat-icon stat-icon-green">✅</div>
          <div class="stat-value">{{ stats.finish }}</div>
          <div class="stat-label">解析完成</div>
        </div>
        <div class="stat-card stat-card-analyzing" @click="setActiveFilter('analyzing')">
          <div class="stat-icon stat-icon-blue">⏳</div>
          <div class="stat-value">{{ stats.analyzing }}</div>
          <div class="stat-label">解析中</div>
        </div>
        <div class="stat-card stat-card-error" @click="setActiveFilter('error')">
          <div class="stat-icon stat-icon-red">⚠</div>
          <div class="stat-value">{{ stats.error }}</div>
          <div class="stat-label">解析异常</div>
        </div>
      </div>

      <!-- ========== 会议列表 ========== -->
      <div class="meeting-list">
        <!-- 顶部加载条（翻页/搜索时显示，不遮挡内容） -->
        <div v-if="isFetching" class="fetching-bar"></div>

        <div class="section-header">
          <div class="title-row">
            <h2 class="section-title">最近会议</h2>
            <div class="search-box">
              <input
                v-model="searchInput"
                type="text"
                placeholder="搜索会议名称..."
                @keyup.enter="handleSearch"
              />
              <button class="search-btn" @click="handleSearch">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                  <circle cx="11" cy="11" r="8"/>
                  <path d="m21 21-4.3-4.3"/>
                </svg>
              </button>
            </div>
          </div>
          <div class="filter-tabs">
            <button
              class="filter-tab"
              :class="{ active: activeFilter === 'all' }"
              @click="setActiveFilter('all')"
            >
              全部
            </button>
            <button
              class="filter-tab"
              :class="{ active: activeFilter === 'active' }"
              @click="setActiveFilter('active')"
            >
              进行中
            </button>
            <button
              class="filter-tab"
              :class="{ active: activeFilter === 'analyzing' }"
              @click="setActiveFilter('analyzing')"
            >
              解析中
            </button>
            <button
              class="filter-tab"
              :class="{ active: activeFilter === 'finish' }"
              @click="setActiveFilter('finish')"
            >
              已完成
            </button>
            <button
              class="filter-tab"
              :class="{ active: activeFilter === 'error' }"
              @click="setActiveFilter('error')"
            >
              异常
            </button>
          </div>
        </div>

        <!-- 加载骨架（仅首次加载、列表为空时显示） -->
        <div v-if="loading" class="meeting-grid">
          <el-skeleton v-for="i in 4" :key="i" :rows="3" animated class="meeting-card-skeleton" />
        </div>

        <!-- 空状态 -->
        <div v-else-if="filteredMeetings.length === 0" class="empty-state">
          <div class="empty-state-icon">📭</div>
          <h3>暂无会议记录</h3>
          <p>
            {{
              activeFilter === 'all'
                ? '点击"创建会议"或"上传录音"开始'
                : '该筛选条件下没有记录'
            }}
          </p>
          <el-button
            v-if="activeFilter !== 'all'"
            @click="setActiveFilter('all')"
            type="primary"
            plain
            >查看全部</el-button
          >
        </div>

        <!-- 卡片网格 -->
        <div v-else class="meeting-grid">
          <article
            v-for="item in filteredMeetings"
            :key="item.id"
            class="meeting-card"
            :class="{
              'meeting-card-disabled': getStatusInfo(item).type === 'analyzing'
            }"
            @click="handleCardClick(item)"
          >
            <button
              class="card-delete-btn"
              title="删除会议"
              @click="handleDeleteMeeting(item, $event)"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
              </svg>
            </button>
            <div class="card-top">
              <span class="card-type-badge" :class="`type-${getStatusInfo(item).type}`">
                <span class="status-dot"></span> {{ getStatusInfo(item).label }}
              </span>
            </div>

            <div class="card-main">
              <div class="card-avatar" :class="getStatusInfo(item).type === 'error' ? 'stone' : 'amber'">
                {{ (item.meeting_name || '会').charAt(0) }}
              </div>
              <div class="card-info">
                <h3 class="card-title">{{ item.meeting_name || '未命名会议' }}</h3>

                <div class="card-meta">
                  <span class="card-meta-item">📅 {{ item.create_time || '未知时间' }}</span>
                </div>
              </div>
            </div>

            <div class="card-footer">
              <span class="status-badge" :class="`status-${getStatusInfo(item).type}`">
                <span class="status-dot"></span> {{ getStatusInfo(item).label }}
              </span>
              <span v-if="item.need_summary === false" class="no-summary-badge">
                🎙 实时转录
              </span>
            </div>
          </article>
        </div>

        <!-- 分页器 -->
        <div v-if="totalCount > pageSize" class="pagination-wrapper">
          <el-pagination
            v-model:current-page="currentPage"
            :total="totalCount"
            :page-size="pageSize"
            layout="prev, pager, next"
            @current-change="loadData"
          />
        </div>
      </div>

      <!-- 加入会议对话框 -->
      <div v-if="joinDialogVisible" class="modal-overlay" @click.self="joinDialogVisible = false">
        <div class="modal">
          <div class="modal-header">
            <div>
              <h2 class="modal-title">加入会议</h2>
              <p class="modal-subtitle">输入会议 ID 加入已有会议</p>
            </div>
            <button class="modal-close" @click="joinDialogVisible = false">✕</button>
          </div>
          <div class="modal-body">
            <div class="form-group">
              <label class="form-label">会议 ID</label>
              <input
                v-model="joinMeetingId"
                type="text"
                placeholder="请输入会议 ID"
                class="form-input"
                @keyup.enter="handleJoinMeeting"
              />
            </div>
          </div>
          <div class="modal-footer">
            <button class="btn-secondary" @click="joinDialogVisible = false">取消</button>
            <button class="btn-primary" @click="handleJoinMeeting">加入</button>
          </div>
        </div>
      </div>

      <!-- 创建会议对话框 -->
      <div v-if="createDialogVisible" class="modal-overlay" @click.self="createDialogVisible = false">
        <div class="modal">
          <div class="modal-header">
            <div>
              <h2 class="modal-title">创建会议</h2>
              <p class="modal-subtitle">创建一场新会议并邀请他人加入</p>
            </div>
            <button class="modal-close" @click="createDialogVisible = false">✕</button>
          </div>
          <div class="modal-body">
            <div class="form-group">
              <label class="form-label">会议名称（选填）</label>
              <input
                v-model="createMeetingName"
                type="text"
                placeholder="请输入会议名称"
                class="form-input"
              />
            </div>
            <div class="form-group">
              <label class="form-label">会议结束后生成纪要</label>
              <div class="switch-row">
                <button
                  class="switch-toggle"
                  :class="{ active: createNeedSummary }"
                  @click="createNeedSummary = !createNeedSummary"
                >
                  <span class="switch-dot"></span>
                </button>
                <span class="switch-label">{{ createNeedSummary ? '需要生成纪要' : '无需生成纪要' }}</span>
              </div>
            </div>
          </div>
          <div class="modal-footer">
            <button class="btn-secondary" @click="createDialogVisible = false">取消</button>
            <button class="btn-primary" :disabled="createLoading" @click="handleCreateConfirm">
              <span v-if="createLoading" class="loading-spinner"></span>
              {{ createLoading ? '创建中...' : '创建' }}
            </button>
          </div>
        </div>
      </div>

      <!-- 删除会议对话框 -->
      <div v-if="deleteDialogVisible" class="modal-overlay" @click.self="deleteDialogVisible = false">
        <div class="modal modal-sm">
          <div class="modal-header">
            <div>
              <h2 class="modal-title">删除会议</h2>
              <p class="modal-subtitle">此操作不可恢复，请确认</p>
            </div>
            <button class="modal-close" @click="deleteDialogVisible = false">✕</button>
          </div>
          <div class="modal-body">
            <div class="delete-content">
              <div class="delete-icon">⚠</div>
              <p class="delete-text">
                确定要删除会议「<span class="delete-name">{{ deleteTarget?.meeting_name }}</span>」吗？删除后将无法恢复。
              </p>
            </div>
          </div>
          <div class="modal-footer">
            <button class="btn-secondary" @click="deleteDialogVisible = false">取消</button>
            <button class="btn-danger" @click="confirmDelete">删除</button>
          </div>
        </div>
      </div>
    </div>
  </DefaultLayout>
</template>

<style scoped lang="scss">
@use '@/styles/mixins.scss' as *;

.dashboard {
  max-width: 1200px;
  margin: 0 auto;
  padding: $space-8;
}

// ---- 页头 ----
.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: $space-8;
}

.page-title {
  font-size: 28px;
  font-weight: 700;
  color: var(--color-stone-800);
  font-family: var(--font-display);
}

.page-subtitle {
  font-size: 14px;
  color: var(--color-stone-500);
  margin-top: 4px;
}

.quick-actions {
  display: flex;
  gap: 12px;
}

// ---- 统计卡 ----
.stats-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 20px;
  margin-bottom: 36px;
}

.stat-card {
  background: white;
  border: 1px solid var(--color-stone-200);
  border-radius: var(--radius-lg);
  padding: 24px;
  cursor: pointer;
  transition: all $transition-normal;

  &:hover {
    box-shadow: $shadow-md;
    transform: translateY(-2px);
  }

  &.stat-card-finish:hover {
    border-color: var(--color-success);
  }
  &.stat-card-analyzing:hover {
    border-color: var(--color-info);
  }
  &.stat-card-error:hover {
    border-color: var(--color-error);
  }
  &.stat-card-total:hover {
    border-color: var(--color-amber-400);
  }
}

.stat-icon {
  width: 40px;
  height: 40px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  margin-bottom: 14px;
}

.stat-icon-amber {
  background: var(--color-amber-50);
  color: var(--color-amber-600);
}
.stat-icon-green {
  background: #ecfdf5;
  color: var(--color-success);
}
.stat-icon-blue {
  background: #eff6ff;
  color: var(--color-info);
}
.stat-icon-red {
  background: #fef2f2;
  color: var(--color-error);
}

.stat-value {
  font-size: 28px;
  font-weight: 700;
  color: var(--color-stone-800);
  line-height: 1;
  margin-bottom: 4px;
}

.stat-label {
  font-size: 13px;
  color: var(--color-stone-500);
  font-weight: 500;
}

// ---- 列表区 ----
.meeting-list {
  min-height: 300px;
  position: relative;
}

// 翻页/搜索加载条（顶部细条不遮挡内容）
.fetching-bar {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 3px;
  background: linear-gradient(90deg, transparent, var(--color-amber-400), transparent);
  border-radius: 0 0 2px 2px;
  z-index: 10;
  animation: fetchingSlide 0.8s ease-in-out infinite;
}

@keyframes fetchingSlide {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(100%); }
}

.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 20px;
  gap: 16px;
  flex-wrap: wrap;
}

.title-row {
  display: flex;
  align-items: center;
  gap: 20px;
}

.search-box {
  display: flex;
  align-items: center;
  border: 1.5px solid var(--color-stone-200);
  border-radius: var(--radius-lg);
  background: var(--color-stone-50);
  overflow: hidden;
  transition: all 0.2s;

  &:focus-within {
    border-color: var(--color-amber-400);
    background: white;
    box-shadow: 0 0 0 3px rgba(245,180,0,0.08);
  }

  input {
    width: 160px;
    padding: 8px 12px;
    border: none;
    background: transparent;
    font-size: 13px;
    color: var(--color-stone-800);
    outline: none;

    &::placeholder {
      color: var(--color-stone-400);
    }
  }
}

.search-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 8px 10px;
  border: none;
  background: transparent;
  color: var(--color-stone-500);
  cursor: pointer;
  transition: color 0.15s;

  &:hover {
    color: var(--color-amber-500);
  }
}

.section-title {
  font-size: 20px;
  font-weight: 600;
  color: var(--color-stone-800);
  font-family: var(--font-display);
}

.filter-tabs {
  display: flex;
  gap: 4px;
  background: var(--color-stone-100);
  padding: 4px;
  border-radius: $radius-md;
}

.filter-tab {
  padding: 6px 16px;
  border: none;
  background: transparent;
  color: var(--color-stone-500);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  border-radius: 6px;
  transition: all $transition-fast;

  &.active {
    background: white;
    color: var(--color-stone-800);
    box-shadow: $shadow-sm;
  }

  &:hover:not(.active) {
    color: var(--color-stone-700);
  }
}

// ---- 会议卡片网格 ----
.meeting-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
  gap: 20px;
}

.meeting-card-skeleton {
  background: white;
  border-radius: $radius-lg;
  padding: 24px;
  min-height: 180px;
}

.meeting-card {
  background: white;
  border: 1px solid var(--color-stone-200);
  border-radius: var(--radius-lg);
  padding: 24px;
  cursor: pointer;
  position: relative;
  overflow: hidden;
  @include card-hover;
  @include card-top-border-hover;

  &.meeting-card-disabled {
    cursor: not-allowed;

    &:hover {
      border-color: var(--color-error);
    }
  }
}

.card-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 14px;
}

.card-delete-btn {
  position: absolute;
  top: 12px;
  right: 12px;
  width: 28px;
  height: 28px;
  border: none;
  background: transparent;
  color: var(--color-stone-400);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 6px;
  transition: all 0.15s;
  opacity: 0;
  z-index: 2;

  &:hover {
    background: #fef2f2;
    color: var(--color-error);
  }
}

.meeting-card:hover .card-delete-btn {
  opacity: 1;
}

.card-type-badge {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 10px;
  border-radius: 6px;
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.03em;

  .status-dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
  }
}

.type-finish {
  background: #ecfdf5;
  color: #065f46;
  .status-dot {
    background: var(--color-success);
  }
}

.type-analyzing {
  background: #fff8e1;
  color: #f57f17;
  .status-dot {
    background: var(--color-warning);
    animation: pulse 1.5s infinite;
  }
}

.type-error {
  background: #fef2f2;
  color: #991b1b;
  .status-dot {
    background: var(--color-error);
  }
}

.type-active {
  background: #eff6ff;
  color: var(--color-info);
  .status-dot {
    background: var(--color-info);
  }
}

.card-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--color-stone-800);
  margin-bottom: 8px;
  line-height: 1.4;
}

.card-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  font-size: 13px;
  color: var(--color-stone-500);
  margin-bottom: 12px;
}

.card-meta-item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.card-footer {
  padding-top: 16px;
  border-top: 1px solid var(--color-stone-100);
  display: flex;
  justify-content: space-between;
  align-items: center;
}

// 状态徽章
.status-badge {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 600;
  padding: 5px 10px;
  border-radius: 20px;

  .status-dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
  }
}

.status-finish {
  background: #ecfdf5;
  color: #065f46;
  .status-dot {
    background: var(--color-success);
  }
}

.status-analyzing {
  background: #fff8e1;
  color: #f57f17;
  .status-dot {
    background: var(--color-warning);
    animation: pulse 1.5s infinite;
  }
}

.status-error {
  background: #fef2f2;
  color: #991b1b;
  .status-dot {
    background: var(--color-error);
  }
}

.status-active {
  background: #eff6ff;
  color: var(--color-info);
  .status-dot {
    background: var(--color-info);
  }
}

// 未生成纪要徽章
.no-summary-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  font-weight: 600;
  color: var(--color-stone-500);
  background: var(--color-stone-100);
  padding: 4px 8px;
  border-radius: 12px;
}

@keyframes pulse {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.4;
  }
}

// ---- 分页 ----
.pagination-wrapper {
  display: flex;
  justify-content: center;
  margin-top: 32px;
  padding: 16px 0;
}

// ---- 空状态 ----
.empty-state {
  text-align: center;
  padding: 60px 20px;
  color: var(--color-stone-400);
}

.empty-state-icon {
  font-size: 48px;
  margin-bottom: 16px;
  opacity: 0.6;
}

.empty-state h3 {
  font-size: 18px;
  color: var(--color-stone-600);
  margin-bottom: 8px;
  font-family: var(--font-display);
}

.empty-state p {
  font-size: 14px;
  margin-bottom: 20px;
}

// ============================================================
// 响应式 — 参照 design/mockups/mobile-responsive/index.html 设计
// 断点：sm ≤640px 手机 / md ≤768px 平板（max-width 语义）
// ============================================================

// ---- 移动端英雄区（默认隐藏） ----
.mobile-hero {
  display: none;
}

// ---- 会议卡片头像（默认隐藏，小屏显示） ----
.card-avatar {
  display: none;
}

@include respond-to(md) {
  .dashboard {
    padding: $space-4;
  }

  // 统计卡：单行4列紧凑样式（设计规范）
  .stats-row {
    grid-template-columns: repeat(4, 1fr);
    gap: $space-2;
    margin-bottom: $space-6;
  }

  .stat-card {
    padding: $space-3 $space-2;
    border-radius: $radius-md;
    text-align: center;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 4px;
    aspect-ratio: 1 / 1;

    &:hover {
      transform: none;
      box-shadow: none;
    }
  }

  .stat-icon {
    display: none;
  }

  .stat-value {
    font-family: var(--font-mono);
    font-size: var(--text-xl);
    font-weight: 700;
    line-height: 1;
    margin-bottom: 0;
  }

  .stat-label {
    font-size: 10px;
    white-space: nowrap;
  }

  .page-header {
    flex-direction: column;
    align-items: flex-start;
    gap: 16px;
  }
}

@include respond-to(sm) {
  .dashboard {
    padding: 0;
    max-width: none;
  }

  // ---- 页头 → 移动端英雄区 ----
  .page-header.desktop-only {
    display: none;
  }

  .mobile-hero {
    display: block;
    background: linear-gradient(160deg, var(--color-amber-50) 0%, var(--color-stone-50) 100%);
    padding: $space-6 $space-4;
    border-bottom: 1px solid var(--color-stone-100);
  }

  .dashboard-greeting {
    font-family: var(--font-display);
    font-size: var(--text-2xl);
    font-weight: 700;
    color: var(--color-stone-900);
    line-height: 1.3;

    span {
      color: var(--color-amber-500);
    }
  }

  .dashboard-subtitle {
    font-size: var(--text-sm);
    color: var(--color-stone-500);
    margin-top: 4px;
  }

  .dashboard-quick-actions {
    display: flex;
    gap: $space-2;
    margin-top: $space-4;
    overflow-x: auto;
    @include scroll-x;
  }

  .quick-action-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 6px;
    padding: 10px 18px;
    border-radius: $radius-full;
    font-size: var(--text-sm);
    font-weight: 600;
    font-family: var(--font-body);
    cursor: pointer;
    border: none;
    min-height: 44px;
    white-space: nowrap;
    flex-shrink: 0;
    transition: all var(--transition-fast);

    &:active {
      transform: scale(0.97);
    }

    &:disabled {
      opacity: 0.5;
    }
  }

  .quick-action-upload {
    display: inline-flex;
    flex-shrink: 0;
  }

  .quick-action-primary {
    background: var(--color-amber-400);
    color: var(--color-stone-900);
    box-shadow: 0 2px 8px rgba(245, 180, 0, 0.25);

    &:active {
      background: var(--color-amber-500);
    }
  }

  .quick-action-secondary {
    background: white;
    color: var(--color-stone-700);
    border: 1.5px solid var(--color-stone-200);

    &:active {
      background: var(--color-stone-100);
    }
  }

  // ---- 统计卡 ----
  .stats-row {
    padding: 0 $space-4;
    margin-top: $space-4;
    margin-bottom: $space-2;
    gap: $space-2;
  }

  // ---- 列表区 ----
  .meeting-list {
    padding: 0 $space-4;
  }

  .section-header {
    flex-direction: column;
    align-items: stretch;
    gap: $space-2;
    margin-bottom: $space-3;
  }

  .title-row {
    justify-content: space-between;
    width: 100%;
  }

  .section-title {
    font-size: 18px;
  }

  .search-box {
    flex: 1;
    max-width: 220px;

    input {
      width: 100%;
    }
  }

  // 筛选 → 横向滚动胶囊（设计规范 filter-chip）
  .filter-tabs {
    display: flex;
    gap: $space-2;
    background: transparent;
    border-radius: 0;
    padding: 2px 0;
    @include scroll-x;
  }

  .filter-tab {
    flex-shrink: 0;
    padding: 5px 14px;
    font-size: var(--text-xs);
    font-weight: 500;
    border-radius: $radius-full;
    border: 1.5px solid var(--color-stone-200);
    background: white;
    color: var(--color-stone-600);
    min-height: 34px;
    display: flex;
    align-items: center;

    &.active {
      background: var(--color-amber-400);
      color: var(--color-stone-900);
      border-color: var(--color-amber-400);
      box-shadow: none;
    }
  }

  // ---- 会议卡片 → 移动端列表样式 ----
  .meeting-grid {
    grid-template-columns: 1fr;
    gap: $space-3;
  }

  .meeting-card {
    padding: $space-4;
    @include card-active;

    &:hover {
      transform: none;
      box-shadow: none;
    }
  }

  // 删除按钮移动端常显（无 hover）
  .card-delete-btn {
    opacity: 1;
  }

  // 状态徽章 → 右上角
  .card-top {
    position: absolute;
    top: 14px;
    right: 46px;
    margin-bottom: 0;
  }

  .card-type-badge {
    font-size: 10px;
    padding: 4px 8px;
  }

  .card-main {
    display: flex;
    align-items: flex-start;
    gap: $space-3;
  }

  .card-avatar {
    display: flex;
    width: 44px;
    height: 44px;
    border-radius: $radius-md;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    font-weight: 700;
    font-size: var(--text-lg);
    font-family: var(--font-display);

    &.amber {
      background: var(--color-amber-100);
      color: var(--color-amber-600);
    }

    &.stone {
      background: var(--color-stone-100);
      color: var(--color-stone-600);
    }
  }

  .card-info {
    flex: 1;
    min-width: 0;
  }

  .card-title {
    font-size: 15px;
    padding-right: 84px;
  }

  .card-meta {
    margin-bottom: 0;
  }

  .card-footer .status-badge {
    font-size: 11px;
    padding: 4px 8px;
  }

  // 弹窗：移动端禁止拉伸开关
  .modal-overlay {
    align-items: flex-end;
  }

  .modal {
    border-radius: 20px 20px 0 0;
    max-width: none;
    max-height: 90vh;
    overflow-y: auto;
  }

  .switch-toggle {
    flex-shrink: 0;
    min-width: 50px;
    min-height: 28px;
  }

  .switch-dot {
    width: 22px;
    height: 22px;
  }

  .switch-toggle.active .switch-dot {
    transform: translateX(22px);
  }
}

// ============================================================
// 弹窗样式 — 与系统风格保持一致
// ============================================================

// 遮罩层
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  backdrop-filter: blur(3px);
}

// 弹窗主体
.modal {
  background: white;
  border-radius: 20px;
  padding: 0;
  width: 100%;
  max-width: 480px;
  box-shadow: var(--shadow-xl);
  animation: modalIn 0.25s ease-out;
  overflow: hidden;

  &.modal-sm {
    max-width: 400px;
  }
}

@keyframes modalIn {
  from { opacity: 0; transform: scale(0.95) translateY(10px); }
  to { opacity: 1; transform: scale(1) translateY(0); }
}

// 弹窗头部
.modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 24px 28px 16px;
}

.modal-title {
  font-family: var(--font-display);
  font-size: 20px;
  font-weight: 700;
  color: var(--color-stone-800);
}

.modal-subtitle {
  font-size: 13px;
  color: var(--color-stone-500);
  margin-top: 4px;
}

.modal-close {
  width: 32px;
  height: 32px;
  border: none;
  background: var(--color-stone-100);
  border-radius: 8px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--color-stone-500);
  transition: all 0.15s;
  font-size: 14px;

  &:hover {
    background: var(--color-stone-200);
    color: var(--color-stone-700);
  }
}

// 弹窗内容
.modal-body {
  padding: 0 28px 24px;
}

// 表单
.form-group {
  margin-bottom: 16px;

  &:last-child {
    margin-bottom: 0;
  }
}

.form-label {
  display: block;
  font-size: 13px;
  font-weight: 600;
  color: var(--color-stone-700);
  margin-bottom: 8px;
}

.form-input {
  width: 100%;
  padding: 12px 16px;
  border: 1.5px solid var(--color-stone-200);
  border-radius: var(--radius-lg);
  font-size: 14px;
  font-family: var(--font-body);
  color: var(--color-stone-800);
  background: var(--color-stone-50);
  outline: none;
  transition: all 0.2s;

  &:focus {
    border-color: var(--color-amber-400);
    background: white;
    box-shadow: 0 0 0 3px rgba(245, 180, 0, 0.08);
  }

  &::placeholder {
    color: var(--color-stone-400);
  }
}

// 开关
.switch-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.switch-toggle {
  position: relative;
  width: 44px;
  height: 24px;
  min-width: 44px;
  min-height: 24px;
  flex-shrink: 0;
  flex-grow: 0;
  border: none;
  border-radius: 12px;
  background: var(--color-stone-300);
  cursor: pointer;
  transition: background 0.2s;
  padding: 0;

  &.active {
    background: var(--color-amber-400);
  }
}

.switch-dot {
  position: absolute;
  top: 2px;
  left: 2px;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: white;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
  transition: transform 0.2s;

  .switch-toggle.active & {
    transform: translateX(20px);
  }
}

.switch-label {
  font-size: 13px;
  color: var(--color-stone-600);
}

// 弹窗底部
.modal-footer {
  display: flex;
  gap: 12px;
  justify-content: flex-end;
  padding: 16px 28px;
  border-top: 1px solid var(--color-stone-100);
  background: var(--color-stone-50);
}

// 按钮
.btn-secondary {
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

.btn-primary {
  padding: 10px 24px;
  border: none;
  border-radius: var(--radius-md);
  background: var(--color-amber-400);
  color: var(--color-stone-900);
  font-size: 14px;
  font-weight: 600;
  font-family: var(--font-body);
  cursor: pointer;
  transition: all 0.2s;

  &:hover:not(:disabled) {
    background: var(--color-amber-500);
    transform: translateY(-1px);
    box-shadow: 0 4px 12px rgba(245, 180, 0, 0.25);
  }

  &:disabled {
    opacity: 0.5;
    cursor: not-allowed;
    transform: none;
    box-shadow: none;
  }
}

.btn-danger {
  padding: 10px 24px;
  border: none;
  border-radius: var(--radius-md);
  background: var(--color-error);
  color: white;
  font-size: 14px;
  font-weight: 600;
  font-family: var(--font-body);
  cursor: pointer;
  transition: all 0.2s;

  &:hover {
    background: #dc2626;
    transform: translateY(-1px);
    box-shadow: 0 4px 12px rgba(220, 38, 38, 0.25);
  }
}

// 加载动画
.loading-spinner {
  display: inline-block;
  width: 14px;
  height: 14px;
  border: 2px solid rgba(0, 0, 0, 0.1);
  border-top-color: var(--color-stone-900);
  border-radius: 50%;
  animation: spin 0.6s linear infinite;
  margin-right: 6px;
  vertical-align: middle;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

// 删除确认
.delete-content {
  text-align: center;
  padding: 20px 0;
}

.delete-icon {
  font-size: 40px;
  margin-bottom: 12px;
  opacity: 0.6;
}

.delete-text {
  font-size: 14px;
  color: var(--color-stone-600);
  line-height: 1.6;
}

.delete-name {
  font-weight: 600;
  color: var(--color-stone-800);
}
</style>
