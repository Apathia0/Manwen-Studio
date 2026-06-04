import { get, post, put, del } from '@/utils/request'

/** 提示词模板项 */
export interface PromptTemplateItem {
  id: number
  name: string
  description: string
  author: { id: number; username: string } | null
  category: string | null
  tags: string[]
  status: string
  visibility: string
  is_public: boolean
  usage_count: number
  like_count: number
  is_liked?: boolean
  framework_prompt?: string | null
  chapter_prompt?: string | null
  character_prompt?: string | null
  manga_style_prompt?: string | null
  framework_params?: Record<string, string> | null
  chapter_params?: Record<string, string> | null
  character_params?: Record<string, string> | null
  manga_style_params?: Record<string, string> | null
  forked_from?: number | null
  submitted_at?: string | null
  reviewed_at?: string | null
  review_note?: string | null
  created_at: string
  updated_at: string
}

/** 模板列表响应 */
export interface TemplateListResponse {
  templates: PromptTemplateItem[]
  total: number
  page: number
  page_size: number
}

/** 系统默认提示词 */
export interface SystemDefaultPrompts {
  framework: string
  chapter: string
  character: string
  manga_style: string
}

/** 创建模板 */
export function createPromptTemplate(data: {
  name: string
  description?: string
  category?: string
  tags?: string[]
  framework_prompt?: string | null
  chapter_prompt?: string | null
  character_prompt?: string | null
  manga_style_prompt?: string | null
  framework_params?: Record<string, string> | null
  chapter_params?: Record<string, string> | null
  character_params?: Record<string, string> | null
  manga_style_params?: Record<string, string> | null
}): Promise<PromptTemplateItem> {
  return post('/api/prompt-templates', data)
}

/** 获取我的模板列表 */
export function listMyTemplates(params?: {
  page?: number
  page_size?: number
  status?: string
}): Promise<TemplateListResponse> {
  return get('/api/prompt-templates/my', params)
}

/** 获取模板详情 */
export function getPromptTemplate(id: number): Promise<PromptTemplateItem> {
  return get(`/api/prompt-templates/${id}`)
}

/** 更新模板 */
export function updatePromptTemplate(id: number, data: Record<string, unknown>): Promise<PromptTemplateItem> {
  return put(`/api/prompt-templates/${id}`, data)
}

/** 删除模板 */
export function deletePromptTemplate(id: number): Promise<void> {
  return del(`/api/prompt-templates/${id}`)
}

/** 提交模板审核 */
export function submitTemplateForReview(id: number): Promise<PromptTemplateItem> {
  return post(`/api/prompt-templates/${id}/submit-for-review`)
}

/** 复制模板（Fork） */
export function forkPromptTemplate(id: number): Promise<PromptTemplateItem> {
  return post(`/api/prompt-templates/${id}/fork`)
}

/** 获取公开模板列表（模板广场） */
export function listPublicTemplates(params?: {
  page?: number
  page_size?: number
  sort?: string
}): Promise<TemplateListResponse> {
  return get('/api/prompt-templates/public', params)
}

/** 点赞模板 */
export function likeTemplate(id: number): Promise<{ like_count: number; is_liked: boolean }> {
  return post(`/api/prompt-templates/${id}/like`)
}

/** 取消点赞 */
export function unlikeTemplate(id: number): Promise<{ like_count: number; is_liked: boolean }> {
  return del(`/api/prompt-templates/${id}/like`)
}

/** 绑定模板到故事 */
export function bindStoryTemplate(storyId: number, templateId: number): Promise<void> {
  return post(`/api/stories/${storyId}/bind-template`, { template_id: templateId })
}

/** 获取故事绑定的模板 */
export function getStoryTemplate(storyId: number): Promise<{ template: PromptTemplateItem | null }> {
  return get(`/api/stories/${storyId}/template`)
}

/** 解绑故事模板 */
export function unbindStoryTemplate(storyId: number): Promise<void> {
  return del(`/api/stories/${storyId}/template`)
}

/** 获取系统默认提示词 */
export function getSystemDefaultPrompts(): Promise<SystemDefaultPrompts> {
  return get('/api/prompt-templates/defaults')
}
