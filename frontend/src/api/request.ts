// ============================================================
// Axios 实例 + 拦截器
// 核心机制：双 Token 自动刷新（401 → refresh → 重试）
// ============================================================

import axios, {
  type AxiosInstance,
  type AxiosRequestConfig,
  type InternalAxiosRequestConfig,
} from 'axios'
import { ElMessage } from 'element-plus'
import type { ApiResponse, TokenData } from './types'

const request: AxiosInstance = axios.create({
  baseURL: '/api/v1',
  timeout: 30000,
  headers: { 'Content-Type': 'application/json' },
})

// ---- Token 存取工具 ----
const TOKEN_KEYS = {
  access: 'access_token',
  refresh: 'refresh_token',
  username: 'username',
} as const

function getAccessToken(): string | null {
  return localStorage.getItem(TOKEN_KEYS.access)
}

function getRefreshToken(): string | null {
  return localStorage.getItem(TOKEN_KEYS.refresh)
}

function setTokens(data: TokenData) {
  localStorage.setItem(TOKEN_KEYS.access, data.access_token)
  localStorage.setItem(TOKEN_KEYS.refresh, data.refresh_token)
}

function clearTokens() {
  localStorage.removeItem(TOKEN_KEYS.access)
  localStorage.removeItem(TOKEN_KEYS.refresh)
  localStorage.removeItem(TOKEN_KEYS.username)
}

// ---- 请求拦截器：自动附加 access_token ----
request.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    const token = getAccessToken()
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => Promise.reject(error),
)

// ---- 响应拦截器：401 自动刷新 + 重试 ----
let isRefreshing = false
let pendingQueue: Array<(token: string) => void> = []

function processQueue(token: string) {
  pendingQueue.forEach((cb) => cb(token))
  pendingQueue = []
}

request.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config as AxiosRequestConfig & { _retry?: boolean }

    // 非 401 错误直接抛出
    if (error.response?.status !== 401 || originalRequest._retry) {
      // 提取后端错误信息
      const detail = error.response?.data?.detail || error.response?.data?.status_message
      if (detail && !error.config?.url?.includes('/auth/')) {
        ElMessage.error(detail)
      }
      return Promise.reject(error)
    }

    // refresh 接口自身 401 → 跳登录
    if (originalRequest.url?.includes('/auth/refresh')) {
      clearTokens()
      window.location.href = '/login'
      return Promise.reject(error)
    }

    // 已经在刷新中 → 排队等待
    if (isRefreshing) {
      return new Promise((resolve) => {
        pendingQueue.push((token: string) => {
          originalRequest.headers = { ...originalRequest.headers, Authorization: `Bearer ${token}` }
          resolve(request(originalRequest))
        })
      })
    }

    // 开始刷新
    originalRequest._retry = true
    isRefreshing = true

    try {
      const refreshToken = getRefreshToken()
      if (!refreshToken) {
        throw new Error('No refresh token')
      }

      const resp = await axios.post<ApiResponse<TokenData>>(
        '/api/v1/auth/refresh',
        { refresh_token: refreshToken },
        { headers: { 'Content-Type': 'application/json' } },
      )

      if (resp.data.status_code === 200) {
        setTokens(resp.data.data)
        processQueue(resp.data.data.access_token)
        originalRequest.headers = {
          ...originalRequest.headers,
          Authorization: `Bearer ${resp.data.data.access_token}`,
        }
        return request(originalRequest)
      }
      throw new Error('Refresh failed')
    } catch (refreshError) {
      processQueue('')
      clearTokens()
      ElMessage.error('登录已过期，请重新登录')
      setTimeout(() => {
        window.location.href = '/login'
      }, 1500)
      return Promise.reject(refreshError)
    } finally {
      isRefreshing = false
    }
  },
)

export { request, getAccessToken, getRefreshToken, setTokens, clearTokens, TOKEN_KEYS }
