<script setup lang="ts">
// ============================================================
// KnowledgeView — 知识库管理
// 基于 design/mockupsknowledge-base.html 设计稿实现
// 功能：左侧知识库列表 / 右侧文件列表 / 新建编辑弹窗（含授权用户管理）
// ============================================================
import { ref, reactive, computed, onMounted, onUnmounted } from 'vue'
import { ElMessage } from 'element-plus'
import DefaultLayout from '@/layouts/DefaultLayout.vue'
import { useKnowledgeStore } from '@/stores/knowledge'
import type { KnowledgeItem, KnowledgeFileItem } from '@/api/types'

const knowledgeStore = useKnowledgeStore()

// ================================================================
// 左侧状态
// ================================================================
const kbKeyword = ref('')
const kbPageNum = ref(1)
const kbPageSize = ref(20)
const kbTotal = ref(0)

// ================================================================
// 右侧状态
// ================================================================
const activeKnowledgeId = ref('')
const activeFilter = ref('all') // all | text | audio | image | video
const keyword = ref('')
const expandedErrorId = ref<string | null>(null)
const polling = ref(false)
const mobileFilterOpen = ref(false)
const showMobileSearch = ref(false)

const filterOptions = [
  { key: 'all', label: '全部类型' },
  { key: 'text', label: '📄 文档' },
  { key: 'audio', label: '🎵 音频' },
  { key: 'image', label: '🖼 图片' },
  { key: 'video', label: '🎬 视频' },
]

const filterLabelMap: Record<string, string> = {
  all: '全部类型',
  text: '文档',
  audio: '音频',
  image: '图片',
  video: '视频',
}
const currentFilterLabel = computed(() => filterLabelMap[activeFilter.value] || '全部类型')

// ================================================================
// 弹窗状态
// ================================================================
const uploadDialogVisible = ref(false)
const chunksDialogVisible = ref(false)
const chunksLoading = ref(false)
const chunksText = ref<string[]>([])
const chunksFileName = ref('')
const deleteKbDialogVisible = ref(false)

// 单个切片查看弹窗
const showSingleChunkModal = ref(false)
const activeChunkIndex = ref(0)
const activeChunkContent = ref('')

// 删除文件确认弹窗
const deleteFileDialogVisible = ref(false)
const deleteFileId = ref('')
const deleteFileName = ref('')

// ================================================================
// 新建知识库弹窗
// ================================================================
const createKbDialogVisible = ref(false)
const createKbForm = reactive({
  name: '',
  description: '',
})
const createKbUserSearch = ref('')
const createKbSelectedUsers = ref<number[]>([])
const createKbUserPage = ref(1)
const createKbUserPageSize = 5

// ================================================================
// 编辑知识库弹窗
// ================================================================
const editKbDialogVisible = ref(false)
const editKbForm = reactive({
  id: '',
  name: '',
  description: '',
})
const editKbUserSearch = ref('')
const editKbSelectedUsers = ref<number[]>([])
const editKbUserPage = ref(1)
const editKbUserPageSize = 5

// ================================================================
// 计算属性
// ================================================================

// 筛选后的知识库列表
const filteredKnowledgeList = computed(() => {
  if (!kbKeyword.value.trim()) return knowledgeStore.knowledgeList
  const k = kbKeyword.value.trim().toLowerCase()
  return knowledgeStore.knowledgeList.filter((item) => item.name.toLowerCase().includes(k))
})

// 分组：我的知识库（创建者 or 仅自己可见） vs 团队共享
const myKnowledgeList = computed(() => {
  return filteredKnowledgeList.value.filter((k) => {
    const users = k.accept_users || k.user_ids || []
    return users.length <= 1
  })
})

const sharedKnowledgeList = computed(() => {
  return filteredKnowledgeList.value.filter((k) => {
    const users = k.accept_users || k.user_ids || []
    return users.length > 1
  })
})

// 统计 — 后端 type: 0=文本 1=音频 2=图片
const stats = computed(() => {
  const all = knowledgeStore.files
  return {
    all: all.length,
    text: all.filter((f) => f.type === 0).length,
    audio: all.filter((f) => f.type === 1).length,
    image: all.filter((f) => f.type === 2).length,
    video: all.filter((f) => f.type !== 0 && f.type !== 1 && f.type !== 2).length,
  }
})

// 筛选映射：前端 filter → 后端 type 值
const filterTypeMap: Record<string, number> = {
  text: 0,
  audio: 1,
  image: 2,
}

// 筛选后的文件列表
const filteredFiles = computed(() => {
  let result = knowledgeStore.files
  if (activeFilter.value !== 'all') {
    const targetType = filterTypeMap[activeFilter.value]
    result = result.filter((f) => f.type === targetType)
  }
  if (keyword.value.trim()) {
    const k = keyword.value.trim().toLowerCase()
    result = result.filter((f) => f.file_name.toLowerCase().includes(k))
  }
  return result
})

// 新建弹窗：筛选+分页后的用户列表
const createKbFilteredUsers = computed(() => {
  const all = knowledgeStore.userList
  if (!createKbUserSearch.value.trim()) return all
  const k = createKbUserSearch.value.trim().toLowerCase()
  return all.filter((u) => u.username.toLowerCase().includes(k))
})
const createKbUserTotal = computed(() => createKbFilteredUsers.value.length)
const createKbUserPages = computed(() => Math.max(1, Math.ceil(createKbFilteredUsers.value.length / createKbUserPageSize)))
const createKbPagedUsers = computed(() => {
  const start = (createKbUserPage.value - 1) * createKbUserPageSize
  return createKbFilteredUsers.value.slice(start, start + createKbUserPageSize)
})

// 编辑弹窗：筛选+分页后的用户列表
const editKbFilteredUsers = computed(() => {
  const all = knowledgeStore.userList
  if (!editKbUserSearch.value.trim()) return all
  const k = editKbUserSearch.value.trim().toLowerCase()
  return all.filter((u) => u.username.toLowerCase().includes(k))
})
const editKbUserTotal = computed(() => editKbFilteredUsers.value.length)
const editKbUserPages = computed(() => Math.max(1, Math.ceil(editKbFilteredUsers.value.length / editKbUserPageSize)))
const editKbPagedUsers = computed(() => {
  const start = (editKbUserPage.value - 1) * editKbUserPageSize
  return editKbFilteredUsers.value.slice(start, start + editKbUserPageSize)
})

// ================================================================
// 工具函数
// ================================================================

/** 状态解析 */
function getStatusInfo(f: KnowledgeFileItem) {
  const s = f.state
  if (s === 1) return { label: '解析完成', type: 'complete', icon: '✅' }
  if (s === 2) return { label: '解析失败', type: 'error', icon: '⚠' }
  if (s === 0) return { label: '正在解析', type: 'processing', icon: '⏳' }
  return { label: '等待中', type: 'pending', icon: '⏸' }
}

/** 文件类型 → CSS class（后端 0=文本 1=音频 2=图片）*/
function getTypeClass(type?: number | string) {
  if (type === 0 || type === 'doc') return 'doc'
  if (type === 1 || type === 'image') return 'image'
  if (type === 2 || type === 'audio') return 'audio'
  if (type === 3 || type === 'video') return 'video'
  return 'other'
}

/** 文件类型 → 简短文本标签 */
function getTypeLabel(type?: number | string) {
  if (type === 0 || type === 'doc') return '文档'
  if (type === 1 || type === 'image') return '图片'
  if (type === 2 || type === 'audio') return '音频'
  if (type === 3 || type === 'video') return '视频'
  return '其他'
}

/** KB 图标 */
function getKbIconClass(index: number) {
  const classes = ['kb-icon-project', 'kb-icon-research', 'kb-icon-resource', 'kb-icon-client', 'kb-icon-team', 'kb-icon-general']
  return classes[index % classes.length]
}
function getKbIcon(index: number) {
  const icons = ['📁', '🔬', '📚', '👥', '👨‍💼', '📦']
  return icons[index % icons.length]
}

/** 切换错误展开 */
function toggleError(fileId: string) {
  expandedErrorId.value = expandedErrorId.value === fileId ? null : fileId
}

/** 切换筛选 */
function changeFilter(filter: string) {
  activeFilter.value = filter
}

/** 移动端：切换搜索框显示并聚焦 */
function toggleMobileSearch() {
  showMobileSearch.value = !showMobileSearch.value
  if (showMobileSearch.value) {
    // 下一帧聚焦搜索输入框
    requestAnimationFrame(() => {
      const input = document.querySelector('.search-box input') as HTMLInputElement | null
      input?.focus()
    })
  }
}

// ================================================================
// 左侧操作
// ================================================================

/** 选择知识库 */
async function selectKnowledge(k: KnowledgeItem) {
  activeKnowledgeId.value = k.id
  expandedErrorId.value = null
  await knowledgeStore.selectKnowledge(k.id, k.name)
  startPolling()
}

