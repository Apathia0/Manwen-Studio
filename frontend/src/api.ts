const BASE = '';
const API_TOKEN = import.meta.env.VITE_API_TOKEN as string | undefined;
export const DEEPSEEK_USAGE_URL = 'https://platform.deepseek.com/usage';
export const IMAGE2_CONSOLE_URL = 'https://api.xbyjs.top/console/token';

export interface ApiKeySettings {
  deepseekApiKey: string;
  deepseekBaseUrl: string;
  deepseekModel: string;
  imageApiKey: string;
  imageBaseUrl: string;
  imageModel: string;
}

// Stored in localStorage so multiple tabs share the same API key settings.
const LS_DEEPSEEK_API_KEY = 'lorevista.deepseekApiKey';
const LS_DEEPSEEK_BASE_URL = 'lorevista.deepseekBaseUrl';
const LS_DEEPSEEK_MODEL = 'lorevista.deepseekModel';
const LS_IMAGE_API_KEY = 'lorevista.imageApiKey';
const LS_IMAGE_BASE_URL = 'lorevista.imageBaseUrl';
const LS_IMAGE_MODEL = 'lorevista.imageModel';
const LS_AUTH_TOKEN = 'lorevista.authToken';
export const API_KEY_CHANGE_EVENT = 'lorevista:api-key-change';
export const AUTH_CHANGE_EVENT = 'lorevista:auth-change';

export type UserRole = 'user' | 'admin';

export interface AuthUser {
  id: number;
  name: string;
  email: string;
  role: UserRole;
  can_override_api_key?: boolean;
  can_override_api_url?: boolean;
}

export interface AuthSession {
  token: string;
  user: AuthUser;
}

export function getApiKeySettings(): ApiKeySettings {
  return {
    deepseekApiKey: localStorage.getItem(LS_DEEPSEEK_API_KEY) || '',
    deepseekBaseUrl: localStorage.getItem(LS_DEEPSEEK_BASE_URL) || '',
    deepseekModel: localStorage.getItem(LS_DEEPSEEK_MODEL) || '',
    imageApiKey: localStorage.getItem(LS_IMAGE_API_KEY) || '',
    imageBaseUrl: localStorage.getItem(LS_IMAGE_BASE_URL) || '',
    imageModel: localStorage.getItem(LS_IMAGE_MODEL) || '',
  };
}

export function saveApiKeySettings(settings: ApiKeySettings): void {
  const deepseek = settings.deepseekApiKey.trim();
  const deepseekBaseUrl = settings.deepseekBaseUrl.trim();
  const deepseekModel = settings.deepseekModel.trim();
  const image = settings.imageApiKey.trim();
  const imageBaseUrl = settings.imageBaseUrl.trim();
  const imageModel = settings.imageModel.trim();
  if (deepseek) localStorage.setItem(LS_DEEPSEEK_API_KEY, deepseek);
  else localStorage.removeItem(LS_DEEPSEEK_API_KEY);
  if (deepseekBaseUrl) localStorage.setItem(LS_DEEPSEEK_BASE_URL, deepseekBaseUrl);
  else localStorage.removeItem(LS_DEEPSEEK_BASE_URL);
  if (deepseekModel) localStorage.setItem(LS_DEEPSEEK_MODEL, deepseekModel);
  else localStorage.removeItem(LS_DEEPSEEK_MODEL);
  if (image) localStorage.setItem(LS_IMAGE_API_KEY, image);
  else localStorage.removeItem(LS_IMAGE_API_KEY);
  if (imageBaseUrl) localStorage.setItem(LS_IMAGE_BASE_URL, imageBaseUrl);
  else localStorage.removeItem(LS_IMAGE_BASE_URL);
  if (imageModel) localStorage.setItem(LS_IMAGE_MODEL, imageModel);
  else localStorage.removeItem(LS_IMAGE_MODEL);
  // Notify same-tab listeners. Other tabs receive the browser 'storage' event.
  try {
    window.dispatchEvent(new Event(API_KEY_CHANGE_EVENT));
  } catch {
    // SSR / non-browser environment — ignore.
  }
}

export function clearApiKeySettings(): void {
  saveApiKeySettings({
    deepseekApiKey: '',
    deepseekBaseUrl: '',
    deepseekModel: '',
    imageApiKey: '',
    imageBaseUrl: '',
    imageModel: '',
  });
}

export function apiHeaders(json = false): HeadersInit {
  const keys = getApiKeySettings();
  const token = getAuthToken();
  return {
    ...(json ? { 'Content-Type': 'application/json' } : {}),
    ...(API_TOKEN ? { 'X-API-Token': API_TOKEN } : {}),
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(keys.deepseekApiKey ? { 'X-DeepSeek-API-Key': keys.deepseekApiKey } : {}),
    ...(keys.deepseekBaseUrl ? { 'X-DeepSeek-Base-URL': keys.deepseekBaseUrl } : {}),
    ...(keys.deepseekModel ? { 'X-DeepSeek-Model': keys.deepseekModel } : {}),
    ...(keys.imageApiKey ? { 'X-Image-API-Key': keys.imageApiKey } : {}),
    ...(keys.imageBaseUrl ? { 'X-Image-Base-URL': keys.imageBaseUrl } : {}),
    ...(keys.imageModel ? { 'X-Image-Model': keys.imageModel } : {}),
  };
}

async function readErrorMessage(res: Response, fallback: string): Promise<string> {
  const text = await res.text();
  if (!text) return fallback;
  try {
    const parsed = JSON.parse(text);
    if (typeof parsed?.detail === 'string' && parsed.detail.trim()) return parsed.detail.trim();
    if (typeof parsed?.message === 'string' && parsed.message.trim()) return parsed.message.trim();
  } catch {
    // Fall through to plain text handling.
  }
  return text.trim() || fallback;
}

export function getAuthToken(): string {
  return localStorage.getItem(LS_AUTH_TOKEN) || '';
}

export function setAuthToken(token: string): void {
  if (token) localStorage.setItem(LS_AUTH_TOKEN, token);
  else localStorage.removeItem(LS_AUTH_TOKEN);
  try {
    window.dispatchEvent(new Event(AUTH_CHANGE_EVENT));
  } catch {
    // ignore for non-browser
  }
}

export function clearAuthToken(): void {
  setAuthToken('');
}

// ─── InkAI Framework Types ──────────────────────────────────

export interface Tags {
  type?: string;
  theme?: string;
  style?: string;
  audience?: string;
}

export interface BigFiveScores {
  O?: number;
  C?: number;
  E?: number;
  A?: number;
  N?: number;
  openness?: number;
  conscientiousness?: number;
  extraversion?: number;
  agreeableness?: number;
  neuroticism?: number;
}

export interface Character {
  name?: string;
  role?: string;
  big_five?: BigFiveScores;
  arc?: Record<string, any>;
  relationships?: Record<string, any>[];
}

export interface Outline {
  three_acts?: Record<string, any>[];
  themes?: string[];
  foreshadowing?: Record<string, any>[];
}

export interface QualityScore {
  content?: number;
  writing?: number;
  character?: number;
  plot?: number;
  overall?: number;
}

export interface FrameworkGenerateResponse {
  tags?: Tags;
  characters?: Character[];
  outline?: Outline;
  chapters?: FrameworkChapterPlan[];
}

