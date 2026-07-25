// ============================================================
// Knowledge Store — 知识库状态管理
// 管理知识库列表 / 当前知识库 / 文件列表 / 上传状态 / 轮询
// ============================================================

import { defineStore } from 'pinia'
import { ref, reactive } from 'vue'
import { knowledgeApi } from '@/api'
import type { KnowledgeItem, KnowledgeFileItem, FileStateData, KnowledgeDetail, UserListItem } from '@/api/types'

export const useKnowledgeStore = defineStore('knowledge', () => {
  // ---- State ----
  const knowledgeList = ref<KnowledgeItem[]>([])
  const currentKnowledgeId = ref<string>('')
  const currentKnowledgeName = ref<string>('')
  const currentKnowledgeDesc = ref<string>('')
  const currentKnowledgeCreater = ref<number>(0)
  const currentKnowledgeAcceptUsers = ref<number[]>([])
  const files = ref<KnowledgeFileItem[]>([])
  const loading = ref(false)
  const fileStateMap = reactive<Map<string, FileStateData>>(new Map())
  const pollTimer = ref<ReturnType<typeof setInterval> | null>(null)
  const pollTargets = reactive<Set<string>>(new Set())
  const userList = ref<UserListItem[]>([])

  // ---- Actions ----

  /** 获取知识库列表 */
  async function loadKnowledgeList(pageNum = 1, pageSize = 20): Promise<void> {
    loading.value = true
    try {
      const data = await knowledgeApi.list(pageNum, pageSize)
      knowledgeList.value = data.items
      // 默认选中第一个知识库
      if (data.items.length > 0 && !currentKnowledgeId.value) {
        selectKnowledge(data.items[0].id, data.items[0].name)
      }
    } finally {
      loading.value = false
    }
  }

  /** 选中知识库并加载文件列表 */
  async function selectKnowledge(knowledgeId: string, name?: string): Promise<void> {
    currentKnowledgeId.value = knowledgeId
    currentKnowledgeName.value = name || ''
    await loadFiles()
  }

  /** 加载文件列表 */
  async function loadFiles(): Promise<void> {
    if (!currentKnowledgeId.value) return
    const data = await knowledgeApi.getFileList(currentKnowledgeId.value)
    files.value = data.items

    // 检查是否有处理中的任务，收集轮询目标
    pollTargets.clear()
    files.value.forEach((f) => {
      if (f.state === 0) {
        pollTargets.add(f.id)
      }
    })
    togglePolling()
  }

  /** 查询知识库详情 */
  async function getDetail(knowledgeId: string): Promise<KnowledgeDetail> {
    const data = await knowledgeApi.getDetail(knowledgeId)
    currentKnowledgeName.value = data.name
    currentKnowledgeDesc.value = data.description || ''
    currentKnowledgeCreater.value = data.creater
    currentKnowledgeAcceptUsers.value = data.accept_users || []
    return data
  }

  /** 获取用户列表 */
  async function loadUserList(): Promise<void> {
    const data = await knowledgeApi.getUserList()
    userList.value = data.items
  }

  /** 创建知识库 */
  async function createKnowledge(
    name: string,
    description?: string,
    acceptUsers?: number[]
  ): Promise<{ id: string; name: string }> {
    const data = await knowledgeApi.create(name, description, acceptUsers)
    knowledgeList.value.push({
      id: data.id,
      name: data.name,
      description: description || null,
      user_ids: data.accept_users,
      accept_users: data.accept_users,
      create_time: new Date().toISOString(),
      update_time: null,
    })
    return data
  }

  /** 更新知识库 */
  async function updateKnowledge(
    knowledgeId: string,
    name?: string,
    description?: string,
    acceptUsers?: number[]
  ): Promise<void> {
    const data = await knowledgeApi.update(knowledgeId, name, description, acceptUsers)
    // 更新列表中的条目
    const idx = knowledgeList.value.findIndex((k) => k.id === knowledgeId)
    if (idx !== -1) {
      knowledgeList.value[idx] = {
        ...knowledgeList.value[idx],
        name: data.name,
        description: description ?? null,
        accept_users: data.accept_users,
      }
    }
    currentKnowledgeName.value = data.name
    currentKnowledgeDesc.value = description || ''
    currentKnowledgeAcceptUsers.value = data.accept_users
  }

  /** 上传文件 */
  async function uploadFile(file: File): Promise<string> {
    const data = await knowledgeApi.uploadFile(file, currentKnowledgeId.value)
    // 上传完成后重新加载文件列表，确保 type 等字段准确
    await loadFiles()
    return data.file_id
  }

  /** 轮询文件状态 */
  async function pollFileStates(): Promise<void> {
    if (pollTargets.size === 0) return

    const promises = Array.from(pollTargets).map(async (fileId) => {
      try {
        const state = await knowledgeApi.getFileState(fileId)
        fileStateMap.set(fileId, state)

        // 更新文件列表中的状态
        const file = files.value.find((f) => f.id === fileId)
        if (file) {
          file.state = state.state
          file.fail_reason = state.fail_reason
          file.chunks_counts = state.chunks_counts
        }

        // 已完成或失败则移除轮询目标
        if (state.state === 1 || state.state === 2) {
          pollTargets.delete(fileId)
        }
      } catch {
        // 轮询失败不中断
      }
    })

    await Promise.all(promises)
    togglePolling()
  }

  /** 启动/停止轮询 */
  function togglePolling(): void {
    if (pollTargets.size > 0 && !pollTimer.value) {
      pollTimer.value = setInterval(pollFileStates, 5000)
    } else if (pollTargets.size === 0 && pollTimer.value) {
      clearInterval(pollTimer.value)
      pollTimer.value = null
    }
  }

  function stopPolling(): void {
    if (pollTimer.value) {
      clearInterval(pollTimer.value)
      pollTimer.value = null
    }
    pollTargets.clear()
  }

  /** 删除文件 */
  async function deleteFile(fileId: string): Promise<void> {
    await knowledgeApi.deleteFile(fileId, currentKnowledgeId.value)
    files.value = files.value.filter((f) => f.id !== fileId)
    pollTargets.delete(fileId)
  }

  /** 删除知识库 */
  async function deleteKnowledge(knowledgeId: string): Promise<void> {
    await knowledgeApi.deleteKnowledge(knowledgeId)
    knowledgeList.value = knowledgeList.value.filter((k) => k.id !== knowledgeId)
    if (currentKnowledgeId.value === knowledgeId) {
      currentKnowledgeId.value = ''
      currentKnowledgeName.value = ''
      files.value = []
    }
  }

  /** 获取文件分块 */
  async function getFileChunks(fileId: string): Promise<string[]> {
    return await knowledgeApi.getFileChunks(fileId, currentKnowledgeId.value)
  }

  return {
    knowledgeList,
    currentKnowledgeId,
    currentKnowledgeName,
    currentKnowledgeDesc,
    currentKnowledgeCreater,
    currentKnowledgeAcceptUsers,
    files,
    loading,
    fileStateMap,
    pollTargets,
    userList,
    loadKnowledgeList,
    selectKnowledge,
    loadFiles,
    getDetail,
    loadUserList,
    createKnowledge,
    updateKnowledge,
    uploadFile,
    pollFileStates,
    togglePolling,
    stopPolling,
    deleteFile,
    deleteKnowledge,
    getFileChunks,
  }
})