/** 加载知识库列表 */
async function loadKbList() {
  await knowledgeStore.loadKnowledgeList(kbPageNum.value, kbPageSize.value)
}

// ================================================================
// 右侧操作
// ================================================================

/** 上传文件 */
async function handleUpload(file: File) {
  try {
    await knowledgeStore.uploadFile(file)
    ElMessage.success('文件已上传，正在后台解析')
    uploadDialogVisible.value = false
    startPolling()
  } catch (e: any) {
    ElMessage.error(e.message || '上传失败')
  }
  return false
}

/** 删除文件 */
function handleDeleteFile(fileId: string, fileName: string) {
  deleteFileId.value = fileId
  deleteFileName.value = fileName
  deleteFileDialogVisible.value = true
}

/** 确认删除文件 */
async function confirmDeleteFile() {
  try {
    await knowledgeStore.deleteFile(deleteFileId.value)
    ElMessage.success('已删除')
    deleteFileDialogVisible.value = false
  } catch (e: any) {
    ElMessage.error(e.message || '删除失败')
  }
}

/** 查看分块 */
async function handleViewChunks(file: KnowledgeFileItem) {
  chunksFileName.value = file.file_name
  chunksLoading.value = true
  chunksDialogVisible.value = true
  try {
    const chunks = await knowledgeStore.getFileChunks(file.id)
    chunksText.value = chunks
  } catch (e: any) {
    ElMessage.error(e.message || '获取分块失败')
    chunksDialogVisible.value = false
  } finally {
    chunksLoading.value = false
  }
}

/** 打开单个切片详情弹窗 */
function openSingleChunk(chunk: string, index: number) {
  activeChunkContent.value = chunk
  activeChunkIndex.value = index + 1
  showSingleChunkModal.value = true
}

// ================================================================
// 轮询
// ================================================================
function startPolling() {
  stopPolling()
  const hasProcessing = knowledgeStore.files.some((f) => f.state === 0)
  if (hasProcessing) {
    polling.value = true
    knowledgeStore.pollFileStates()
    // 每 5 秒轮询一次
    const timer = setInterval(async () => {
      const stillProcessing = knowledgeStore.files.some((f) => f.state === 0)
      if (!stillProcessing) {
        stopPolling()
        return
      }
      await knowledgeStore.pollFileStates()
    }, 5000)
    // 保存 timer id
    ;(knowledgeStore as any)._pollTimer = timer
  }
}

function stopPolling() {
  polling.value = false
  if ((knowledgeStore as any)._pollTimer) {
    clearInterval((knowledgeStore as any)._pollTimer)
    ;(knowledgeStore as any)._pollTimer = null
  }
}

// ================================================================
// 新建知识库
// ================================================================

/** 打开新建弹窗：先获取用户列表 */
async function openCreateKbDialog() {
  createKbForm.name = ''
  createKbForm.description = ''
  createKbSelectedUsers.value = []
  createKbUserSearch.value = ''
  createKbUserPage.value = 1
  createKbDialogVisible.value = true
  try {
    await knowledgeStore.loadUserList()
  } catch (e: any) {
    ElMessage.error('获取用户列表失败')
  }
}

/** 确认创建 */
async function handleCreateKb() {
  if (!createKbForm.name.trim()) {
    ElMessage.warning('请输入知识库名称')
    return
  }
  try {
    await knowledgeStore.createKnowledge(
      createKbForm.name,
      createKbForm.description,
      createKbSelectedUsers.value
    )
    ElMessage.success('知识库已创建')
    createKbDialogVisible.value = false
    // 刷新列表
    await loadKbList()
  } catch (e: any) {
    ElMessage.error(e.message || '创建失败')
  }
}

/** 切换用户选中状态（新建） */
function toggleCreateUser(userId: number) {
  const idx = createKbSelectedUsers.value.indexOf(userId)
  if (idx === -1) {
    createKbSelectedUsers.value.push(userId)
  } else {
    createKbSelectedUsers.value.splice(idx, 1)
  }
}

// ================================================================
// 编辑知识库
// ================================================================

/** 打开编辑弹窗：先获取详情和用户列表 */
async function openEditKbDialog() {
  if (!activeKnowledgeId.value) return
  editKbForm.id = activeKnowledgeId.value
  editKbUserSearch.value = ''
  editKbUserPage.value = 1
  editKbDialogVisible.value = true
  try {
    // 并行获取详情和用户列表
    const [detail] = await Promise.all([
      knowledgeStore.getDetail(activeKnowledgeId.value),
      knowledgeStore.loadUserList(),
    ])
    editKbForm.name = detail.name
    editKbForm.description = detail.description || ''
    editKbSelectedUsers.value = [...(detail.accept_users || [])]
  } catch (e: any) {
    ElMessage.error(e.message || '获取知识库详情失败')
  }
}

/** 确认编辑 */
async function handleEditKb() {
  if (!editKbForm.name.trim()) {
    ElMessage.warning('请输入知识库名称')
    return
  }
  try {
    await knowledgeStore.updateKnowledge(
      editKbForm.id,
      editKbForm.name,
      editKbForm.description,
      editKbSelectedUsers.value
    )
    ElMessage.success('知识库已更新')
    editKbDialogVisible.value = false
    await loadKbList()
  } catch (e: any) {
    ElMessage.error(e.message || '更新失败')
  }
}

/** 切换用户选中状态（编辑） */
function toggleEditUser(userId: number) {
  const idx = editKbSelectedUsers.value.indexOf(userId)
  if (idx === -1) {
    editKbSelectedUsers.value.push(userId)
  } else {
    editKbSelectedUsers.value.splice(idx, 1)
  }
}

// ================================================================
// 删除知识库
// ================================================================

/** 打开删除确认弹窗 */
function openDeleteKbDialog() {
  if (!activeKnowledgeId.value) return
  deleteKbDialogVisible.value = true
}

/** 确认删除 */
async function handleDeleteKnowledge() {
  try {
    await knowledgeStore.deleteKnowledge(activeKnowledgeId.value)
    activeKnowledgeId.value = ''
    ElMessage.success('已删除')
    deleteKbDialogVisible.value = false
    await loadKbList()
  } catch (e: any) {
    ElMessage.error(e.message || '删除失败')
  }
}

// ================================================================
// 生命周期
// ================================================================
onMounted(async () => {
  await loadKbList()
  startPolling()
})

onUnmounted(() => {
  stopPolling()
  knowledgeStore.stopPolling()
})
</script>

