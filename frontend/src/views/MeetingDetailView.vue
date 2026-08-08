<script setup lang="ts">
// ============================================================
// MeetingDetailView — 会议纪要详情
// 功能：显示会议的完整AI处理结果（摘要/行动项/主题/转写）
// ============================================================
import { ref, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import DefaultLayout from '@/layouts/DefaultLayout.vue'
import { meetingApi } from '@/api'
import type { MeetingResultData } from '@/api/types'
import { renderMarkdown, renderInline } from '@/utils/markdown'

const route = useRoute()
const router = useRouter()

// ---- 状态 ----
const loading = ref(false)
const resultData = ref<MeetingResultData | null>(null)
const activeModule = ref('summary')

const meetingId = computed(() => route.params.meetingId as string)

// ---- 模块定义 ----
interface ModuleDef {
  key: string
  label: string
  icon: string
  iconClass?: string
}

// 是否显示实时转录（need_summary=false）
const showRealtimeTranscript = computed(() => resultData.value?.need_summary === false)

const modules = computed<ModuleDef[]>(() => {
  // 实时转录模式：只显示实时转录文本
  if (showRealtimeTranscript.value) {
    return [{ key: 'realtime', label: '实时转录', icon: '💬', iconClass: 'section-icon-cyan' }]
  }

  // AI 纪要模式：根据 task_result 动态生成模块
  const list: ModuleDef[] = []
  if (getValue('summary')) {
    list.push({ key: 'summary', label: '摘要', icon: '📝', iconClass: 'section-icon-amber' })
  }
  if (getValue('complete_text')) {
    list.push({ key: 'complete_text', label: '完整转写', icon: '📄', iconClass: 'section-icon-blue' })
  }
  if (getActionItems().length > 0) {
    list.push({ key: 'action_items', label: '行动项', icon: '✅', iconClass: 'section-icon-green' })
  }
  if (getThemeSegmentation().length > 0) {
    list.push({ key: 'themes', label: '讨论主题', icon: '🏷', iconClass: 'section-icon-purple' })
  }
  if (getSentences().length > 0) {
    list.push({ key: 'transcript', label: '时间戳转写', icon: '💬', iconClass: 'section-icon-cyan' })
  }
  return list
})

function switchModule(key: string) {
  activeModule.value = key
  // 滚动到 Tabs 位置
  setTimeout(() => {
    document.querySelector('.module-tabs')?.scrollIntoView({ behavior: 'smooth' })
  }, 50)
}

// 从 task_result 解析出的结构化数据
const taskResult = computed(() => {
  const data = resultData.value?.task_result
  if (!data || typeof data === 'string') return { raw: data }
  return data
})

// ---- 辅助方法 ----

/** 从多个可能的 key 获取第一个有值的字符串 */
function getValue(...keys: string[]): string {
  for (const k of keys) {
    const v = taskResult.value[k]
    if (v && typeof v === 'string' && v.trim()) return v.trim()
    if (v && typeof v === 'object') {
      const str = Object.values(v).filter(Boolean).join('\n')
      if (str) return str
    }
  }
  return ''
}

/** 获取时间戳转写句子数组 */
function getSentences(): string[] {
  const s = taskResult.value['sentences_with_time']
  if (Array.isArray(s)) return s
  if (typeof s === 'string') return s.split('\n').filter(Boolean)
  return []
}

/** 获取行动项列表 */
function getActionItems(): string[] {
  const action = taskResult.value['action']
  if (!action) return []
  if (Array.isArray(action)) return action as string[]
  if (typeof action === 'string') {
    const lines = action.split(/[\n\r]+/)
    return lines
      .map((l) => l.replace(/^[\s\-•\d.]+/, '').trim())
      .filter((l) => l.length > 0)
  }
  return []
}

/** 获取主题分割列表 */
function getThemeSegmentation(): string[] {
  const t = taskResult.value['theme_segmentation']
  if (!t) return []
  if (Array.isArray(t)) return t as string[]
  if (typeof t === 'string') {
    return t
      .split(/[\n\r]+/)
      .map((l) => l.replace(/^[\s\-\d.]+/, '').trim())
      .filter((l) => l.length > 0)
  }
  return []
}

/** 渲染单条时间戳转写句子 */
function renderSingleSentence(line: string): string {
  const match = line.match(/^(\[\s*[\d:]+\s*~\s*[\d:]+\])\s*([^:]+)\s*:\s*(.*)$/)
  if (match) {
    const [, time, speaker, text] = match
    return `<span class="ts-time">${time}</span><span class="ts-speaker">${speaker}</span><span class="ts-text">${text}</span>`
  }
  return line
}

/** 行内 Markdown（无包裹 <p>） */
function mdInline(text: string): string {
  try {
    return renderInline(text)
  } catch {
    return escapeHtml(text)
  }
}

/** 获取实时转录文本行列表 */
function getRealtimeLines(): string[] {
  const lines = resultData.value?.realtime_asr_text
  if (Array.isArray(lines) && lines.length > 0) return lines
  return []
}

/** 渲染单条实时转录句子 */
function renderRealtimeLine(line: string): string {
  const match = line.match(/^(\[\s*[\d:]+\s*~\s*[\d:]+\])\s*(\[[^\]]+\])\s*:\s*(.*)$/)
  if (match) {
    const [, time, speaker, text] = match
    return `<span class="rt-time">${time}</span><span class="rt-speaker">${speaker}</span><span class="rt-text">${text}</span>`
  }
  return `<span class="rt-text">${line}</span>`
}

