// ============================================================
// 知识库 API — 知识库列表 / 上传 / 状态 / 文件列表 / 分块 / 删除
// ============================================================

import { request } from '../request'
import type {
  ApiResponse,
  UploadFileData,
  FileStateData,
  KnowledgeFileItem,
  KnowledgeListData,
  KnowledgeDetail,
  UserListData,
} from '../types'

export const knowledgeApi = {
  /**
   * 获取知识库列表（分页）
   * 后端 POST /kb/list，参数包在 body 中
   */
  async list(pageNum = 1, pageSize = 20, name?: string): Promise<KnowledgeListData> {
    const resp = await request.post<ApiResponse<KnowledgeListData>>('/kb/list', {
      page_num: pageNum,
      page_size: pageSize,
      name: name || '',
    })
    if (resp.data.status_code === 200) return resp.data.data
    throw new Error(resp.data.status_message)
  },

  /** 查询知识库详情 */
  async getDetail(knowledgeId: string): Promise<KnowledgeDetail> {
    const resp = await request.get<ApiResponse<KnowledgeDetail>>('/kb/detail', {
      params: { knowledge_id: knowledgeId },
    })
    if (resp.data.status_code === 200) return resp.data.data
    throw new Error(resp.data.status_message)
  },

  /** 创建知识库 */
  async create(
    name: string,
    description?: string,
    acceptUsers?: number[]
  ): Promise<{ id: string; name: string; accept_users: number[] }> {
    const resp = await request.post<ApiResponse<{ id: string; name: string; accept_users: number[] }>>('/kb/create', {
      name,
      description: description || '',
      accept_users: acceptUsers || [],
    })
    if (resp.data.status_code === 200) return resp.data.data
    throw new Error(resp.data.status_message)
  },

  /** 更新知识库信息 */
  async update(
    knowledgeId: string,
    name?: string,
    description?: string,
    acceptUsers?: number[]
  ): Promise<{ id: string; name: string; accept_users: number[] }> {
    const resp = await request.post<ApiResponse<{ id: string; name: string; accept_users: number[] }>>('/kb/update', {
      knowledge_id: knowledgeId,
      name,
      description,
      accept_users: acceptUsers,
    })
    if (resp.data.status_code === 200) return resp.data.data
    throw new Error(resp.data.status_message)
  },

  /** 获取用户列表 */
  async getUserList(pageNum = 1, pageSize = 50, username?: string): Promise<UserListData> {
    const resp = await request.get<ApiResponse<UserListData>>('/user/list', {
      params: { page_num: pageNum, page_size: pageSize, username: username || '' },
    })
    if (resp.data.status_code === 200) return resp.data.data
    throw new Error(resp.data.status_message)
  },

  /** 上传文件到指定知识库 */
  async uploadFile(file: File, knowledgeId?: string): Promise<UploadFileData> {
    const formData = new FormData()
    formData.append('file', file)
    if (knowledgeId) formData.append('knowledge_id', knowledgeId)
    const resp = await request.post<ApiResponse<UploadFileData>>('/knowledge/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    if (resp.data.status_code === 200) return resp.data.data
    throw new Error(resp.data.status_message)
  },

  /** 查询文件解析状态 */
  async getFileState(fileId: string): Promise<FileStateData> {
    const resp = await request.get<ApiResponse<FileStateData>>('/knowledge/file_state', {
      params: { file_id: fileId },
    })
    if (resp.data.status_code === 200) return resp.data.data
    throw new Error(resp.data.status_message)
  },

  /** 获取知识库下的文件列表 */
  async getFileList(
    knowledgeId: string,
    pageNum = 1,
    pageSize = 50
  ): Promise<{ items: KnowledgeFileItem[]; total: number }> {
    const resp = await request.get<ApiResponse<{ items: KnowledgeFileItem[]; total: number }>>(
      '/knowledge/file_list',
      { params: { knowledge_id: knowledgeId, page_num: pageNum, page_size: pageSize } }
    )
    if (resp.data.status_code === 200) return resp.data.data
    throw new Error(resp.data.status_message)
  },

  /** 获取文件分块详情 */
  async getFileChunks(fileId: string, knowledgeId: string): Promise<string[]> {
    const resp = await request.get<ApiResponse<string[]>>('/knowledge/get_file_chunks', {
      params: { file_id: fileId, knowledge_id: knowledgeId },
    })
    if (resp.data.status_code === 200) return resp.data.data
    throw new Error(resp.data.status_message)
  },

  /** 删除知识库文件 */
  async deleteFile(fileId: string, knowledgeId: string): Promise<void> {
    const resp = await request.get<ApiResponse<null>>('/knowledge/delete_file', {
      params: { file_id: fileId, knowledge_id: knowledgeId },
    })
    if (resp.data.status_code !== 200) throw new Error(resp.data.status_message)
  },

  /** 删除知识库 */
  async deleteKnowledge(knowledgeId: string): Promise<void> {
    const resp = await request.post<ApiResponse<null>>('/kb/delete', {
      knowledge_id: knowledgeId,
    })
    if (resp.data.status_code !== 200) throw new Error(resp.data.status_message)
  },
}
