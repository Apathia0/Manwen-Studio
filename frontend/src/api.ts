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
const LS_DEEPSEEK_API_KEY = 'storycanvas.deepseekApiKey';
const LS_DEEPSEEK_BASE_URL = 'storycanvas.deepseekBaseUrl';
const LS_DEEPSEEK_MODEL = 'storycanvas.deepseekModel';
const LS_IMAGE_API_KEY = 'storycanvas.imageApiKey';
const LS_IMAGE_BASE_URL = 'storycanvas.imageBaseUrl';
const LS_IMAGE_MODEL = 'storycanvas.imageModel';
const LS_AUTH_TOKEN = 'storycanvas.authToken';
export const API_KEY_CHANGE_EVENT = 'storycanvas:api-key-change';
export const AUTH_CHANGE_EVENT = 'storycanvas:auth-change';

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

export interface InstallStatus {
  installed: boolean;
  source: string;
  database_reachable?: boolean | null;
  database_error?: string | null;
  requires_restart?: boolean;
}

export interface InstallDatabaseConfig {
  host: string;
  port: number;
  database: string;
  username: string;
  password: string;
  sslmode: string;
}

export interface InstallRedisConfig {
  host: string;
  port: number;
  db: number;
  username: string;
  password: string;
  tls: boolean;
}

export interface InstallAdminConfig {
  name: string;
  email: string;
  password: string;
  confirmPassword: string;
}

export interface InstallCompleteRequest {
  database: InstallDatabaseConfig;
  redis: InstallRedisConfig;
  admin: InstallAdminConfig;
}

export interface InstallTestResponse {
  ok: boolean;
  database_url?: string;
  redis_url?: string;
}

export interface InstallCompleteResponse {
  ok: boolean;
  installed: boolean;
  requires_restart: boolean;
  message: string;
  database_url: string;
  redis_url: string;
  env_path: string;
  backup_path?: string | null;
  admin: {
    id: number;
    email: string;
    name: string;
  };
}

export interface InstallRestartResponse {
  ok: boolean;
  mode: string;
  message: string;
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
  creative_brief?: CreativeBrief;  // 分析卡（仅 assistant 消息）
}

export interface Understanding {
  concept: string;
  setting: string;
  tone: string;
  goals: string;
  synthesis: string;
}

export interface OnboardingMessageOut {
  reply: string;
  // 新字段
  understanding: Understanding;
  understanding_depth: number;
  phase: 'extracting';
  has_brief: boolean;
  creative_brief?: CreativeBrief;
  // 保留兼容字段
  collected_info: Record<string, string>;
  step: number;
  total_steps: number;
  is_complete: boolean;
}

export interface CreativeBrief extends Record<string, any> {
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
  world_setting?: any;
  open_story_notes?: string;
}

export interface StoryBible extends Record<string, any> {
  raw_input?: Record<string, any>;
  creative_brief?: CreativeBrief;
  writing_guidance?: Record<string, any>;
  import_guidance?: Record<string, any>;
}

export interface OnboardingConfirmResponse {
  story_id: number;
  story_bible: StoryBible;
  creative_brief: CreativeBrief;
  framework?: {
    tags?: Tags;
    characters?: Character[];
    outline?: Outline;
  } | null;
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

export type AgentMode = 'chat' | 'analyze' | 'execute';

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
  epay_enabled?: boolean;
  epay_gateway?: string;
  epay_pid?: string;
  epay_key?: string;
  epay_type?: string;
  epay_notify_url?: string;
  epay_return_url?: string;
  mapay_enabled?: boolean;
  mapay_gateway?: string;
  mapay_pid?: string;
  mapay_key?: string;
  mapay_type?: string;
  mapay_notify_url?: string;
  mapay_return_url?: string;
}