function escapeHtml(str: string): string {
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
}

const displayName = computed(() => resultData.value?.task_name || resultData.value?.meeting_name || '未命名会议')
const displayDate = computed(() => resultData.value?.create_time || '未知时间')

// ---- 数据加载 ----
async function loadDetail() {
  const mid = meetingId.value
  if (!mid) {
    ElMessage.error('无效的会议 ID')
    router.push('/dashboard')
    return
  }

  loading.value = true
  try {
    resultData.value = await meetingApi.getResult(mid)

    if (!resultData.value) {
      ElMessage.error('未找到对应的会议记录')
      router.push('/dashboard')
      return
    }

    // 如果当前激活的模块在可用模块中不存在，重置为第一个
    if (!modules.value.some((m) => m.key === activeModule.value) && modules.value.length > 0) {
      activeModule.value = modules.value[0].key
    }
    // 实时转录模式默认选中 realtime
    if (showRealtimeTranscript.value && modules.value.length > 0) {
      activeModule.value = 'realtime'
    }
  } catch (e: any) {
    ElMessage.error(e.message || '加载失败')
  } finally {
    loading.value = false
  }
}

function copyToClipboard() {
  let text = ''

  if (showRealtimeTranscript.value) {
    // need_summary 为假：复制实时转录
    const lines = getRealtimeLines()
    text = lines.join('\n')
  } else {
    // need_summary 为真：复制摘要
    text = getValue('summary')
  }

  if (!text) {
    ElMessage.warning('暂无可复制的内容')
    return
  }

  // 优先 Clipboard API，失败回退 execCommand
  if (navigator.clipboard) {
    navigator.clipboard.writeText(text).then(
      () => ElMessage.success('已复制到剪贴板'),
      () => fallbackCopy(text)
    )
  } else {
    fallbackCopy(text)
  }
}

function fallbackCopy(text: string) {
  const textarea = document.createElement('textarea')
  textarea.value = text
  textarea.style.position = 'fixed'
  textarea.style.top = '0'
  textarea.style.left = '0'
  textarea.style.opacity = '0'
  document.body.appendChild(textarea)
  textarea.focus()
  textarea.select()
  try {
    document.execCommand('copy')
    ElMessage.success('已复制到剪贴板')
  } catch {
    ElMessage.error('复制失败，请手动选择')
  } finally {
    document.body.removeChild(textarea)
  }
}

