<script setup lang="ts">
// ============================================================
// EditContextModal — 修改讨论范围弹窗
// 为已存在的会话修改关联的会议和知识库
// ============================================================

import { ref, computed, onMounted, watch, nextTick } from 'vue'
import type { Ref } from 'vue'
import { useChatStore } from '@/stores/chat'
import type { ChatSession, MeetingItem, KnowledgeItem } from '@/api/types'

interface Props {
  visible: boolean
  session: ChatSession
}

const props = defineProps<Props>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'save', data: { meetingIds: string[]; knowledgeIds: string[]; needKb: boolean }): void
}>()

const chatStore = useChatStore()

// ===== 搜索 =====
const meetingSearch = ref('')
const knowledgeSearch = ref('')

// ===== 分页 =====
const meetingPage = ref(1)
const knowledgePage = ref(1)
const pageSize = 5

// ===== 计算属性 =====
const selectedMeetingCount = computed(() => chatStore.selectedMeetingIds.length)
const selectedKbCount = computed(() => chatStore.selectedKnowledgeIds.length)

const meetingTotal = computed(() => chatStore.meetingTotal)
const knowledgeTotal = computed(() => chatStore.knowledgeTotal)

const totalMeetingPages = computed(() => Math.max(1, Math.ceil(meetingTotal.value / pageSize)))
const totalKnowledgePages = computed(() => Math.max(1, Math.ceil(knowledgeTotal.value / pageSize)))

// ===== 数据加载 =====
const knowledgeAnchorRef = ref<HTMLElement | null>(null)

function scrollAnchorIntoView(anchorRef: Ref<HTMLElement | null>) {
  const el = anchorRef.value
  if (!el) return
  el.scrollIntoView({ block: 'end', behavior: 'smooth' })
  const scrollParent = el.closest('.modal-body') as HTMLElement | null
  if (scrollParent) {
    requestAnimationFrame(() => {
      scrollParent.scrollTo({ top: scrollParent.scrollHeight, behavior: 'smooth' })
    })
  }
}

async function loadMeetings() {
  await chatStore.loadAvailableMeetings(meetingPage.value, meetingSearch.value)
}

async function loadKnowledge() {
  await chatStore.loadAvailableKnowledge(knowledgePage.value, knowledgeSearch.value)
  await nextTick()
  scrollAnchorIntoView(knowledgeAnchorRef)
}

function handleMeetingSearch() {
  meetingPage.value = 1
  loadMeetings()
}

function handleKnowledgeSearch() {
  knowledgePage.value = 1
  loadKnowledge()
}

function handleMeetingPageChange(page: number) {
  meetingPage.value = page
  loadMeetings()
}

function handleKnowledgePageChange(page: number) {
  knowledgePage.value = page
  loadKnowledge()
}

// ===== 选择操作 =====

function isMeetingSelected(meeting: MeetingItem): boolean {
  return chatStore.selectedMeetingIds.includes(meeting.id)
}

function isKnowledgeSelected(kb: KnowledgeItem): boolean {
  return chatStore.selectedKnowledgeIds.includes(kb.id)
}

function toggleMeeting(meeting: MeetingItem) {
  chatStore.toggleMeeting(meeting.id)
}

function toggleKnowledge(kb: KnowledgeItem) {
  chatStore.toggleKnowledge(kb.id)
}

// ===== 保存 =====

function handleSave() {
  emit('save', {
    meetingIds: [...chatStore.selectedMeetingIds],
    knowledgeIds: [...chatStore.selectedKnowledgeIds],
    needKb: chatStore.needKb,
  })
}

function handleClose() {
  emit('close')
}

// ===== 生命周期 =====

/**
 * 每次弹窗可见时加载数据。
 * - 首次挂载时如果 visible=true，onMounted 触发加载
 * - 后续 visible 由 false→true 变化时，watch 触发加载
 */
function onModalOpened() {
  if (!props.session) return
  chatStore.restoreSelectionFromSession(props.session)
  meetingSearch.value = ''
  knowledgeSearch.value = ''
  meetingPage.value = 1
  knowledgePage.value = 1
  loadMeetings()
  if (chatStore.needKb) loadKnowledge()
}