export interface ImportChapterInfo {
  chapter_number: number;
  title: string;
  content: string;
  detection_method?: string;
}

export interface ImportParseResponse {
  detected_title: string;
  chapters: ImportChapterInfo[];
  total_word_count?: number;
}

export interface ImportCreateRequest {
  title: string;
  chapters: ImportChapterInfo[];
  analyze_framework?: boolean;
}

export interface FrameworkAnalyzeResponse {
  tags?: Tags;
  characters?: Character[];
  outline?: Outline;
  chapters?: FrameworkChapterPlan[];
}

export interface FrameworkChapterPlan {
  act: string;
  chapter_number: number;
  title: string;
  summary?: string;
  key_events?: string[];
  goal?: string;
  conflict?: string;
  hook?: string;
  payoff?: string;
  highlight?: string;
}

export interface OutlineChapterPlanInput {
  title: string;
  summary?: string;
  key_events?: string[];
  act?: string;
  goal?: string;
  conflict?: string;
  hook?: string;
  payoff?: string;
  highlight?: string;
}

export interface FrameworkChatMessage {
  role: 'user' | 'assistant';
  content: string;
}

export interface FrameworkAdjustResponse {
  reply: string;
  story: {
    description?: string;
    tags?: Tags;
    characters?: Character[];
    outline?: Outline;
  };
  chapters?: FrameworkChapterPlan[];
  applied_operations?: string[];
  warnings?: string[];
  validation_errors?: string[];
}

export interface FrameworkContinueResponse extends FrameworkAdjustResponse {}

// ─── 框架快照 ─────────────────────────────────────────

export interface FrameworkSnapshotItem {
  id: number;
  source: string;
  reply_summary: string;
  created_at: string;
}

export interface FrameworkSnapshotListResponse {
  snapshots: FrameworkSnapshotItem[];
}

export interface FrameworkRestoreResponse {
  story: {
    description?: string;
    tags?: Tags;
    characters?: Character[];
    outline?: Outline;
  };
  snapshot_data: {
    description: string;
    tags: Tags;
    characters: Character[];
    outline: Outline;
  };
  message: string;
}

// ─── Onboarding / Story Bible ─────────────────────────────

export interface OnboardingChatMessage {
  role: 'user' | 'assistant';
  content: string;
}

export interface OnboardingMessageOut {
  reply: string;
  collected_info: Record<string, string>;
  step: number;
  total_steps: number;
  is_complete: boolean;
  creative_brief?: Record<string, any>;
}

export interface CreativeBrief {
  project_positioning: string;
  genre: string;
  audience: string;
  tone: string;
  core_hook: string;
  one_line_premise: string;
  protagonist_core: string;
  main_conflict: string;
  longline_mystery: string;
  serial_length_target: string;
  must_keep_rules: string[];
  reveal_strategy: string;
  pacing_strategy: string;
}

export interface StoryBible {
  raw_input?: {
    raw_idea: string;
    raw_length_goal: string;
    raw_must_keep: string;
    raw_hidden_setting: string;
    raw_notes: string;
  };
  creative_brief?: CreativeBrief;
  writing_guidance?: {
    opening_strategy: string;
    chapter_density_strategy: string;
    midgame_engine: string;
    late_game_direction: string;
    forbidden_patterns: string[];
    preferred_plot_patterns: string[];
  };
  import_guidance?: {
    context_source?: string;
    import_material_type?: string;
    must_keep?: string;
    author_goal?: string;
    adjustment_scope?: string;
    longline_plan?: string;
    tone_guardrails?: string;
  };
}

export interface OnboardingConfirmResponse {
  story_id: number;
  story_bible: StoryBible;
  creative_brief: CreativeBrief;
}

export interface Story {
  id: number;
  title: string;
  description?: string;
  cover_image?: string | null;
  has_character_profiles?: boolean;
  has_ref_image?: boolean;
  tags?: Tags;
  outline?: Outline;
  characters?: Character[];
  story_bible?: StoryBible;
  story_memory?: Record<string, any> | null;
  onboarding_completed?: boolean;
  source_type?: 'manual' | 'import' | string;
  import_context_completed?: boolean;
  created_at: string;
}

export interface AdminReviewStory {
  id: number;
  title: string;
  description?: string;
  cover_image?: string | null;
  created_at: string;
  chapter_count: number;
}

export interface AdminReviewChapter {
  id: number;
  chapter_number: number;
  title: string;
  status?: string | null;
  word_count?: number | null;
  created_at: string;
  novel_content: string;
}

export interface AdminReviewStoryChaptersResponse {
  story: {
    id: number;
    title: string;
    description?: string;
    created_at: string;
    owner_user_id?: number | null;
  };
  chapters: AdminReviewChapter[];
}

export interface ChatMessage {
  id: number;
  chapter_id: number;
  role: string;
  content: string;
  created_at: string;
}

export interface AgentConversationMessage {
  id: number;
  conversation_id: number;
  role: 'user' | 'assistant';
  content: string;
  created_at: string;
}

export interface AgentConversationSummary {
  id: number;
  story_id: number;
  chapter_id?: number | null;
  title: string;
  last_message_preview: string;
  message_count: number;
  created_at: string;
  updated_at: string;
}

export interface AgentConversation {
  id: number;
  story_id: number;
  chapter_id?: number | null;
  title: string;
  created_at: string;
  updated_at: string;
  messages: AgentConversationMessage[];
}

export interface MangaImage {
  id: number;
  chapter_id: number;
  image_number: number;
  image_path: string;
  prompt: string | null;
  created_at: string;
}

export interface Chapter {
  id: number;
  story_id: number;
  chapter_number: number;
  title?: string | null;
  novel_content: string | null;
  content_source?: 'chat' | 'import' | null;
  act?: string;
  key_events?: any[];
  quality_score?: QualityScore;
  memory_summary?: Record<string, any> | null;
  status?: string;
  word_count?: number;
  created_at: string;
  messages: ChatMessage[];
  images: MangaImage[];
}

export interface PublicPlan {
  id: number;
  code: string;
  name: string;
  description?: string;
  monthly_price: number;
  yearly_price?: number | null;
  currency: string;
  is_recommended: boolean;
  features: Record<string, any>;
}

export interface PaymentMethodOption {
  key: string;
  label: string;
  enabled: boolean;
  provider: string;
}

export interface PaymentSettings {
  enabled: boolean;
  mode: string;
  default_method: string;
  order_expire_minutes: number;
  auto_activate_free_plan?: boolean;
  instructions: string;
  methods: PaymentMethodOption[];
  mock_enabled?: boolean;
  wechat_enabled?: boolean;
  wechat_app_id?: string;
  wechat_mch_id?: string;
  wechat_notify_url?: string;
  alipay_enabled?: boolean;
  alipay_app_id?: string;
  alipay_pid?: string;
  alipay_gateway?: string;
  alipay_sign_type?: string;
  alipay_app_private_key?: string;
  alipay_public_key?: string;
  alipay_notify_url?: string;
}

export interface BillingCheckout {
  mode: string;
  method: string;
  provider: string;
  instructions: string;
  amount: number;
  currency: string;
  plan_name: string;
  billing_cycle: 'monthly' | 'yearly';
  expires_at: string;
  qr_code_text: string;
  payment_url: string;
  can_mock_confirm: boolean;
}