export interface BillingCheckout {
  method: string;
  provider: string;
  source?: string;
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

export interface QuotaPriceItem {
  feature_key: string;
  name: string;
  description: string;
  category: string;
  price_per_unit: number;
  unit: string;
}

export interface PurchaseQuotaResponse {
  ok: boolean;
  message: string;
  status: string;
  order: AdminOrderItem;
  checkout: BillingCheckout;
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

export interface AdminRevenueSummary {
  total_revenue: number;
  total_orders: number;
  paid_orders: number;
  cancelled_orders: number;
  expired_orders: number;
  monthly_revenue: number;
  monthly_orders: number;
  monthly_paid_orders: number;
  conversion_rate: number;
  active_subscriptions: number;
  monthly_new_users: number;
}

export interface AdminOrderSearchParams {
  page?: number;
  page_size?: number;
  status?: string;
  start_date?: string;
  end_date?: string;
}

export interface AdminOrderSearchResult {
  items: AdminOrderItem[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface AdminRevenueMonthlyItem {
  period: string;
  revenue: number;
  orders: number;
  paid: number;
  cancelled: number;
  expired: number;
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

export interface AdminSystemUpdateStatus {
  status: 'idle' | 'queued' | 'running' | 'succeeded' | 'failed' | 'unknown' | string;
  message: string;
  running: boolean;
  target_version?: string | null;
  current_version?: string;
  started_at?: string | null;
  finished_at?: string | null;
  exit_code?: number | null;
  log_tail: string[];
}

export interface AdminSystemUpdateCheck {
  configured: boolean;
  current_version: string;
  latest_version?: string | null;
  update_available: boolean;
  release_notes: string;
  published_at?: string | null;
  min_supported_version?: string | null;
  channel?: string | null;
  manifest_url?: string;
  message: string;
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
    video_base_url: string;
    video_model: string;
    video_api_key: string;
    video_provider?: string;
    image_size: string;
    image_quality: string;
    image_background: string;
    image_moderation: string;
    image_output_format: string;
    image_output_compression: string;
    image_input_fidelity: string;
    enable_user_override: boolean;
    enable_user_url_override?: boolean;
    oss_enabled?: boolean;
    oss_access_key_id?: string;
    oss_access_key_secret?: string;
    oss_endpoint?: string;
    oss_bucket?: string;
    oss_public_url_base?: string;
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
  pricing: {
    quota_framework_generate: number;
    quota_chapter_expand: number;
    quota_scene_generate: number;
    quota_manga_image_generate: number;
    quota_ai_text_advanced: number;
    quota_video_shot_split: number;
    quota_video_generate: number;
  };
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

export async function getInstallStatus(): Promise<InstallStatus> {
  const res = await fetch(`${BASE}/api/install/status`);
  if (!res.ok) throw new Error(await readErrorMessage(res, '安装状态检查失败'));
  return res.json();
}

export async function testInstallDatabase(payload: InstallDatabaseConfig): Promise<InstallTestResponse> {
  const res = await fetch(`${BASE}/api/install/test-database`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '数据库连接测试失败'));
  return res.json();
}

export async function testInstallRedis(payload: InstallRedisConfig): Promise<InstallTestResponse> {
  const res = await fetch(`${BASE}/api/install/test-redis`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, 'Redis 连接测试失败'));
  return res.json();
}

export async function completeInstall(payload: InstallCompleteRequest): Promise<InstallCompleteResponse> {
  const res = await fetch(`${BASE}/api/install/complete`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '系统安装失败'));
  return res.json();
}

export async function restartInstallBackend(): Promise<InstallRestartResponse> {
  const res = await fetch(`${BASE}/api/install/restart`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '自动重启失败'));
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
    headers: apiHeaders(true),
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

export async function getPaymentConfig(): Promise<{
  enabled: boolean;
  default_method: string;
  order_expire_minutes: number;
  instructions: string;
  methods: PaymentMethodOption[];
}> {
  const res = await fetch(`${BASE}/api/billing/payment-config`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getQuotaPrices(): Promise<QuotaPriceItem[]> {
  const res = await fetch(`${BASE}/api/billing/quota-prices`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function purchaseQuota(
  featureKey: string,
  amount: number,
  paymentMethod?: string,
): Promise<PurchaseQuotaResponse> {
  const body: Record<string, unknown> = { feature_key: featureKey, amount };
  if (paymentMethod) body.payment_method = paymentMethod;
  const res = await fetch(`${BASE}/api/billing/purchase-quota`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function subscribePlan(
  planId: number,
  billingCycle: 'monthly' | 'yearly' = 'monthly',
  paymentMethod?: string,
): Promise<{
  ok: boolean;
  message: string;
  status: string;
  subscription: SubscriptionSummary;
  order: AdminOrderItem;
  checkout: BillingCheckout;
}> {
  const body: Record<string, unknown> = { plan_id: planId, billing_cycle: billingCycle };
  if (paymentMethod) body.payment_method = paymentMethod;
  const res = await fetch(`${BASE}/api/billing/subscribe`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text();
    let detail = text;
    try { detail = JSON.parse(text).detail || text; } catch { /* 非 JSON 响应直接使用原文 */ }
    throw new Error(detail);
  }
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

export async function searchAdminOrders(
  params: AdminOrderSearchParams
): Promise<AdminOrderSearchResult> {
  const search = new URLSearchParams();
  if (params.page) search.set('page', String(params.page));
  if (params.page_size) search.set('page_size', String(params.page_size));
  if (params.status) search.set('status', params.status);
  if (params.start_date) search.set('start_date', params.start_date);
  if (params.end_date) search.set('end_date', params.end_date);
  const qs = search.toString();
  const res = await fetch(`${BASE}/api/admin/orders/search${qs ? '?' + qs : ''}`, {
    headers: apiHeaders(),
  });
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

export async function getAdminRevenueSummary(): Promise<AdminRevenueSummary> {
  const res = await fetch(`${BASE}/api/admin/revenue/summary`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getAdminRevenueMonthly(months = 12): Promise<AdminRevenueMonthlyItem[]> {
  const res = await fetch(`${BASE}/api/admin/revenue/monthly?months=${months}`, { headers: apiHeaders() });
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

export async function getAdminSystemUpdateStatus(): Promise<AdminSystemUpdateStatus> {
  const res = await fetch(`${BASE}/api/admin/system/update/status`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await readErrorMessage(res, '获取更新状态失败'));
  return res.json();
}

export async function checkAdminSystemUpdate(): Promise<AdminSystemUpdateCheck> {
  const res = await fetch(`${BASE}/api/admin/system/update/check`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await readErrorMessage(res, '检测系统更新失败'));
  return res.json();
}

export async function startAdminSystemUpdate(targetVersion?: string): Promise<AdminSystemUpdateStatus> {
  const body = targetVersion?.trim() ? { target_version: targetVersion.trim() } : {};
  const res = await fetch(`${BASE}/api/admin/system/update`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '启动系统更新失败'));
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

async function fetchWithTimeout(url: string, options: RequestInit & { timeout?: number }, fallbackMsg: string): Promise<Response> {
  const timeout = options.timeout ?? 300_000;
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeout);
  const { timeout: _timeout, ...fetchOptions } = options;
  try {
    const res = await fetch(url, { ...fetchOptions, signal: controller.signal });
    if (!res.ok) throw new Error(await readErrorMessage(res, fallbackMsg));
    return res;
  } catch (err: unknown) {
    if (err instanceof DOMException && err.name === 'AbortError') {
      throw new Error(`${fallbackMsg}：请求超时，请重试或减少内容描述`);
    }
    throw err;
  } finally {
    clearTimeout(timeoutId);
  }
}

export async function generateStoryCover(storyId: number, instruction: string = ''): Promise<{ cover_image: string; prompt: string }> {
  const res = await fetchWithTimeout(
    `${BASE}/api/stories/${storyId}/generate-cover`,
    { method: 'POST', headers: apiHeaders(true), body: JSON.stringify({ instruction }) },
    '生成封面失败',
  );
  return res.json();
}

export async function adjustStoryCover(storyId: number, instruction: string): Promise<{ cover_image: string; prompt: string }> {
  const res = await fetchWithTimeout(
    `${BASE}/api/stories/${storyId}/adjust-cover`,
    { method: 'POST', headers: apiHeaders(true), body: JSON.stringify({ instruction }) },
    '调整封面失败',
  );
  return res.json();
}

function isAbsoluteAssetUrl(value: string): boolean {
  return /^https?:\/\//.test(value);
}

function normalizeAssetPath(value: string): string {
  return value.replace(/\\/g, '/');
}

export function toPublicMangaAssetUrl(filePath: string | null | undefined): string | null {
  if (!filePath) return null;
  if (isAbsoluteAssetUrl(filePath) || filePath.startsWith('/static/')) return filePath;
  return `${BASE}/static/manga/${normalizeAssetPath(filePath).replace('manga_outputs/', '')}`;
}

export function toPublicVideoAssetUrl(filePath: string | null | undefined): string | null {
  if (!filePath) return null;
  if (isAbsoluteAssetUrl(filePath) || filePath.startsWith('/static/')) return filePath;
  return `${BASE}/static/video/${normalizeAssetPath(filePath).replace('video_outputs/', '')}`;
}

export function coverImageUrl(coverPath: string | null | undefined): string | null {
  return toPublicMangaAssetUrl(coverPath);
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
  if (imagePath.startsWith('http://') || imagePath.startsWith('https://')) return imagePath;
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
  options?: { mode?: ImageRedrawMode; mask?: string; size?: string; stylePresetName?: string; styleRefUrl?: string },
): Promise<{ id: number; image_number: number; image_path: string; prompt: string }> {
  const res = await fetch(`${BASE}/api/chapters/${chapterId}/regenerate-image/${imageNumber}`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify({ prompt, mode: options?.mode, mask: options?.mask, size: options?.size, style_preset_name: options?.stylePresetName, style_ref_url: options?.styleRefUrl }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

// ─── Generate Manga (SSE with progress) ─────────────────────

export interface MangaProgress {
  type: 'status' | 'scenes' | 'progress' | 'image' | 'done' | 'error';
  data: any;
}

export interface MangaGenStatusResponse {
  task_id: string | null;
  status: 'none' | 'pending' | 'running' | 'succeeded' | 'failed' | 'retrying';
  progress: number;
  total: number;
  error_message: string | null;
  stage?: string | null;
  message?: string | null;
  retry_count?: number;
  max_retries?: number;
  next_retry_at?: string | null;
  created_at: string | null;
  completed_at: string | null;
}

export async function getMangaGenerationStatus(chapterId: number): Promise<MangaGenStatusResponse> {
  const response = await fetch(`${BASE}/api/chapters/${chapterId}/manga-generation-status`, {
    headers: apiHeaders(),
  });
  if (!response.ok) {
    throw new Error(`获取漫画生成状态失败: ${response.statusText}`);
  }
  return response.json();
}

export async function cancelMangaGeneration(chapterId: number): Promise<{ ok: boolean; message: string }> {
  const res = await fetch(`${BASE}/api/chapters/${chapterId}/cancel-manga-generation`, {
    method: 'POST',
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '取消漫画生成失败'));
  return res.json();
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
  size?: string,
  stylePresetName?: string,
  styleRefUrl?: string,
): AbortController {
  const controller = new AbortController();

  const body: Record<string, string> = {};
  if (size) body.size = size;
  if (stylePresetName) body.style_preset_name = stylePresetName;
  if (styleRefUrl) body.style_ref_url = styleRefUrl;

  fetch(`${BASE}/api/chapters/${chapterId}/generate-manga-stream`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify(body),
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

export async function uploadCharacterRefImage(
  storyId: number,
  characterName: string,
  imageBase64: string,
  replaceExisting?: boolean
): Promise<{ images: RefImage[]; max: number }> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/character-ref-images/upload`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify({
      image: imageBase64,
      character_name: characterName,
      replace_existing: replaceExisting,
    }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function deleteCharacterRefImage(
  storyId: number,
  filename: string
): Promise<{ images: RefImage[] }> {
  const res = await fetch(
    `${BASE}/api/stories/${storyId}/character-ref-images/${encodeURIComponent(filename)}`,
    { method: 'DELETE', headers: apiHeaders() },
  );
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

// ─── Onboarding / Story Bible ────────────────────────────────

export async function sendOnboardingMessage(
  storyId: number,
  messages: { role: string; content: string }[],
  understanding: Record<string, string> = {},
): Promise<OnboardingMessageOut> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/onboarding/message`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify({ messages, understanding }),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '引导对话失败'));
  return res.json();
}

export async function confirmOnboarding(
  storyId: number,
  understanding: Record<string, string>,
  messages: { role: string; content: string }[],
  creativeBrief?: CreativeBrief,
): Promise<OnboardingConfirmResponse> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 300_000);
  let res: Response;
  try {
    res = await fetch(`${BASE}/api/stories/${storyId}/onboarding/confirm`, {
      method: 'POST',
      headers: apiHeaders(true),
      body: JSON.stringify({ understanding, messages, creative_brief: creativeBrief }),
      signal: controller.signal,
    });
  } catch (e) {
    clearTimeout(timer);
    throw new Error(e instanceof DOMException && e.name === 'AbortError' ? '确认引导超时，请重试' : '确认引导失败');
  }
  clearTimeout(timer);
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
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 300_000);
  let res: Response;
  try {
    res = await fetch(`${BASE}/api/stories/${storyId}/framework/generate`, {
      method: 'POST',
      headers: apiHeaders(true),
      body: JSON.stringify({ description }),
      signal: controller.signal,
    });
  } catch (e) {
    clearTimeout(timer);
    throw new Error(e instanceof DOMException && e.name === 'AbortError' ? '框架生成超时，请重试' : '框架生成失败');
  }
  clearTimeout(timer);
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
  // imagePath could be:
  //   - "manga_outputs/chapter_1/panel_01_abc12345.png" (local)
  //   - "https://oss.../manga_outputs/chapter_1/panel_01_abc12345.png" (OSS URL)
  // For OSS/full URLs, use directly; otherwise proxy through /static/manga/
  if (imagePath.startsWith('http://') || imagePath.startsWith('https://')) {
    return cacheBust ? `${imagePath}?t=${cacheBust}` : imagePath;
  }
  const url = `${BASE}/static/manga/${imagePath.replace('manga_outputs/', '')}`;
  return cacheBust ? `${url}?t=${cacheBust}` : url;
}

export function agentChatStream(
  storyId: number,
  conversationId: number,
  content: string,
  chapterId?: number,
  mode: AgentMode = 'execute',
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
    body: JSON.stringify({ conversation_id: conversationId, content, chapter_id: chapterId, mode }),
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

export async function agentConfirmChanges(storyId: number, conversationId?: number | null): Promise<void> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/agent/confirm`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify(conversationId ? { conversation_id: conversationId } : {}),
  });
  if (!res.ok) throw new Error(await res.text());
}

export async function agentRollbackChanges(storyId: number, conversationId?: number | null): Promise<void> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/agent/rollback`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify(conversationId ? { conversation_id: conversationId } : {}),
  });
  if (!res.ok) throw new Error(await res.text());
}

// ── Video Workflow ──────────────────────────────────────────

export interface ScriptScene {
  id: number;
  chapter_id: number;
  scene_number: number;
  title: string;
  location?: string | null;
  time_of_day?: string | null;
  characters: string[];
  summary: string;
  dialogue: { speaker: string; text: string }[];
  voiceover?: string | null;
  mood?: string | null;
  estimated_duration_seconds?: number | null;
  source_type: string;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface VideoShot {
  id: number;
  scene_id: number;
  shot_number: number;
  title: string;
  shot_type?: string | null;
  camera_angle?: string | null;
  camera_movement?: string | null;
  composition?: string | null;
  action_description?: string | null;
  dialogue?: string | null;
  sound_design?: string | null;
  duration_seconds?: number | null;
  storyboard_prompt?: string | null;
  video_prompt?: string | null;
  negative_prompt?: string | null;
  first_frame_prompt?: string | null;
  last_frame_prompt?: string | null;
  character_prompts_json?: Array<{ name: string; prompt: string }> | null;
  scene_prompt?: string | null;
  prop_prompts_json?: Array<{ name: string; prompt: string }> | null;
  continuity_notes?: string | null;
  status: string;
  style_preset?: string | null;
  storyboard_asset_id?: number | null;
  storyboard_locked: boolean;
  created_at: string;
  updated_at: string;
  character_involvement?: string | null;
  scene_mood?: string | null;
}

export interface VideoAsset {
  id: number;
  story_id?: number | null;
  chapter_id?: number | null;
  scene_id?: number | null;
  shot_id?: number | null;
  asset_type: string;
  name: string;
  file_path: string;
  provider?: string | null;
  prompt?: string | null;
  meta_json?: Record<string, unknown> | null;
  asset_subtype?: string | null;
  source_asset_ids_json?: number[] | null;
  style_preset?: string | null;
  locked: boolean;
  revision: number;
  is_master: boolean;
  status: string;
  hash_key?: string | null;
  usage_scope?: string | null;
  inherit_to_next_shot?: boolean | null;
  story_level_default?: boolean | null;
  chapter_level_default?: boolean | null;
  created_at: string;
}

export interface VideoGenerationJob {
  id: number;
  shot_id: number;
  provider: string;
  provider_job_id?: string | null;
  model?: string | null;
  status: string;
  progress: number;
  duration_seconds?: number | null;
  aspect_ratio?: string | null;
  request_payload?: Record<string, any> | null;
  error_message?: string | null;
  stage?: string | null;
  message?: string | null;
  provider_status?: string | null;
  retry_count?: number;
  max_retries?: number;
  next_retry_at?: string | null;
  input_mode?: string | null;
  source_storyboard_asset_id?: number | null;
  submitted_at: string;
  completed_at?: string | null;
  clip?: RenderedClip | null;
  job?: {
    id?: number | null;
    status?: string | null;
    progress?: number;
  };
}

export interface RenderedClip {
  id: number;
  shot_id: number;
  job_id?: number | null;
  video_path: string;
  thumbnail_path?: string | null;
  duration_seconds?: number | null;
  resolution?: string | null;
  version: number;
  is_active: boolean;
  meta?: Record<string, any> | null;
  source_storyboard_asset_id?: number | null;
  style_preset?: string | null;
  continuity_score?: number | null;
  quality_score?: number | null;
  review_status?: string;
  created_at: string;
}

export interface VideoProject {
  id: number;
  story_id: number;
  chapter_id: number;
  name: string;
  timeline: Array<{ shot_id: number; clip_id: number; order: number; enabled: boolean }>;
  subtitle: Array<{ start_ms: number; end_ms: number; text: string }>;
  bgm_path?: string | null;
  cover_path?: string | null;
  status: string;
  output_path?: string | null;
  created_at: string;
  updated_at: string;
}

export interface StoryVideoCharacterVersion {
  id: number;
  label: string;
  is_default: boolean;
  ref_asset_id?: number | null;
  ref_asset_url?: string | null;
  appearance_card: string;
  sort_order: number;
}

export interface StoryVideoCharacter {
  name: string;
  versions: StoryVideoCharacterVersion[];
}

export interface ChapterVideoShot {
  id: number;
  workflow_id: number;
  shot_index: number;
  source_text_span?: string | null;
  scene_location?: string | null;
  time_of_day?: string | null;
  characters?: string[] | null;
  story_summary?: string | null;
  dialogue_or_narration?: string | null;
  camera_plan?: string | null;
  motion_plan?: string | null;
  emotion_plan?: string | null;
  continuity_notes?: string | null;
  storyboard_prompt?: string | null;
  video_prompt?: string | null;
  character_prompts?: Array<{ name: string; prompt: string }> | null;
  scene_prompt?: string | null;
  prop_prompts?: Array<{ name: string; prompt: string }> | null;
  key_props?: string[] | null;
  scene_asset_candidates?: string[] | null;
  character_reference_ids?: number[] | null;
  scene_reference_ids?: number[] | null;
  prop_reference_ids?: Array<number | null> | null;
  storyboard_json?: Record<string, unknown> | null;
  storyboard_image_url?: string | null;
  video_url?: string | null;
  status: string;
  error_message?: string | null;
  created_at: string;
}

export interface ChapterVideoWorkflow {
  id: number;
  chapter_id: number;
  story_id: number;
  workflow_status: string;
  character_reference_ids?: number[] | null;
  video_style?: string | null;
  style_reference_image_url?: string | null;
  duration_per_shot: number;
  total_shots: number;
  completed_shots: number;
  failed_shots: number;
  error_message?: string | null;
  task_id?: string | null;
  stage?: string | null;
  message?: string | null;
  retry_count?: number;
  max_retries?: number;
  next_retry_at?: string | null;
  created_at: string;
  updated_at: string;
  shots: ChapterVideoShot[];
}

export interface ChapterVideoWorkflowStatus {
  id: number;
  chapter_id: number;
  workflow_status: string;
  total_shots: number;
  completed_shots: number;
  failed_shots: number;
  error_message?: string | null;
  task_id?: string | null;
  stage?: string | null;
  message?: string | null;
  retry_count?: number;
  max_retries?: number;
  next_retry_at?: string | null;
}

export async function generateScreenplay(chapterId: number, payload: {
  mode?: string;
  style?: string;
  target_duration_seconds?: number;
  scene_count_hint?: number;
  regenerate?: boolean;
}): Promise<{ screenplay: string; scenes: ScriptScene[] }> {
  const res = await fetch(`${BASE}/api/video/chapters/${chapterId}/screenplay/generate`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await res.text());
  const data = await res.json();
  return {
    screenplay: data.screenplay || '',
    scenes: (data.scenes || []) as ScriptScene[],
  };
}

export async function listScreenplayScenes(chapterId: number): Promise<{ scenes: ScriptScene[]; screenplay: string }> {
  const res = await fetch(`${BASE}/api/video/chapters/${chapterId}/screenplay/scenes`, {
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(await res.text());
  const data = await res.json();
  return {
    scenes: (data.scenes || []) as ScriptScene[],
    screenplay: data.screenplay || '',
  };
}

export async function generateSceneShots(sceneId: number, payload: { style?: string; shot_count_hint?: number; regenerate?: boolean; duration_budget_seconds?: number }): Promise<{ scene_id: number; shots: VideoShot[] }> {
  const res = await fetch(`${BASE}/api/video/scenes/${sceneId}/shots/generate`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function listSceneShots(sceneId: number): Promise<{ scene_id: number; shots: VideoShot[] }> {
  const res = await fetch(`${BASE}/api/video/scenes/${sceneId}/shots`, {
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function updateVideoShot(shotId: number, payload: Partial<VideoShot>): Promise<VideoShot> {
  const res = await fetch(`${BASE}/api/shots/${shotId}`, {
    method: 'PATCH',
    headers: apiHeaders(true),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function generateShotPrompts(shotId: number, payload: { style?: string; provider?: string; include_references?: boolean; instruction?: string; continuity_notes?: string }): Promise<{ shot: VideoShot }> {
  const res = await fetch(`${BASE}/api/shots/${shotId}/prompts/generate`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await res.text());
  const data = await res.json();
  return { shot: data };
}

export interface ShotAssetPromptDraft {
  shot_id: number;
  style_preset: string;
  character_prompts: Array<{ name: string; prompt: string }>;
  scene_prompt: string;
  prop_prompts: Array<{ name: string; prompt: string }>;
  storyboard_prompt: string;
  first_frame_prompt: string;
  last_frame_prompt: string;
  video_prompt: string;
}

export async function parseShotAssetPrompts(shotId: number, payload?: {
  style?: string;
  style_preset?: string;
  provider?: string;
  instruction?: string;
}): Promise<ShotAssetPromptDraft> {
  const res = await fetch(`${BASE}/api/shots/${shotId}/asset-prompts/parse`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify(payload || {}),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function generateShotCharacterAsset(shotId: number, payload: {
  character_name: string;
  prompt: string;
  style_preset?: string;
  reference_asset_ids?: number[];
  source_asset_ids?: number[];
}): Promise<VideoAsset> {
  const res = await fetch(`${BASE}/api/shots/${shotId}/assets/character/generate`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function generateShotPropAsset(shotId: number, payload: {
  prop_name: string;
  prompt: string;
  style_preset?: string;
  reference_asset_ids?: number[];
  source_asset_ids?: number[];
}): Promise<VideoAsset> {
  const res = await fetch(`${BASE}/api/shots/${shotId}/prop-assets/generate`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function generateShotSceneAsset(shotId: number, payload: {
  prompt: string;
  style_preset?: string;
  reference_asset_ids?: number[];
  source_asset_ids?: number[];
}): Promise<VideoAsset> {
  const res = await fetch(`${BASE}/api/shots/${shotId}/scene-assets/generate`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

/** 一键生成章节分镜（分镜列表） */
export async function generateChapterStoryboard(chapterId: number, payload?: {
  provider?: string;
  style?: string;
  style_preset?: string;
}): Promise<{ shots: any[] }> {
  const res = await fetch(`${BASE}/api/chapters/${chapterId}/storyboard/generate`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: payload ? JSON.stringify(payload) : '{}',
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function createChapterVideoWorkflow(payload: {
  chapter_id: number;
  character_reference_ids?: number[];
  video_style?: string;
  style_reference_image_url?: string | null;
}): Promise<ChapterVideoWorkflow> {
  const res = await fetch(`${BASE}/api/video/chapter-workflows`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getChapterVideoWorkflow(workflowId: number): Promise<ChapterVideoWorkflow> {
  const res = await fetch(`${BASE}/api/video/chapter-workflows/${workflowId}`, {
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function listChapterVideoWorkflows(chapterId: number): Promise<{ workflows: ChapterVideoWorkflow[]; total: number }> {
  const res = await fetch(`${BASE}/api/video/chapter-workflows/by-chapter/${chapterId}`, {
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getChapterVideoWorkflowStatus(workflowId: number): Promise<ChapterVideoWorkflowStatus> {
  const res = await fetch(`${BASE}/api/video/chapter-workflows/${workflowId}/status`, {
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function regenerateChapterWorkflowStoryboard(shotId: number, promptOverride?: string, referenceAssetIds?: number[]): Promise<ChapterVideoShot> {
  const res = await fetch(`${BASE}/api/video/chapter-workflows/shots/${shotId}/regenerate-storyboard`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify({
      target: 'storyboard',
      prompt_override: promptOverride ?? null,
      reference_asset_ids: referenceAssetIds ?? [],
    }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function regenerateChapterWorkflowVideo(shotId: number, promptOverride?: string, referenceAssetIds?: number[], aspectRatio: '16:9' | '9:16' = '16:9'): Promise<ChapterVideoShot> {
  const res = await fetch(`${BASE}/api/video/chapter-workflows/shots/${shotId}/regenerate-video`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify({
      target: 'video',
      prompt_override: promptOverride ?? null,
      reference_asset_ids: referenceAssetIds ?? [],
      aspect_ratio: aspectRatio,
    }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function previewVideoPrompt(
  shotId: number,
  referenceAssetIds?: number[],
  promptOverride?: string,
): Promise<{ assembled_prompt: string; parts: { part1: string; part2: string; part3: string | null } }> {
  const params = new URLSearchParams();
  if (referenceAssetIds && referenceAssetIds.length > 0) {
    params.set('reference_asset_ids', referenceAssetIds.join(','));
  }
  if (promptOverride) {
    params.set('prompt_override', promptOverride);
  }
  const qs = params.toString();
  const url = `${BASE}/api/video/chapter-workflows/shots/${shotId}/preview-video-prompt${qs ? `?${qs}` : ''}`;
  const res = await fetch(url, { headers: apiHeaders(true) });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function concatChapterVideoWorkflow(workflowId: number): Promise<{ video_url: string; shot_count: number; duration_seconds: number; message?: string }> {
  const res = await fetch(`${BASE}/api/video/chapter-workflows/${workflowId}/concat`, {
    method: 'POST',
    headers: apiHeaders(true),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function listStoryVideoCharacters(storyId: number): Promise<{ characters: StoryVideoCharacter[]; video_character_profiles: string }> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/video-characters`, {
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function generateStoryVideoCharacters(storyId: number): Promise<{ characters: StoryVideoCharacter[]; video_character_profiles: string }> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/video-characters/generate`, {
    method: 'POST',
    headers: apiHeaders(true),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function parseChapterWorkflowShots(workflowId: number): Promise<Record<string, unknown>> {
  const res = await fetch(`${BASE}/api/video/chapter-workflows/${workflowId}/parse`, {
    method: 'POST',
    headers: apiHeaders(true),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function generateChapterWorkflowShotDetails(
  workflowId: number,
  payload: { shot_ids: number[] }
): Promise<Record<string, unknown>> {
  const res = await fetch(`${BASE}/api/video/chapter-workflows/${workflowId}/generate-details`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function uploadStyleReferenceImage(
  workflowId: number,
  file: File
): Promise<{ success: boolean; style_reference_image_url: string }> {
  const formData = new FormData();
  formData.append('file', file);
  const res = await fetch(`${BASE}/api/video/chapter-workflows/${workflowId}/style-reference`, {
    method: 'POST',
    headers: apiHeaders(),
    body: formData,
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function generateChapterWorkflowStoryboards(
  workflowId: number,
  payload: { shot_ids: number[] }
): Promise<Record<string, unknown>> {
  const res = await fetch(`${BASE}/api/video/chapter-workflows/${workflowId}/storyboards`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function generateChapterWorkflowVideos(
  workflowId: number,
  payload: { shot_ids: number[] }
): Promise<Record<string, unknown>> {
  const res = await fetch(`${BASE}/api/video/chapter-workflows/${workflowId}/videos`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function runAllChapterWorkflowStages(workflowId: number): Promise<Record<string, unknown>> {
  const res = await fetch(`${BASE}/api/video/chapter-workflows/${workflowId}/run-all`, {
    method: 'POST',
    headers: apiHeaders(true),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function reanalyzeChapterWorkflowStoryboardPrompt(
  workflowId: number,
  payload: { shot_ids: number[] }
): Promise<Record<string, unknown>> {
  const res = await fetch(`${BASE}/api/video/chapter-workflows/${workflowId}/storyboards/reanalyze-prompt`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function renderStoryboardFrame(shotId: number, payload: {
  provider?: string;
  aspect_ratio?: string;
  overwrite?: boolean;
  style_preset?: string;
  prompt?: string;
  reference_asset_ids?: number[];
}): Promise<{ shot_status: string; asset: VideoAsset; storyboard_locked: boolean }> {
  const res = await fetch(`${BASE}/api/shots/${shotId}/storyboard/render`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await res.text());
  const data = await res.json();
  return {
    shot_status: 'storyboard_ready',
    asset: data,
    storyboard_locked: false,
  };
}



export async function renderShotVideo(shotId: number, payload: {
  provider?: string;
  model?: string;
  duration_seconds?: number;
  aspect_ratio?: string;
  fps?: number;
  use_reference_assets?: boolean;
  reference_asset_ids?: number[];
  seed?: number;
  overwrite_active_clip?: boolean;
  prompt?: string;
  negative_prompt?: string;
  style?: string;
  input_mode?: string;
  source_storyboard_asset_id?: number;
}): Promise<{ job: VideoGenerationJob }> {
  const res = await fetch(`${BASE}/api/shots/${shotId}/video/render`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await res.text());
  const data = await res.json();
  return { job: data.job || data };
}

export async function approveShotStoryboard(shotId: number): Promise<{ storyboard_locked: boolean; storyboard_asset_id: number }> {
  const res = await fetch(`${BASE}/api/shots/${shotId}/storyboard/approve`, {
    method: 'POST',
    headers: apiHeaders(true),
  });
  if (!res.ok) throw new Error(await res.text());
  const data = await res.json();
  return {
    storyboard_locked: true,
    storyboard_asset_id: data.storyboard_asset_id ?? 0,
  };
}

export async function rejectShotStoryboard(shotId: number): Promise<{ storyboard_locked: boolean; storyboard_asset_id: number }> {
  const res = await fetch(`${BASE}/api/shots/${shotId}/storyboard/reject`, {
    method: 'POST',
    headers: apiHeaders(true),
  });
  if (!res.ok) throw new Error(await res.text());
  const data = await res.json();
  return {
    storyboard_locked: false,
    storyboard_asset_id: data.storyboard_asset_id ?? 0,
  };
}

export async function setMasterStoryboard(shotId: number, assetId: number): Promise<{ shot_id: number; asset_id: number }> {
  const res = await fetch(`${BASE}/api/shots/${shotId}/storyboard/${assetId}/master`, {
    method: 'POST',
    headers: apiHeaders(true),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getShotStoryboards(shotId: number): Promise<{
  assets: VideoAsset[];
  active_storyboard_asset_id?: number | null;
  storyboard_locked: boolean;
}> {
  const res = await fetch(`${BASE}/api/shots/${shotId}/storyboards`, {
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(await res.text());
  const data = await res.json();
  return {
    assets: data.storyboards || [],
    active_storyboard_asset_id: data.active_storyboard_id,
    storyboard_locked: data.storyboard_locked ?? false,
  };
}

export async function deleteShot(shotId: number): Promise<{ ok: boolean; shot_id: number }> {
  const res = await fetch(`${BASE}/api/shots/${shotId}`, {
    method: 'DELETE',
    headers: apiHeaders(true),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function createSceneShot(sceneId: number, payload?: Partial<VideoShot>): Promise<VideoShot> {
  const res = await fetch(`${BASE}/api/video/scenes/${sceneId}/shots`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify(payload || {}),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function reorderSceneShots(sceneId: number, payload: { shot_ids: number[] }): Promise<{ scene_id: number; shots: VideoShot[] }> {
  const res = await fetch(`${BASE}/api/video/scenes/${sceneId}/shots/reorder`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await res.text());
  const data = await res.json();
  return {
    scene_id: data.scene_id ?? sceneId,
    shots: data.shots || data.shot_ids?.map((id: number) => ({ id, shot_number: id })) || [],
  };
}

export async function getVideoJob(jobId: number): Promise<VideoGenerationJob> {
  const res = await fetch(`${BASE}/api/video-jobs/${jobId}`, {
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function retryVideoJob(jobId: number, payload?: { provider?: string; model?: string; duration_seconds?: number; aspect_ratio?: string; seed?: number; request_payload?: Record<string, unknown> }): Promise<VideoGenerationJob> {
  const res = await fetch(`${BASE}/api/video/jobs/${jobId}/retry`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify(payload || {}),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function listShotClips(shotId: number): Promise<{ shot_id: number; clips: RenderedClip[]; active_clip_id?: number }> {
  const res = await fetch(`${BASE}/api/shots/${shotId}/clips`, {
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function activateShotClip(shotId: number, clipId: number): Promise<{ active_clip_id: number }> {
  const res = await fetch(`${BASE}/api/shots/${shotId}/clips/${clipId}/activate`, {
    method: 'POST',
    headers: apiHeaders(true),
  });
  if (!res.ok) throw new Error(await res.text());
  return { active_clip_id: clipId };
}

export async function listVideoAssets(chapterId: number, assetType?: string): Promise<{ chapter_id: number; assets: VideoAsset[] }> {
  const params = assetType ? `?asset_type=${encodeURIComponent(assetType)}` : '';
  const res = await fetch(`${BASE}/api/chapters/${chapterId}/video-assets${params}`, {
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function createVideoAsset(chapterId: number, payload: {
  story_id?: number;
  scene_id?: number;
  shot_id?: number;
  asset_type: string;
  name: string;
  file_path: string;
  provider?: string;
  prompt?: string;
  meta?: Record<string, unknown>;
}): Promise<VideoAsset> {
  const res = await fetch(`${BASE}/api/chapters/${chapterId}/video-assets`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function deleteVideoAsset(assetId: number): Promise<{ ok: boolean; asset_id: number }> {
  const res = await fetch(`${BASE}/api/video-assets/${assetId}`, {
    method: 'DELETE',
    headers: apiHeaders(true),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export interface ReanalyzeShotPromptsResponse {
  shot_id: number;
  storyboard_prompt: string;
  video_prompt: string;
  character_prompts: Array<{ name: string; prompt: string }>;
  scene_prompt?: string;
  prop_prompts?: Array<{ name: string; prompt: string }>;
}

export async function reanalyzeChapterShotPrompts(shotId: number): Promise<ReanalyzeShotPromptsResponse> {
  const res = await fetch(`${BASE}/api/video/chapter-workflows/shots/${shotId}/reanalyze-prompts`, {
    method: 'POST',
    headers: apiHeaders(true),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function clearShotStoryboard(shotId: number): Promise<{ ok: boolean; shot: ChapterVideoShot }> {
  const res = await fetch(`${BASE}/api/video/chapter-workflows/shots/${shotId}/clear-storyboard`, {
    method: 'POST',
    headers: apiHeaders(true),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function clearShotVideo(shotId: number): Promise<{ ok: boolean; shot: ChapterVideoShot }> {
  const res = await fetch(`${BASE}/api/video/chapter-workflows/shots/${shotId}/clear-video`, {
    method: 'POST',
    headers: apiHeaders(true),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function resetChapterWorkflow(workflowId: number): Promise<{ ok: boolean; workflow_status: string }> {
  const res = await fetch(`${BASE}/api/video/chapter-workflows/${workflowId}/reset`, {
    method: 'POST',
    headers: apiHeaders(true),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function replaceVideoAsset(assetId: number, file: File): Promise<{ ok: boolean; asset: { id: number; file_path: string; revision: number } }> {
  const formData = new FormData();
  formData.append('file', file);
  const res = await fetch(`${BASE}/api/video-assets/${assetId}/replace`, {
    method: 'POST',
    headers: apiHeaders(),
    body: formData,
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function regenerateVideoAsset(assetId: number, prompt?: string, mask?: string): Promise<{ ok: boolean; asset: { id: number; file_path: string; revision: number } }> {
  const body: Record<string, unknown> = {};
  if (prompt) body.prompt = prompt;
  if (mask) { body.mask = mask; body.mode = 'partial'; }
  const res = await fetch(`${BASE}/api/video-assets/${assetId}/regen`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function uploadShotStoryboard(shotId: number, file: File): Promise<{ ok: boolean; shot: ChapterVideoShot }> {
  const formData = new FormData();
  formData.append('file', file);
  const res = await fetch(`${BASE}/api/video/chapter-workflows/shots/${shotId}/upload-storyboard`, {
    method: 'POST',
    headers: apiHeaders(),
    body: formData,
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function uploadShotVideo(shotId: number, file: File): Promise<{ ok: boolean; shot: ChapterVideoShot }> {
  const formData = new FormData();
  formData.append('file', file);
  const res = await fetch(`${BASE}/api/video/chapter-workflows/shots/${shotId}/upload-video`, {
    method: 'POST',
    headers: apiHeaders(),
    body: formData,
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function saveChapterShotPrompts(shotId: number, prompts: { storyboard_prompt?: string | null; video_prompt?: string | null; scene_prompt?: string | null; prop_prompts?: Array<{ name: string; prompt: string }> | null }): Promise<{ ok: boolean; shot: ChapterVideoShot }> {
  const res = await fetch(`${BASE}/api/video/chapter-workflows/shots/${shotId}/save-prompts`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify(prompts),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function createVideoProject(chapterId: number, payload: {
  name: string;
  timeline: Array<{ shot_id: number; clip_id: number; order: number; enabled: boolean }>;
  subtitle?: Array<{ start_ms: number; end_ms: number; text: string }>;
  bgm_path?: string;
  cover_path?: string;
}): Promise<VideoProject> {
  const res = await fetch(`${BASE}/api/video/chapters/${chapterId}/projects`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getVideoProject(projectId: number): Promise<VideoProject> {
  const res = await fetch(`${BASE}/api/video/projects/${projectId}`, {
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function updateVideoProject(projectId: number, payload: Partial<VideoProject>): Promise<VideoProject> {
  const res = await fetch(`${BASE}/api/video/projects/${projectId}`, {
    method: 'PATCH',
    headers: apiHeaders(true),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function compileVideoProject(projectId: number, payload: {
  resolution?: string;
  fps?: number;
  burn_subtitle?: boolean;
  include_bgm?: boolean;
}): Promise<{ project_id: number; output_path: string; status: string }> {
  const res = await fetch(`${BASE}/api/video/projects/${projectId}/compile`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export interface ShotFrameAsset {
  id: number;
  asset_type: string;
  name: string;
  file_path: string;
  prompt?: string | null;
  meta_json?: Record<string, unknown> | null;
  style_preset?: string | null;
  revision: number;
  is_master: boolean;
  status: string;
  created_at: string;
}

export interface ShotFramesResponse {
  shot_id: number;
  first_frames: ShotFrameAsset[];
  last_frames: ShotFrameAsset[];
}

export interface ChapterShotFramesResponse {
  chapter_id: number;
  shots: Array<{
    shot_id: number;
    shot_number: number | null;
    scene_id: number | null;
    frames: {
      first_frames: ShotFrameAsset[];
      last_frames: ShotFrameAsset[];
    };
  }>;
}

export async function generateShotFrames(shotId: number, payload: {
  frame_type?: string;
  prompt?: string | null;
  overwrite?: boolean;
  style_preset?: string;
  reference_asset_ids?: number[];
  inherit_character_assets?: boolean;
  inherit_scene_assets?: boolean;
  inherit_storyboard_asset?: boolean;
}): Promise<ShotFramesResponse> {
  const res = await fetch(`${BASE}/api/shots/${shotId}/frames/generate`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function regenerateShotFrame(shotId: number, payload: {
  asset_id: number;
  prompt: string;
  mode?: string;
  mask?: string | null;
  style_preset?: string;
  reference_asset_ids?: number[];
}): Promise<ShotFrameAsset> {
  const res = await fetch(`${BASE}/api/shots/${shotId}/frames/regen`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getShotFrames(shotId: number): Promise<ShotFramesResponse> {
  const res = await fetch(`${BASE}/api/shots/${shotId}/frames`, {
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function listChapterShotFrames(chapterId: number): Promise<ChapterShotFramesResponse> {
  const res = await fetch(`${BASE}/api/video/chapters/${chapterId}/frames`, {
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export interface VideoStylePreset {
  id: number;
  name: string;
  category: string;
  image_url?: string | null;
  prompt_template?: string | null;
  image_style_params?: Record<string, unknown> | null;
  video_style_params?: Record<string, unknown> | null;
  sort_order: number;
}

export async function getStoryVideoStylePreset(storyId: number): Promise<{ story_id: number; style_preset_id: number | null; style_preset: VideoStylePreset | null }> {
  const res = await fetch(`${BASE}/api/video/stories/${storyId}/style-preset`, {
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function setStoryVideoStylePreset(storyId: number, stylePresetId: number): Promise<{ story_id: number; style_preset_id: number }> {
  const res = await fetch(`${BASE}/api/video/stories/${storyId}/style-preset`, {
    method: 'PUT',
    headers: apiHeaders(true),
    body: JSON.stringify({ style_preset_id: stylePresetId }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function setShotVideoStylePreset(shotId: number, stylePreset: string): Promise<{ shot_id: number; style_preset: string }> {
  const res = await fetch(`${BASE}/api/shots/${shotId}/style-preset`, {
    method: 'PUT',
    headers: apiHeaders(true),
    body: JSON.stringify({ style_preset: stylePreset }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function deleteShotVideoStylePreset(shotId: number): Promise<{ shot_id: number; style_preset: null }> {
  const res = await fetch(`${BASE}/api/shots/${shotId}/style-preset`, {
    method: 'DELETE',
    headers: apiHeaders(true),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export interface ShotAssetBundle {
  shot_id: number;
  shot_number?: number | null;
  scene_id?: number | null;
  style_preset?: string | null;
  storyboard_asset: VideoAsset | null;
  storyboard_locked: boolean;
  first_frame: VideoAsset | null;
  last_frame: VideoAsset | null;
  character_references: VideoAsset[];
  scene_references: VideoAsset[];
  available_character_assets: VideoAsset[];
  available_scene_assets: VideoAsset[];
}

export async function getShotAssetBundle(shotId: number): Promise<ShotAssetBundle> {
  const res = await fetch(`${BASE}/api/shots/${shotId}/assets/bundle`, {
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function updateAssetScope(assetId: number, payload: { usage_scope: string; inherit_to_next_shot?: boolean }): Promise<{ asset_id: number; usage_scope: string; inherit_to_next_shot: boolean }> {
  const res = await fetch(`${BASE}/api/video-assets/${assetId}/scope`, {
    method: 'PUT',
    headers: apiHeaders(true),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function promoteAsset(assetId: number, payload: { level: string; inherit_to_next_shot?: boolean }): Promise<{ asset_id: number; level: string }> {
  const res = await fetch(`${BASE}/api/video-assets/${assetId}/promote`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function listStylePresets(): Promise<{ presets: VideoStylePreset[] }> {
  const res = await fetch(`${BASE}/api/video-style-presets`, {
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function uploadMangaStyleReference(chapterId: number, file: File): Promise<{ success: boolean; style_reference_image_url: string }> {
  const formData = new FormData();
  formData.append('file', file);
  const res = await fetch(`${BASE}/api/chapters/${chapterId}/upload-style-reference`, {
    method: 'POST',
    headers: apiHeaders(),
    body: formData,
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function createStylePreset(data: {
  name: string;
  category?: string;
  image_url?: string | null;
  prompt_template?: string;
  image_style_params?: Record<string, unknown>;
  video_style_params?: Record<string, unknown>;
  sort_order?: number;
}): Promise<VideoStylePreset> {
  const res = await fetch(`${BASE}/api/video-style-presets`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function updateStylePreset(
  presetId: number,
  data: {
    name?: string;
    category?: string;
    image_url?: string | null;
    prompt_template?: string;
    image_style_params?: Record<string, unknown>;
    video_style_params?: Record<string, unknown>;
    sort_order?: number;
  }
): Promise<VideoStylePreset> {
  const res = await fetch(`${BASE}/api/video-style-presets/${presetId}`, {
    method: 'PUT',
    headers: apiHeaders(true),
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function deleteStylePreset(presetId: number): Promise<void> {
  const res = await fetch(`${BASE}/api/video-style-presets/${presetId}`, {
    method: 'DELETE',
    headers: apiHeaders(true),
  });
  if (!res.ok) throw new Error(await res.text());
}

export interface CharacterVersion {
  id: number;
  version: string;
  label: string;
  appearance_card: string;
  ref_asset?: VideoAsset | null;
  ref_asset_id?: number | null;
  ref_asset_url?: string | undefined;
  is_default: boolean;
  sort_order: number;
}

export interface VideoCharacter {
  name: string;
  versions: CharacterVersion[];
}

export interface VideoCharactersResponse {
  characters: VideoCharacter[];
  video_character_profiles: string;
}

export async function listVideoCharacters(storyId: number): Promise<VideoCharactersResponse> {
  const res = await fetch(`${BASE}/api/video/stories/${storyId}/characters`, {
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function generateVideoCharacters(storyId: number): Promise<VideoCharactersResponse> {
  const res = await fetch(`${BASE}/api/video/stories/${storyId}/characters/generate`, {
    method: 'POST',
    headers: apiHeaders(true),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function createCharacterVersion(
  storyId: number,
  characterName: string,
  payload: { version_label: string; appearance_card?: string; set_default?: boolean },
): Promise<{ version: CharacterVersion }> {
  const res = await fetch(`${BASE}/api/video/stories/${storyId}/characters/${characterName}/versions`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await res.text());
  const data = await res.json();
  const version: CharacterVersion = {
    id: data.id ?? Date.now(),
    version: data.version_label ?? payload.version_label,
    label: data.version_label ?? payload.version_label,
    appearance_card: data.appearance_card ?? payload.appearance_card ?? '',
    ref_asset: data.ref_asset ?? null,
    ref_asset_url: data.ref_asset?.file_path ?? null,
    is_default: data.is_default ?? false,
    sort_order: data.sort_order ?? 0,
  };
  return { version };
}

export async function deleteCharacterVersion(
  storyId: number,
  characterName: string,
  versionLabel: string | number,
): Promise<{ ok: boolean }> {
  const label = String(versionLabel);
  const res = await fetch(`${BASE}/api/video/stories/${storyId}/characters/${characterName}/versions/${label}`, {
    method: 'DELETE',
    headers: apiHeaders(true),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function generateCharacterRefImage(
  storyId: number,
  characterName: string,
  versionId: number,
  stylePreset?: string,
): Promise<VideoAsset> {
  const res = await fetch(`${BASE}/api/video/stories/${storyId}/characters/${characterName}/ref-image/generate`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify({ version_id: versionId, style_preset: stylePreset }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function deleteVideoCharacterRefImage(
  storyId: number,
  characterName: string,
  versionId: number,
): Promise<{ ok: boolean }> {
  const res = await fetch(`${BASE}/api/video/stories/${storyId}/characters/${characterName}/ref-image`, {
    method: 'DELETE',
    headers: apiHeaders(true),
    body: JSON.stringify({ version_id: versionId }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function redrawCharacterRefImage(
  storyId: number,
  characterName: string,
  versionId: number,
  payload: { prompt: string; mode: ImageRedrawMode; mask?: string },
): Promise<VideoAsset> {
  const res = await fetch(`${BASE}/api/video/stories/${storyId}/characters/${characterName}/ref-image/redraw`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify({ version_id: versionId, ...payload }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

// ─── Prompt Template API ─────────────────────────────────

export interface PromptTemplateItem {
  id: number;
  name: string;
  description: string;
  author: { id: number; username: string } | null;
  category: string | null;
  tags: string[];
  status: string;
  visibility: string;
  is_public: boolean;
  usage_count: number;
  like_count: number;
  is_liked?: boolean;
  framework_prompt?: string | null;
  chapter_prompt?: string | null;
  character_prompt?: string | null;
  manga_style_prompt?: string | null;
  framework_params?: Record<string, string> | null;
  chapter_params?: Record<string, string> | null;
  character_params?: Record<string, string> | null;
  manga_style_params?: Record<string, string> | null;
  forked_from?: number | null;
  submitted_at?: string | null;
  reviewed_at?: string | null;
  review_note?: string | null;
  created_at: string;
  updated_at: string;
}

export interface TemplateListResponse {
  templates: PromptTemplateItem[];
  total: number;
  page: number;
  page_size: number;
}

export async function createPromptTemplate(data: {
  name: string;
  description?: string;
  category?: string;
  tags?: string[];
  framework_prompt?: string | null;
  chapter_prompt?: string | null;
  character_prompt?: string | null;
  manga_style_prompt?: string | null;
  framework_params?: Record<string, string> | null;
  chapter_params?: Record<string, string> | null;
  character_params?: Record<string, string> | null;
  manga_style_params?: Record<string, string> | null;
}): Promise<PromptTemplateItem> {
  const res = await fetch(`${BASE}/api/prompt-templates`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '创建模板失败'));
  return res.json();
}

export async function listMyTemplates(params?: {
  page?: number; page_size?: number; status?: string;
}): Promise<TemplateListResponse> {
  const query = new URLSearchParams();
  if (params?.page) query.set('page', String(params.page));
  if (params?.page_size) query.set('page_size', String(params.page_size));
  if (params?.status) query.set('status', params.status);
  const res = await fetch(`${BASE}/api/prompt-templates/my?${query}`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await readErrorMessage(res, '获取模板列表失败'));
  return res.json();
}

export async function getPromptTemplate(id: number): Promise<PromptTemplateItem> {
  const res = await fetch(`${BASE}/api/prompt-templates/${id}`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await readErrorMessage(res, '获取模板详情失败'));
  return res.json();
}

export async function updatePromptTemplate(id: number, data: Record<string, unknown>): Promise<PromptTemplateItem> {
  const res = await fetch(`${BASE}/api/prompt-templates/${id}`, {
    method: 'PUT', headers: apiHeaders(true), body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '更新模板失败'));
  return res.json();
}

export async function deletePromptTemplate(id: number): Promise<void> {
  const res = await fetch(`${BASE}/api/prompt-templates/${id}`, { method: 'DELETE', headers: apiHeaders() });
  if (!res.ok) throw new Error(await readErrorMessage(res, '删除模板失败'));
}

export async function submitTemplateForReview(id: number): Promise<PromptTemplateItem> {
  const res = await fetch(`${BASE}/api/prompt-templates/${id}/submit-for-review`, {
    method: 'POST', headers: apiHeaders(true),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '提交审核失败'));
  return res.json();
}

export async function forkPromptTemplate(id: number): Promise<PromptTemplateItem> {
  const res = await fetch(`${BASE}/api/prompt-templates/${id}/fork`, {
    method: 'POST', headers: apiHeaders(true),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '复制模板失败'));
  return res.json();
}

export async function listPublicTemplates(params?: {
  sort?: string; category?: string; page?: number; page_size?: number;
}): Promise<TemplateListResponse> {
  const query = new URLSearchParams();
  if (params?.sort) query.set('sort', params.sort);
  if (params?.category) query.set('category', params.category);
  if (params?.page) query.set('page', String(params.page || 1));
  if (params?.page_size) query.set('page_size', String(params.page_size || 20));
  const res = await fetch(`${BASE}/api/prompt-templates/public?${query}`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await readErrorMessage(res, '获取公开模板失败'));
  return res.json();
}

export async function likeTemplate(id: number): Promise<{ like_count: number; is_liked: boolean }> {
  const res = await fetch(`${BASE}/api/prompt-templates/${id}/like`, {
    method: 'POST', headers: apiHeaders(true),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '点赞失败'));
  return res.json();
}

export async function unlikeTemplate(id: number): Promise<{ like_count: number; is_liked: boolean }> {
  const res = await fetch(`${BASE}/api/prompt-templates/${id}/like`, {
    method: 'DELETE', headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '取消点赞失败'));
  return res.json();
}

export async function bindStoryTemplate(storyId: number, templateId: number): Promise<void> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/bind-template`, {
    method: 'POST', headers: apiHeaders(true),
    body: JSON.stringify({ template_id: templateId }),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '绑定模板失败'));
}

export async function getStoryTemplate(storyId: number): Promise<{ template: PromptTemplateItem | null }> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/template`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await readErrorMessage(res, '获取作品模板失败'));
  return res.json();
}

export async function unbindStoryTemplate(storyId: number): Promise<void> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/template`, {
    method: 'DELETE', headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '解绑模板失败'));
}

export interface SystemDefaultPrompts {
  framework: string;
  chapter: string;
  character: string;
  manga_style: string;
}

export async function getSystemDefaultPrompts(): Promise<SystemDefaultPrompts> {
  const res = await fetch(`${BASE}/api/prompt-templates/defaults`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await readErrorMessage(res, '获取系统默认提示词失败'));
  return res.json();
}

// Admin: template review
export async function listPendingTemplates(page = 1, pageSize = 50): Promise<TemplateListResponse> {
  const res = await fetch(`${BASE}/api/admin/prompt-templates/pending?page=${page}&page_size=${pageSize}`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await readErrorMessage(res, '获取待审核列表失败'));
  return res.json();
}

export async function approveTemplate(id: number, visibility: string, note?: string): Promise<PromptTemplateItem> {
  const res = await fetch(`${BASE}/api/admin/prompt-templates/${id}/approve`, {
    method: 'POST', headers: apiHeaders(true),
    body: JSON.stringify({ visibility, note: note || '' }),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '审核操作失败'));
  return res.json();
}

export async function rejectTemplate(id: number, note: string): Promise<PromptTemplateItem> {
  const res = await fetch(`${BASE}/api/admin/prompt-templates/${id}/reject`, {
    method: 'POST', headers: apiHeaders(true),
    body: JSON.stringify({ note }),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '拒绝操作失败'));
  return res.json();
}

// ── Admin: 系统默认提示词管理 ─────────────────────────────

export interface AdminSystemPrompt {
  key: string;
  name: string;
  content: string;
}

export interface AdminSystemPromptsResponse {
  [shortKey: string]: AdminSystemPrompt;
}

export interface AdminUpdateSystemPromptsResponse {
  updated: string[];
  prompts: AdminSystemPromptsResponse;
}

export async function getAdminSystemPrompts(): Promise<AdminSystemPromptsResponse> {
  const res = await fetch(`${BASE}/api/admin/system-prompts`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await readErrorMessage(res, '获取系统提示词失败'));
  return res.json();
}

export async function updateAdminSystemPrompts(payload: Record<string, string>): Promise<AdminUpdateSystemPromptsResponse> {
  const res = await fetch(`${BASE}/api/admin/system-prompts`, {
    method: 'PUT',
    headers: apiHeaders(true),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '保存系统提示词失败'));
  return res.json();
}