function exportMarkdown() {
  const lines = [
    `# ${resultData.value?.task_name || resultData.value?.meeting_name || '会议纪要'}`,
    '',
    '## 摘要',
    taskResult.value['summary'] || '*暂无摘要*',
    '',
    '## 完整转写',
    taskResult.value['complete_text'] || '*暂无完整转写*',
    '',
    '## 行动项',
    taskResult.value['action'] || '*暂无行动项*',
    '',
    '## 主题分割',
    taskResult.value['theme_segmentation'] || '*暂无主题分割*',
    '',
    '## 时间戳转写',
    ...getSentences(),
  ]

  const md = lines.join('\n')
  const blob = new Blob([md], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${resultData.value?.task_name || 'meeting'}-${meetingId.value}.md`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

onMounted(loadDetail)
</script>

<template>
  <DefaultLayout>
    <div v-loading="loading" class="detail-page">
      <!-- ========== 标题区 ========== -->
      <div class="detail-header">
        <el-button text @click="router.push('/dashboard')">← 返回会议列表</el-button>
        <h1 class="detail-title">{{ displayName }}</h1>
        <div class="detail-meta">
          <span class="detail-meta-item">📅 {{ displayDate }}</span>
          <span v-if="showRealtimeTranscript" class="status-badge status-realtime">
            <span class="status-dot"></span> 实时转录
          </span>
          <span v-else class="status-badge status-complete">
            <span class="status-dot"></span> 已完成
          </span>
        </div>
        <div class="detail-actions">
          <el-button @click="copyToClipboard">📋 复制纪要</el-button>
          <el-button @click="exportMarkdown">📤 导出 Markdown</el-button>
        </div>
      </div>

      <!-- ========== 模块切换 Tab ========== -->
      <nav v-if="modules.length > 0" class="module-tabs">
        <button
          v-for="mod in modules"
          :key="mod.key"
          :class="['module-tab', { active: activeModule === mod.key }]"
          type="button"
          @click="switchModule(mod.key)"
        >
          <span class="module-tab-icon">{{ mod.icon }}</span>
          <span class="module-tab-label">{{ mod.label }}</span>
          <span v-if="mod.key === 'action_items'" class="module-tab-count">
            {{ getActionItems().length }}
          </span>
        </button>
      </nav>

      <!-- ========== 实时转录（need_summary=false） ========== -->
      <section
        v-if="showRealtimeTranscript && getRealtimeLines().length > 0"
        :class="['content-section', 'module-content', { active: activeModule === 'realtime' }]"
      >
        <div class="section-header">
          <h2 class="section-title">
            <span class="section-icon section-icon-cyan">💬</span> 实时转录
          </h2>
          <span class="section-count">共 {{ getRealtimeLines().length }} 条</span>
        </div>
        <div class="realtime-transcript">
          <div v-for="(line, idx) in getRealtimeLines()" :key="idx" class="rt-line">
            <div v-html="renderRealtimeLine(line)"></div>
          </div>
        </div>
      </section>

      <!-- ========== AI 摘要 ========== -->
      <section
        v-if="getValue('summary')"
        :class="['content-section', 'module-content', { active: activeModule === 'summary' }]"
      >
        <div class="section-header">
          <h2 class="section-title">
            <span class="section-icon section-icon-amber">📝</span> AI 摘要
          </h2>
        </div>
        <div class="markdown-content" v-html="renderMarkdown(getValue('summary'))"></div>
      </section>

      <!-- ========== 完整转写文本 ========== -->
      <section
        v-if="getValue('complete_text')"
        :class="['content-section', 'module-content', { active: activeModule === 'complete_text' }]"
      >
        <div class="section-header">
          <h2 class="section-title">
            <span class="section-icon section-icon-blue">📄</span> 完整转写文本
          </h2>
        </div>
        <div class="markdown-content" v-html="renderMarkdown(getValue('complete_text'))"></div>
      </section>

      <!-- ========== 行动项 ========== -->
      <section
        v-if="getActionItems().length > 0"
        :class="['content-section', 'module-content', { active: activeModule === 'action_items' }]"
      >
        <div class="section-header">
          <h2 class="section-title">
            <span class="section-icon section-icon-green">✅</span> 行动项
          </h2>
          <span class="section-count">{{ getActionItems().length }} 项</span>
        </div>
        <div class="action-items">
          <div v-for="(item, idx) in getActionItems()" :key="idx" class="action-item">
            <div class="action-checkbox"></div>
            <div class="action-content">
              <div class="action-text" v-html="mdInline(item)"></div>
            </div>
          </div>
        </div>
      </section>

      <!-- ========== 主题分割 ========== -->
      <section
        v-if="getThemeSegmentation().length > 0"
        :class="['content-section', 'module-content', { active: activeModule === 'themes' }]"
      >
        <div class="section-header">
          <h2 class="section-title">
            <span class="section-icon section-icon-purple">🏷</span> 讨论主题
          </h2>
        </div>
        <div class="theme-list">
          <div v-for="(theme, idx) in getThemeSegmentation()" :key="idx" class="theme-item">
            <div class="theme-number">{{ idx + 1 }}</div>
            <div class="theme-name" v-html="mdInline(theme)"></div>
          </div>
        </div>
      </section>

      <!-- ========== 时间戳转写 ========== -->
      <section
        v-if="getSentences().length > 0"
        :class="['content-section', 'module-content', { active: activeModule === 'transcript' }]"
      >
        <div class="section-header">
          <h2 class="section-title">
            <span class="section-icon section-icon-cyan">💬</span> 时间戳转写
          </h2>
          <span class="section-count">带时间戳</span>
        </div>
        <div class="timestamp-transcript">
          <div v-for="(line, idx) in getSentences()" :key="idx" class="ts-line">
            <div v-html="renderSingleSentence(line)"></div>
          </div>
        </div>
      </section>

      <!-- ========== 空状态 ========== -->
      <el-empty
        v-if="!loading && modules.length === 0"
        description="纪要内容尚未生成或为空"
      />
    </div>
  </DefaultLayout>
</template>

<style scoped lang="scss">
@use '@/styles/mixins.scss' as *;

.detail-page {
  max-width: 900px;
  margin: 0 auto;
  padding: 40px 32px;
}

// ---- 标题区 ----
.detail-header {
  margin-bottom: 40px;
}

.detail-title {
  font-family: var(--font-display);
  font-size: 32px;
  font-weight: 700;
  color: var(--color-stone-800);
  margin: 16px 0;
  line-height: 1.3;
}

.detail-meta {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 24px;
  font-size: 14px;
  color: var(--color-stone-500);
}

.detail-meta-item {
  display: flex;
  align-items: center;
  gap: 6px;
}

.detail-actions {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

// 状态徽章
.status-badge {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 600;
  padding: 5px 12px;
  border-radius: 20px;

  .status-dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
  }
}

.status-complete {
  background: #ecfdf5;
  color: #065f46;
  .status-dot {
    background: var(--color-success);
  }
}

.status-realtime {
  background: #eff6ff;
  color: var(--color-info);
  .status-dot {
    background: var(--color-info);
  }
}

// ---- 模块切换 Tab ----
.module-tabs {
  display: flex;
  gap: 8px;
  margin-bottom: 24px;
  background: white;
  padding: 8px;
  border-radius: var(--radius-xl);
  border: 1px solid var(--color-stone-200);
  position: sticky;
  top: 64px;
  z-index: 90;
  box-shadow: $shadow-md;
  overflow-x: auto;
  scroll-behavior: smooth;

  &::-webkit-scrollbar { height: 0; }
  -ms-overflow-style: none;
  scrollbar-width: none;
}

.module-tab {
  flex: 1;
  min-width: fit-content;
  padding: 12px 20px;
  border: none;
  border-radius: $radius-lg;
  font-size: 14px;
  font-weight: 600;
  font-family: var(--font-body);
  cursor: pointer;
  transition: all $transition-fast;
  background: transparent;
  color: var(--color-stone-600);
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  white-space: nowrap;

  &:hover {
    background: var(--color-stone-50);
    color: var(--color-stone-800);
  }

  &.active {
    background: var(--color-amber-400);
    color: var(--color-stone-900);
    box-shadow: 0 2px 8px rgba(245, 180, 0, 0.3);
  }
}

.module-tab-icon {
  font-size: 16px;
}

.module-tab-label {
  font-weight: 600;
}

.module-tab-count {
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 12px;
  background: var(--color-stone-100);
  color: var(--color-stone-600);
}

.module-tab.active .module-tab-count {
  background: rgba(0, 0, 0, 0.1);
  color: var(--color-stone-900);
}

// ---- 模块内容区域 ----
.module-content {
  display: none;
  animation: fadeIn 0.25s ease-out;

  &.active {
    display: block;
  }
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}

.section-count {
  font-size: 13px;
  color: var(--color-stone-500);
}

// ---- 内容区块 ----
.content-section {
  background: white;
  border: 1px solid var(--color-stone-200);
  border-radius: var(--radius-xl);
  padding: 32px;
  margin-bottom: 24px;
}

.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 24px;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--color-stone-100);
}

.section-title {
  font-family: var(--font-display);
  font-size: 18px;
  font-weight: 600;
  color: var(--color-stone-800);
  display: flex;
  align-items: center;
  gap: 10px;
}

.section-icon {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 15px;
}

.section-icon-amber {
  background: var(--color-amber-50);
  color: var(--color-amber-600);
}
.section-icon-green {
  background: #ecfdf5;
  color: var(--color-success);
}
.section-icon-blue {
  background: #eff6ff;
  color: var(--color-info);
}
.section-icon-purple {
  background: #f3e8ff;
  color: #8b5cf6;
}
.section-icon-cyan {
  background: #ecfeff;
  color: #06b6d4;
}

// ---- Markdown 渲染 ----
.markdown-content {
  font-size: 15px;
  line-height: 1.8;
  color: var(--color-stone-700);
  :deep(h1) {
    font-family: var(--font-display);
    font-size: 24px;
    margin: 32px 0 16px;
    padding-bottom: 8px;
    border-bottom: 2px solid var(--color-amber-200);
    color: var(--color-stone-800);
    &:first-child { margin-top: 0; }
  }
  :deep(h2) {
    font-family: var(--font-display);
    font-size: 20px;
    margin: 28px 0 12px;
    color: var(--color-stone-800);
  }
  :deep(h3) {
    font-size: 17px;
    margin: 24px 0 10px;
    color: var(--color-stone-800);
  }
  :deep(p) { margin-bottom: 14px; }
  :deep(ul), :deep(ol) { margin: 12px 0 16px; padding-left: 24px; }
  :deep(li) { margin-bottom: 8px; }
  :deep(li::marker) { color: var(--color-amber-500); }
  :deep(strong) { color: var(--color-stone-800); font-weight: 600; }
  :deep(blockquote) {
    border-left: 3px solid var(--color-amber-300);
    background: var(--color-amber-50);
    padding: 14px 20px;
    margin: 16px 0;
    border-radius: 0 var(--radius-md) var(--radius-md) 0;
    color: var(--color-stone-700);
  }
  :deep(code) {
    font-family: var(--font-mono);
    font-size: 13px;
    background: var(--color-stone-100);
    padding: 2px 6px;
    border-radius: 4px;
    color: var(--color-stone-800);
  }
  :deep(pre) {
    background: var(--color-stone-900);
    color: var(--color-stone-100);
    padding: 20px;
    border-radius: $radius-md;
    overflow-x: auto;
    margin: 16px 0;
    font-family: var(--font-mono);
    font-size: 13px;
    line-height: 1.6;
    code { background: transparent; padding: 0; color: inherit; }
  }
  :deep(table) {
    width: 100%;
    border-collapse: collapse;
    margin: 16px 0;
    font-size: 14px;
  }
  :deep(th) {
    background: var(--color-stone-100);
    padding: 10px 14px;
    text-align: left;
    font-weight: 600;
    color: var(--color-stone-700);
    border-bottom: 2px solid var(--color-stone-200);
  }
  :deep(td) { padding: 10px 14px; border-bottom: 1px solid var(--color-stone-100); }
  :deep(tr:hover td) { background: var(--color-stone-50); }
  :deep(hr) { border: none; border-top: 1px solid var(--color-stone-200); margin: 28px 0; }
}

// ---- 行动项 ----
.action-items {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.action-item {
  display: flex;
  align-items: flex-start;
  gap: 14px;
  padding: 16px;
  background: var(--color-stone-50);
  border: 1px solid var(--color-stone-200);
  border-radius: $radius-md;
}

.action-checkbox {
  width: 20px;
  height: 20px;
  border: 2px solid var(--color-stone-300);
  border-radius: 50%;
  flex-shrink: 0;
  margin-top: 2px;
  cursor: pointer;
  transition: all $transition-fast;

  &:hover {
    border-color: var(--color-amber-400);
  }
}

.action-content {
  flex: 1;
}

.action-text {
  font-size: 14px;
  font-weight: 500;
  color: var(--color-stone-800);
  line-height: 1.5;
}

// ---- 主题列表 ----
.theme-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.theme-item {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 14px 18px;
  background: white;
  border: 1px solid var(--color-stone-200);
  border-radius: $radius-md;
  transition: all $transition-fast;

  &:hover {
    border-color: var(--color-amber-300);
    box-shadow: $shadow-sm;
  }
}

.theme-number {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: var(--color-amber-100);
  color: var(--color-amber-600);
  font-size: 14px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.theme-name {
  font-size: 15px;
  font-weight: 500;
  color: var(--color-stone-800);
}

// ---- 时间戳转写 ----
.timestamp-transcript {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.ts-line {
  display: flex;
  gap: 14px;
  padding: 12px 16px;
  background: var(--color-stone-50);
  border-radius: $radius-md;
  border-left: 3px solid var(--color-amber-300);
  font-size: 14px;
  line-height: 1.6;

  > div {
    display: contents;
  }
}

.ts-time {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--color-stone-500);
  flex-shrink: 0;
  min-width: 140px;
}

.ts-speaker {
  font-weight: 600;
  color: var(--color-amber-600);
  flex-shrink: 0;
  min-width: 80px;
}

.ts-text {
  color: var(--color-stone-700);
}

// ---- 实时转录 ----
.realtime-transcript {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.rt-line {
  display: flex;
  gap: 14px;
  padding: 12px 16px;
  background: var(--color-stone-50);
  border-radius: $radius-md;
  border-left: 3px solid var(--color-info);
  font-size: 14px;
  line-height: 1.6;

  > div {
    display: contents;
  }
}

.rt-time {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--color-stone-500);
  flex-shrink: 0;
  min-width: 140px;
}

.rt-speaker {
  font-weight: 600;
  color: var(--color-info);
  flex-shrink: 0;
  min-width: 80px;
}

.rt-text {
  color: var(--color-stone-700);
}

// ---- 响应式 ----
@include respond-to(md) {
  .detail-page { padding: 24px 16px; }
  .content-section { padding: 20px; }
  .detail-title { font-size: 24px; }
  .detail-meta { flex-wrap: wrap; gap: 12px; }
  .ts-line {
    flex-direction: column;
    gap: 4px;
  }
  .ts-time, .ts-speaker { min-width: auto; }
  .module-tabs { top: 56px; }
  .detail-actions { gap: 8px; }

  // 模块 Tab → 胶囊（参照 mobile-responsive 设计 transcript-tabs）
  .module-tab {
    border-radius: var(--radius-full);
    padding: 10px 18px;
  }
}

@include respond-to(sm) {
  .detail-page {
    padding: 16px 12px;
  }

  .detail-header {
    margin-bottom: 20px;
    background: linear-gradient(160deg, var(--color-amber-50) 0%, var(--color-stone-50) 100%);
    border-radius: var(--radius-lg);
    padding: 16px;
  }

  .detail-title {
    font-size: 20px;
    margin: 12px 0;
  }

  .content-section {
    padding: 16px;
    border-radius: var(--radius-lg);
    margin-bottom: 16px;
  }

  .section-header {
    margin-bottom: 16px;
    padding-bottom: 12px;
  }

  .section-title {
    font-size: 16px;
  }

  .module-tab {
    padding: 10px 14px;
    font-size: 13px;
    gap: 6px;
  }

  .module-tab-icon {
    font-size: 14px;
  }

  .markdown-content {
    font-size: 14px;
    line-height: 1.7;
  }

  .rt-time, .ts-time {
    min-width: auto;
    font-size: 11px;
  }

  .rt-speaker, .ts-speaker {
    min-width: auto;
    font-size: 12px;
  }

  .rt-text, .ts-text {
    font-size: 13px;
  }
}
</style>