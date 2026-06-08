import { get, post, put, del } from '@/utils/request'

// ─── 管理员 API ─────────────────────────────────

// --- 套餐管理 ---

export interface AdminPlan {
  id: number
  code: string
  name: string
  description?: string
  monthly_price: number
  yearly_price?: number | null
  currency: string
  is_visible: boolean
  is_recommended: boolean
}

export interface AdminFeatureCatalogItem {
  key: string
  name: string
  description: string
  category: string
  value_type: 'number' | 'boolean' | 'text'
  default_rule?: { reset_period: string; deduct_mode: string }
}

export interface AdminFeatureItem {
  feature_key: string
  value: any
}

export interface AdminQuotaRule {
  feature_key: string
  reset_period: string
  deduct_mode: string
  extra_config: Record<string, any>
}

/** 获取所有套餐 */
export function getAdminPlans(): Promise<AdminPlan[]> {
  return get('/api/admin/plans')
}

/** 创建套餐 */
export function createAdminPlan(data: {
  code: string
  name: string
  description?: string
  monthly_price?: number
  yearly_price?: number
  currency?: string
}): Promise<void> {
  return post('/api/admin/plans', data)
}

/** 更新套餐 */
export function updateAdminPlan(planId: number, data: Partial<AdminPlan>): Promise<void> {
  return put(`/api/admin/plans/${planId}`, data)
}

/** 删除套餐 */
export function deleteAdminPlan(planId: number): Promise<void> {
  return del(`/api/admin/plans/${planId}`)
}

/** 获取功能目录 */
export function getAdminFeatureCatalog(): Promise<AdminFeatureCatalogItem[]> {
  return get('/api/admin/feature-catalog')
}

/** 获取套餐功能配置 */
export function getAdminPlanFeatures(planId: number): Promise<AdminFeatureItem[]> {
  return get(`/api/admin/plans/${planId}/features`)
}

/** 保存套餐功能配置 */
export function saveAdminPlanFeatures(planId: number, items: AdminFeatureItem[]): Promise<void> {
  return put(`/api/admin/plans/${planId}/features`, items)
}

/** 获取套餐配额规则 */
export function getAdminQuotaRules(planId: number): Promise<AdminQuotaRule[]> {
  return get(`/api/admin/plans/${planId}/quota-rules`)
}

/** 保存套餐配额规则 */
export function saveAdminQuotaRules(planId: number, items: AdminQuotaRule[]): Promise<void> {
  return put(`/api/admin/plans/${planId}/quota-rules`, items)
}

// --- 用户管理 ---

export interface AdminUserItem {
  id: number
  name: string
  email: string
  role: 'user' | 'admin'
  status: 'active' | 'disabled'
  allow_api_key_override?: boolean
  allow_api_url_override?: boolean
  created_at: string
  plan_name: string
}

export interface AdminUserEntitlements {
  user: AdminUserItem
  subscription: {
    status: string
    billing_cycle?: string
    current_period_start?: string | null
    current_period_end?: string | null
    expires_at?: string | null
  }
  plan: { id: number; code: string; name: string }
  entitlements: Record<string, any>
  usage: AdminUsageItem[]
}

export interface AdminUsageItem {
  feature_key: string
  base_limit: number
  granted: number
  limit: number
  used: number
  remaining: number
}

/** 获取所有用户 */
export function getAdminUsers(): Promise<AdminUserItem[]> {
  return get('/api/admin/users')
}

/** 创建用户 */
export function createAdminUser(data: {
  name: string
  email: string
  password: string
  role?: string
  allow_api_key_override?: boolean
  allow_api_url_override?: boolean
}): Promise<void> {
  return post('/api/admin/users', data)
}

/** 更新用户 */
export function updateAdminUser(userId: number, data: Partial<AdminUserItem & { password: string }>): Promise<void> {
  return put(`/api/admin/users/${userId}`, data)
}

/** 删除/停用用户 */
export function deleteAdminUser(userId: number): Promise<void> {
  return del(`/api/admin/users/${userId}`)
}

/** 获取用户权益详情 */
export function getAdminUserEntitlements(userId: number): Promise<AdminUserEntitlements> {
  return get(`/api/admin/users/${userId}/entitlements`)
}

/** 更新用户订阅 */
export function adminUpdateUserSubscription(userId: number, planId: number): Promise<void> {
  return post(`/api/admin/users/${userId}/subscription`, { plan_id: planId })
}

/** 补发用户额度 */
export function adminGrantUserQuota(userId: number, featureKey: string, amount: number): Promise<{
  ok: boolean
  feature_key: string
  granted_amount: number
  before_granted: number
  after_granted: number
  usage: AdminUsageItem[]
}> {
  return post(`/api/admin/users/${userId}/quota-grants`, { feature_key: featureKey, amount })
}

// --- 内容审核 ---

export interface AdminReviewStory {
  id: number
  title: string
  description?: string
  cover_image?: string | null
  created_at: string
  chapter_count: number
}

