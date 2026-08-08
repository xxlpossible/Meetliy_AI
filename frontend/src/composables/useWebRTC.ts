// ============================================================
// useWebRTC — WebRTC Mesh 音频 P2P 传输
//
// 架构：
//   每个参会者之间建立 1:1 RTCPeerConnection（Mesh 拓扑），
//   通过 MeetingRoomView 中继信令（offer/answer/ICE candidate）
//   经后端 WebSocket 的 signal 通道转发。
//
// v2 设计（生产级修复）：
//   1. 移除 onnegotiationneeded 依赖：较小方在 connectToPeer 中显式
//      createOffer，不再依赖浏览器只触发一次且时机不可控的异步钩子。
//   2. 防冲突 (glare)：userId 较小方为发起方（显式 createOffer），
//      较大方只创建 PE 并等待远端 offer。
//   3. ICE / connection 状态自愈：进入 failed 时自动关闭旧 PC 并重建 +
//      重新协商（带指数退避冷却），同时 channel 断开或切标签页/最小化
//      不影响 WebRTC 连接本身（浏览器将 RTC 视为后台任务保障）。
//   4. ICE 候选缓存：早于 setRemoteDescription 到达的 ICE 候选暂存到
//      pendingCandidates，远端描述就绪后刷新。
// ============================================================

import { ref } from 'vue'

/** STUN 服务器 */
const RTC_CONFIG: RTCConfiguration = {
  iceServers: [
    { urls: 'stun:stun.l.google.com:19302' },
    { urls: 'stun:stun1.l.google.com:19302' },
  ],
}