<template>
  <DefaultLayout>
    <div class="knowledge-page">
      <!-- ========== 主体双栏布局 ========== -->
      <div class="layout">
        <!-- ========== 左侧知识库列表 ========== -->
        <aside class="sidebar">
          <div class="sidebar-header">
            <h2 class="sidebar-title">知识库</h2>
            <button class="btn-create-kb desktop-create" @click="openCreateKbDialog">
              <span style="font-size: 16px">+</span>
              新建知识库
            </button>
            <div class="kb-search">
              <span>🔍</span>
              <input v-model="kbKeyword" type="text" placeholder="搜索知识库..." />
            </div>
          </div>

          <!-- 移动端：横向滚动列表上方标题（仅 sm 显示，参照 mobile-responsive 设计 mobile-row-between） -->
          <div class="kb-scroll-header">
            <span class="kb-scroll-title">我的知识库</span>
            <span class="kb-scroll-count">共 {{ filteredKnowledgeList.length }} 个</span>
          </div>

          <div v-loading="knowledgeStore.loading" class="kb-list">
            <div v-if="!knowledgeStore.loading && filteredKnowledgeList.length === 0" class="kb-empty">
              <el-empty description="暂无知识库" :image-size="60" />
            </div>

            <!-- 我的知识库 -->
            <template v-if="myKnowledgeList.length > 0">
              <div class="kb-group-label">我的知识库</div>
              <div
                v-for="(k, idx) in myKnowledgeList"
                :key="k.id"
                class="kb-item"
                :class="{ active: activeKnowledgeId === k.id }"
                @click="selectKnowledge(k)"
              >
                <div class="kb-icon" :class="getKbIconClass(idx)">{{ getKbIcon(idx) }}</div>
                <div class="kb-info">
                  <div class="kb-name">{{ k.name }}</div>
                  <div class="kb-meta">
                    <span>{{ (k.accept_users || k.user_ids || []).length }} 人</span>
                    <span v-if="(k.accept_users || k.user_ids || []).length > 1" class="kb-badge shared">已共享</span>
                    <span v-if="k.create_time" class="kb-badge">{{ k.create_time }}</span>
                  </div>
                </div>
              </div>
            </template>

            <!-- 团队共享 -->
            <template v-if="sharedKnowledgeList.length > 0">
              <div class="kb-group-label" style="margin-top: 6px">团队共享</div>
              <div
                v-for="(k, idx) in sharedKnowledgeList"
                :key="k.id"
                class="kb-item"
                :class="{ active: activeKnowledgeId === k.id }"
                @click="selectKnowledge(k)"
              >
                <div class="kb-icon" :class="getKbIconClass(idx + myKnowledgeList.length)">{{ getKbIcon(idx + myKnowledgeList.length) }}</div>
                <div class="kb-info">
                  <div class="kb-name">{{ k.name }}</div>
                  <div class="kb-meta">
                    <span>{{ (k.accept_users || k.user_ids || []).length }} 人</span>
                    <span class="kb-badge shared">已共享</span>
                    <span v-if="k.create_time" class="kb-badge">{{ k.create_time }}</span>
                  </div>
                </div>
              </div>
            </template>

            <!-- 移动端：新建知识库卡片（横向滚动列表末尾，参照 mobile-responsive 设计 kb-list-card-add） -->
            <div class="kb-item kb-item-add" @click="openCreateKbDialog">
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
              <span>新建知识库</span>
            </div>
          </div>

          <!-- 移动端：当前知识库信息条（参照 mobile-responsive 设计） -->
          <div v-if="knowledgeStore.currentKnowledgeName" class="kb-current-info">
            <span class="kb-current-label">当前：</span>
            <span class="kb-current-name">{{ knowledgeStore.currentKnowledgeName }}</span>
            <span class="kb-current-sep">·</span>
            <span class="kb-current-meta">{{ knowledgeStore.files.length }} 个文件</span>
          </div>

          <!-- 底部分页 -->
          <div class="kb-pagination" v-if="kbTotal > kbPageSize">
            <button class="kb-pagination-btn" :disabled="kbPageNum <= 1" @click="kbPageNum--; loadKbList()">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M15 18l-6-6 6-6" /></svg>
            </button>
            <button
              v-for="p in Math.min(5, Math.ceil(kbTotal / kbPageSize))"
              :key="p"
              class="kb-pagination-btn"
              :class="{ active: kbPageNum === p }"
              @click="kbPageNum = p; loadKbList()"
            >{{ p }}</button>
            <button class="kb-pagination-btn" :disabled="kbPageNum >= Math.ceil(kbTotal / kbPageSize)" @click="kbPageNum++; loadKbList()">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M9 18l6-6-6-6" /></svg>
            </button>
          </div>
        </aside>

        <!-- ========== 右侧文件区域 ========== -->
        <main class="content">
          <!-- 未选中知识库 -->
          <div v-if="!activeKnowledgeId" class="no-selection">
            <div class="no-selection-icon">📚</div>
            <h3>请选择一个知识库</h3>
            <p>从左侧选择要查看的知识库，或新建一个知识库</p>
          </div>

          <div v-else class="content-inner">
            <!-- 内容头部 -->
            <div class="content-header">
              <div class="breadcrumb">
                <a href="#">工作台</a> / {{ knowledgeStore.currentKnowledgeName }}
              </div>
              <div class="content-title-row">
                <div class="content-title-group">
                  <div class="content-icon" :class="getKbIconClass(0)">📁</div>
                  <div>
                    <h1 class="content-title">{{ knowledgeStore.currentKnowledgeName }}</h1>
                    <p class="content-desc">{{ knowledgeStore.files.length }} 个文件</p>
                  </div>
                </div>
                <div class="content-actions">
                  <button class="btn-secondary" @click="openEditKbDialog">
                    <span>✎</span> 编辑
                  </button>
                  <button class="btn-secondary btn-danger" @click="openDeleteKbDialog">
                    <span>🗑</span> 删除
                  </button>
                  <button class="btn-primary" @click="uploadDialogVisible = true">
                    <span>⬆</span> 上传文件
                  </button>
                </div>
              </div>
            </div>

            <!-- 移动端：三按钮平齐操作栏（参照 mobile-responsive 设计：搜索/上传图标 + 筛选按钮） -->
            <div class="action-bar-mobile">
              <button class="action-bar-icon-btn" @click="toggleMobileSearch" aria-label="搜索文件">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
              </button>
              <button class="action-bar-icon-btn" @click="uploadDialogVisible = true" aria-label="上传文件">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
              </button>
              <button class="action-bar-icon-btn" @click="openEditKbDialog" aria-label="编辑知识库">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
              </button>
              <button
                class="filter-toggle-btn"
                :class="{ expanded: mobileFilterOpen }"
                @click="mobileFilterOpen = !mobileFilterOpen"
              >
                <span>{{ currentFilterLabel }}</span>
                <svg class="filter-toggle-arrow" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="6 9 12 15 18 9"/></svg>
              </button>
            </div>

            <!-- 移动端：筛选按钮展开后的分类下拉（参照 mobile-responsive 设计 filter-dropdown） -->
            <div v-if="mobileFilterOpen" class="filter-dropdown-mobile">
              <button
                v-for="f in filterOptions"
                :key="f.key"
                class="filter-dropdown-chip"
                :class="{ active: activeFilter === f.key }"
                @click="changeFilter(f.key); mobileFilterOpen = false"
              >{{ f.label }}</button>
            </div>

            <!-- 操作栏（移动端搜索激活时通过 .mobile-search-visible 强制显示） -->
            <div class="action-bar" :class="{ 'mobile-search-visible': showMobileSearch }">
              <div class="search-box">
                <span>🔍</span>
                <input v-model="keyword" type="text" placeholder="搜索文件名..." />
              </div>
              <div class="filter-group">
                <button class="filter-chip" :class="{ active: activeFilter === 'all' }" @click="changeFilter('all')">全部</button>
                <button class="filter-chip" :class="{ active: activeFilter === 'text' }" @click="changeFilter('text')">📄 文本</button>
                <button class="filter-chip" :class="{ active: activeFilter === 'audio' }" @click="changeFilter('audio')">🎵 音频</button>
                <button class="filter-chip" :class="{ active: activeFilter === 'image' }" @click="changeFilter('image')">🖼 图片</button>
                <button class="filter-chip" :class="{ active: activeFilter === 'video' }" @click="changeFilter('video')">🎬 视频</button>
              </div>
            </div>

            <!-- 分类统计卡 -->
            <div class="stats-bar">
              <div class="stat-card" :class="{ active: activeFilter === 'all' }" @click="changeFilter('all')">
                <div class="stat-icon stat-icon-other">
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" /></svg>
                </div>
                <div class="stat-info">
                  <div class="stat-count">{{ stats.all }}</div>
                  <div class="stat-label">全部文件</div>
                </div>
              </div>
              <div class="stat-card" :class="{ active: activeFilter === 'text' }" @click="changeFilter('text')">
                <div class="stat-icon stat-icon-text">📄</div>
                <div class="stat-info">
                  <div class="stat-count">{{ stats.text }}</div>
                  <div class="stat-label">文本文档</div>
                </div>
              </div>
              <div class="stat-card" :class="{ active: activeFilter === 'audio' }" @click="changeFilter('audio')">
                <div class="stat-icon stat-icon-audio">🎵</div>
                <div class="stat-info">
                  <div class="stat-count">{{ stats.audio }}</div>
                  <div class="stat-label">音频文件</div>
                </div>
              </div>
              <div class="stat-card" :class="{ active: activeFilter === 'image' }" @click="changeFilter('image')">
                <div class="stat-icon stat-icon-image">🖼</div>
                <div class="stat-info">
                  <div class="stat-count">{{ stats.image }}</div>
                  <div class="stat-label">图片素材</div>
                </div>
              </div>
              <div class="stat-card" :class="{ active: activeFilter === 'video' }" @click="changeFilter('video')">
                <div class="stat-icon stat-icon-video">🎬</div>
                <div class="stat-info">
                  <div class="stat-count">{{ stats.video }}</div>
                  <div class="stat-label">视频资料</div>
                </div>
              </div>
            </div>

            <!-- 文件滚动区 -->
            <div class="file-scroll-area">
              <el-empty v-if="filteredFiles.length === 0" description="暂无文件" />

              <div v-else class="file-list">
                <div
                  v-for="file in filteredFiles"
                  :key="file.id"
                  class="file-card"
                  :class="{ expanded: expandedErrorId === file.id }"
                >
                  <div class="file-type-icon" :class="`type-${getTypeClass(file.type)}`">
                    {{ getTypeLabel(file.type) }}
                  </div>
                  <div class="file-info">
                    <div class="file-name" :title="file.file_name">{{ file.file_name }}</div>
                    <div class="file-meta">
                      <span class="file-meta-item">📅 {{ file.create_time || '未知' }}</span>
                      <span v-if="file.chunks_counts" class="file-meta-item">🧩 {{ file.chunks_counts }} 个分块</span>
                    </div>
                    <!-- 错误原因展开 -->
                    <div v-if="getStatusInfo(file).type === 'error' && file.fail_reason && expandedErrorId === file.id" class="error-detail">
                      <strong>错误原因：</strong>{{ file.fail_reason }}
                    </div>
                  </div>
                  <div class="file-status">
                    <span
                      class="status-badge"
                      :class="`status-${getStatusInfo(file).type}`"
                      :style="getStatusInfo(file).type === 'error' ? 'cursor:pointer' : ''"
                      @click="getStatusInfo(file).type === 'error' && toggleError(file.id)"
                    >
                      <span class="status-dot"></span>
                      {{ getStatusInfo(file).label }}
                      {{ getStatusInfo(file).type === 'error' ? '▼' : '' }}
                    </span>
                    <div v-if="getStatusInfo(file).type === 'processing'" class="progress-bar">
                      <div class="progress-fill" style="width: 65%"></div>
                    </div>
                  </div>
                  <div class="file-actions">
                    <button
                      v-if="getStatusInfo(file).type === 'complete'"
                      class="file-action-btn"
                      title="查看"
                      @click="handleViewChunks(file)"
                    >👁</button>
                    <button
                      v-if="getStatusInfo(file).type === 'error'"
                      class="file-action-btn"
                      title="重试"
                    >🔄</button>
                    <button
                      v-if="getStatusInfo(file).type === 'complete'"
                      class="file-action-btn"
                      title="下载"
                    >⬇</button>
                    <button
                      class="file-action-btn danger"
                      title="删除"
                      @click="handleDeleteFile(file.id, file.file_name)"
                    >🗑</button>
                  </div>
                </div>
              </div>
            </div>

            <!-- 文件分页 -->
            <div class="file-pagination" v-if="knowledgeStore.files.length > 0">
              <button class="file-pagination-btn" disabled>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M15 18l-6-6 6-6" /></svg>
              </button>
              <button class="file-pagination-btn active">1</button>
              <span class="file-pagination-text">共 {{ knowledgeStore.files.length }} 个文件</span>
              <button class="file-pagination-btn">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M9 18l6-6-6-6" /></svg>
              </button>
            </div>
          </div>
        </main>
      </div>

      <!-- ============================================================ -->
      <!-- ======================== 弹窗区域 ========================== -->
      <!-- ============================================================ -->

      <!-- ========== 新建知识库弹窗 ========== -->
      <el-dialog v-model="createKbDialogVisible" width="500px" destroy-on-close :show-close="false">
        <div class="modal-inner">
          <div class="modal-header">
            <h2 class="modal-title">新建知识库</h2>
            <button class="modal-close" @click="createKbDialogVisible = false">✕</button>
          </div>
          <div class="form-group">
            <label class="form-label">知识库名称</label>
            <input v-model="createKbForm.name" class="form-input" placeholder="输入知识库名称，如：用户调研报告" />
          </div>
          <div class="form-group">
            <label class="form-label">描述（可选）</label>
            <textarea v-model="createKbForm.description" class="form-input form-textarea" placeholder="描述这个知识库的用途和内容..."></textarea>
          </div>
          <!-- 授权用户选择 -->
          <div class="grant-section">
            <label class="form-label">
              <span style="margin-right: 4px">🔐</span>新增授权用户
            </label>
            <p class="grant-tip">选择可访问该知识库的用户</p>
            <div class="grant-search">
              <span>🔍</span>
              <input v-model="createKbUserSearch" type="text" placeholder="搜索用户名..." />
            </div>
            <div class="grant-selected-count">已选 {{ createKbSelectedUsers.length }} 个用户</div>
            <div class="grant-user-list">
              <div
                v-for="user in createKbPagedUsers"
                :key="user.id"
                class="grant-user-item"
                :class="{ selected: createKbSelectedUsers.includes(user.id) }"
                @click="toggleCreateUser(user.id)"
              >
                <div class="grant-user-checkbox">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="3.5"><path d="M20 6L9 17l-5-5" /></svg>
                </div>
                <div class="grant-user-avatar">{{ user.username.charAt(0) }}</div>
                <div class="grant-user-info">
                  <div class="grant-user-name">{{ user.username }}</div>
                </div>
              </div>
              <div v-if="createKbPagedUsers.length === 0" class="grant-empty">无匹配用户</div>
            </div>
            <div class="grant-pagination" v-if="createKbUserPages > 1">
              <button class="grant-pagination-btn" :disabled="createKbUserPage <= 1" @click="createKbUserPage--">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M15 18l-6-6 6-6" /></svg>
              </button>
              <button
                v-for="p in createKbUserPages"
                :key="p"
                class="grant-pagination-btn"
                :class="{ active: createKbUserPage === p }"
                @click="createKbUserPage = p"
              >{{ p }}</button>
              <span class="grant-pagination-text">共 {{ createKbUserTotal }} 个用户</span>
              <button class="grant-pagination-btn" :disabled="createKbUserPage >= createKbUserPages" @click="createKbUserPage++">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M9 18l6-6-6-6" /></svg>
              </button>
            </div>
          </div>
          <div class="modal-footer">
            <button class="btn-secondary" @click="createKbDialogVisible = false">取消</button>
            <button class="btn-primary" @click="handleCreateKb">确认创建</button>
          </div>
        </div>
      </el-dialog>

      <!-- ========== 编辑知识库弹窗 ========== -->
      <el-dialog v-model="editKbDialogVisible" width="500px" destroy-on-close :show-close="false">
        <div class="modal-inner">
          <div class="modal-header">
            <h2 class="modal-title">编辑知识库</h2>
            <button class="modal-close" @click="editKbDialogVisible = false">✕</button>
          </div>
          <div class="form-group">
            <label class="form-label">知识库名称</label>
            <input v-model="editKbForm.name" class="form-input" placeholder="输入知识库名称" />
          </div>
          <div class="form-group">
            <label class="form-label">描述</label>
            <textarea v-model="editKbForm.description" class="form-input form-textarea" placeholder="描述这个知识库的用途和内容..."></textarea>
          </div>
          <!-- 授权用户管理 -->
          <div class="grant-section">
            <label class="form-label">
              <span style="margin-right: 4px">🔐</span>授权用户管理
            </label>
            <p class="grant-tip">添加或移除可访问该知识库的用户</p>
            <div class="grant-search">
              <span>🔍</span>
              <input v-model="editKbUserSearch" type="text" placeholder="搜索用户名..." />
            </div>
            <div class="grant-selected-count">已选 {{ editKbSelectedUsers.length }} 个用户</div>
            <div class="grant-user-list">
              <div
                v-for="user in editKbPagedUsers"
                :key="user.id"
                class="grant-user-item"
                :class="{ selected: editKbSelectedUsers.includes(user.id) }"
                @click="toggleEditUser(user.id)"
              >
                <div class="grant-user-checkbox">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="3.5"><path d="M20 6L9 17l-5-5" /></svg>
                </div>
                <div class="grant-user-avatar">{{ user.username.charAt(0) }}</div>
                <div class="grant-user-info">
                  <div class="grant-user-name">{{ user.username }}</div>
                </div>
              </div>
              <div v-if="editKbPagedUsers.length === 0" class="grant-empty">无匹配用户</div>
            </div>
            <div class="grant-pagination" v-if="editKbUserPages > 1">
              <button class="grant-pagination-btn" :disabled="editKbUserPage <= 1" @click="editKbUserPage--">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M15 18l-6-6 6-6" /></svg>
              </button>
              <button
                v-for="p in editKbUserPages"
                :key="p"
                class="grant-pagination-btn"
                :class="{ active: editKbUserPage === p }"
                @click="editKbUserPage = p"
              >{{ p }}</button>
              <span class="grant-pagination-text">共 {{ editKbUserTotal }} 个用户</span>
              <button class="grant-pagination-btn" :disabled="editKbUserPage >= editKbUserPages" @click="editKbUserPage++">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M9 18l6-6-6-6" /></svg>
              </button>
            </div>
          </div>
          <div class="modal-footer">
            <button class="btn-secondary" @click="editKbDialogVisible = false">取消</button>
            <button class="btn-primary" @click="handleEditKb">保存修改</button>
          </div>
        </div>
      </el-dialog>

      <!-- ========== 删除知识库确认弹窗 ========== -->
      <el-dialog v-model="deleteKbDialogVisible" width="400px" destroy-on-close :show-close="false">
        <div class="modal-inner">
          <div class="modal-header">
            <h2 class="modal-title">删除知识库</h2>
            <button class="modal-close" @click="deleteKbDialogVisible = false">✕</button>
          </div>
          <div class="delete-warning">
            <div class="delete-icon">⚠️</div>
            <p class="delete-title">
              确定要删除知识库「{{ knowledgeStore.currentKnowledgeName }}」吗？
            </p>
            <p class="delete-desc">
              此操作将永久删除该知识库及其包含的所有文件，且无法恢复。请谨慎操作。
            </p>
          </div>
          <div class="modal-footer" style="justify-content: center">
            <button class="btn-secondary" @click="deleteKbDialogVisible = false">取消</button>
            <button class="btn-danger" @click="handleDeleteKnowledge">确认删除</button>
          </div>
        </div>
      </el-dialog>

      <!-- ========== 删除文件确认弹窗 ========== -->
      <el-dialog v-model="deleteFileDialogVisible" width="380px" destroy-on-close :show-close="false" align-center>
        <div class="modal-inner">
          <div class="delete-warning">
            <div class="delete-icon">⚠️</div>
            <p class="delete-title">
              确定要删除文件「{{ deleteFileName }}」吗？
            </p>
            <p class="delete-desc">
              此操作将永久删除该文件及其包含的所有向量数据，且无法恢复。
            </p>
          </div>
          <div class="modal-footer" style="justify-content: center; gap: 10px;">
            <button class="btn-secondary" @click="deleteFileDialogVisible = false">取消</button>
            <button class="btn-danger" @click="confirmDeleteFile">确认删除</button>
          </div>
        </div>
      </el-dialog>

      <!-- ========== 上传对话框 ========== -->
      <el-dialog v-model="uploadDialogVisible" title="上传知识文件" width="500px" destroy-on-close>
        <div>
          <el-upload
            :show-file-list="false"
            :before-upload="handleUpload"
            drag
            class="dialog-upload-zone"
          >
            <div class="upload-icon">⬆</div>
            <div class="upload-text">点击或拖拽文件到此处</div>
            <div class="upload-hint">支持 .pdf .docx .txt .md .mp3 .wav .jpg .png .mp4 等格式<br />最大 100MB</div>
          </el-upload>
          <div style="margin-top: 14px; font-size: 13px; color: var(--color-stone-600)">
            文件将上传到：<strong>{{ knowledgeStore.currentKnowledgeName }}</strong>
          </div>
        </div>
        <template #footer>
          <div style="display: flex; justify-content: flex-end; gap: 10px;">
            <button class="btn-secondary" @click="uploadDialogVisible = false">取消</button>
            <!-- <button class="btn-primary" @click="uploadDialogVisible = false">确认上传</button> -->
          </div>
        </template>
      </el-dialog>

      <!-- ========== 切片列表弹窗 ========== -->
      <el-dialog
        v-model="chunksDialogVisible"
        :title="`文档切片列表 - ${chunksFileName}`"
        width="75%"
        class="fixed-chunk-dialog"
        append-to-body
        :show-close="true"
        align-center
      >
        <!-- 内容区域 -->
        <div class="chunk-grid-container" v-loading="chunksLoading">
          <el-empty v-if="!chunksLoading && chunksText.length === 0" description="暂无切片数据" />

          <!-- 卡片网格 -->
          <div v-else class="chunk-grid">
            <div
              v-for="(chunk, index) in chunksText"
              :key="index"
              class="chunk-card"
            >
              <!-- 卡片头部 -->
              <div class="card-header">
                <span class="fragment-title">片段 {{ index + 1 }}</span>
              </div>

              <!-- 字符统计 -->
              <div class="card-meta">
                {{ chunk?.length ?? 0 }} 个字符
              </div>

              <!-- 内容预览 -->
              <div class="card-body">
                {{ chunk }}
              </div>

              <!-- 底部操作栏：仅保留查看按钮 -->
              <div class="card-footer single-action">
                <el-button
                  type="primary"
                  plain
                  class="btn-view-detail"
                  @click="openSingleChunk(chunk, index)"
                >
                  查看详情
                </el-button>
              </div>
            </div>
          </div>
        </div>

        <template #footer>
          <div class="dialog-footer">
            <el-button @click="chunksDialogVisible = false">关闭列表</el-button>
          </div>
        </template>
      </el-dialog>

      <!-- 单个切片详细内容查看弹窗 -->
      <el-dialog
        v-model="showSingleChunkModal"
        :title="`片段 ${activeChunkIndex} 详情`"
        width="600px"
        append-to-body
        class="single-chunk-dialog"
      >
        <div class="single-chunk-content">
          {{ activeChunkContent }}
        </div>
        <template #footer>
          <div style="display: flex; justify-content: center;">
            <el-button style="background: var(--color-stone-100); color: var(--color-stone-700); border-color: var(--color-stone-200); padding: 8px 24px;" @click="showSingleChunkModal = false">关闭</el-button>
          </div>
        </template>
      </el-dialog>
    </div>
  </DefaultLayout>