export interface UsageItem {
  feature_key: string;
  limit: number;
  used: number;
  remaining: number;
}

export interface UsageResponse {
  period_key: string;
  plan_code: string;
  items: UsageItem[];
}

export interface EntitlementResponse {
  plan: { id: number; code: string; name: string };
  entitlements: Record<string, any>;
}

export interface SubscriptionSummary {
  status: string;
  billing_cycle?: 'monthly' | 'yearly' | string;
  current_period_start?: string | null;
  current_period_end?: string | null;
  expires_at?: string | null;
  plan: {
    id: number;
    code: string;
    name: string;
    monthly_price: number;
    yearly_price?: number | null;
    currency: string;
  };
}

export interface AdminPlan {
  id: number;
  code: string;
  name: string;
  description?: string;
  monthly_price: number;
  yearly_price?: number | null;
  currency: string;
  is_visible: boolean;
  is_recommended: boolean;
}

export interface AdminFeatureCatalogItem {
  key: string;
  name: string;
  description: string;
  category: string;
  value_type: 'number' | 'boolean' | 'text';
  default_rule?: {
    reset_period: string;
    deduct_mode: string;
  };
}

export interface AdminFeatureItem {
  feature_key: string;
  value: any;
}

export interface AdminQuotaRule {
  feature_key: string;
  reset_period: string;
  deduct_mode: string;
  extra_config: Record<string, any>;
}

export interface AdminOrderItem {
  order_no: string;
  user_id: number;
  user_name?: string | null;
  plan_id: number;
  plan_name?: string | null;
  amount: number;
  currency: string;
  status: string;
  source?: string;
  billing_cycle?: string;
  payment_provider?: string;
  payment_method?: string;
  operator?: {
    id: number | null;
    name: string;
    email?: string;
  } | null;
  note?: string;
  extra?: Record<string, any>;
  paid_at?: string | null;
  expired_at?: string | null;
  created_at: string;
}

export interface AdminAuditLogItem {
  id: number;
  actor_user_id: number | null;
  actor_name: string | null;
  action: string;
  target_type: string;
  target_id: string | null;
  summary: string | null;
  detail: Record<string, any>;
  created_at: string;
}

export interface AdminUserItem {
  id: number;
  name: string;
  email: string;
  role: UserRole;
  status: 'active' | 'disabled';
  allow_api_key_override?: boolean;
  allow_api_url_override?: boolean;
  created_at: string;
  plan_name: string;
}

export interface PlatformSettings {
  basic: {
    site_name: string;
    site_slogan: string;
    support_email: string;
    icp: string;
    copyright: string;
    notice: string;
    icon_url: string;
    icon_data?: string;
    icon_mime?: string;
    clear_icon?: boolean;
  };
  api: {
    deepseek_base_url: string;
    deepseek_model: string;
    deepseek_api_key: string;
    image_base_url: string;
    image_model: string;
    image_api_key: string;
    enable_user_override: boolean;
    enable_user_url_override?: boolean;
  };
  auth: {
    require_email_code_for_register: boolean;
    require_email_code_for_login: boolean;
    email_code_expire_minutes: number;
    email_code_length: number;
  };
  email: {
    smtp_enabled: boolean;
    smtp_host: string;
    smtp_port: number;
    smtp_username: string;
    smtp_password: string;
    smtp_from_email: string;
    smtp_from_name: string;
    smtp_use_tls: boolean;
    smtp_use_ssl: boolean;
  };
  payment: PaymentSettings;
}

export interface PublicPlatformSettings {
  site_name: string;
  site_slogan: string;
  support_email: string;
  icp: string;
  copyright: string;
  notice: string;
  icon_url: string;
  api?: {
    deepseek_base_url?: string;
    deepseek_model?: string;
    image_base_url?: string;
    image_model?: string;
  };
  auth?: {
    require_email_code_for_register?: boolean;
    require_email_code_for_login?: boolean;
    email_code_expire_minutes?: number;
  };
}

export interface MySubscriptionResponse {
  user: AuthUser;
  subscription: SubscriptionSummary;
  latest_order: AdminOrderItem | null;
}

export interface PlatformAnnouncement {
  enabled: boolean;
  title: string;
  content: string;
}

export async function sendEmailVerificationCode(payload: { email: string; purpose: 'register' | 'login' }): Promise<{ ok: boolean; expires_in_seconds: number }> {
  const res = await fetch(`${BASE}/api/auth/send-email-code`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '验证码发送失败，请稍后重试。'));
  return res.json();
}

export async function register(payload: { name: string; email: string; password: string; verification_code?: string }): Promise<AuthSession> {
  const res = await fetch(`${BASE}/api/auth/register`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '注册失败，请稍后重试。'));
  return res.json();
}

export async function login(payload: { email: string; password: string; verification_code?: string }): Promise<AuthSession> {
  const res = await fetch(`${BASE}/api/auth/login`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '登录失败，请检查账号或密码。'));
  return res.json();
}

export async function logout(): Promise<void> {
  const res = await fetch(`${BASE}/api/auth/logout`, { method: 'POST', headers: apiHeaders() });
  if (!res.ok) throw new Error(await res.text());
}

export async function me(): Promise<AuthUser> {
  const res = await fetch(`${BASE}/api/auth/me`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function changePassword(old_password: string, new_password: string): Promise<void> {
  const res = await fetch(`${BASE}/api/user/password`, {
    method: 'PUT',
    headers: apiHeaders(),
    body: JSON.stringify({ old_password, new_password }),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '密码修改失败'));
}

export async function sendResetEmailCode(email: string): Promise<{ ok: boolean; expires_in_seconds: number }> {
  const res = await fetch(`${BASE}/api/auth/forgot-password`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify({ email }),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '验证码发送失败，请稍后重试。'));
  return res.json();
}

export async function resetPassword(email: string, verification_code: string): Promise<{ ok: boolean; message: string }> {
  const res = await fetch(`${BASE}/api/auth/reset-password`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify({ email, verification_code }),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '密码重置失败'));
  return res.json();
}

