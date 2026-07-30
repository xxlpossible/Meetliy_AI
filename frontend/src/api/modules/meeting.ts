// ============================================================
// 会议 API — 创建 / 加入 / 参与者 / 结束 / 列表 / 状态 / 结果 / 上传 / WS URL
// ============================================================

import { request } from '../request'
import type {
  ApiResponse,
  MeetingListData,
  MeetingStatisticsData,
  CreateMeetingData,
  JoinMeetingData,
  Participant,
  MeetingStatusItem,
  MeetingResultData,
} from '../types'

export const meetingApi = {
  /** 创建会议 */
  async create(meetingName?: string, needSummary?: boolean): Promise<CreateMeetingData> {
    const resp = await request.post<ApiResponse<CreateMeetingData>>('/meeting/create', {
      meeting_name: meetingName || null,
      need_summary: needSummary !== undefined ? needSummary : true,
    })
    if (resp.data.status_code === 200) return resp.data.data
    throw new Error(resp.data.status_message)
  },

  /** 加入会议 */
  async join(meetingId: string): Promise<JoinMeetingData> {
    const resp = await request.post<ApiResponse<JoinMeetingData>>(`/meeting/${meetingId}/join`)
    if (resp.data.status_code === 200) return resp.data.data
    throw new Error(resp.data.status_message)
  },

  /** 获取活跃参会者 */
  async getParticipants(meetingId: string): Promise<Participant[]> {
    const resp = await request.get<ApiResponse<{ participants: Participant[] }>>(
      `/meeting/${meetingId}/participants`,
    )
    if (resp.data.status_code === 200) return resp.data.data.participants
    throw new Error(resp.data.status_message)
  },

  /** 主持人结束会议 */
  async end(meetingId: string): Promise<{ task_id: string | null; need_summary: boolean }> {
    const resp = await request.post<ApiResponse<{ task_id: string | null; need_summary: boolean }>>(`/meeting/${meetingId}/end`)
    if (resp.data.status_code === 200) return resp.data.data
    throw new Error(resp.data.status_message)
  },

  /**
   * 我的会议列表（分页）
   * 后端 POST /meeting/list，参数包在 body 中
   */
  async list(pageNum = 1, pageSize = 6, meetingName?: string, status?: number): Promise<MeetingListData> {
    const body: Record<string, any> = {
      page_num: pageNum,
      page_size: pageSize,
    }
    if (meetingName) body.meeting_name = meetingName
    if (status !== undefined) body.status = status
    const resp = await request.post<ApiResponse<MeetingListData>>('/meeting/list', body)
    if (resp.data.status_code === 200) return resp.data.data
    throw new Error(resp.data.status_message)
  },

  /**
   * 软删除会议（仅主持人）
   * 后端 DELETE /meeting/{meeting_id}
   */
  async deleteMeeting(meetingId: string): Promise<void> {
    const resp = await request.delete<ApiResponse<void>>(`/meeting/${meetingId}`)
    if (resp.data.status_code === 200) return
    throw new Error(resp.data.status_message)
  },

  /**
   * 会议状态分布统计（DashBoard 数字仪表盘）
   * 后端 GET /meeting/statistics，返回全部会议的总数及各状态数量
   */
  async statistics(): Promise<MeetingStatisticsData> {
    const resp = await request.get<ApiResponse<MeetingStatisticsData>>('/meeting/statistics')
    if (resp.data.status_code === 200) return resp.data.data
    throw new Error(resp.data.status_message)
  },

  /** 上传录音文件，返回 task_id */
  async uploadFile(file: File, taskName?: string): Promise<string> {
    const formData = new FormData()
    formData.append('audio_file', file)
    if (taskName) formData.append('task_name', taskName)
    const resp = await request.post<ApiResponse<string>>('/meeting/start_task', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    if (resp.data.status_code === 200) return resp.data.data
    throw new Error(resp.data.status_message)
  },

  /**
   * 批量查询会议状态（轮询）
   * 后端 POST /meeting/status，参数包在 body 中
   */
  async getStatus(meetingIds: string[]): Promise<MeetingStatusItem[]> {
    const resp = await request.post<ApiResponse<MeetingStatusItem[]>>('/meeting/status', {
      meeting_ids: meetingIds,
    })
    if (resp.data.status_code === 200) return resp.data.data
    throw new Error(resp.data.status_message)
  },

  /**
   * 查询会议解析结果
   * 后端 GET /meeting/{meeting_id}/result
   */
  async getResult(meetingId: string, taskId?: string): Promise<MeetingResultData> {
    const query = taskId ? `?task_id=${encodeURIComponent(taskId)}` : ''
    const resp = await request.get<ApiResponse<MeetingResultData>>(
      `/meeting/${meetingId}/result${query}`,
    )
    if (resp.data.status_code === 200) return resp.data.data
    throw new Error(resp.data.status_message)
  },
}