</template>

<style scoped lang="scss">
@use '@/styles/mixins.scss' as *;

// ================================================================
// 主体布局
// ================================================================
.knowledge-page {
  height: calc(100vh - 64px);
  display: flex;
  flex-direction: column;
}

.layout {
  display: flex;
  flex: 1;
  min-height: 0;
  background: var(--color-stone-50);
}

// ================================================================
// 左侧
// ================================================================
.sidebar {
  width: 320px;
  min-width: 320px;
  background: white;
  border-right: 1px solid var(--color-stone-200);
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
}

.sidebar-header {
  padding: 24px 24px 16px;
  border-bottom: 1px solid var(--color-stone-100);
}

.sidebar-title {
  font-family: var(--font-display);
  font-size: 16px;
  font-weight: 600;
  color: var(--color-stone-800);
  margin-bottom: 16px;
}

.btn-create-kb {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 10px 14px;
  border: 1.5px dashed var(--color-stone-300);
  border-radius: $radius-lg;
  background: var(--color-stone-50);
  color: var(--color-stone-600);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
  margin-bottom: 14px;

  &:hover {
    border-color: var(--color-amber-400);
    background: var(--color-amber-50);
    color: var(--color-amber-600);
  }
}

.kb-search {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  border: 1.5px solid var(--color-stone-200);
  border-radius: $radius-lg;
  background: var(--color-stone-50);
  transition: all 0.2s;

  &:focus-within {
    border-color: var(--color-amber-400);
    background: white;
    box-shadow: 0 0 0 3px rgba(245, 180, 0, 0.08);
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

.kb-list {
  flex: 1;
  overflow-y: auto;
  padding: 6px 16px;
}

.kb-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
}

// 移动端 KB 列表上方标题（桌面端默认隐藏）
.kb-scroll-header {
  display: none;
}

// 移动端当前知识库信息条（桌面端默认隐藏）
.kb-current-info {
  display: none;
}

// 移动端三按钮平齐操作栏（桌面端默认隐藏）
.action-bar-mobile {
  display: none;
}

.kb-group-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--color-stone-400);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  padding: 14px 10px 8px;
}

