// ============================================================
// useChatSSE — AI 对话 SSE 流式连接管理
// 提供：流式对话请求、消息接收、自动重连、错误处理
// ============================================================

import { ref, onUnmounted } from 'vue'
import { ElMessage } from 'element-plus'
import { getAccessToken } from '@/api/request'
import { useChatStore } from '@/stores/chat'

export interface SSEMessage {
  status: 'start' | 'streaming' | 'done' | 'error'
  text?: string
  question?: string
  message?: string
  partial?: string
}

export function useChatSSE() {
  const chatStore = useChatStore()
  const controller = ref<AbortController | null>(null)
  const isRequesting = ref(false)
  const retryAttempts = ref(0)
  const maxRetryAttempts = 3
  const retryTimer = ref<ReturnType<typeof setTimeout> | null>(null)

  /**
   * 发送 SSE 流式请求
   * @param sessionId 会话 ID
   * @param question 用户问题
   * @param meetingIds 会议 ID 列表
   * @param knowledgeIds 知识库 ID 列表
   * @param needKb 是否查询知识库
   */
  async function sendQuestion(
    sessionId: string,
    question: string,
    meetingIds: string[],
    knowledgeIds: string[],
    needKb: boolean
  ): Promise<void> {
    // 取消之前的请求
    cancelRequest()

    const token = getAccessToken()
    if (!token) {
      ElMessage.error('请先登录')
      return
    }

    const ctrl = new AbortController()
    controller.value = ctrl

    isRequesting.value = true
    retryAttempts.value = 0

    try {
      const response = await fetch('/api/v1/chat/sse/chat', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
        body: JSON.stringify({
          question,
          session_id: sessionId,
          meeting_ids: meetingIds,
          knowledge_ids: knowledgeIds,
          need_kb: needKb,
        }),
        signal: ctrl.signal,
      })

      if (!response.ok) {
        if (response.status === 401) {
          ElMessage.error('认证失败，请重新登录')
          isRequesting.value = false
          return
        }
        throw new Error(`SSE 请求失败: ${response.status}`)
      }

      const reader = response.body?.getReader()
      if (!reader) {
        throw new Error('无法读取响应流')
      }

      const decoder = new TextDecoder('utf-8')
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()

        if (done) {
          break
        }

        buffer += decoder.decode(value, { stream: true })

        // 解析 SSE 事件
        const events = buffer.split('\n\n')
        buffer = events.pop() || ''

        for (const eventStr of events) {
          const lines = eventStr.split('\n')
          let eventData = ''

          for (const line of lines) {
            if (line.startsWith('data:')) {
              eventData += line.slice(5).trim()
            }
          }

          if (eventData) {
            try {
              const msg: SSEMessage = JSON.parse(eventData)
              handleMessage(msg)
            } catch (e) {
              // 忽略解析失败的消息
            }
          }
        }
      }
    } catch (err: any) {
      if (err.name === 'AbortError') {
        // 用户主动取消，忽略
        return
      }

      console.error('[ChatSSE] 请求失败:', err)
      ElMessage.error(`请求失败: ${err.message}`)

      // 标记流式结束
      chatStore.finishAiMessage()

      // 尝试重连
      if (retryAttempts.value < maxRetryAttempts) {
        retryAttempts.value++
        retryTimer.value = setTimeout(() => {
          sendQuestion(sessionId, question, meetingIds, knowledgeIds, needKb)
        }, 2000 * retryAttempts.value)
      }
    } finally {
      isRequesting.value = false
      controller.value = null
    }
  }

  /**
   * 处理 SSE 消息
   */
  function handleMessage(msg: SSEMessage): void {
    switch (msg.status) {
      case 'start':
        chatStore.startAiMessage()
        break
      case 'streaming':
        chatStore.appendAiText(msg.text || '')
        break
      case 'done':
        chatStore.appendAiText(msg.text || '')
        chatStore.finishAiMessage()
        break
      case 'error':
        chatStore.finishAiMessage()
        ElMessage.error(msg.message || 'AI 回答失败')
        break
    }
  }

  /**
   * 取消当前请求
   */
  function cancelRequest(): void {
    if (retryTimer.value) {
      clearTimeout(retryTimer.value)
      retryTimer.value = null
    }

    if (controller.value) {
      controller.value.abort()
      controller.value = null
    }
  }

  // 组件卸载时自动取消请求
  onUnmounted(() => {
    cancelRequest()
  })

  return {
    isRequesting,
    sendQuestion,
    cancelRequest,
  }
}
