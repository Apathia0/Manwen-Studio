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
    video_base_url: string
    video_model: string
    video_api_key: string
    video_provider?: string
    image_size: string
    image_quality: string
    image_background: string
    image_moderation: string
    image_output_format: string
    image_output_compression: string
    image_input_fidelity: string
    enable_user_override: boolean
    enable_user_url_override?: boolean
    oss_enabled?: boolean
    oss_access_key_id?: string
    oss_access_key_secret?: string
    oss_endpoint?: string
    oss_bucket?: string
    oss_public_url_base?: string
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

// --- 风格预设管理 ---

export interface VideoStylePreset {
  id: number
  name: string
  category: string
  image_url: string | null
  prompt_template: string | null
  image_style_params: Record<string, unknown> | null
  video_style_params: Record<string, unknown> | null
  sort_order: number
}

/** 获取风格预设列表 */
export function listStylePresets(): Promise<{ presets: VideoStylePreset[] }> {
  return get('/api/video-style-presets')
}

/** 创建风格预设 */
export function createStylePreset(data: {
  name: string
  category?: string
  image_url?: string | null
  prompt_template?: string
  image_style_params?: Record<string, unknown>
  video_style_params?: Record<string, unknown>
  sort_order?: number
}): Promise<VideoStylePreset> {
  return post('/api/video-style-presets', data)
}

/** 更新风格预设 */
export function updateStylePreset(presetId: number, data: {
  name?: string
  category?: string
  image_url?: string | null
  prompt_template?: string
  image_style_params?: Record<string, unknown>
  video_style_params?: Record<string, unknown>
  sort_order?: number
}): Promise<VideoStylePreset> {
  return put(`/api/video-style-presets/${presetId}`, data)
}

/** 删除风格预设 */
export function deleteStylePreset(presetId: number): Promise<void> {
  return del(`/api/video-style-presets/${presetId}`)
}

// --- 系统默认提示词管理 ---

export interface AdminSystemPrompt {
  key: string
  name: string
  content: string
}

export interface AdminSystemPromptsResponse {
  [shortKey: string]: AdminSystemPrompt
}

export interface AdminUpdateSystemPromptsResponse {
  updated: string[]
  prompts: AdminSystemPromptsResponse
}

export function getAdminSystemPrompts(): Promise<AdminSystemPromptsResponse> {
  return get('/api/admin/system-prompts')
}

export function updateAdminSystemPrompts(payload: Record<string, string>): Promise<AdminUpdateSystemPromptsResponse> {
  return put('/api/admin/system-prompts', payload)
}

// --- 系统更新 ---

export interface AdminSystemUpdateStatus {
  status: 'idle' | 'queued' | 'running' | 'succeeded' | 'failed' | 'unknown' | string
  message: string
  running: boolean
  target_version?: string | null
  current_version?: string
  started_at?: string | null
  finished_at?: string | null
  exit_code?: number | null
  log_tail: string[]
}

export interface AdminSystemUpdateCheck {
  configured: boolean
  current_version: string
  latest_version?: string | null
  update_available: boolean
  release_notes: string
  published_at?: string | null
  min_supported_version?: string | null
  channel?: string | null
  manifest_url?: string
  message: string
}

/** 获取系统更新状态 */
export function getAdminSystemUpdateStatus(): Promise<AdminSystemUpdateStatus> {
  return get('/api/admin/system/update/status')
}

/** 检测系统更新 */
export function checkAdminSystemUpdate(): Promise<AdminSystemUpdateCheck> {
  return get('/api/admin/system/update/check')
}

/** 启动系统更新 */
export function startAdminSystemUpdate(targetVersion?: string): Promise<AdminSystemUpdateStatus> {
  return post('/api/admin/system/update', targetVersion ? { target_version: targetVersion } : {})
}

// --- 收入与订单 ---

export interface AdminRevenueSummary {
  total_revenue: number
  total_orders: number
  paid_orders: number
  cancelled_orders: number
  expired_orders: number
  monthly_revenue: number
  monthly_orders: number
  monthly_paid_orders: number
  conversion_rate: number
  active_subscriptions: number
  monthly_new_users: number
}

export interface AdminRevenueMonthlyItem {
  period: string
  revenue: number
  orders: number
  paid: number
  cancelled: number
  expired: number
}

/** 获取收入汇总 */
export function getAdminRevenueSummary(): Promise<AdminRevenueSummary> {
  return get('/api/admin/revenue/summary')
}

/** 获取月度收入 */
export function getAdminRevenueMonthly(months = 12): Promise<AdminRevenueMonthlyItem[]> {
  return get('/api/admin/revenue/monthly', { months })
}

/** 搜索订单 */
export function searchAdminOrders(params: {
  page?: number
  page_size?: number
  status?: string
  start_date?: string
  end_date?: string
}): Promise<{ items: AdminOrderItem[]; total: number; page: number; page_size: number; total_pages: number }> {
  return get('/api/admin/orders/search', params)
}

// --- 视频资产管理 ---

export interface AdminAssetScopeResult {
  asset_id: number
  usage_scope: string
  inherit_to_next_shot: boolean
}

export interface AdminAssetPromoteResult {
  id: number
  usage_scope: string
  inherit_to_next_shot: boolean
  chapter_level_default: boolean
  story_level_default: boolean
}

/** 更新视频资产使用范围 */
export function updateAssetScope(
  assetId: number,
  payload: {
    usage_scope: string
    inherit_to_next_shot?: boolean
  }
): Promise<AdminAssetScopeResult> {
  return put(`/api/video-assets/${assetId}/scope`, payload)
}

/** 提升视频资产级别 */
export function promoteAsset(
  assetId: number,
  payload: {
    level: string
    inherit_to_next_shot?: boolean
  }
): Promise<AdminAssetPromoteResult> {
  return post(`/api/video-assets/${assetId}/promote`, payload)
}
