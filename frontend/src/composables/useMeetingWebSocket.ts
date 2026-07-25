// ============================================================
// useMeetingWebSocket — 会议 WebSocket 连接管理
// 发送 PCM 二进制音频帧，接收服务端消息：
//   transcript / participants_list / participant_joined /
//   participant_left / speech_started / speech_stopped / meeting_ended
// ============================================================

import { ref } from 'vue'

export interface MeetingWSMessage {
  type: string
  [key: string]: any
}

export function useMeetingWebSocket() {
  const connected = ref(false)

  let ws: WebSocket | null = null
  let messageHandler: ((msg: MeetingWSMessage) => void) | null = null
  let closeHandler: ((code: number) => void) | null = null

  /**
   * 连接 WebSocket
   * @param url 完整的 ws://... URL（含 token + meeting_id）
   * @param onMessage 收到文本消息的回调
   * @param onClose 连接关闭的回调（接收 close code）
   */
  function connect(
    url: string,
    onMessage: (msg: MeetingWSMessage) => void,
    onClose?: (code: number) => void,
  ): void {
    messageHandler = onMessage
    closeHandler = onClose || null

    ws = new WebSocket(url)
    ws.binaryType = 'arraybuffer'

    ws.onopen = () => {
      connected.value = true
    }

    ws.onmessage = (event: MessageEvent) => {
      if (typeof event.data === 'string') {
        try {
          const msg = JSON.parse(event.data)
          messageHandler?.(msg)
        } catch {
          // 忽略非 JSON 消息
        }
      }
      // 二进制帧是回声，前端不需要处理
    }

    ws.onclose = (event: CloseEvent) => {
      connected.value = false
      closeHandler?.(event.code)
    }

    ws.onerror = () => {
      connected.value = false
    }
  }

  /** 发送 PCM 音频帧（二进制） */
  function sendAudio(buffer: ArrayBuffer): boolean {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(buffer)
      return true
    }
    return false
  }

  /** 发送 JSON 信令消息（WebRTC 等） */
  function sendSignal(toUserId: number, signalType: string, data: any): boolean {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ to_user_id: toUserId, signal_type: signalType, data }))
      return true
    }
    return false
  }

  /** 关闭连接 */
  function disconnect(): void {
    if (ws) {
      ws.close()
      ws = null
    }
    connected.value = false
  }

  return { connected, connect, sendAudio, sendSignal, disconnect }
}