export interface AdminReviewChapter {
  id: number
  chapter_number: number
  title: string
  status?: string | null
  word_count?: number | null
  created_at: string
  novel_content: string
}

export interface AdminReviewStoryChaptersResponse {
  story: { id: number; title: string; description?: string; created_at: string; owner_user_id?: number | null }
  chapters: AdminReviewChapter[]
}

/** 获取用户的作品列表 */
export function getAdminUserStories(userId: number): Promise<AdminReviewStory[]> {
  return get(`/api/admin/users/${userId}/stories`)
}

/** 获取作品的章节列表 */
export function getAdminStoryChapters(storyId: number): Promise<AdminReviewStoryChaptersResponse> {
  return get(`/api/admin/stories/${storyId}/chapters`)
}

// --- 订单管理 ---

export interface AdminOrderItem {
  order_no: string
  user_id: number
  user_name?: string | null
  plan_id: number
  plan_name?: string | null
  amount: number
  currency: string
  status: string
  source?: string
  billing_cycle?: string
  payment_provider?: string
  payment_method?: string
  operator?: { id: number | null; name: string; email?: string } | null
  note?: string
  extra?: Record<string, any>
  paid_at?: string | null
  expired_at?: string | null
  created_at: string
}

/** 获取所有订单 */
export function getAdminOrders(): Promise<AdminOrderItem[]> {
  return get('/api/admin/orders')
}

/** 更新订单状态 */
export function updateAdminOrderStatus(orderNo: string, status: 'paid' | 'cancelled' | 'expired', note = ''): Promise<{ ok: boolean; order: AdminOrderItem }> {
  return post(`/api/admin/orders/${orderNo}/status`, { status, note })
}

// --- 审计日志 ---

export interface AdminAuditLogItem {
  id: number
  actor_user_id: number | null
  actor_name: string | null
  action: string
  target_type: string
  target_id: string | null
  summary: string | null
  detail: Record<string, any>
  created_at: string
}

/** 获取审计日志 */
export function getAdminAuditLogs(params?: {
  action?: string
  limit?: number
}): Promise<AdminAuditLogItem[]> {
  return get('/api/admin/audit-logs', params)
}

// --- 平台设置 ---

export interface PlatformSettings {
  basic: {
    site_name: string
    site_slogan: string
    support_email: string
    icp: string
    copyright: string
    notice: string
    icon_url: string
    icon_data?: string
    icon_mime?: string
    clear_icon?: boolean
  }
  api: {
    deepseek_base_url: string
    deepseek_model: string
    deepseek_api_key: string
    image_base_url: string
    image_model: string
    image_api_key: string
    image_size: string
    image_quality: string
    image_background: string
    image_moderation: string
    image_output_format: string
    image_output_compression: string
    image_input_fidelity: string
    enable_user_override: boolean
    enable_user_url_override?: boolean
  }
  auth: {
    require_email_code_for_register: boolean
    require_email_code_for_login: boolean
    email_code_expire_minutes: number
    email_code_length: number
  }
  email: {
    smtp_enabled: boolean
    smtp_host: string
    smtp_port: number
    smtp_username: string
    smtp_password: string
    smtp_from_email: string
    smtp_from_name: string
    smtp_use_tls: boolean
    smtp_use_ssl: boolean
  }
  payment: Record<string, any>
}

/** 获取平台设置 */
export function getAdminPlatformSettings(): Promise<PlatformSettings> {
  return get('/api/admin/platform/settings')
}

/** 更新平台设置 */
export function updateAdminPlatformSettings(settings: PlatformSettings): Promise<PlatformSettings> {
  return put('/api/admin/platform/settings', settings)
}

// --- 公告管理 ---

export interface PlatformAnnouncement {
  enabled: boolean
  title: string
  content: string
}

/** 获取公告 */
export function getAdminAnnouncement(): Promise<PlatformAnnouncement> {
  return get('/api/admin/platform/announcement')
}

/** 更新公告 */
export function updateAdminAnnouncement(data: PlatformAnnouncement): Promise<{ ok: boolean; announcement: PlatformAnnouncement }> {
  return put('/api/admin/platform/announcement', data)
}

// --- 模板审核 ---

import type { PromptTemplateItem, TemplateListResponse } from './templates'

export type { PromptTemplateItem, TemplateListResponse }

/** 获取待审核模板 */
export function listPendingTemplates(page = 1, pageSize = 50): Promise<TemplateListResponse> {
  return get('/api/admin/prompt-templates/pending', { page, page_size: pageSize })
}

/** 通过模板 */
export function approveTemplate(id: number, visibility: string, note?: string): Promise<PromptTemplateItem> {
  return post(`/api/admin/prompt-templates/${id}/approve`, { visibility, note })
}

/** 拒绝模板 */
export function rejectTemplate(id: number, note: string): Promise<PromptTemplateItem> {
  return post(`/api/admin/prompt-templates/${id}/reject`, { note })
}
