// ============================================================
// 音频/转写 API — 上传录音 / 列表 / 状态查询 / 删除 / 更新
// ============================================================

import { request } from '../request'
import type { ApiResponse, TranscriptionListData, TaskStatusItem } from '../types'

export const audioApi = {
  /** 上传录音文件 */
  async uploadFile(file: File, taskName?: string): Promise<string> {
    const formData = new FormData()
    formData.append('audio_file', file)
    if (taskName) formData.append('task_name', taskName)
    const resp = await request.post<ApiResponse<string>>('/audio/start_task', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    if (resp.data.status_code === 200) return resp.data.data
    throw new Error(resp.data.status_message)
  },

  /** 获取转写列表 */
  async list(pageNum = 1, pageSize = 10): Promise<TranscriptionListData> {
    const resp = await request.post<ApiResponse<TranscriptionListData>>('/audio/list', {
      page_num: pageNum,
      page_size: pageSize,
    })
    if (resp.data.status_code === 200) return resp.data.data
    throw new Error(resp.data.status_message)
  },

  /** 批量查询任务状态（后端 embed=True，需包装为 { task_ids }） */
  async getTaskStatus(taskIds: string[]): Promise<TaskStatusItem[]> {
    const resp = await request.post<ApiResponse<TaskStatusItem[]>>('/audio/getTask/status', {
      task_ids: taskIds,
    })
    if (resp.data.status_code === 200) return resp.data.data
    throw new Error(resp.data.status_message)
  },

  /** 删除转写记录 */
  async delete(taskId: string): Promise<void> {
    const resp = await request.post<ApiResponse<null>>('/audio/delete', { task_id: taskId })
    if (resp.data.status_code !== 200) throw new Error(resp.data.status_message)
  },

  /** 更新转写记录 */
  async update(taskId: string, taskName: string, note?: string): Promise<void> {
    const resp = await request.post<ApiResponse<null>>('/audio/update', {
      task_id: taskId,
      task_name: taskName,
      note,
    })
    if (resp.data.status_code !== 200) throw new Error(resp.data.status_message)
  },
}