function toggleNeedKb() {
  chatStore.needKb = !chatStore.needKb
  if (chatStore.needKb && chatStore.availableKnowledge.length === 0) {
    loadKnowledge()
  }
  if (!chatStore.needKb) {
    chatStore.selectedKnowledgeIds = []
  }
}

// 首次挂载（如果 visible 初始为 true）
onMounted(() => {
  if (props.visible) {
    onModalOpened()
  }
})

// 后续 visible 变化（false → true）
watch(() => props.visible, (val) => {
  if (val) {
    onModalOpened()
  }
})
</script>

<template>
  <div v-if="visible" class="modal-overlay" @click.self="handleClose">
    <div class="modal">
      <div class="modal-header">
        <div>
          <h2 class="modal-title">修改讨论范围</h2>
          <p class="modal-subtitle">增加或移除本次对话参考的会议和知识库</p>
        </div>
        <button class="modal-close" @click="handleClose">✕</button>
      </div>

      <div class="modal-body">
        <!-- 选择会议 -->
        <div class="select-section">
          <div class="select-section-header">
            <span class="select-section-title">
              📋 选择会议
              <span class="select-section-count">已选 {{ selectedMeetingCount }} 个</span>
            </span>
            <div class="select-search">
              <input
                v-model="meetingSearch"
                type="text"
                placeholder="搜索会议..."
                @input="handleMeetingSearch"
              />
            </div>
          </div>

          <!-- 会议列表：仅首次加载无数据时显示"加载中"；翻页时保留旧列表 -->
          <div
            v-if="chatStore.meetingsLoading && chatStore.availableMeetings.length === 0"
            class="select-empty"
          >
            <p>加载中...</p>
          </div>

          <div v-else-if="!chatStore.meetingsLoading && chatStore.availableMeetings.length === 0" class="select-empty">
            <div class="select-empty-icon">📋</div>
            <p>暂无可选择的会议</p>
          </div>

          <div v-else>
            <div :class="{ 'select-list-fetching': chatStore.meetingsLoading }">
              <div
                v-for="meeting in chatStore.availableMeetings"
                :key="meeting.id"
                class="select-option"
                :class="{ selected: isMeetingSelected(meeting) }"
                @click="toggleMeeting(meeting)"
              >
                <div class="select-option-checkbox">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3">
                    <polyline points="20 6 9 17 4 12"/>
                  </svg>
                </div>
                <div class="select-option-icon icon-meeting">📋</div>
                <div class="select-option-info">
                  <div class="select-option-name">{{ meeting.meeting_name }}</div>
                  <div class="select-option-desc">ID: {{ meeting.id }} · {{ meeting.task_id ? '已转写' : '处理中' }}</div>
                </div>
              </div>

              <!-- 会议分页 -->
              <div v-if="totalMeetingPages > 1" class="select-pagination">
                <button
                  class="select-pagination-btn"
                  :disabled="meetingPage <= 1"
                  @click="handleMeetingPageChange(meetingPage - 1)"
                >
                  <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                    <path d="M15 18l-6-6 6-6"/>
                  </svg>
                </button>
                <span class="select-pagination-text">{{ meetingPage }} / {{ totalMeetingPages }}</span>
                <button
                  class="select-pagination-btn"
                  :disabled="meetingPage >= totalMeetingPages"
                  @click="handleMeetingPageChange(meetingPage + 1)"
                >
                  <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                    <path d="M9 18l6-6-6-6"/>
                  </svg>
                </button>
              </div>
            </div>
          </div>
        </div>

        <!-- 选择知识库 -->
        <div class="select-section">
          <div class="select-section-header">
            <span class="select-section-title">
              📚 选择知识库
              <span class="select-section-count" v-if="chatStore.needKb">已选 {{ selectedKbCount }} 个</span>
            </span>
            <button
              class="need-kb-toggle"
              :class="{ active: chatStore.needKb }"
              @click="toggleNeedKb"
            >
              <span class="toggle-dot"></span>
              使用知识库
            </button>
          </div>

          <div v-if="chatStore.needKb">
            <div class="select-search" style="margin-bottom:12px;">
              <input
                v-model="knowledgeSearch"
                type="text"
                placeholder="搜索知识库..."
                @input="handleKnowledgeSearch"
              />
            </div>

            <!-- 知识库列表：仅首次加载无数据时显示"加载中"；翻页时保留旧列表 -->
            <div
              v-if="chatStore.knowledgeLoading && chatStore.availableKnowledge.length === 0"
              class="select-empty"
            >
              <p>加载中...</p>
            </div>

            <div v-else-if="!chatStore.knowledgeLoading && chatStore.availableKnowledge.length === 0" class="select-empty">
              <div class="select-empty-icon">📚</div>
              <p>暂无可选择的知识库</p>
            </div>

            <div v-else>
              <div :class="{ 'select-list-fetching': chatStore.knowledgeLoading }">
                <div
                  v-for="kb in chatStore.availableKnowledge"
                  :key="kb.id"
                  class="select-option"
                  :class="{ selected: isKnowledgeSelected(kb) }"
                  @click="toggleKnowledge(kb)"
                >
                  <div class="select-option-checkbox">
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3">
                      <polyline points="20 6 9 17 4 12"/>
                    </svg>
                  </div>
                  <div class="select-option-icon icon-kb">📚</div>
                  <div class="select-option-info">
                    <div class="select-option-name">{{ kb.name }}</div>
                    <div class="select-option-desc">{{ kb.description || '无描述' }}</div>
                  </div>
                </div>

                <!-- 知识库分页 -->
                <div v-if="totalKnowledgePages > 1" class="select-pagination">
                  <button
                    class="select-pagination-btn"
                    :disabled="knowledgePage <= 1"
                    @click="handleKnowledgePageChange(knowledgePage - 1)"
                  >
                    <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                      <path d="M15 18l-6-6 6-6"/>
                    </svg>
                  </button>
                  <span class="select-pagination-text">{{ knowledgePage }} / {{ totalKnowledgePages }}</span>
                  <button
                    class="select-pagination-btn"
                    :disabled="knowledgePage >= totalKnowledgePages"
                    @click="handleKnowledgePageChange(knowledgePage + 1)"
                  >
                    <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                      <path d="M9 18l6-6-6-6"/>
                    </svg>
                  </button>
                </div>
                <!-- 锚点：翻页后自动滚动到此 -->
                <div ref="knowledgeAnchorRef"></div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div class="modal-footer">
        <button class="btn-secondary" @click="handleClose">取消</button>
        <button class="btn-primary" @click="handleSave">
          保存修改
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped lang="scss">
@use '@/styles/mixins.scss' as *;