/** ICE/connection 失败后的重建参数 */
const MAX_REBUILD_ATTEMPTS = 5          // 最多重建 5 次
const REBUILD_BASE_DELAY_MS = 1000      // 基础延迟 1 秒
const REBUILD_MAX_DELAY_MS = 10_000     // 最大延迟 10 秒

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

  /** 重建防抖定时器 */
  const rebuildTimers = new Map<number, ReturnType<typeof setTimeout>>()

  /** 每个 peer 的当前重建次数（每次成功连接后应重置） */
  const rebuildAttempts = new Map<number, number>()

  let localStream: MediaStream | null = null
  let sendSignalFn: ((toUserId: number, signalType: string, data: any) => void) | null = null
  let myUserId: number | null = null

  // ============================================================
  // 初始化
  // ============================================================

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

  // ============================================================
  // PC 创建 / 显式协商
  // ============================================================

  /**
   * 创建与指定 peer 的 RTCPeerConnection。
   * 不再设置 onnegotiationneeded —— 发起由 connectToPeer 显式调用 createOffer。
   */
  function createPeerConnection(targetUserId: number): RTCPeerConnection {
    const pc = new RTCPeerConnection(RTC_CONFIG)
    peerConnections.set(targetUserId, pc)

    // ---- 接收远程音轨 ----
    pc.ontrack = (event: RTCTrackEvent) => {
      const remoteStream = event.streams[0]
      if (!remoteStream) return
      console.log(`[WebRTC] 收到远程音轨: user=${targetUserId}`)
      playRemoteAudio(targetUserId, remoteStream)
    }

    // ---- ICE 候选 ----
    pc.onicecandidate = (event: RTCPeerConnectionIceEvent) => {
      if (event.candidate) {
        sendSignalFn!(targetUserId, 'ice', event.candidate.toJSON())
      } else {
        console.log(`[WebRTC] ICE 候选收集完毕: user=${targetUserId}`)
      }
    }

    // ---- ICE 连接状态 → 失败时自动重建 ----
    pc.oniceconnectionstatechange = () => {
      console.log(`[WebRTC] ICE 状态: user=${targetUserId}, state=${pc.iceConnectionState}`)
      if (pc.iceConnectionState === 'failed') {
        console.warn(`[WebRTC] ICE 失败 → 调度自动重建: user=${targetUserId}`)
        scheduleRebuild(targetUserId)
      } else if (pc.iceConnectionState === 'connected' || pc.iceConnectionState === 'completed') {
        // 连接成功后重置重建计数
        rebuildAttempts.delete(targetUserId)
      }
    }

    // ---- 连接状态 → 失败兜底 ----
    pc.onconnectionstatechange = () => {
      console.log(`[WebRTC] 连接状态: user=${targetUserId}, state=${pc.connectionState}`)
      if (pc.connectionState === 'failed') {
        console.warn(`[WebRTC] 连接失败 → 调度自动重建: user=${targetUserId}`)
        scheduleRebuild(targetUserId)
      } else if (pc.connectionState === 'connected') {
        rebuildAttempts.delete(targetUserId)
      }
    }

    // ---- 添加本地音轨 ----
    if (localStream) {
      localStream.getAudioTracks().forEach((track) => {
        pc.addTrack(track, localStream!)
      })
      console.log(`[WebRTC] 已添加本地音轨到 PC(${targetUserId})`)
    }

    return pc
  }

  /**
   * 对已有的 PC 显式发起 offer（用于新建或 ICE 失败后的重建）。
   * 不依赖 onnegotiationneeded —— 由调用方在 PC signalingState 稳定后显式调用。
   */
  async function initiateOffer(peerUserId: number): Promise<void> {
    const pc = peerConnections.get(peerUserId)
    if (!pc) return

    // 防止重复发起：如果已有 local offer 或正在协商中，跳过
    if (pc.signalingState !== 'stable') {
      console.warn(
        `[WebRTC] 跳过发起 offer: signalingState=${pc.signalingState}, user=${peerUserId}`,
      )
      return
    }

    try {
      const offer = await pc.createOffer()
      await pc.setLocalDescription(offer)
      sendSignalFn!(peerUserId, 'offer', pc.localDescription)
      console.log(`[WebRTC] 已发送 offer: user=${peerUserId}`)
    } catch (e) {
      console.error(`[WebRTC] 发起 offer 失败 (${peerUserId}):`, e)
      // 发起异常 → 关闭 PC，等 ICE failed 检测触发重建
      cleanupPeerSilent(peerUserId)
    }
  }

  // ============================================================
  // connectToPeer — 唯一的外部连接入口
  // ============================================================

  /**
   * 为指定 peer 发起 / 建立 WebRTC 连接。
   *
   * - 较小方（myUserId < peerUserId）：创建 PC → 显式 createOffer 发起
   * - 较大方（myUserId > peerUserId）：创建 PC → 等待远端 offer
   *
   * ✓ 由 handleParticipantsList / handleParticipantJoined 触发
   * ✓ ICE/connection failed 自动重建时也会经此入口
   */
  async function connectToPeer(peerUserId: number): Promise<void> {
    if (!localStream || !myUserId || !sendSignalFn) {
      console.warn('[WebRTC] connectToPeer: 未初始化')
      return
    }

    const existing = peerConnections.get(peerUserId)
    if (existing) {
      const ice = existing.iceConnectionState
      const conn = existing.connectionState
      if (ice === 'connected' || ice === 'completed' || conn === 'connected') {
        console.log(`[WebRTC] connectToPeer: PC(${peerUserId}) 已连接，跳过`)
        return
      }
      // 存在但未连接（checking/new/disconnected）：不重复创建，
      // 由 ICE/connection 状态监听负责触发 rebuild
      console.log(
        `[WebRTC] connectToPeer: PC(${peerUserId}) 已存在 (ice=${ice}, conn=${conn})，跳过`,
      )
      return
    }

    const isInitiator = myUserId < peerUserId

    if (isInitiator) {
      console.log(`[WebRTC] 发起 WebRTC 连接: my=${myUserId} < peer=${peerUserId}`)
      const pc = createPeerConnection(peerUserId)

      // 让浏览器完成 addTrack 后的内部处理，确保 signalingState 回到 stable
      await new Promise((resolve) => setTimeout(resolve, 0))

      await initiateOffer(peerUserId)
    } else {
      console.log(`[WebRTC] 等待对方 offer: my=${myUserId} > peer=${peerUserId}`)
      createPeerConnection(peerUserId)
    }
  }

  // ============================================================
  // ICE / connection 失败 → 自动重建
  // ============================================================

  /**
   * 调度 PC 重建（带指数退避和最大次数限制）。
   * 由 oniceconnectionstatechange / onconnectionstatechange → failed 触发。
   */
  function scheduleRebuild(peerUserId: number): void {
    // 清除已有重建定时器（避免堆积）
    const existingTimer = rebuildTimers.get(peerUserId)
    if (existingTimer) {
      clearTimeout(existingTimer)
    }

    const attempts = rebuildAttempts.get(peerUserId) || 0
    if (attempts >= MAX_REBUILD_ATTEMPTS) {
      console.error(
        `[WebRTC] 重建次数已达上限 (${MAX_REBUILD_ATTEMPTS}): user=${peerUserId}，停止重建`,
      )
      return
    }

    rebuildAttempts.set(peerUserId, attempts + 1)

    // 指数退避：1s → 2s → 4s → 8s → 10s(封顶)
    const delay = Math.min(REBUILD_BASE_DELAY_MS * Math.pow(2, attempts), REBUILD_MAX_DELAY_MS)
    console.log(
      `[WebRTC] 将在 ${delay / 1000}s 后重建 PC: user=${peerUserId} (第 ${attempts + 1}/${MAX_REBUILD_ATTEMPTS} 次)`,
    )

    const timer = setTimeout(() => {
      rebuildTimers.delete(peerUserId)
      rebuildPeer(peerUserId)
    }, delay)

    rebuildTimers.set(peerUserId, timer)
  }

  /** 关闭旧 PC → 重建 → 重新走发起 / 等待流程 */
  async function rebuildPeer(peerUserId: number): Promise<void> {
    // 页面已销毁（closeAll 清空了状态）
    if (!localStream || !myUserId || !sendSignalFn) return

    console.log(`[WebRTC] 开始重建 PC: user=${peerUserId}`)

    // 关闭旧 PC（静默清理，不触发新一轮 on...statechange）
    const oldPc = peerConnections.get(peerUserId)
    if (oldPc) {
      oldPc.oniceconnectionstatechange = null
      oldPc.onconnectionstatechange = null
      oldPc.onicecandidate = null
      oldPc.ontrack = null
      oldPc.close()
      peerConnections.delete(peerUserId)
    }

    // 清除缓存的 ICE 候选
    pendingCandidates.delete(peerUserId)

    // 重新走 connectToPeer（总是走发起 / 等待逻辑）
    await connectToPeer(peerUserId)
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

  /** 收到远端 Offer → createAnswer（含碰撞处理） */
  async function handleRemoteOffer(peerId: number, sdp: RTCSessionDescriptionInit): Promise<void> {
    console.log(`[WebRTC] 收到 offer: user=${peerId}`)

    let pc = peerConnections.get(peerId)
    if (!pc) {
      // PC 不存在 → 创建等待方 PC（不设 onnegotiationneeded）
      pc = createPeerConnection(peerId)
    }

    try {
      // ---- 碰撞处理（双方同时发起 offer） ----
      // 仅在两方都重建时可能发生；正常情况下只有较小方发起。
      if (pc.signalingState === 'have-local-offer' && myUserId !== null) {
        const isPolite = myUserId < peerId
        if (isPolite) {
          // Polite 方：忽略远端 offer（我的 offer 优先）
          console.log(`[WebRTC] polite 方忽略远端 offer: user=${peerId}`)
          return
        }
        // Impolite 方：回滚本地 offer，接受远端
        console.log(`[WebRTC] impolite 方回滚本地，接受远端: user=${peerId}`)
        await pc.setLocalDescription({ type: 'rollback' })
      }

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
      cleanupPeerSilent(peerId)
    }
  }

  /** 收到远端 Answer → setRemoteDescription */
  async function handleRemoteAnswer(peerId: number, sdp: RTCSessionDescriptionInit): Promise<void> {
    const pc = peerConnections.get(peerId)
    if (!pc) {
      console.warn(`[WebRTC] 收到未知 peer ${peerId} 的 answer`)
      return
    }

    // 本地必须有 pending offer 才接受 answer
    if (pc.signalingState !== 'have-local-offer') {
      console.warn(
        `[WebRTC] 忽略 answer: signalingState=${pc.signalingState}, user=${peerId}`,
      )
      return
    }

    try {
      console.log(`[WebRTC] 收到 answer: user=${peerId}`)
      await pc.setRemoteDescription(new RTCSessionDescription(sdp))
      console.log(`[WebRTC] 远程描述已设置(answer): user=${peerId}`)
      await flushPendingCandidates(peerId, pc)
    } catch (e) {
      console.error(`[WebRTC] handleAnswer 失败 (${peerId}):`, e)
      cleanupPeerSilent(peerId)
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
      console.log(
        `[WebRTC] 缓存 ICE 候选: user=${peerId}, 缓存数=${pendingCandidates.get(peerId)!.length}`,
      )
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

  /**
   * 静默清理单个 peer（不触发新的状态变更回调）。
   * 用于协商失败、连接异常时的内部清理，不需要通知外部。
   */
  function cleanupPeerSilent(peerId: number): void {
    const pc = peerConnections.get(peerId)
    if (pc) {
      pc.oniceconnectionstatechange = null
      pc.onconnectionstatechange = null
      pc.onicecandidate = null
      pc.ontrack = null
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

    // 清理重建状态
    const timer = rebuildTimers.get(peerId)
    if (timer) {
      clearTimeout(timer)
      rebuildTimers.delete(peerId)
    }
  }

  /**
   * 关闭与指定 peer 的连接及音频（外部调用：participant_left 或主动断开）。
   * 也会清理该 peer 的重建状态。
   */
  function closePeerConnection(peerId: number): void {
    // 先清理重建状态（避免 active 的 rebuild timer 在外部 close 后又重建 PC）
    const timer = rebuildTimers.get(peerId)
    if (timer) {
      clearTimeout(timer)
      rebuildTimers.delete(peerId)
    }
    rebuildAttempts.delete(peerId)

    cleanupPeerSilent(peerId)
  }

  /** 关闭所有连接（组件卸载 / 离开会议时调用） */
  function closeAll(): void {
    // 1. 清除所有重建定时器
    rebuildTimers.forEach((timer) => clearTimeout(timer))
    rebuildTimers.clear()
    rebuildAttempts.clear()

    // 2. 关闭所有 RTCPeerConnection
    peerConnections.forEach((pc) => {
      pc.oniceconnectionstatechange = null
      pc.onconnectionstatechange = null
      pc.onicecandidate = null
      pc.ontrack = null
      pc.close()
    })
    peerConnections.clear()

    // 3. 清理音频元素
    remoteAudios.forEach((audio) => {
      audio.srcObject = null
      audio.remove()
    })
    remoteAudios.clear()

    // 4. 清理 ICE 缓存与状态引用
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
