// ============================================================
// 用户 API — 个人资料 / 修改密码
// ============================================================

import { request } from '../request'
import type { ApiResponse, UserProfile, UpdateProfileRequest, ChangePasswordRequest } from '../types'

/** 从错误响应中提取后端返回的错误信息（兼容 FastAPI 422 的数组 detail） */
function getDetail(e: any): string {
  const detail = e?.response?.data?.detail
  if (Array.isArray(detail)) {
    return detail.map((d: any) => d?.msg).filter(Boolean).join('；')
  }
  return detail || e?.response?.data?.status_message || ''
}

export const userApi = {
  /** 获取当前用户资料 */
  async getProfile(): Promise<UserProfile> {
    try {
      const resp = await request.get<ApiResponse<UserProfile>>('/user/profile')
      if (resp.data.status_code === 200) {
        return resp.data.data
      }
      throw new Error(resp.data.status_message)
    } catch (e: any) {
      throw new Error(getDetail(e) || '获取资料失败')
    }
  },

  /** 更新当前用户资料（用户名） */
  async updateProfile(data: UpdateProfileRequest): Promise<UserProfile> {
    try {
      const resp = await request.put<ApiResponse<UserProfile>>('/user/profile', data)
      if (resp.data.status_code === 200) {
        return resp.data.data
      }
      throw new Error(resp.data.status_message)
    } catch (e: any) {
      throw new Error(getDetail(e) || '保存失败，请稍后重试')
    }
  },

  /** 上传头像（multipart 文件上传），返回更新后的用户资料 */
  async uploadAvatar(file: File): Promise<UserProfile> {
    try {
      const formData = new FormData()
      formData.append('file', file, file.name)
      const resp = await request.post<ApiResponse<UserProfile>>('/user/avatar', formData, {
        // 置空 Content-Type，交由浏览器/axios 自动生成 multipart/form-data 及 boundary
        headers: { 'Content-Type': undefined },
      })
      if (resp.data.status_code === 200) {
        return resp.data.data
      }
      throw new Error(resp.data.status_message)
    } catch (e: any) {
      throw new Error(getDetail(e) || '头像上传失败，请稍后重试')
    }
  },

  /** 修改密码 */
  async changePassword(data: ChangePasswordRequest): Promise<void> {
    try {
      const resp = await request.put<ApiResponse<null>>('/user/password', data)
      if (resp.data.status_code !== 200) {
        throw new Error(resp.data.status_message)
      }
    } catch (e: any) {
      throw new Error(getDetail(e) || '修改密码失败，请稍后重试')
    }
  },
}
