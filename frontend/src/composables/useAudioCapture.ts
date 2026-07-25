// ============================================================
// useAudioCapture — 麦克风采集 + PCM 编码
// 通过 AudioContext + ScriptProcessorNode 采集音频，重采样到 16kHz，
// 转 Int16 PCM 后通过回调向外抛出二进制帧。
// ============================================================

import { ref, onUnmounted } from 'vue'

export function useAudioCapture() {
  const isCapturing = ref(false)
  const error = ref<string | null>(null)

  let mediaStream: MediaStream | null = null
  let audioContext: AudioContext | null = null
  let processor: ScriptProcessorNode | null = null
  let source: MediaStreamAudioSourceNode | null = null

  /** Float32 → Int16 PCM 编码 */
  function float32ToInt16(float32Array: Float32Array): ArrayBuffer {
    const int16Array = new Int16Array(float32Array.length)
    for (let i = 0; i < float32Array.length; i++) {
      const s = Math.max(-1, Math.min(1, float32Array[i]))
      int16Array[i] = s < 0 ? s * 0x8000 : s * 0x7fff
    }
    return int16Array.buffer
  }

  /**
   * 开始采集
   * @param onChunk 每次采集到 PCM 帧时的回调（ArrayBuffer, 16kHz, Int16, mono）
   */
  async function start(onChunk: (pcm: ArrayBuffer) => void): Promise<void> {
    error.value = null

    // 安全检查：getUserMedia 需要安全上下文
    if (!window.isSecureContext) {
      error.value =
        '当前页面非安全上下文，浏览器禁止访问麦克风。\n' +
        '请在 localhost 或 HTTPS 下访问。'
      throw new Error(error.value)
    }

    try {
      // 1. 获取麦克风流（请求 16kHz 单声道，回声消除等）
      mediaStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          sampleRate: 16000,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      })

      // 2. 创建 AudioContext
      audioContext = new AudioContext({ sampleRate: 16000 })
      source = audioContext.createMediaStreamSource(mediaStream)

      // 3. ScriptProcessorNode — 每 4096 采样触发一次
      const bufferSize = 4096
      processor = audioContext.createScriptProcessor(bufferSize, 1, 1)

      processor.onaudioprocess = (e: AudioProcessingEvent) => {
        const inputData = e.inputBuffer.getChannelData(0)
        // 复制数据（避免引用被复用）
        const copy = new Float32Array(inputData.length)
        copy.set(inputData)
        const pcm = float32ToInt16(copy)
        onChunk(pcm)
      }

      source.connect(processor)
      // 接入零增益节点防止本地回声（保持 audio graph 存活但不播放）
      const silentGain = audioContext.createGain()
      silentGain.gain.value = 0
      processor.connect(silentGain)
      silentGain.connect(audioContext.destination)

      isCapturing.value = true
    } catch (e: any) {
      error.value = e.message || '麦克风启动失败'
      throw e
    }
  }

  /** 停止采集并释放资源 */
  function stop(): void {
    if (processor) {
      processor.disconnect()
      processor = null
    }
    if (source) {
      source.disconnect()
      source = null
    }
    if (audioContext) {
      audioContext.close().catch(() => {})
      audioContext = null
    }
    if (mediaStream) {
      mediaStream.getTracks().forEach((t) => t.stop())
      mediaStream = null
    }
    isCapturing.value = false
  }

  /** 获取当前采集的 MediaStream（供 WebRTC 复用） */
  function getStream(): MediaStream | null {
    return mediaStream
  }

  /** 启用/禁用音频轨道（控制 WebRTC 发送+本地 PCM 采集） */
  function setTrackEnabled(enabled: boolean): void {
    if (mediaStream) {
      mediaStream.getAudioTracks().forEach((t) => (t.enabled = enabled))
    }
  }

  onUnmounted(stop)

  return { isCapturing, error, start, stop, getStream, setTrackEnabled }
}