.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  backdrop-filter: blur(3px);
}

.modal {
  background: white;
  border-radius: 20px;
  padding: 0;
  width: 100%;
  max-width: 580px;
  box-shadow: var(--shadow-xl);
  animation: modalIn 0.25s ease-out;
  overflow: hidden;
}

@keyframes modalIn {
  from { opacity: 0; transform: scale(0.95) translateY(10px); }
  to { opacity: 1; transform: scale(1) translateY(0); }
}

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

.modal-body {
  padding: 0 28px 24px;
  max-height: 60vh;
  overflow-y: auto;
}

.modal-footer {
  display: flex;
  gap: 12px;
  justify-content: flex-end;
  padding: 16px 28px;
  border-top: 1px solid var(--color-stone-100);
  background: var(--color-stone-50);
}

// 选择区
.select-section {
  margin-bottom: 24px;

  &:last-child {
    margin-bottom: 0;
  }
}

.select-section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
  gap: 12px;
}

.select-section-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--color-stone-800);
  display: flex;
  align-items: center;
  gap: 8px;
  white-space: nowrap;
}

.select-section-count {
  font-size: 13px;
  color: var(--color-stone-500);
  font-weight: 400;
}

.select-search {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 9px 14px;
  border: 1.5px solid var(--color-stone-200);
  border-radius: var(--radius-lg);
  background: var(--color-stone-50);
  transition: all 0.2s;
  flex: 1;
  max-width: 220px;

  &:focus-within {
    border-color: var(--color-amber-400);
    background: white;
    box-shadow: 0 0 0 3px rgba(245,180,0,0.08);
  }

  input {
    flex: 1;
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

.select-pagination {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid var(--color-stone-100);
}

.select-pagination-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border: 1px solid var(--color-stone-200);
  border-radius: var(--radius-md);
  background: white;
  color: var(--color-stone-600);
  font-size: 11px;
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

.select-pagination-text {
  font-size: 11px;
  color: var(--color-stone-500);
  padding: 0 6px;
  white-space: nowrap;
}

// 翻页时的微妙加载态（列表保留可见，透明度降低）
.select-list-fetching {
  opacity: 0.6;
  pointer-events: none;
  transition: opacity 0.15s;
}

// 可选项
.select-option {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 14px;
  border: 1px solid var(--color-stone-200);
  border-radius: var(--radius-lg);
  margin-bottom: 6px;
  cursor: pointer;
  transition: all 0.15s;
  user-select: none;

  &:hover {
    border-color: var(--color-amber-300);
    background: var(--color-amber-50);
  }

  &.selected {
    border-color: var(--color-amber-400);
    background: var(--color-amber-50);
  }
}

.select-option-checkbox {
  width: 20px;
  height: 20px;
  border: 2px solid var(--color-stone-300);
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: all 0.15s;

  svg {
    opacity: 0;
    transition: opacity 0.15s;
  }
}

.select-option.selected .select-option-checkbox {
  background: var(--color-amber-400);
  border-color: var(--color-amber-400);
  color: white;
}

.select-option.selected .select-option-checkbox svg {
  opacity: 1;
}

.select-option-icon {
  width: 36px;
  height: 36px;
  border-radius: 9px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
  flex-shrink: 0;
}

.icon-meeting {
  background: linear-gradient(135deg, #DBEAFE, #BFDBFE);
  color: #1D4ED8;
}

.icon-kb {
  background: linear-gradient(135deg, #ECFDF5, #A7F3D0);
  color: #059669;
}

.select-option-info {
  flex: 1;
  min-width: 0;
}

.select-option-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-stone-800);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.select-option-desc {
  font-size: 11px;
  color: var(--color-stone-500);
  margin-top: 2px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

// need_kb 切换按钮
.need-kb-toggle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  border: 1.5px solid var(--color-stone-200);
  border-radius: 20px;
  background: white;
  color: var(--color-stone-500);
  font-size: 12px;
  font-weight: 500;
  font-family: var(--font-body);
  cursor: pointer;
  transition: all 0.2s;
  user-select: none;
  white-space: nowrap;

  &:hover {
    border-color: var(--color-amber-300);
    background: var(--color-amber-50);
    color: var(--color-amber-600);
  }

  &.active {
    border-color: var(--color-amber-400);
    background: var(--color-amber-50);
    color: var(--color-amber-600);
    box-shadow: 0 0 0 2px rgba(245,180,0,0.08);
  }

  .toggle-dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: var(--color-stone-400);
    transition: all 0.2s;
  }

  &.active .toggle-dot {
    background: var(--color-amber-500);
    box-shadow: 0 0 4px rgba(245,180,0,0.4);
  }
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

  &:hover {
    background: var(--color-amber-500);
    transform: translateY(-1px);
    box-shadow: 0 4px 12px rgba(245,180,0,0.25);
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

// ===== 移动端响应式 =====
@include respond-to(sm) {
  .modal {
    max-width: calc(100vw - 32px);
    border-radius: 16px;
  }

  .modal-header {
    padding: 20px 20px 12px;
  }

  .modal-title {
    font-size: 18px;
  }

  .modal-body {
    padding: 0 20px 16px;
    max-height: 55vh;
  }

  .modal-footer {
    padding: 12px 20px;
    gap: 8px;
  }

  .select-section-header {
    flex-direction: column;
    align-items: flex-start;
    gap: 10px;
  }

  .select-search {
    max-width: 100%;
    width: 100%;
  }

  .select-option {
    padding: 10px 12px;
    gap: 8px;
  }
}
</style>
