// ============================================================
// useTempChat — 会议中临时对话（SSE 流式）
// 调用后端 /chat/temp/question，逐 token 累积，支持 abort
// ============================================================

import { ref } from 'vue'
import { chatApi } from '@/api'

export function useTempChat() {
  const streaming = ref(false)
  const currentReply = ref('')
  const error = ref<string | null>(null)

  let abortController: AbortController | null = null
  let reader: ReadableStreamDefaultReader<Uint8Array> | null = null

  /**
   * 发起临时对话
   * @param context 当前转写上下文
   * @param question 用户问题
   * @param history 对话历史
   * @param onToken 收到 token 时的回调
   * @param onComplete 流式完成回调
   */
  async function ask(
    context: string,
    question: string,
    history: any[] = [],
    onToken?: (text: string) => void,
    onComplete?: () => void,
  ): Promise<void> {
    streaming.value = true
    error.value = null
    currentReply.value = ''
    abortController = new AbortController()

    try {
      const stream = await chatApi.tempQuestion(context, question, history)
      reader = stream.getReader()
      const decoder = new TextDecoder()

      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })

        // 按 SSE 事件解析
        const parts = buffer.split('\n\n')
        buffer = parts.pop() || ''

        for (const part of parts) {
          if (!part.trim()) continue
          const lines = part.split('\n')
          for (const line of lines) {
            if (line.startsWith('data: ')) {
              const jsonStr = line.slice(6)
              try {
                const data = JSON.parse(jsonStr)
                if (data.text) {
                  currentReply.value += data.text
                  onToken?.(data.text)
                }
                if (data.status === 'done' || data.status === 'error') {
                  streaming.value = false
                  onComplete?.()
                  return
                }
              } catch {
                // 忽略解析失败
              }
            }
          }
        }
      }

      streaming.value = false
      onComplete?.()
    } catch (e: any) {
      error.value = e.message || '对话失败'
      streaming.value = false
    }
  }

  /** 中止当前流式输出 */
  function abort(): void {
    if (reader) {
      reader.cancel()
      reader = null
    }
    if (abortController) {
      abortController.abort()
      abortController = null
    }
    streaming.value = false
  }

  return { streaming, currentReply, error, ask, abort }
}
