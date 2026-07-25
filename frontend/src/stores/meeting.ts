// ============================================================
// Meeting Store — 会议状态管理
// 管理当前会议信息 / 参与者列表 / 转写记录
// ============================================================

import { defineStore } from 'pinia'
import { ref, reactive } from 'vue'
import { meetingApi } from '@/api'
import type { MeetingItem, Participant } from '@/api/types'

export const useMeetingStore = defineStore('meeting', () => {
  // ---- State ----
  const meetings = ref<MeetingItem[]>([])
  const currentMeetingId = ref<string | null>(null)
  const currentMeetingName = ref<string>('')
  const isHost = ref(false)
  const participants = reactive<Map<number, Participant>>(new Map())
  const speakingSpeakers = reactive<Set<number>>(new Set())

  // ---- Actions ----

  /** 加载会议列表 */
  async function loadMeetings(): Promise<void> {
    const data = await meetingApi.list()
    meetings.value = data.data
  }

  /** 创建会议 */
  async function createMeeting(name?: string): Promise<string> {
    const data = await meetingApi.create(name)
    currentMeetingId.value = data.meeting_id
    currentMeetingName.value = data.meeting_name
    isHost.value = true
    return data.meeting_id
  }

  /** 加入会议 */
  async function joinMeeting(meetingId: string): Promise<void> {
    const data = await meetingApi.join(meetingId)
    currentMeetingId.value = data.meeting_id
    currentMeetingName.value = data.meeting_name
    isHost.value = data.is_host
    // 初始化参与者列表
    participants.clear()
    data.participants.forEach((p) => {
      participants.set(p.id, p)
    })
  }

  /** 设置当前会议（从路由进入时） */
  function setCurrentMeeting(meetingId: string, name: string, host: boolean): void {
    currentMeetingId.value = meetingId
    currentMeetingName.value = name
    isHost.value = host
  }

  /** 添加参与者 */
  function addParticipant(p: Participant): void {
    participants.set(p.id, p)
  }

  /** 移除参与者 */
  function removeParticipant(userId: number): void {
    participants.delete(userId)
  }

  /** 设置说话状态 */
  function setSpeaking(speakerId: number, speaking: boolean): void {
    if (speaking) {
      speakingSpeakers.add(speakerId)
    } else {
      speakingSpeakers.delete(speakerId)
    }
  }

  /** 重置会议状态 */
  function reset(): void {
    currentMeetingId.value = null
    currentMeetingName.value = ''
    isHost.value = false
    participants.clear()
    speakingSpeakers.clear()
  }

  return {
    meetings,
    currentMeetingId,
    currentMeetingName,
    isHost,
    participants,
    speakingSpeakers,
    loadMeetings,
    createMeeting,
    joinMeeting,
    setCurrentMeeting,
    addParticipant,
    removeParticipant,
    setSpeaking,
    reset,
  }
})
