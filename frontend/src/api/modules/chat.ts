// ============================================================
// AI 对话 API — Session-based 会话管理 / 聊天记录 / 临时对话(SSE)
// ============================================================

import { request } from '../request'
import type { ApiResponse, ChatMessageListData, SessionListData } from '../types'

export const chatApi = {
  // ==================== 会话管理 ====================

  /** 获取当前用户的会话列表 */
  async getSessionList(pageNum = 1, pageSize = 20): Promise<SessionListData> {
    const resp = await request.post<ApiResponse<SessionListData>>('/session/list', {
      page_num: pageNum,
      page_size: pageSize,
    })
    if (resp.data.status_code === 200) return resp.data.data
    throw new Error(resp.data.status_message)
  },

  /** 更新会话信息 */
  async updateSession(
    sessionId: string,
    sessionName?: string,
    meetingIds?: string[],
    knowledgeIds?: string[],
    needKb?: boolean
  ): Promise<{ session_id: string; session_name: string | null; meeting_ids: string[] | null; knowledge_ids: string[] | null; need_kb: boolean | null; update_time: string | null }> {
    const resp = await request.post<ApiResponse<any>>('/session/update', {
      session_id: sessionId,
      session_name: sessionName,
      meeting_ids: meetingIds,
      knowledge_ids: knowledgeIds,
      need_kb: needKb,
    })
    if (resp.data.status_code === 200) return resp.data.data
    throw new Error(resp.data.status_message)
  },

  /** 删除会话 */
  async deleteSession(sessionId: string): Promise<void> {
    const resp = await request.delete<ApiResponse<null>>('/session/delete', {
      params: { session_id: sessionId },
    })
    if (resp.data.status_code !== 200) throw new Error(resp.data.status_message)
  },

  // ==================== 聊天记录 ====================

  /** 获取聊天记录列表（session-based） */
  async getChatList(sessionId: string, pageNum = 1, pageSize = 50): Promise<ChatMessageListData> {
    const resp = await request.post<ApiResponse<ChatMessageListData>>(
      '/chat/list',
      { session_id: sessionId, page_num: pageNum, page_size: pageSize },
    )
    if (resp.data.status_code === 200) return resp.data.data
    throw new Error(resp.data.status_message)
  },

  /** 保存聊天记录 */
  async addChatMessage(sessionId: string, role: string, content: string, turnIndex: number): Promise<void> {
    const resp = await request.post<ApiResponse<null>>('/chat/add', {
      session_id: sessionId,
      role,
      content,
      turn_index: turnIndex,
    })
    if (resp.data.status_code !== 200) throw new Error(resp.data.status_message)
  },

  /** 更新聊天记录 */
  async updateChatMessage(chatId: number, content: string): Promise<void> {
    const resp = await request.post<ApiResponse<null>>('/chat/update', {
      chat_id: chatId,
      content,
    })
    if (resp.data.status_code !== 200) throw new Error(resp.data.status_message)
  },

  /** 删除聊天记录 */
  async deleteChatMessage(chatId: number): Promise<void> {
    const resp = await request.delete<ApiResponse<null>>('/chat/delete', {
      params: { chat_id: chatId },
    })
    if (resp.data.status_code !== 200) throw new Error(resp.data.status_message)
  },

  // ==================== 临时对话（SSE）====================

  /**
   * 会中临时对话（SSE 流式）
   * 使用 fetch + ReadableStream 消费 SSE，因为需要 POST 请求体
   */
  async tempQuestion(text: string, question: string, history: any[] = []): Promise<ReadableStream<Uint8Array>> {
    const token = localStorage.getItem('access_token')
    const resp = await fetch('/api/v1/chat/temp/question', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({ text, question, history }),
    })
    if (!resp.ok || !resp.body) {
      throw new Error(`临时对话请求失败: ${resp.status}`)
    }
    return resp.body
  },
}