export async function getPublicPlans(): Promise<PublicPlan[]> {
  const res = await fetch(`${BASE}/api/plans/public`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getMyUsage(): Promise<UsageResponse> {
  const res = await fetch(`${BASE}/api/me/usage`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getMyEntitlements(): Promise<EntitlementResponse> {
  const res = await fetch(`${BASE}/api/me/entitlements`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getMySubscription(): Promise<MySubscriptionResponse> {
  const res = await fetch(`${BASE}/api/me/subscription`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getMyOrders(): Promise<AdminOrderItem[]> {
  const res = await fetch(`${BASE}/api/me/orders`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function subscribePlan(planId: number, billingCycle: 'monthly' | 'yearly' = 'monthly'): Promise<{
  ok: boolean;
  message: string;
  status: string;
  subscription: SubscriptionSummary;
  order: AdminOrderItem;
  checkout: BillingCheckout;
}> {
  const res = await fetch(`${BASE}/api/billing/subscribe`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify({ plan_id: planId, billing_cycle: billingCycle }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function confirmMyOrderMock(orderNo: string): Promise<{
  ok: boolean;
  status: string;
  order: AdminOrderItem;
  subscription: SubscriptionSummary;
}> {
  const res = await fetch(`${BASE}/api/me/orders/${orderNo}/mock-confirm`, {
    method: 'POST',
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function cancelMyOrder(orderNo: string): Promise<{
  ok: boolean;
  status: string;
  order: AdminOrderItem;
}> {
  const res = await fetch(`${BASE}/api/me/orders/${orderNo}/cancel`, {
    method: 'POST',
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function syncMyOrder(orderNo: string): Promise<{
  ok: boolean;
  status: string;
  order: AdminOrderItem;
  subscription: SubscriptionSummary;
  checkout?: BillingCheckout | null;
}> {
  const res = await fetch(`${BASE}/api/me/orders/${orderNo}/sync`, {
    method: 'POST',
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getAdminPlans(): Promise<AdminPlan[]> {
  const res = await fetch(`${BASE}/api/admin/plans`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function createAdminPlan(payload: {
  code: string;
  name: string;
  description?: string;
  monthly_price?: number;
  yearly_price?: number;
  currency?: string;
  is_visible?: boolean;
  is_recommended?: boolean;
}): Promise<void> {
  const res = await fetch(`${BASE}/api/admin/plans`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await res.text());
}

export async function deleteAdminPlan(planId: number): Promise<void> {
  const res = await fetch(`${BASE}/api/admin/plans/${planId}`, {
    method: 'DELETE',
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(await res.text());
}

export async function getAdminFeatureCatalog(): Promise<AdminFeatureCatalogItem[]> {
  const res = await fetch(`${BASE}/api/admin/feature-catalog`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function updateAdminPlan(planId: number, payload: Partial<AdminPlan> & { description?: string }): Promise<void> {
  const res = await fetch(`${BASE}/api/admin/plans/${planId}`, {
    method: 'PUT',
    headers: apiHeaders(true),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await res.text());
}

export async function getAdminPlanFeatures(planId: number): Promise<AdminFeatureItem[]> {
  const res = await fetch(`${BASE}/api/admin/plans/${planId}/features`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function saveAdminPlanFeatures(planId: number, items: AdminFeatureItem[]): Promise<void> {
  const res = await fetch(`${BASE}/api/admin/plans/${planId}/features`, {
    method: 'PUT',
    headers: apiHeaders(true),
    body: JSON.stringify({ items }),
  });
  if (!res.ok) throw new Error(await res.text());
}

export async function getAdminQuotaRules(planId: number): Promise<AdminQuotaRule[]> {
  const res = await fetch(`${BASE}/api/admin/plans/${planId}/quota-rules`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function saveAdminQuotaRules(planId: number, items: AdminQuotaRule[]): Promise<void> {
  const res = await fetch(`${BASE}/api/admin/plans/${planId}/quota-rules`, {
    method: 'PUT',
    headers: apiHeaders(true),
    body: JSON.stringify({ items }),
  });
  if (!res.ok) throw new Error(await res.text());
}

export async function getAdminUserEntitlements(userId: number): Promise<{
  user: AuthUser;
  subscription: {
    status: string;
    billing_cycle?: string;
    current_period_start?: string | null;
    current_period_end?: string | null;
    expires_at?: string | null;
  };
  plan: { id: number; code: string; name: string };
  entitlements: Record<string, any>;
  usage: UsageItem[];
}> {
  const res = await fetch(`${BASE}/api/admin/users/${userId}/entitlements`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getAdminUserStories(userId: number): Promise<AdminReviewStory[]> {
  const res = await fetch(`${BASE}/api/admin/users/${userId}/stories`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getAdminStoryChapters(storyId: number): Promise<AdminReviewStoryChaptersResponse> {
  const res = await fetch(`${BASE}/api/admin/stories/${storyId}/chapters`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function adminUpdateUserSubscription(userId: number, planId: number): Promise<void> {
  const res = await fetch(`${BASE}/api/admin/users/${userId}/subscription`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify({ plan_id: planId }),
  });
  if (!res.ok) throw new Error(await res.text());
}

export async function adminGrantUserQuota(userId: number, featureKey: string, amount: number): Promise<{
  ok: boolean;
  feature_key: string;
  granted_amount: number;
  before_granted: number;
  after_granted: number;
  usage: UsageItem[];
}> {
  const res = await fetch(`${BASE}/api/admin/users/${userId}/quota-grants`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify({ feature_key: featureKey, amount }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getAdminOrders(): Promise<AdminOrderItem[]> {
  const res = await fetch(`${BASE}/api/admin/orders`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function updateAdminOrderStatus(
  orderNo: string,
  status: 'paid' | 'cancelled' | 'expired',
  note = '',
): Promise<{ ok: boolean; order: AdminOrderItem }> {
  const res = await fetch(`${BASE}/api/admin/orders/${orderNo}/status`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify({ status, note }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getAdminAuditLogs(params?: {
  action?: string;
  actor_name?: string;
  target_type?: string;
  target_id?: string;
  limit?: number;
}): Promise<AdminAuditLogItem[]> {
  const query = new URLSearchParams();
  if (params?.action) query.set('action', params.action);
  if (params?.actor_name) query.set('actor_name', params.actor_name);
  if (params?.target_type) query.set('target_type', params.target_type);
  if (params?.target_id) query.set('target_id', params.target_id);
  if (params?.limit) query.set('limit', String(params.limit));
  const suffix = query.toString() ? `?${query.toString()}` : '';
  const res = await fetch(`${BASE}/api/admin/audit-logs${suffix}`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getAdminUsers(): Promise<AdminUserItem[]> {
  const res = await fetch(`${BASE}/api/admin/users`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function createAdminUser(payload: {
  name: string;
  email: string;
  password: string;
  role?: UserRole;
  allow_api_key_override?: boolean;
  allow_api_url_override?: boolean;
}): Promise<void> {
  const res = await fetch(`${BASE}/api/admin/users`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await res.text());
}

export async function updateAdminUser(
  userId: number,
  payload: Partial<{
    name: string;
    email: string;
    password: string;
    role: UserRole;
    status: 'active' | 'disabled';
    allow_api_key_override: boolean;
    allow_api_url_override: boolean;
  }>,
): Promise<void> {
  const res = await fetch(`${BASE}/api/admin/users/${userId}`, {
    method: 'PUT',
    headers: apiHeaders(true),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await res.text());
}

export async function deleteAdminUser(userId: number): Promise<void> {
  const res = await fetch(`${BASE}/api/admin/users/${userId}`, {
    method: 'DELETE',
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(await res.text());
}

export async function getAdminPlatformSettings(): Promise<PlatformSettings> {
  const res = await fetch(`${BASE}/api/admin/platform/settings`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function updateAdminPlatformSettings(payload: PlatformSettings): Promise<PlatformSettings> {
  const res = await fetch(`${BASE}/api/admin/platform/settings`, {
    method: 'PUT',
    headers: apiHeaders(true),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await res.text());
  const data = await res.json();
  return data.settings;
}

export async function getAdminAnnouncement(): Promise<PlatformAnnouncement> {
  const res = await fetch(`${BASE}/api/admin/platform/announcement`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function updateAdminAnnouncement(payload: PlatformAnnouncement): Promise<{ ok: boolean; announcement: PlatformAnnouncement }> {
  const res = await fetch(`${BASE}/api/admin/platform/announcement`, {
    method: 'PUT',
    headers: apiHeaders(true),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getPublicAnnouncement(): Promise<PlatformAnnouncement> {
  const res = await fetch(`${BASE}/api/platform/announcement`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getPublicPlatformSettings(): Promise<PublicPlatformSettings> {
  const res = await fetch(`${BASE}/api/platform/settings/public`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

// ─── Story ──────────────────────────────────────────────────

export async function createStory(title: string = '未命名故事', description: string = ''): Promise<Story> {
  const res = await fetch(`${BASE}/api/stories`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify({ title, description }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function listStories(): Promise<Story[]> {
  const res = await fetch(`${BASE}/api/stories`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getStory(storyId: number): Promise<Story> {
  const res = await fetch(`${BASE}/api/stories/${storyId}`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function updateStory(
  storyId: number,
  data: {
    title?: string;
    description?: string;
    tags?: Tags;
    outline?: Outline;
    characters?: Character[];
  },
): Promise<Story> {
  const res = await fetch(`${BASE}/api/stories/${storyId}`, {
    method: 'PUT',
    headers: apiHeaders(true),
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function deleteStory(storyId: number): Promise<void> {
  const res = await fetch(`${BASE}/api/stories/${storyId}`, { method: 'DELETE', headers: apiHeaders() });
  if (!res.ok) throw new Error(await res.text());
}

export async function uploadStoryCover(storyId: number, base64: string): Promise<string> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/upload-cover`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify({ image: base64 }),
  });
  if (!res.ok) throw new Error(await res.text());
  const data = await res.json();
  return data.cover_image;
}

export async function generateStoryCover(storyId: number, instruction: string = ''): Promise<{ cover_image: string; prompt: string }> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/generate-cover`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify({ instruction }),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '生成封面失败'));
  return res.json();
}

export async function adjustStoryCover(storyId: number, instruction: string): Promise<{ cover_image: string; prompt: string }> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/adjust-cover`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify({ instruction }),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '调整封面失败'));
  return res.json();
}

export function coverImageUrl(coverPath: string | null | undefined): string | null {
  if (!coverPath) return null;
  return `${BASE}/static/manga/${coverPath.replace('manga_outputs/', '')}`;
}

// ─── Chapter ────────────────────────────────────────────────

export async function getChapter(chapterId: number): Promise<Chapter> {
  const res = await fetch(`${BASE}/api/chapters/${chapterId}`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function listChapters(storyId: number): Promise<Chapter[]> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/chapters`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function createNextChapter(storyId: number): Promise<Chapter> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/chapters`, { method: 'POST', headers: apiHeaders() });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function deleteChapter(chapterId: number): Promise<void> {
  const res = await fetch(`${BASE}/api/chapters/${chapterId}`, { method: 'DELETE', headers: apiHeaders() });
  if (!res.ok) throw new Error(await res.text());
}

// ─── Chat (SSE) ─────────────────────────────────────────────

export function chatStream(
  chapterId: number,
  content: string,
  onToken: (token: string) => void,
  _onDone: (fullContent: string) => void,
  onError: (err: string) => void,
): AbortController {
  const controller = new AbortController();

  fetch(`${BASE}/api/chapters/${chapterId}/chat`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify({ content }),
    signal: controller.signal,
  })
    .then(async (res) => {
      if (!res.ok) {
        onError(await res.text());
        return;
      }
      const reader = res.body?.getReader();
      if (!reader) return;
      const decoder = new TextDecoder();
      let buffer = '';
      let currentEvent = 'message';
      const handleLine = (line: string) => {
        const trimmed = line.trim();
        if (!trimmed || trimmed.startsWith(':')) return;
        if (trimmed.startsWith('event:')) {
          currentEvent = trimmed.slice(6).trim();
        } else if (trimmed.startsWith('data:')) {
          const dataStr = trimmed.slice(5).trim();
          try {
            const data = JSON.parse(dataStr);
            if (currentEvent === 'token' && data.content !== undefined) {
              onToken(data.content);
            } else if (currentEvent === 'done' && data.content !== undefined) {
              _onDone(data.content);
            } else if (currentEvent === 'error' || data.error) {
              onError(data.error);
            }
          } catch {
            // ignore
          }
          currentEvent = 'message';
        }
      };

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          handleLine(line);
        }
      }
      if (buffer.trim()) handleLine(buffer);

      // If stream ended without a done event, call onDone with empty
      // This handles edge cases where connection closes unexpectedly
    })
    .catch((err) => {
      if (err.name !== 'AbortError') {
        onError(err.message);
      }
    });

  return controller;
}

// ─── Generate Novel ─────────────────────────────────────────

export async function generateNovel(chapterId: number): Promise<Chapter> {
  const res = await fetch(`${BASE}/api/chapters/${chapterId}/generate-novel`, {
    method: 'POST',
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function importNovel(chapterId: number, content: string): Promise<Chapter> {
  const res = await fetch(`${BASE}/api/chapters/${chapterId}/import-novel`, {
    method: 'POST',
    headers: { ...apiHeaders(), 'Content-Type': 'application/json' },
    body: JSON.stringify({ content }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function saveChapterContent(chapterId: number, content: string): Promise<Chapter> {
  const res = await fetch(`${BASE}/api/chapters/${chapterId}/content`, {
    method: 'PUT',
    headers: apiHeaders(true),
    body: JSON.stringify({ content }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function adjustChapterContent(chapterId: number, instruction: string): Promise<Chapter> {
  const res = await fetch(`${BASE}/api/chapters/${chapterId}/adjust-content`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify({ instruction }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function saveContinuityMemory(
  chapterId: number,
  data: { chapter_summary?: Record<string, any>; chapter_handoff?: Record<string, any> },
): Promise<Chapter> {
  const res = await fetch(`${BASE}/api/chapters/${chapterId}/continuity-memory`, {
    method: 'PATCH',
    headers: apiHeaders(true),
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

// ─── Scenes ─────────────────────────────────────────────────

export interface ScenesPayload {
  scenes: string[];
  sanitized_indices?: number[];
}

export async function generateScenes(chapterId: number, signal?: AbortSignal): Promise<ScenesPayload> {
  const res = await fetch(`${BASE}/api/chapters/${chapterId}/generate-scenes`, { method: 'POST', headers: apiHeaders(), signal });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getScenes(chapterId: number): Promise<ScenesPayload> {
  const res = await fetch(`${BASE}/api/chapters/${chapterId}/scenes`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function updateScenes(chapterId: number, scenes: string[]): Promise<void> {
  const res = await fetch(`${BASE}/api/chapters/${chapterId}/scenes`, {
    method: 'PUT',
    headers: apiHeaders(true),
    body: JSON.stringify({ scenes }),
  });
  if (!res.ok) throw new Error(await res.text());
}

// ─── Character Profiles ─────────────────────────────────────

// Story-level (global)
export async function getStoryCharacters(storyId: number): Promise<string> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/characters`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await res.text());
  const data = await res.json();
  return data.characters;
}

export async function saveStoryCharacters(storyId: number, characters: string): Promise<void> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/characters`, {
    method: 'PUT',
    headers: apiHeaders(true),
    body: JSON.stringify({ characters }),
  });
  if (!res.ok) throw new Error(await res.text());
}

// Chapter-level (with source info)
export async function getCharacters(chapterId: number): Promise<{ characters: string; source: 'chapter' | 'story' | 'none' }> {
  const res = await fetch(`${BASE}/api/chapters/${chapterId}/characters`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await res.text());
  return await res.json();
}

export async function saveCharacters(chapterId: number, characters: string): Promise<void> {
  const res = await fetch(`${BASE}/api/chapters/${chapterId}/characters`, {
    method: 'PUT',
    headers: apiHeaders(true),
    body: JSON.stringify({ characters }),
  });
  if (!res.ok) throw new Error(await res.text());
}

export async function resetChapterCharacters(chapterId: number): Promise<void> {
  const res = await fetch(`${BASE}/api/chapters/${chapterId}/characters`, {
    method: 'DELETE',
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(await res.text());
}

export async function generateStoryCharactersFromFramework(storyId: number): Promise<{ characters: string }> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/characters/generate`, {
    method: 'POST',
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(await res.text());
  return await res.json();
}

// ─── Reference Images (垫图，支持多图) ────────────────────────

export type RefSource = 'chapter' | 'story' | 'none';

export interface RefImage {
  filename: string;
  image_path: string;
  size_kb: number;
  label?: string;
  kind?: string;
}

export interface RefImagesPayload {
  images: RefImage[];
  max: number;
  source?: RefSource;
}

export type ImageRedrawMode = 'regenerate' | 'full' | 'partial';

export function refImageUrl(imagePath: string): string {
  return `${BASE}/static/manga/${imagePath.replace('manga_outputs/', '')}`;
}

// Story-level
export async function getStoryRefImages(storyId: number): Promise<RefImagesPayload> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/ref-images`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function addStoryRefImage(storyId: number, base64: string): Promise<RefImagesPayload> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/ref-images`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify({ image: base64 }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function deleteStoryRefImage(storyId: number, filename: string): Promise<RefImagesPayload> {
  const res = await fetch(
    `${BASE}/api/stories/${storyId}/ref-images/${encodeURIComponent(filename)}`,
    { method: 'DELETE', headers: apiHeaders() },
  );
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function redrawStoryRefImage(
  storyId: number,
  filename: string,
  data: { prompt: string; mode: ImageRedrawMode; mask?: string },
): Promise<RefImagesPayload> {
  const res = await fetch(
    `${BASE}/api/stories/${storyId}/ref-images/${encodeURIComponent(filename)}/redraw`,
    {
      method: 'POST',
      headers: apiHeaders(true),
      body: JSON.stringify(data),
    },
  );
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

// Chapter-level (with story fallback)
export async function getChapterRefImages(chapterId: number): Promise<RefImagesPayload> {
  const res = await fetch(`${BASE}/api/chapters/${chapterId}/ref-images`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function addChapterRefImage(chapterId: number, base64: string): Promise<RefImagesPayload> {
  const res = await fetch(`${BASE}/api/chapters/${chapterId}/ref-images`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify({ image: base64 }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function deleteChapterRefImage(chapterId: number, filename: string): Promise<RefImagesPayload> {
  const res = await fetch(
    `${BASE}/api/chapters/${chapterId}/ref-images/${encodeURIComponent(filename)}`,
    { method: 'DELETE', headers: apiHeaders() },
  );
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function redrawChapterRefImage(
  chapterId: number,
  filename: string,
  data: { prompt: string; mode: ImageRedrawMode; mask?: string },
): Promise<RefImagesPayload> {
  const res = await fetch(
    `${BASE}/api/chapters/${chapterId}/ref-images/${encodeURIComponent(filename)}/redraw`,
    {
      method: 'POST',
      headers: apiHeaders(true),
      body: JSON.stringify(data),
    },
  );
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

// ─── Color Mode ─────────────────────────────────────────────

export type ColorMode = 'bw' | 'color';

export async function getColorMode(chapterId: number): Promise<ColorMode> {
  const res = await fetch(`${BASE}/api/chapters/${chapterId}/color-mode`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await res.text());
  const data = await res.json();
  return data.color_mode || 'bw';
}

export async function setColorMode(chapterId: number, mode: ColorMode): Promise<void> {
  const res = await fetch(`${BASE}/api/chapters/${chapterId}/color-mode`, {
    method: 'PUT',
    headers: apiHeaders(true),
    body: JSON.stringify({ color_mode: mode }),
  });
  if (!res.ok) throw new Error(await res.text());
}

// ─── Image Count ─────────────────────────────────────────────

export const ALLOWED_IMAGE_COUNTS = [4, 6, 8, 10, 12, 15, 20] as const;

export async function getImageCount(chapterId: number): Promise<number> {
  const res = await fetch(`${BASE}/api/chapters/${chapterId}/image-count`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await res.text());
  const data = await res.json();
  return data.image_count || 10;
}

export async function setImageCount(chapterId: number, count: number): Promise<void> {
  const res = await fetch(`${BASE}/api/chapters/${chapterId}/image-count`, {
    method: 'PUT',
    headers: apiHeaders(true),
    body: JSON.stringify({ image_count: count }),
  });
  if (!res.ok) throw new Error(await res.text());
}

export async function regenerateImage(
  chapterId: number,
  imageNumber: number,
  prompt: string,
  options?: { mode?: ImageRedrawMode; mask?: string },
): Promise<{ id: number; image_number: number; image_path: string; prompt: string }> {
  const res = await fetch(`${BASE}/api/chapters/${chapterId}/regenerate-image/${imageNumber}`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify({ prompt, mode: options?.mode, mask: options?.mask }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

// ─── Generate Manga (SSE with progress) ─────────────────────

export interface MangaProgress {
  type: 'status' | 'scenes' | 'progress' | 'image' | 'done' | 'error';
  data: any;
}

export async function resetMangaImages(chapterId: number): Promise<void> {
  const res = await fetch(`${BASE}/api/chapters/${chapterId}/manga-images`, {
    method: 'DELETE',
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(await res.text());
}

export function generateMangaStream(
  chapterId: number,
  onEvent: (event: MangaProgress) => void,
): AbortController {
  const controller = new AbortController();

  fetch(`${BASE}/api/chapters/${chapterId}/generate-manga-stream`, {
    method: 'POST',
    headers: apiHeaders(),
    signal: controller.signal,
  })
    .then(async (res) => {
      if (!res.ok) {
        onEvent({ type: 'error', data: { error: await res.text() } });
        return;
      }
      const reader = res.body?.getReader();
      if (!reader) return;
      const decoder = new TextDecoder();
      let buffer = '';
      let currentEvent = 'message';
      const handleLine = (line: string) => {
        const trimmed = line.trim();
        if (!trimmed || trimmed.startsWith(':')) return;
        if (trimmed.startsWith('event:')) {
          currentEvent = trimmed.slice(6).trim();
        } else if (trimmed.startsWith('data:')) {
          const dataStr = trimmed.slice(5).trim();
          try {
            const data = JSON.parse(dataStr);
            const eventType = currentEvent as MangaProgress['type'];
            onEvent({ type: eventType, data });
          } catch {
            // ignore unparseable data
          }
          currentEvent = 'message';
        }
      };

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          handleLine(line);
        }
      }
      if (buffer.trim()) handleLine(buffer);
    })
    .catch((err) => {
      if (err.name !== 'AbortError') {
        onEvent({ type: 'error', data: { error: err.message } });
      }
    });

  return controller;
}

/** SSE 流式生成角色参考图，每生成一张即时回调 */
export type CharRefEvent =
  | { type: 'snapshot'; data: { images: RefImage[]; max: number; generated: string[]; skipped: string[] } }
  | { type: 'image'; data: { images: RefImage[]; max: number; generated: string[] } }
  | { type: 'done'; data: { images: RefImage[]; max: number; generated: string[]; skipped: string[] } }
  | { type: 'error'; data: { error: string } };

export function generateStoryCharRefStream(
  storyId: number,
  data: { character_name?: string; overwrite?: boolean },
  onEvent: (event: CharRefEvent) => void,
): AbortController {
  const controller = new AbortController();

  fetch(`${BASE}/api/stories/${storyId}/character-ref-images/generate`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify(data ?? {}),
    signal: controller.signal,
  })
    .then(async (res) => {
      if (!res.ok) {
        onEvent({ type: 'error', data: { error: await res.text() } });
        return;
      }
      const reader = res.body?.getReader();
      if (!reader) return;
      const decoder = new TextDecoder();
      let buffer = '';
      let currentEvent = 'message';
      const handleLine = (line: string) => {
        const trimmed = line.trim();
        if (!trimmed || trimmed.startsWith(':')) return;
        if (trimmed.startsWith('event:')) {
          currentEvent = trimmed.slice(6).trim();
        } else if (trimmed.startsWith('data:')) {
          const dataStr = trimmed.slice(5).trim();
          try {
            const parsed = JSON.parse(dataStr);
            const eventType = currentEvent as CharRefEvent['type'];
            onEvent({ type: eventType, data: parsed });
          } catch {
            // ignore unparseable data
          }
          currentEvent = 'message';
        }
      };

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';
        for (const line of lines) {
          handleLine(line);
        }
      }
      if (buffer.trim()) handleLine(buffer);
    })
    .catch((err) => {
      if (err.name !== 'AbortError') {
        onEvent({ type: 'error', data: { error: err.message } });
      }
    });

  return controller;
}

// ─── Onboarding / Story Bible ────────────────────────────────

export async function sendOnboardingMessage(
  storyId: number,
  messages: { role: string; content: string }[],
  collectedInfo: Record<string, string> = {},
  step = 1,
): Promise<OnboardingMessageOut> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/onboarding/message`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify({ messages, collected_info: collectedInfo, step }),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '引导对话失败'));
  return res.json();
}

export async function confirmOnboarding(
  storyId: number,
  collectedInfo: Record<string, string>,
  messages: { role: string; content: string }[],
): Promise<OnboardingConfirmResponse> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/onboarding/confirm`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify({ collected_info: collectedInfo, messages }),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '确认引导失败'));
  return res.json();
}

export async function skipOnboarding(storyId: number): Promise<{ story_id: number; onboarding_completed: boolean }> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/onboarding/skip`, {
    method: 'POST',
    headers: apiHeaders(true),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '跳过引导失败'));
  return res.json();
}

export async function sendImportGuidanceMessage(
  storyId: number,
  messages: { role: string; content: string }[],
  collectedInfo: Record<string, string> = {},
  step = 1,
): Promise<OnboardingMessageOut> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/import-context/message`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify({ messages, collected_info: collectedInfo, step }),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '导入补充对话失败'));
  return res.json();
}

export async function confirmImportGuidance(
  storyId: number,
  collectedInfo: Record<string, string>,
  messages: { role: string; content: string }[],
): Promise<OnboardingConfirmResponse> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/import-context/confirm`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify({ collected_info: collectedInfo, messages }),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '确认导入补充失败'));
  return res.json();
}

export async function skipImportGuidance(storyId: number): Promise<{ ok: true; story_id: number }> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/import-context/skip`, {
    method: 'POST',
    headers: apiHeaders(true),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '跳过导入补充失败'));
  return res.json();
}

export async function getStoryBible(storyId: number): Promise<{ story_bible: StoryBible }> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/story-bible`, {
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function updateStoryBible(storyId: number, storyBible: Partial<StoryBible>): Promise<{ story_bible: StoryBible }> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/story-bible`, {
    method: 'PATCH',
    headers: apiHeaders(true),
    body: JSON.stringify({ story_bible: storyBible }),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '更新作品圣经失败'));
  return res.json();
}

// ─── InkAI Framework ────────────────────────────────────────

export async function generateFramework(storyId: number, description: string): Promise<FrameworkGenerateResponse> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/framework/generate`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify({ description }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function parseImportFile(file: File): Promise<ImportParseResponse> {
  const formData = new FormData();
  formData.append('file', file);
  const res = await fetch(`${BASE}/api/import/parse`, {
    method: 'POST',
    headers: apiHeaders(),
    body: formData,
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '导入解析失败'));
  return res.json();
}

export async function createImportStory(payload: ImportCreateRequest): Promise<Story> {
  const res = await fetch(`${BASE}/api/import/create`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '导入创建失败'));
  return res.json();
}

export async function analyzeFramework(storyId: number): Promise<FrameworkAnalyzeResponse> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/framework/analyze`, {
    method: 'POST',
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '框架分析失败'));
  return res.json();
}

export async function regenerateTags(storyId: number): Promise<Tags> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/framework/tags`, {
    method: 'POST',
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(await res.text());
  const data = await res.json();
  return data.tags ?? data;
}

export async function regenerateCharacters(storyId: number): Promise<Character[]> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/framework/characters`, {
    method: 'POST',
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(await res.text());
  const data = await res.json();
  return data.characters ?? data;
}

export async function regenerateOutline(storyId: number): Promise<Outline> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/framework/outline`, {
    method: 'POST',
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(await res.text());
  const data = await res.json();
  return data.outline ?? data;
}

export async function saveOutlineChapterPlan(
  storyId: number,
  data:
    | { mode: 'append'; chapter: OutlineChapterPlanInput }
    | { mode: 'insert_after'; after_chapter_number: number; chapter: OutlineChapterPlanInput }
    | { mode: 'update'; target_chapter_number: number; chapter: OutlineChapterPlanInput },
): Promise<Outline> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/framework/chapters/manual`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(await res.text());
  const payload = await res.json();
  return payload.outline ?? payload;
}

export async function adjustFramework(
  storyId: number,
  messages: FrameworkChatMessage[],
): Promise<FrameworkAdjustResponse> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/framework/adjust`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify({ messages }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function listFrameworkSnapshots(
  storyId: number
): Promise<FrameworkSnapshotListResponse> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/framework/snapshots`, {
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(`获取快照列表失败: ${res.status}`);
  return res.json();
}

export async function restoreFrameworkSnapshot(
  storyId: number,
  snapshotId: number
): Promise<FrameworkRestoreResponse> {
  const res = await fetch(
    `${BASE}/api/stories/${storyId}/framework/snapshots/${snapshotId}/restore`,
    {
      method: 'POST',
      headers: apiHeaders(),
    }
  );
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `回滚失败: ${res.status}`);
  }
  return res.json();
}

export async function generateStoryCharacterRefImages(
  storyId: number,
  data?: { character_name?: string; overwrite?: boolean },
): Promise<RefImagesPayload & { generated?: string[]; skipped?: string[] }> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/character-ref-images/generate`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify(data ?? {}),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function continueFramework(storyId: number): Promise<FrameworkContinueResponse> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/framework/continue`, {
    method: 'POST',
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function expandChapter(
  storyId: number,
  data: {
    act: string;
    chapter_number: number;
    chapter_title: string;
    key_events?: string[];
    summary?: string;
    goal?: string;
    conflict?: string;
    hook?: string;
    payoff?: string;
    highlight?: string;
  },
): Promise<Chapter> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/expand-chapter`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function rewriteSelection(
  chapterId: number,
  selectedText: string,
  context?: string,
): Promise<string> {
  const res = await fetch(`${BASE}/api/chapters/${chapterId}/rewrite-selection`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify({ selected_text: selectedText, chapter_context: context }),
  });
  if (!res.ok) throw new Error(await res.text());
  const data = await res.json();
  return data.rewritten_text ?? data;
}

export async function assessQuality(chapterId: number): Promise<QualityScore> {
  const res = await fetch(`${BASE}/api/chapters/${chapterId}/quality-assess`, {
    method: 'POST',
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(await res.text());
  const data = await res.json();
  return data.scores ?? data;
}

export async function scenesFromSelection(
  chapterId: number,
  data: { selected_text: string; character_profiles?: any[]; page_count?: number },
): Promise<ScenesPayload & { page_count?: number }> {
  const res = await fetch(`${BASE}/api/chapters/${chapterId}/scenes-from-selection`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export function mangaImageUrl(imagePath: string, cacheBust?: number): string {
  // imagePath is like "manga_outputs/chapter_1/panel_01_abc12345.png"
  // Served at /static/manga/chapter_1/panel_01_abc12345.png
  const url = `${BASE}/static/manga/${imagePath.replace('manga_outputs/', '')}`;
  return cacheBust ? `${url}?t=${cacheBust}` : url;
}

export function agentChatStream(
  storyId: number,
  conversationId: number,
  content: string,
  chapterId?: number,
  callbacks?: {
    onToken?: (token: string) => void;
    onToolCall?: (toolCall: { id: string; name: string; args: any; status: 'running' }) => void;
    onToolResult?: (toolCall: { id: string; name: string; args: any; status: 'success' | 'error'; summary?: string }) => void;
    onDone?: (content: string, pendingChanges?: any[]) => void;
    onError?: (err: string) => void;
  },
): AbortController {
  const controller = new AbortController();
  const toolCalls = new Map<string, { id: string; name: string; args: any; status: 'running' | 'success' | 'error'; summary?: string }>();

  fetch(`${BASE}/api/stories/${storyId}/agent/chat`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify({ conversation_id: conversationId, content, chapter_id: chapterId }),
    signal: controller.signal,
  })
    .then(async (res) => {
      if (!res.ok) {
        callbacks?.onError?.(await res.text());
        return;
      }
      const reader = res.body?.getReader();
      if (!reader) return;
      const decoder = new TextDecoder();
      let buffer = '';
      let currentEvent = 'message';
      const handleLine = (line: string) => {
        const trimmed = line.trim();
        if (!trimmed || trimmed.startsWith(':')) return;
        if (trimmed.startsWith('event:')) {
          currentEvent = trimmed.slice(6).trim();
        } else if (trimmed.startsWith('data:')) {
          const dataStr = trimmed.slice(5).trim();
          try {
            const data = JSON.parse(dataStr);
            if (currentEvent === 'token' && data.content !== undefined) {
              callbacks?.onToken?.(data.content);
            } else if (currentEvent === 'tool_call') {
              const key = `${String(data.name || 'tool')}:${toolCalls.size}`;
              const toolCall = {
                id: key,
                name: String(data.name || 'tool'),
                args: data.arguments ?? data.args ?? {},
                status: 'running' as const,
              };
              toolCalls.set(key, toolCall);
              callbacks?.onToolCall?.(toolCall);
            } else if (currentEvent === 'tool_result') {
              const existingEntry = Array.from(toolCalls.values()).reverse().find(
                (item) => item.name === String(data.name || 'tool') && item.status === 'running',
              );
              const key = existingEntry?.id ?? `${String(data.name || 'tool')}:${toolCalls.size}`;
              const rawResult = data.result;
              let status: 'success' | 'error' = 'success';
              let summary = '';
              if (typeof rawResult === 'string') {
                summary = rawResult;
                try {
                  const parsed = JSON.parse(rawResult);
                  if (parsed && typeof parsed === 'object' && 'error' in parsed) {
                    status = 'error';
                    summary = String((parsed as { error?: unknown }).error || '执行失败');
                  }
                } catch {
                  // keep plain string summary
                }
              } else if (rawResult && typeof rawResult === 'object' && 'error' in rawResult) {
                status = 'error';
                summary = String((rawResult as { error?: unknown }).error || '执行失败');
              } else if (rawResult !== undefined) {
                summary = typeof rawResult === 'string' ? rawResult : JSON.stringify(rawResult);
              }
              const toolCall = {
                id: key,
                name: String(data.name || existingEntry?.name || 'tool'),
                args: existingEntry?.args ?? {},
                status,
                summary,
              };
              toolCalls.set(key, toolCall);
              callbacks?.onToolResult?.(toolCall);
            } else if (currentEvent === 'done') {
              callbacks?.onDone?.(data.content ?? '', data.pending_changes);
            } else if (currentEvent === 'error' || data.error) {
              callbacks?.onError?.(data.error);
            }
          } catch {
            // ignore
          }
          currentEvent = 'message';
        }
      };

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          handleLine(line);
        }
      }
      if (buffer.trim()) handleLine(buffer);
    })
    .catch((err) => {
      if (err.name !== 'AbortError') {
        callbacks?.onError?.(err.message);
      }
    });

  return controller;
}

export async function listAgentConversations(storyId: number): Promise<AgentConversationSummary[]> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/agent/conversations`, {
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '获取助手历史失败'));
  return res.json();
}

export async function createAgentConversation(
  storyId: number,
  data?: { title?: string; chapter_id?: number },
): Promise<AgentConversation> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/agent/conversations`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify(data ?? {}),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '创建助手对话失败'));
  return res.json();
}

export async function getAgentConversation(storyId: number, conversationId: number): Promise<AgentConversation> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/agent/conversations/${conversationId}`, {
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '获取助手对话失败'));
  return res.json();
}

export async function deleteAgentConversation(storyId: number, conversationId: number): Promise<void> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/agent/conversations/${conversationId}`, {
    method: 'DELETE',
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '删除助手对话失败'));
}

export async function agentConfirmChanges(storyId: number): Promise<void> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/agent/confirm`, {
    method: 'POST',
    headers: apiHeaders(true),
  });
  if (!res.ok) throw new Error(await res.text());
}

export async function agentRollbackChanges(storyId: number): Promise<void> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/agent/rollback`, {
    method: 'POST',
    headers: apiHeaders(true),
  });
  if (!res.ok) throw new Error(await res.text());
}
