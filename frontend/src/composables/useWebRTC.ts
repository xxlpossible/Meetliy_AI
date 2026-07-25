// ============================================================
// useWebRTC — WebRTC Mesh 音频 P2P 传输
//
// 架构：
//   每个参会者之间建立 1:1 RTCPeerConnection（Mesh 拓扑），
//   通过 MeetingRoomView 中继信令（offer/answer/ICE candidate）
//   经后端 WebSocket 的 signal 通道转发。
//
// 关键设计（参考 frontend_test/meeting.js 已验证方案）：
//   1. 使用 onnegotiationneeded 事件触发 createOffer（而非手动调用），
//      确保在 addTrack 后由浏览器自动触发协商。
//   2. 事件处理器必须在 addTrack 之前设置，否则 ontrack 可能丢失。
//   3. ICE 候选缓存：早于 setRemoteDescription 到达的 ICE 候选
//      暂存到 pendingCandidates，远端描述就绪后刷新。
//   4. 防冲突 (glare)：userId 较小方为 initiator（设 onnegotiationneeded），
//      较大方等待对方 offer。
// ============================================================

import { ref } from 'vue'

/** STUN 服务器 */
const RTC_CONFIG: RTCConfiguration = {
  iceServers: [
    { urls: 'stun:stun.l.google.com:19302' },
    { urls: 'stun:stun1.l.google.com:19302' },
  ],
}

export interface WebRTCSignal {
  signal_type: 'offer' | 'answer' | 'ice'
  data: any
  from: number
}