.kb-item {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 14px 16px;
  border-radius: $radius-lg;
  cursor: pointer;
  transition: all 0.15s;
  margin-bottom: 4px;
  position: relative;

  &:hover {
    background: var(--color-stone-50);
  }

  &.active {
    background: var(--color-amber-50);
    border: 1px solid var(--color-amber-200);
  }

  &.active::before {
    content: '';
    position: absolute;
    left: 0;
    top: 8px;
    bottom: 8px;
    width: 3px;
    background: var(--color-amber-400);
    border-radius: 0 3px 3px 0;
  }
}

// 移动端新建知识库卡片（桌面端隐藏）
.kb-item-add {
  display: none;
}

.kb-icon {
  width: 40px;
  height: 40px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  flex-shrink: 0;
}

.kb-icon-project { background: linear-gradient(135deg, #DBEAFE, #BFDBFE); color: #1D4ED8; }
.kb-icon-research { background: linear-gradient(135deg, #F3E8FF, #E9D5FF); color: #7C3AED; }
.kb-icon-resource { background: linear-gradient(135deg, #ECFDF5, #A7F3D0); color: #059669; }
.kb-icon-team { background: linear-gradient(135deg, #FFF3D6, #FFE089); color: #B37B00; }
.kb-icon-general { background: linear-gradient(135deg, #F3F1ED, #E8E4DC); color: #787165; }
.kb-icon-client { background: linear-gradient(135deg, #FFE4E6, #FECDD3); color: #E11D48; }

.kb-info {
  flex: 1;
  min-width: 0;
}

.kb-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--color-stone-800);
  margin-bottom: 3px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.kb-meta {
  font-size: 12px;
  color: var(--color-stone-400);
  display: flex;
  align-items: center;
  gap: 8px;
}

.kb-badge {
  font-size: 10px;
  font-weight: 600;
  padding: 2px 7px;
  border-radius: 10px;
  background: var(--color-stone-100);
  color: var(--color-stone-500);

  &.shared {
    background: #EFF6FF;
    color: var(--color-info);
  }
}

.kb-pagination {
  padding: 12px 20px;
  border-top: 1px solid var(--color-stone-100);
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  flex-shrink: 0;
}

.kb-pagination-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border: 1px solid var(--color-stone-200);
  border-radius: $radius-md;
  background: white;
  color: var(--color-stone-600);
  font-size: 12px;
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

  &.active {
    background: var(--color-amber-400);
    border-color: var(--color-amber-400);
    color: var(--color-stone-900);
  }
}

// ================================================================
// 右侧
// ================================================================
.content {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  overflow: hidden;
  background: var(--color-stone-50);
}

.content-inner {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  padding: 28px 36px 0;
  overflow: hidden;
}

.no-selection {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px;
  text-align: center;
}

.no-selection-icon {
  font-size: 64px;
  margin-bottom: 20px;
  opacity: 0.3;
}

.no-selection h3 {
  font-family: var(--font-display);
  font-size: 18px;
  color: var(--color-stone-600);
  margin-bottom: 8px;
}

.no-selection p {
  font-size: 13px;
  color: var(--color-stone-400);
}

// ---- 头部 ----
.content-header {
  padding: 0 0 20px;
  flex-shrink: 0;
}

.breadcrumb {
  font-size: 13px;
  color: var(--color-stone-400);
  margin-bottom: 14px;

  a {
    color: var(--color-stone-500);
    text-decoration: none;

    &:hover {
      color: var(--color-amber-600);
    }
  }
}

.content-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 20px;
}

.content-title-group {
  display: flex;
  align-items: center;
  gap: 14px;
}

.content-icon {
  width: 44px;
  height: 44px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 22px;
}

.content-title {
  font-family: var(--font-display);
  font-size: 22px;
  font-weight: 700;
  color: var(--color-stone-800);
  margin-bottom: 4px;
}

.content-desc {
  font-size: 13px;
  color: var(--color-stone-500);
}

.content-actions {
  display: flex;
  gap: 10px;
}

// ---- 按钮 ----
.btn-primary {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 18px;
  border: none;
  border-radius: $radius-md;
  background: var(--color-amber-400);
  color: var(--color-stone-900);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
  white-space: nowrap;

  &:hover {
    background: var(--color-amber-500);
    transform: translateY(-1px);
    box-shadow: 0 4px 12px rgba(245, 180, 0, 0.25);
  }
}

.btn-secondary {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 18px;
  border: 1.5px solid var(--color-stone-200);
  border-radius: $radius-md;
  background: white;
  color: var(--color-stone-700);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s;

  &:hover {
    background: var(--color-stone-50);
    border-color: var(--color-stone-300);
  }
}

.btn-danger {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 18px;
  border: none;
  border-radius: $radius-md;
  background: linear-gradient(135deg, #FCA5A5, #F87171);
  color: white;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
  white-space: nowrap;

  &:hover {
    background: linear-gradient(135deg, #F87171, #EF4444);
    transform: translateY(-1px);
    box-shadow: 0 4px 12px rgba(239, 68, 68, 0.25);
  }
}

// ---- 操作栏 ----
.action-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 0 16px;
  flex-shrink: 0;
}

.search-box {
  display: flex;
  align-items: center;
  gap: 10px;
  flex: 1;
  max-width: 320px;
  padding: 9px 14px;
  border: 1.5px solid var(--color-stone-200);
  border-radius: $radius-md;
  background: var(--color-stone-50);
  transition: all 0.2s;

  &:focus-within {
    border-color: var(--color-amber-400);
    background: white;
    box-shadow: 0 0 0 3px rgba(245, 180, 0, 0.08);
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

.filter-group {
  display: flex;
  gap: 6px;
}

.filter-chip {
  padding: 7px 14px;
  border: 1px solid var(--color-stone-200);
  border-radius: 20px;
  background: white;
  color: var(--color-stone-600);
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s;

  &:hover {
    background: var(--color-stone-50);
  }

  &.active {
    background: var(--color-amber-50);
    border-color: var(--color-amber-200);
    color: var(--color-amber-600);
  }
}

// ---- 统计卡 ----
.stats-bar {
  display: flex;
  gap: 12px;
  margin-bottom: 24px;
  flex-shrink: 0;
}

.stat-card {
  flex: 1;
  background: white;
  border: 1px solid var(--color-stone-200);
  border-radius: $radius-xl;
  padding: 16px 18px;
  display: flex;
  align-items: center;
  gap: 14px;
  transition: all 0.2s;
  cursor: pointer;
  box-shadow: $shadow-sm;

  &:hover {
    border-color: var(--color-amber-200);
    box-shadow: $shadow-md;
    transform: translateY(-2px);
  }

  &.active {
    background: var(--color-amber-50);
    border-color: var(--color-amber-300);
  }
}

.stat-icon {
  width: 40px;
  height: 40px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 17px;
  flex-shrink: 0;
}

.stat-icon-text { background: #EFF6FF; color: var(--color-info); }
.stat-icon-audio { background: #ECFDF5; color: var(--color-success); }
.stat-icon-image { background: #F3E8FF; color: #8B5CF6; }
.stat-icon-video { background: #FFF8E1; color: var(--color-warning); }
.stat-icon-other { background: var(--color-stone-100); color: var(--color-stone-500); }

.stat-info { flex: 1; }

.stat-count {
  font-size: 20px;
  font-weight: 700;
  color: var(--color-stone-800);
  line-height: 1.1;
}

.stat-label {
  font-size: 12px;
  color: var(--color-stone-500);
  margin-top: 2px;
}

// ---- 文件滚动区 ----
.file-scroll-area {
  flex: 1;
  overflow-y: auto;
  padding: 0 0 24px;
  min-height: 0;
}

.file-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.file-card {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 14px 18px;
  background: white;
  border: 1px solid var(--color-stone-200);
  border-radius: $radius-lg;
  transition: all 0.2s;

  &:hover {
    border-color: var(--color-amber-200);
    box-shadow: $shadow-md;
    transform: translateY(-1px);
  }
}

.file-type-icon {
  width: 40px;
  height: 40px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 17px;
  flex-shrink: 0;
}

.type-doc { background: var(--color-file-doc-bg); color: var(--color-file-doc); }
.type-image { background: var(--color-file-image-bg); color: var(--color-file-image); }
.type-audio { background: var(--color-file-audio-bg); color: var(--color-file-audio); }
.type-video { background: var(--color-file-video-bg); color: var(--color-file-video); }
.type-other { background: var(--color-stone-100); color: var(--color-stone-500); }

.file-info {
  flex: 1;
  min-width: 0;
}

.file-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--color-stone-800);
  margin-bottom: 3px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.file-meta {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 12px;
  color: var(--color-stone-500);
}

.file-meta-item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.file-status {
  display: flex;
  align-items: center;
  gap: 8px;
}

.status-badge {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 11px;
  font-weight: 600;
  padding: 4px 10px;
  border-radius: 20px;
  white-space: nowrap;
}

.status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
}

.status-processing { background: #FFF8E1; color: #F57F17; }
.status-processing .status-dot { background: var(--color-warning); animation: pulse 1.5s infinite; }

.status-complete { background: #ECFDF5; color: #065F46; }
.status-complete .status-dot { background: var(--color-success); }

.status-error { background: #FEF2F2; color: #991B1B; }
.status-error .status-dot { background: var(--color-error); }

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}

.progress-bar {
  width: 60px;
  height: 3px;
  background: var(--color-stone-100);
  border-radius: 2px;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: var(--color-amber-400);
  border-radius: 2px;
  transition: width 0.3s;
}

.error-detail {
  display: none;
  margin-top: 10px;
  padding: 10px 14px;
  background: #FEF2F2;
  border: 1px solid #FECACA;
  border-radius: $radius-md;
  font-size: 12px;
  color: #991B1B;
  line-height: 1.5;
}

.file-card.expanded .error-detail {
  display: block;
}

.file-actions {
  display: flex;
  gap: 4px;
}

.file-action-btn {
  width: 30px;
  height: 30px;
  border: 1px solid var(--color-stone-200);
  border-radius: 6px;
  background: white;
  color: var(--color-stone-500);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  transition: all 0.15s;

  &:hover {
    background: var(--color-stone-50);
    border-color: var(--color-stone-300);
    color: var(--color-stone-700);
  }

  &.danger:hover {
    background: #FEF2F2;
    border-color: #FECACA;
    color: var(--color-error);
  }
}

// ---- 文件分页 ----
.file-pagination {
  padding: 16px 0 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  flex-shrink: 0;
}

.file-pagination-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  border: 1px solid var(--color-stone-200);
  border-radius: $radius-md;
  background: white;
  color: var(--color-stone-600);
  font-size: 12px;
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

  &.active {
    background: var(--color-amber-400);
    border-color: var(--color-amber-400);
    color: var(--color-stone-900);
  }
}

.file-pagination-text {
  font-size: 12px;
  color: var(--color-stone-500);
  padding: 0 10px;
  white-space: nowrap;
}

// ================================================================
// 弹窗内部
// ================================================================
.modal-inner {
  padding: 4px;
}

.modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 20px;
}

.modal-title {
  font-family: var(--font-display);
  font-size: 18px;
  font-weight: 600;
  color: var(--color-stone-800);
}

.modal-close {
  width: 30px;
  height: 30px;
  border: none;
  background: var(--color-stone-100);
  border-radius: 7px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--color-stone-500);
  transition: all 0.15s;

  &:hover {
    background: var(--color-stone-200);
    color: var(--color-stone-700);
  }
}

.form-group {
  margin-bottom: 16px;
}

.form-label {
  display: block;
  font-size: 13px;
  font-weight: 600;
  color: var(--color-stone-700);
  margin-bottom: 6px;
}

.form-input {
  width: 100%;
  padding: 10px 14px;
  border: 1.5px solid var(--color-stone-200);
  border-radius: $radius-md;
  font-size: 13px;
  color: var(--color-stone-800);
  background: white;
  transition: all 0.2s;
  outline: none;
  font-family: inherit;

  &:focus {
    border-color: var(--color-amber-400);
    box-shadow: 0 0 0 3px rgba(245, 180, 0, 0.08);
  }
}

.form-textarea {
  resize: vertical;
  min-height: 80px;
}

.modal-footer {
  display: flex;
  gap: 10px;
  justify-content: flex-end;
  margin-top: 20px;
}

// ================================================================
// 授权用户区域
// ================================================================
.grant-section {
  border-top: 1px solid var(--color-stone-200);
  padding-top: 14px;
  margin-top: 12px;
}

.grant-tip {
  font-size: 11px;
  color: var(--color-stone-500);
  margin: 0 0 8px;
}

.grant-search {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 10px;
  border: 1.5px solid var(--color-stone-200);
  border-radius: $radius-lg;
  background: var(--color-stone-50);
  transition: all 0.2s;
  margin-bottom: 6px;

  &:focus-within {
    border-color: var(--color-amber-400);
    background: white;
    box-shadow: 0 0 0 3px rgba(245, 180, 0, 0.08);
  }

  input {
    flex: 1;
    border: none;
    background: transparent;
    font-size: 12px;
    color: var(--color-stone-800);
    outline: none;

    &::placeholder {
      color: var(--color-stone-400);
    }
  }
}

.grant-selected-count {
  font-size: 12px;
  font-weight: 600;
  color: var(--color-amber-600);
  margin-bottom: 6px;
}

.grant-user-list {
  max-height: 160px;
  overflow-y: auto;
  border: 1px solid var(--color-stone-200);
  border-radius: $radius-lg;
  padding: 4px;
  min-height: 100px;
}

.grant-empty {
  text-align: center;
  padding: 20px;
  color: var(--color-stone-400);
  font-size: 12px;
}

.grant-user-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  border-radius: $radius-md;
  cursor: pointer;
  transition: all 0.15s;

  &:hover {
    background: var(--color-stone-50);
  }

  &.selected {
    background: var(--color-amber-50);
  }
}

.grant-user-checkbox {
  width: 20px;
  height: 20px;
  border: 1.5px solid var(--color-stone-300);
  border-radius: 5px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: all 0.15s;
  background: white;

  svg {
    opacity: 0;
    transition: opacity 0.15s;
  }
}

.grant-user-item.selected .grant-user-checkbox {
  background: var(--color-amber-400);
  border-color: var(--color-amber-400);

  svg {
    opacity: 1;
  }
}

.grant-user-avatar {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: var(--color-stone-100);
  border: 1.5px solid var(--color-stone-200);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 600;
  color: var(--color-stone-600);
  flex-shrink: 0;
}

.grant-user-info {
  flex: 1;
  min-width: 0;
}

.grant-user-name {
  font-size: 13px;
  font-weight: 500;
  color: var(--color-stone-800);
}

.grant-pagination {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 8px 0 0;
}

.grant-pagination-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border: 1px solid var(--color-stone-200);
  border-radius: $radius-md;
  background: white;
  color: var(--color-stone-600);
  font-size: 11px;
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

  &.active {
    background: var(--color-amber-400);
    border-color: var(--color-amber-400);
    color: var(--color-stone-900);
  }
}

.grant-pagination-text {
  font-size: 11px;
  color: var(--color-stone-500);
  padding: 0 8px;
  white-space: nowrap;
}

// ================================================================
// 删除确认
// ================================================================
.delete-warning {
  text-align: center;
  padding: 16px 0 12px;
}

.delete-icon {
  font-size: 40px;
  margin-bottom: 12px;
}

.delete-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--color-stone-800);
  margin-bottom: 6px;
}

.delete-desc {
  font-size: 12px;
  color: var(--color-stone-500);
  line-height: 1.5;
}

// ================================================================
// 上传区域
// ================================================================
.dialog-upload-zone {
  :deep(.el-upload-dragger) {
    border: 2px dashed var(--color-stone-300);
    border-radius: $radius-xl;
    padding: 32px;
    text-align: center;
    background: var(--color-stone-50);
    transition: all 0.2s;

    &:hover {
      border-color: var(--color-amber-400);
      background: var(--color-amber-50);
    }
  }
}

.upload-icon {
  font-size: 28px;
  margin-bottom: 8px;
  color: var(--color-stone-400);
}

.upload-text {
  font-size: 14px;
  font-weight: 500;
  color: var(--color-stone-600);
  margin-bottom: 4px;
}

.upload-hint {
  font-size: 12px;
  color: var(--color-stone-400);
  line-height: 1.6;
}

// ================================================================
// 切片网格
// ================================================================
.chunk-grid-container {
  max-height: 70vh;
  overflow-y: auto;
  min-height: 400px;
}

.chunk-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 14px;
  padding: 10px 0;
}

.chunk-card {
  background: white;
  border: 1px solid var(--color-stone-200);
  border-radius: $radius-lg;
  padding: 16px;
  display: flex;
  flex-direction: column;
  transition: all 0.2s;

  &:hover {
    border-color: var(--color-amber-200);
    box-shadow: $shadow-md;
    transform: translateY(-2px);
  }
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.fragment-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--color-stone-800);
}

.card-meta {
  font-size: 12px;
  color: var(--color-stone-400);
  margin-bottom: 10px;
}

.card-body {
  flex: 1;
  font-size: 13px;
  line-height: 1.6;
  color: var(--color-stone-700);
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 5;
  -webkit-box-orient: vertical;
  white-space: pre-wrap;
  word-break: break-all;
  background: var(--color-stone-50);
  padding: 10px 12px;
  border-radius: $radius-md;
  margin-bottom: 10px;
  min-height: 80px;
}

.card-footer {
  display: flex;
  gap: 8px;
  margin-top: auto;

  &.single-action {
    justify-content: center;
  }
}

.btn-view-detail {
  width: 100%;
  border: none;
  background: transparent;
  color: var(--color-amber-600);
  font-size: 13px;

  &:hover {
    color: var(--color-amber-700);
    background: var(--color-amber-50);
  }
}

// ================================================================
// 单个切片详情弹窗
// ================================================================
.single-chunk-content {
  max-height: 60vh;
  overflow-y: auto;
  font-size: 14px;
  line-height: 1.8;
  color: var(--color-stone-800);
  white-space: pre-wrap;
  word-break: break-all;
  padding: 16px;
  background: var(--color-stone-50);
  border-radius: $radius-md;
  border: 1px solid var(--color-stone-200);
}

.dialog-footer {
  text-align: center;
}

// ================================================================
// 切片弹窗响应式
// ================================================================
@media (max-width: 1200px) {
  .chunk-grid {
    grid-template-columns: repeat(3, 1fr);
  }
}

@media (max-width: 900px) {
  .chunk-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (max-width: 600px) {
  .chunk-grid {
    grid-template-columns: 1fr;
  }
}

// ================================================================
// 响应式
// ================================================================

// ---- el-dialog 全局圆角（与 NewChatModal 的 20px 保持一致） ----
:deep(.el-dialog) {
  border-radius: 20px;
}

@include respond-to(md) {
  .layout {
    flex-direction: column;
  }

  .sidebar {
    width: 100%;
    max-height: none;
    min-height: 220px;
    border-right: none;
    border-bottom: 1px solid var(--color-stone-200);
    flex-shrink: 0;
  }

  .sidebar-header {
    padding: 14px 16px;
  }

  .kb-search {
    display: none;
  }

  // 知识库列表 → 横向滚动卡片选择器（参照 mobile-responsive 设计 kb-list-scroll）
  .kb-list {
    display: flex;
    gap: var(--space-3);
    padding: var(--space-3) var(--space-4);
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
    scrollbar-width: none;
    scroll-snap-type: x mandatory;
    scroll-padding-left: var(--space-4);
    scroll-padding-right: var(--space-4);

    &::-webkit-scrollbar { display: none; }
    -ms-overflow-style: none;
  }

  .kb-group-label {
    display: none;
  }

  // 知识库卡片（参照 mobile-responsive 设计 kb-list-card：竖排 148px 卡片）
  .kb-item {
    flex: 0 0 148px;
    flex-direction: column;
    align-items: flex-start;
    gap: var(--space-2);
    margin-bottom: 0;
    padding: 12px;
    border: 1.5px solid var(--color-stone-200);
    border-radius: var(--radius-lg);
    background: white;
    box-shadow: $shadow-sm;
    scroll-snap-align: start;

    &:active {
      background: var(--color-stone-50);
      transform: scale(0.97);
    }

    &.active {
      border-color: var(--color-amber-400);
      background: var(--color-amber-50);
      box-shadow: 0 0 0 2px rgba(245, 180, 0, 0.12);
    }
  }

  .kb-icon {
    width: 36px;
    height: 36px;
    font-size: 16px;
    border-radius: var(--radius-md);
  }

  .kb-info {
    display: block;
  }

  .kb-name {
    font-size: var(--text-sm);
    white-space: normal;
    display: -webkit-box;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 2;
    margin-bottom: 0;
  }

  .kb-meta {
    display: flex;
    font-size: var(--text-xs);
  }

  .kb-item.active::before {
    display: none;
  }

  // 桌面端新建按钮隐藏，改用列表末尾虚线卡片
  .btn-create-kb.desktop-create {
    display: none;
  }

  .kb-item-add {
    display: flex;
    border-style: dashed;
    justify-content: center;
    align-items: center;
    color: var(--color-stone-400);
    min-height: 104px;
    cursor: pointer;
    background: white;

    svg {
      color: var(--color-stone-300);
    }
  }

  // ---- 移动端 KB 列表上方标题 ----
  .kb-scroll-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: var(--space-3) var(--space-4) 0;
  }

  .kb-scroll-title {
    font-family: var(--font-display);
    font-weight: 600;
    font-size: var(--text-sm);
    color: var(--color-stone-800);
  }

  .kb-scroll-count {
    font-size: var(--text-xs);
    color: var(--color-stone-400);
  }

  // ---- 移动端当前知识库信息条 ----
  .kb-current-info {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: var(--space-1) var(--space-4) var(--space-2);
    flex-wrap: wrap;
  }

  .kb-current-label {
    font-size: 11px;
    color: var(--color-stone-400);
  }

  .kb-current-name {
    font-size: var(--text-xs);
    font-weight: 600;
    color: var(--color-amber-600);
  }

  .kb-current-sep {
    color: var(--color-stone-300);
  }

  .kb-current-meta {
    font-size: 11px;
    color: var(--color-stone-400);
  }

  // ---- 移动端三按钮平齐操作栏 ----
  .action-bar-mobile {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    padding: var(--space-2) 0;
  }

  .action-bar-icon-btn {
    width: 36px;
    height: 36px;
    border-radius: 50%;
    background: var(--color-stone-100);
    border: none;
    color: var(--color-stone-600);
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    flex-shrink: 0;
    transition: all var(--transition-fast);

    &:active {
      background: var(--color-stone-200);
      transform: scale(0.95);
    }
  }

  .filter-toggle-btn {
    flex: 0 0 auto;
    min-width: 0;
    padding: 8px 12px;
    min-height: 44px;
    background: white;
    border: 1.5px solid var(--color-stone-200);
    border-radius: var(--radius-full);
    font-size: var(--text-xs);
    font-weight: 500;
    color: var(--color-stone-700);
    font-family: var(--font-body);
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 6px;
    cursor: pointer;
    transition: all var(--transition-fast);

    .filter-toggle-arrow {
      transition: transform var(--transition-fast);
    }

    &.expanded .filter-toggle-arrow {
      transform: rotate(180deg);
    }
  }

  .kb-pagination {
    display: none;
  }

  .content-inner {
    padding: 20px 16px 0;
  }

  .content-title-row {
    flex-direction: column;
    align-items: flex-start;
    gap: 12px;
  }

  .action-bar {
    flex-direction: column;
    gap: 10px;
    padding: 0 0 12px;
  }

  .search-box {
    max-width: 100%;
  }

  .filter-group {
    flex-wrap: wrap;
  }

  .stats-bar {
    flex-wrap: wrap;
    margin-bottom: 16px;
  }

  .stat-card {
    flex: 0 0 calc(50% - 6px);
  }

  .file-scroll-area {
    padding: 0 0 16px;
  }

  .file-pagination {
    padding: 12px 0 16px;
  }

  // "新建知识库" / "编辑知识库" / "删除文件" 弹窗 → 移动端居中
  :deep(.el-overlay-dialog) {
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
  }

  :deep(.el-dialog) {
    position: relative !important;
    top: 0 !important;
    margin: 0 !important;
    transform: none !important;
    width: 92% !important;
    max-width: 500px;
  }

  // 筛选下拉菜单
  .filter-dropdown-mobile {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
    padding: 0 0 var(--space-3);
  }

  .filter-dropdown-chip {
    padding: 6px 14px;
    border-radius: var(--radius-full);
    border: 1.5px solid var(--color-stone-200);
    background: white;
    font-size: var(--text-xs);
    font-weight: 500;
    color: var(--color-stone-700);
    font-family: var(--font-body);
    cursor: pointer;
    transition: all var(--transition-fast);
    min-height: 36px;

    &:active {
      background: var(--color-stone-100);
    }

    &.active {
      background: var(--color-amber-400);
      color: var(--color-stone-900);
      border-color: var(--color-amber-400);
    }
  }

  // 搜索激活时强制显示 search-box
  .action-bar.mobile-search-visible {
    display: flex;
    flex-direction: column;
    gap: 10px;

    .search-box {
      max-width: 100%;
    }

    .filter-group {
      display: none;
    }
  }
}

@include respond-to(sm) {
  .knowledge-page {
    height: auto;
    min-height: calc(100vh - 64px);
  }

  // 桌面专用元素移动端隐藏
  .action-bar {
    display: none;
  }

  // 手机端：操作栏缩小上间距 + 筛选按钮靠右
  .action-bar-mobile {
    padding: 4px 0 8px;
  }

  .filter-toggle-btn {
    margin-left: auto;
  }

  .stats-bar {
    display: none;
  }

  .breadcrumb {
    display: none;
  }

  .content-actions .btn-secondary {
    display: none;
  }

  // 移动端去掉"上传文件"文字按钮（仅保留图标按钮）
  .content-actions .btn-primary {
    display: none;
  }

  // 移动端隐藏标题行（icon + 名称 + 编辑/删除/上传按钮）
  .content-title-row {
    display: none;
  }

  .content-header {
    display: none;
  }

  :deep(.el-overlay-dialog) {
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
  }

  :deep(.el-dialog) {
    position: relative !important;
    top: 0 !important;
    margin: 0 !important;
    transform: none !important;
    width: 94% !important;
    max-width: 500px;
  }

  .sidebar {
    max-height: none;
  }

  .sidebar-header {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    align-items: center;
  }

  .sidebar-title {
    margin-bottom: 0;
  }

  .btn-create-kb {
    width: auto;
    margin-bottom: 0;
  }

  .kb-item {
    flex: 0 0 140px;
  }

  .kb-icon {
    width: 36px;
    height: 36px;
    font-size: 16px;
  }

  .content-inner {
    padding: 16px 12px 0;
  }

  .content-title {
    font-size: 18px;
  }

  .content-actions {
    gap: 6px;

    .btn-primary,
    .btn-secondary,
    .btn-danger {
      padding: 8px 12px;
      font-size: 12px;
      gap: 4px;
    }
  }

  .filter-group {
    width: 100%;
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;

    &::-webkit-scrollbar { height: 0; }
    -ms-overflow-style: none;
    scrollbar-width: none;
  }

  .filter-chip {
    flex-shrink: 0;
    white-space: nowrap;
  }

  .stats-bar {
    gap: 8px;
  }

  .stat-card {
    flex: 0 0 calc(50% - 4px);
    padding: 12px;
    gap: 8px;
  }

  .stat-icon {
    width: 32px;
    height: 32px;
    font-size: 14px;
  }

  .stat-count {
    font-size: 16px;
  }

  .stat-label {
    font-size: 11px;
  }

  .file-card {
    flex-wrap: wrap;
    padding: 12px;
    gap: 10px;
  }

  .file-type-icon {
    width: 32px;
    height: 32px;
    font-size: 14px;
  }

  .file-status {
    margin-left: auto;
  }

  .file-actions {
    width: 100%;
    justify-content: flex-end;
  }

  // 移动端搜索激活时强制显示搜索框（覆盖 display:none）
  .action-bar.mobile-search-visible {
    display: flex;
    flex-direction: column;
    gap: 10px;
    padding: 0 0 12px;

    .search-box {
      max-width: 100%;
    }

    .filter-group {
      display: none;
    }
  }
}
</style>
