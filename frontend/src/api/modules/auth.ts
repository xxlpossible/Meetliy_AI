// ============================================================
// 认证 API — 注册 / 登录 / 刷新
// ============================================================

import { request, setTokens } from '../request'
import type { ApiResponse, TokenData, LoginRequest, RegisterRequest } from '../types'

export const authApi = {
  /** 用户登录 */
  async login(data: LoginRequest): Promise<TokenData> {
    const resp = await request.post<ApiResponse<TokenData>>('/auth/login', data)
    if (resp.data.status_code === 200) {
      setTokens(resp.data.data)
      localStorage.setItem('username', data.username)
      return resp.data.data
    }
    throw new Error(resp.data.status_message)
  },

  /** 用户注册 */
  async register(data: RegisterRequest): Promise<void> {
    const resp = await request.post<ApiResponse<null>>('/auth/register', data)
    if (resp.data.status_code !== 200) {
      throw new Error(resp.data.status_message)
    }
  },

  /** 刷新 Token（拦截器内部调用，也可手动调用） */
  async refresh(refreshToken: string): Promise<TokenData> {
    const resp = await request.post<ApiResponse<TokenData>>('/auth/refresh', {
      refresh_token: refreshToken,
    })
    if (resp.data.status_code === 200) {
      setTokens(resp.data.data)
      return resp.data.data
    }
    throw new Error(resp.data.status_message)
  },
}