export function useWebRTC() {
  const isReady = ref(false)

  /** 所有活跃的对等连接 */
  const peerConnections = new Map<number, RTCPeerConnection>()

  /** 远程音频元素 */
  const remoteAudios = new Map<number, HTMLAudioElement>()

  /**
   * 缓存早于 setRemoteDescription 到达的 ICE 候选
   * peerUserId → RTCIceCandidateInit[]
   */
  const pendingCandidates = new Map<number, RTCIceCandidateInit[]>()

  let localStream: MediaStream | null = null
  let sendSignalFn: ((toUserId: number, signalType: string, data: any) => void) | null = null
  let myUserId: number | null = null

  /**
   * 初始化 WebRTC（仅注入依赖，不发起连接）
   * @param stream    本地麦克风 MediaStream
   * @param userId    当前用户 ID
   * @param sendSignal 发送信令的函数
   */
  function initialize(
    stream: MediaStream,
    userId: number,
    sendSignal: (toUserId: number, signalType: string, data: any) => void,
  ): void {
    localStream = stream
    myUserId = userId
    sendSignalFn = sendSignal
    isReady.value = true
  }

  /**
   * 核心：创建与指定 peer 的 RTCPeerConnection
   * @param isInitiator   userId 较小方为 true（设 onnegotiationneeded 主动发 offer）
   */
  function createPeerConnection(targetUserId: number, isInitiator: boolean): RTCPeerConnection {
    const pc = new RTCPeerConnection(RTC_CONFIG)
    peerConnections.set(targetUserId, pc)

    // ---- 1. 事件处理器（必须在 addTrack 之前设置） ----

    // 发起方：监听 onnegotiationneeded 触发 createOffer
    if (isInitiator) {
      pc.onnegotiationneeded = async () => {
        try {
          console.log(`[WebRTC] onnegotiationneeded → createOffer: user=${targetUserId}`)
          const offer = await pc.createOffer()
          await pc.setLocalDescription(offer)
          sendSignalFn!(targetUserId, 'offer', pc.localDescription)
        } catch (e) {
          console.error(`[WebRTC] createOffer 失败 (${targetUserId}):`, e)
        }
      }
    }

    // 接收远程音轨
    pc.ontrack = (event: RTCTrackEvent) => {
      const remoteStream = event.streams[0]
      if (!remoteStream) return
      console.log(`[WebRTC] 收到远程音轨: user=${targetUserId}, tracks=${remoteStream.getAudioTracks().length}`)
      playRemoteAudio(targetUserId, remoteStream)
    }

    // ICE 候选
    pc.onicecandidate = (event: RTCPeerConnectionIceEvent) => {
      if (event.candidate) {
        sendSignalFn!(targetUserId, 'ice', event.candidate.toJSON())
      } else {
        console.log(`[WebRTC] ICE 候选收集完毕: user=${targetUserId}`)
      }
    }

    // 连接状态
    pc.oniceconnectionstatechange = () => {
      console.log(`[WebRTC] ICE 状态: user=${targetUserId}, state=${pc.iceConnectionState}`)
    }

    pc.onconnectionstatechange = () => {
      console.log(`[WebRTC] 连接状态: user=${targetUserId}, state=${pc.connectionState}`)
    }

    // ---- 2. 添加本地音轨（可能触发 onnegotiationneeded） ----
    if (localStream) {
      localStream.getAudioTracks().forEach((track) => {
        pc.addTrack(track, localStream!)
      })
      console.log(`[WebRTC] 已添加本地音轨到 PC(${targetUserId})`)
    }

    return pc
  }

  /**
   * 为指定 peer 发起连接
   * - 仅在 WS 已连接后调用（由 handleParticipantsList / handleParticipantJoined 触发）
   * - 防冲突：userId 较小方设为 initiator
   */
  function connectToPeer(peerUserId: number): void {
    if (!localStream || !myUserId || !sendSignalFn) {
      console.warn('[WebRTC] connectToPeer: 未初始化')
      return
    }
    if (peerConnections.has(peerUserId)) {
      console.log(`[WebRTC] connectToPeer: PC(${peerUserId}) 已存在，跳过`)
      return
    }

    if (myUserId < peerUserId) {
      // 我 ID 较小 → 发起方 → 设 onnegotiationneeded 主动发 offer
      console.log(`[WebRTC] 发起 WebRTC 连接: my=${myUserId} < peer=${peerUserId}`)
      createPeerConnection(peerUserId, true)
    } else {
      // 我 ID 较大 → 等待方 → 不设 onnegotiationneeded，等对方 offer
      console.log(`[WebRTC] 等待对方 offer: my=${myUserId} > peer=${peerUserId}`)
      createPeerConnection(peerUserId, false)
    }
  }

  // ============================================================
  // 信令处理
  // ============================================================

  async function handleSignal(signal: WebRTCSignal): Promise<void> {
    const { signal_type, data, from } = signal
    if (from === myUserId) return

    switch (signal_type) {
      case 'offer':
        await handleRemoteOffer(from, data)
        break
      case 'answer':
        await handleRemoteAnswer(from, data)
        break
      case 'ice':
        await handleRemoteIce(from, data)
        break
    }
  }

  /** 收到远端 Offer → createAnswer */
  async function handleRemoteOffer(peerId: number, sdp: RTCSessionDescriptionInit): Promise<void> {
    console.log(`[WebRTC] 收到 offer: user=${peerId}`)

    let pc = peerConnections.get(peerId)
    if (!pc) {
      // 如果 PC 不存在（竞态：participant_joined 和信号几乎同时到达），创建非发起方 PC
      pc = createPeerConnection(peerId, false)
    }

    try {
      await pc.setRemoteDescription(new RTCSessionDescription(sdp))
      console.log(`[WebRTC] 远程描述已设置(offer): user=${peerId}`)

      // 刷新此前缓存的 ICE 候选
      await flushPendingCandidates(peerId, pc)

      const answer = await pc.createAnswer()
      await pc.setLocalDescription(answer)
      sendSignalFn!(peerId, 'answer', pc.localDescription)
      console.log(`[WebRTC] 已发送 answer: user=${peerId}`)
    } catch (e) {
      console.error(`[WebRTC] handleOffer 失败 (${peerId}):`, e)
      closePeerConnection(peerId)
    }
  }

  /** 收到远端 Answer → setRemoteDescription */
  async function handleRemoteAnswer(peerId: number, sdp: RTCSessionDescriptionInit): Promise<void> {
    const pc = peerConnections.get(peerId)
    if (!pc) {
      console.warn(`[WebRTC] 收到未知 peer ${peerId} 的 answer`)
      return
    }
    try {
      console.log(`[WebRTC] 收到 answer: user=${peerId}`)
      await pc.setRemoteDescription(new RTCSessionDescription(sdp))
      console.log(`[WebRTC] 远程描述已设置(answer): user=${peerId}`)
      await flushPendingCandidates(peerId, pc)
    } catch (e) {
      console.error(`[WebRTC] handleAnswer 失败 (${peerId}):`, e)
      closePeerConnection(peerId)
    }
  }

  /** 收到远端 ICE candidate */
  async function handleRemoteIce(peerId: number, candidate: RTCIceCandidateInit): Promise<void> {
    const pc = peerConnections.get(peerId)
    if (!pc) return

    if (pc.remoteDescription) {
      // 远端描述已设置 → 直接添加
      try {
        await pc.addIceCandidate(new RTCIceCandidate(candidate))
      } catch (e) {
        console.warn(`[WebRTC] addIceCandidate 失败 (${peerId}):`, e)
      }
    } else {
      // 远端描述尚未设置 → 缓存
      if (!pendingCandidates.has(peerId)) {
        pendingCandidates.set(peerId, [])
      }
      pendingCandidates.get(peerId)!.push(candidate)
      console.log(`[WebRTC] 缓存 ICE 候选: user=${peerId}, 缓存数=${pendingCandidates.get(peerId)!.length}`)
    }
  }

  /** 刷新 pendingCandidates 中缓存的 ICE 候选 */
  async function flushPendingCandidates(peerId: number, pc: RTCPeerConnection): Promise<void> {
    const buffered = pendingCandidates.get(peerId)
    if (!buffered || buffered.length === 0) return

    console.log(`[WebRTC] 刷新 ${buffered.length} 个缓存的 ICE 候选: user=${peerId}`)
    for (const candidate of buffered) {
      try {
        await pc.addIceCandidate(new RTCIceCandidate(candidate))
      } catch (e) {
        console.warn(`[WebRTC] 刷新 ICE 候选失败 (${peerId}):`, e)
      }
    }
    pendingCandidates.delete(peerId)
  }

  // ============================================================
  // 音频播放 & 资源清理
  // ============================================================

  function playRemoteAudio(peerId: number, stream: MediaStream): void {
    const oldAudio = remoteAudios.get(peerId)
    if (oldAudio) {
      oldAudio.srcObject = null
      oldAudio.remove()
    }

    const audio = new Audio()
    audio.srcObject = stream
    audio.autoplay = true
    audio.play().catch((e) => console.warn('[WebRTC] 自动播放被阻止:', e))
    remoteAudios.set(peerId, audio)
  }

  function closePeerConnection(peerId: number): void {
    const pc = peerConnections.get(peerId)
    if (pc) {
      pc.close()
      peerConnections.delete(peerId)
    }
    const audio = remoteAudios.get(peerId)
    if (audio) {
      audio.srcObject = null
      audio.remove()
      remoteAudios.delete(peerId)
    }
    pendingCandidates.delete(peerId)
  }

  function closeAll(): void {
    peerConnections.forEach((pc) => pc.close())
    peerConnections.clear()

    remoteAudios.forEach((audio) => {
      audio.srcObject = null
      audio.remove()
    })
    remoteAudios.clear()

    pendingCandidates.clear()
    localStream = null
    myUserId = null
    sendSignalFn = null
    isReady.value = false
  }

  return {
    isReady,
    initialize,
    connectToPeer,
    handleSignal,
    closePeerConnection,
    closeAll,
  }
}
