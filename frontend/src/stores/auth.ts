// ============================================================
// Auth Store — 鉴权状态管理
// 管理 access_token / refresh_token / 用户信息
// ============================================================

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { authApi } from '@/api'
import { getAccessToken, clearTokens } from '@/api/request'
import type { LoginRequest, RegisterRequest } from '@/api/types'

export const useAuthStore = defineStore('auth', () => {
  // ---- State ----
  const accessToken = ref<string | null>(getAccessToken())
  const username = ref<string>(localStorage.getItem('username') || '')
  const userId = ref<number | null>(null)

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
    parseUserId()
  }

  /** 注册 */
  async function register(data: RegisterRequest): Promise<void> {
    await authApi.register(data)
  }

  /** 登出 */
  function logout(): void {
    clearTokens()
    accessToken.value = null
    username.value = ''
    userId.value = null
  }

  // 初始化时解析 userId
  if (accessToken.value) {
    parseUserId()
  }

  return {
    accessToken,
    username,
    userId,
    isLoggedIn,
    login,
    register,
    logout,
    parseUserId,
  }
})
