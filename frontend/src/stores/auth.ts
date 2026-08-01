// ============================================================
// Auth Store — 鉴权状态管理
// 管理 access_token / refresh_token / 用户信息
// ============================================================

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { authApi, userApi } from '@/api'
import { getAccessToken, clearTokens } from '@/api/request'
import type { LoginRequest, RegisterRequest, UpdateProfileRequest, ChangePasswordRequest } from '@/api/types'

export const useAuthStore = defineStore('auth', () => {
  // ---- State ----
  const accessToken = ref<string | null>(getAccessToken())
  const username = ref<string>(localStorage.getItem('username') || '')
  const userId = ref<number | null>(null)
  const avatar = ref<string | null>(localStorage.getItem('avatar') || null)

  // ---- Getters ----
  const isLoggedIn = computed(() => !!accessToken.value)

  // ---- Actions ----

  /** 从 JWT payload 解析 user_id */
  function parseUserId(): number | null {
    const token = accessToken.value
    if (!token) return null
    try {
      const payload = JSON.parse(atob(token.split('.')[1]))
      userId.value = payload.user_id ?? null
      return userId.value
    } catch {
      return null
    }
  }

  /** 登录 */
  async function login(data: LoginRequest): Promise<void> {
    await authApi.login(data)
    accessToken.value = getAccessToken()
    username.value = data.username
    localStorage.setItem('username', data.username)
    parseUserId()
    // 登录后拉取头像等资料
    await fetchProfile()
  }

  /** 注册 */
  async function register(data: RegisterRequest): Promise<void> {
    await authApi.register(data)
  }

  /** 拉取当前用户资料（更新用户名/头像） */
  async function fetchProfile(): Promise<void> {
    try {
      const profile = await userApi.getProfile()
      username.value = profile.username
      avatar.value = profile.avatar
      localStorage.setItem('username', profile.username)
      if (profile.avatar) {
        localStorage.setItem('avatar', profile.avatar)
      } else {
        localStorage.removeItem('avatar')
      }
      if (profile.id != null) userId.value = profile.id
    } catch {
      // 拉取失败不阻断登录流程
    }
  }

  /** 更新用户资料（用户名） */
  async function updateProfile(data: UpdateProfileRequest): Promise<void> {
    const profile = await userApi.updateProfile(data)
    username.value = profile.username
    avatar.value = profile.avatar
    localStorage.setItem('username', profile.username)
    if (profile.avatar) {
      localStorage.setItem('avatar', profile.avatar)
    } else {
      localStorage.removeItem('avatar')
    }
  }

  /** 上传头像（文件直接上传，返回并保存 OSS URL） */
  async function uploadAvatar(file: File): Promise<void> {
    const profile = await userApi.uploadAvatar(file)
    avatar.value = profile.avatar
    if (profile.avatar) {
      localStorage.setItem('avatar', profile.avatar)
    } else {
      localStorage.removeItem('avatar')
    }
  }

  /** 修改密码 */
  async function changePassword(data: ChangePasswordRequest): Promise<void> {
    await userApi.changePassword(data)
  }

  /** 登出 */
  function logout(): void {
    clearTokens()
    accessToken.value = null
    username.value = ''
    userId.value = null
    avatar.value = null
    localStorage.removeItem('avatar')
  }

  // 初始化时解析 userId
  if (accessToken.value) {
    parseUserId()
    fetchProfile()
  }

  return {
    accessToken,
    username,
    userId,
    avatar,
    isLoggedIn,
    login,
    register,
    fetchProfile,
    updateProfile,
    uploadAvatar,
    changePassword,
    logout,
    parseUserId,
  }
})
