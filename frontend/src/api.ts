import { normalizeErrorMessage, readResponseError } from './lib/errors';

const BASE = '';
const DEFAULT_API_ERROR_MESSAGE = '请求失败，请稍后重试';
const API_TOKEN = import.meta.env.VITE_API_TOKEN as string | undefined;
export const DEEPSEEK_USAGE_URL = 'https://platform.deepseek.com/usage';
export const IMAGE2_CONSOLE_URL = 'https://api.xbyjs.top/console/token';

export interface ApiKeySettings {
  deepseekApiKey: string;
  upstreamBaseUrl: string;
  deepseekBaseUrl: string;
  deepseekModel: string;
  imageApiKey: string;
  imageBaseUrl: string;
  imageModel: string;
  videoBaseUrl: string;
  videoModel: string;
}

// Stored in localStorage so multiple tabs share the same API key settings.
const LS_DEEPSEEK_API_KEY = 'storycanvas.deepseekApiKey';
const LS_UPSTREAM_BASE_URL = 'storycanvas.upstreamBaseUrl';
const LS_DEEPSEEK_BASE_URL = 'storycanvas.deepseekBaseUrl';
const LS_DEEPSEEK_MODEL = 'storycanvas.deepseekModel';
const LS_IMAGE_API_KEY = 'storycanvas.imageApiKey';
const LS_IMAGE_BASE_URL = 'storycanvas.imageBaseUrl';
const LS_IMAGE_MODEL = 'storycanvas.imageModel';
const LS_VIDEO_BASE_URL = 'storycanvas.videoBaseUrl';
const LS_VIDEO_MODEL = 'storycanvas.videoModel';
const LS_AUTH_TOKEN = 'storycanvas.authToken';
const LS_AUTH_USER_ID = 'storycanvas.authUserId';
const LS_CREDENTIAL_MODE = 'storycanvas_credential_mode';
const LS_CHAPTER_GENERATION_TASKS = 'storycanvas.chapterGenerationTasks';
const LEGACY_API_SETTING_KEYS = [
  LS_DEEPSEEK_API_KEY,
  LS_UPSTREAM_BASE_URL,
  LS_DEEPSEEK_BASE_URL,
  LS_DEEPSEEK_MODEL,
  LS_IMAGE_API_KEY,
  LS_IMAGE_BASE_URL,
  LS_IMAGE_MODEL,
  LS_VIDEO_BASE_URL,
  LS_VIDEO_MODEL,
  LS_CREDENTIAL_MODE,
] as const;
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

function scopedApiSettingKey(key: string): string | null {
  const userId = localStorage.getItem(LS_AUTH_USER_ID);
  return userId ? `${key}.user.${userId}` : null;
}

function getScopedApiSetting(key: string): string {
  const scopedKey = scopedApiSettingKey(key);
  return scopedKey ? localStorage.getItem(scopedKey) || '' : '';
}

function setScopedApiSetting(key: string, value: string): void {
  const scopedKey = scopedApiSettingKey(key);
  if (!scopedKey) return;
  if (value) localStorage.setItem(scopedKey, value);
  else localStorage.removeItem(scopedKey);
}

export function getApiKeySettings(): ApiKeySettings {
  const upstreamBaseUrl = getScopedApiSetting(LS_UPSTREAM_BASE_URL);
  const deepseekBaseUrl = getScopedApiSetting(LS_DEEPSEEK_BASE_URL);
  const imageBaseUrl = getScopedApiSetting(LS_IMAGE_BASE_URL);
  const videoBaseUrl = getScopedApiSetting(LS_VIDEO_BASE_URL);
  const legacyUrls = [deepseekBaseUrl, imageBaseUrl, videoBaseUrl].filter(Boolean);
  const legacySharedUrl = legacyUrls.length > 0 && legacyUrls.every((url) => url === legacyUrls[0]) ? legacyUrls[0] : '';
  return {
    deepseekApiKey: getScopedApiSetting(LS_DEEPSEEK_API_KEY),
    upstreamBaseUrl: upstreamBaseUrl || legacySharedUrl,
    deepseekBaseUrl,
    deepseekModel: getScopedApiSetting(LS_DEEPSEEK_MODEL),
    imageApiKey: getScopedApiSetting(LS_IMAGE_API_KEY),
    imageBaseUrl,
    imageModel: getScopedApiSetting(LS_IMAGE_MODEL),
    videoBaseUrl,
    videoModel: getScopedApiSetting(LS_VIDEO_MODEL),
  };
}

export function saveApiKeySettings(settings: ApiKeySettings): void {
  const deepseek = settings.deepseekApiKey.trim();
  const upstreamBaseUrl = settings.upstreamBaseUrl.trim();
  const deepseekBaseUrl = settings.deepseekBaseUrl.trim();
  const deepseekModel = settings.deepseekModel.trim();
  const image = settings.imageApiKey.trim();
  const imageBaseUrl = settings.imageBaseUrl.trim();
  const imageModel = settings.imageModel.trim();
  const videoBaseUrl = settings.videoBaseUrl.trim();
  const videoModel = settings.videoModel.trim();
  setScopedApiSetting(LS_DEEPSEEK_API_KEY, deepseek);
  setScopedApiSetting(LS_UPSTREAM_BASE_URL, upstreamBaseUrl);
  setScopedApiSetting(LS_DEEPSEEK_BASE_URL, deepseekBaseUrl);
  setScopedApiSetting(LS_DEEPSEEK_MODEL, deepseekModel);
  setScopedApiSetting(LS_IMAGE_API_KEY, image);
  setScopedApiSetting(LS_IMAGE_BASE_URL, imageBaseUrl);
  setScopedApiSetting(LS_IMAGE_MODEL, imageModel);
  setScopedApiSetting(LS_VIDEO_BASE_URL, videoBaseUrl);
  setScopedApiSetting(LS_VIDEO_MODEL, videoModel);
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
    upstreamBaseUrl: '',
    deepseekBaseUrl: '',
    deepseekModel: '',
    imageApiKey: '',
    imageBaseUrl: '',
    imageModel: '',
    videoBaseUrl: '',
    videoModel: '',
  });
}

export function clearApiUrlOverrideSettings(): void {
  const settings = getApiKeySettings();
  saveApiKeySettings({
    ...settings,
    upstreamBaseUrl: '',
    deepseekBaseUrl: '',
    deepseekModel: '',
    imageBaseUrl: '',
    imageModel: '',
    videoBaseUrl: '',
    videoModel: '',
  });
}

function applyApiUrlOverrideCapability(user: AuthUser): AuthUser {
  const legacyValues = new Map(
    LEGACY_API_SETTING_KEYS.map((key) => [key, localStorage.getItem(key) || '']),
  );
  localStorage.setItem(LS_AUTH_USER_ID, String(user.id));
  for (const [key, value] of legacyValues) {
    const scopedKey = scopedApiSettingKey(key);
    if (value && scopedKey && !localStorage.getItem(scopedKey)) {
      localStorage.setItem(scopedKey, value);
    }
    localStorage.removeItem(key);
  }
  if (!user.can_override_api_url) clearApiUrlOverrideSettings();
  if (!user.can_override_api_key && !user.can_override_api_url) setLocalCredentialMode('platform');
  return user;
}

export function apiHeaders(json = false): HeadersInit {
  const keys = getApiKeySettings();
  const token = getAuthToken();
  const mode = getLocalCredentialMode();
  const upstreamBaseUrl = keys.upstreamBaseUrl.trim();
  return {
    ...(json ? { 'Content-Type': 'application/json' } : {}),
    ...(API_TOKEN ? { 'X-API-Token': API_TOKEN } : {}),
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    'X-Credential-Mode': mode,
    ...(mode === 'user_key' && keys.deepseekApiKey ? { 'X-DeepSeek-API-Key': keys.deepseekApiKey } : {}),
    ...(mode === 'user_key' && (upstreamBaseUrl || keys.deepseekBaseUrl) ? { 'X-DeepSeek-Base-URL': upstreamBaseUrl || keys.deepseekBaseUrl } : {}),
    ...(mode === 'user_key' && keys.deepseekModel ? { 'X-DeepSeek-Model': keys.deepseekModel } : {}),
    ...(mode === 'user_key' && keys.imageApiKey ? { 'X-Image-API-Key': keys.imageApiKey } : {}),
    ...(mode === 'user_key' && (upstreamBaseUrl || keys.imageBaseUrl) ? { 'X-Image-Base-URL': upstreamBaseUrl || keys.imageBaseUrl } : {}),
    ...(mode === 'user_key' && keys.imageModel ? { 'X-Image-Model': keys.imageModel } : {}),
    ...(mode === 'user_key' && (upstreamBaseUrl || keys.videoBaseUrl) ? { 'X-Video-Base-URL': upstreamBaseUrl || keys.videoBaseUrl } : {}),
    ...(mode === 'user_key' && keys.videoModel ? { 'X-Video-Model': keys.videoModel } : {}),
  };
}

async function readErrorMessage(res: Response, fallback: string): Promise<string> {
  return readResponseError(res, fallback);
}

export function getAuthToken(): string {
  return localStorage.getItem(LS_AUTH_TOKEN) || '';
}

export function setAuthToken(token: string): void {
  if (token) localStorage.setItem(LS_AUTH_TOKEN, token);
  else {
    localStorage.removeItem(LS_AUTH_TOKEN);
    localStorage.removeItem(LS_AUTH_USER_ID);
  }
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
  decision?: OnboardingDecision;
}

export interface Understanding {
  concept: string;
  setting: string;
  tone: string;
  goals: string;
  synthesis: string;
}

export interface OnboardingDecisionOption {
  id: string;
  label: string;
  value: string;
  reason?: string;
}

export interface OnboardingDecision {
  field: keyof Understanding;
  question: string;
  options: OnboardingDecisionOption[];
}

export interface OnboardingMessageOut {
  reply: string;
  // 新字段
  understanding: Understanding;
  understanding_depth: number;
  phase: 'extracting' | 'refining' | 'deciding' | 'synthesizing';
  has_brief: boolean;
  creative_brief?: CreativeBrief;
  active_field?: keyof Understanding;
  incomplete_fields: (keyof Understanding)[];
  decision?: OnboardingDecision;
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

/** Novel autopilot data stored in the story bible or supplied by a host workflow. */
export interface CreativeProfile {
  platform_mode: string;
  audience_mode: string;
  genre: string;
  custom_genre?: string;
  pace_mode: string;
  target_length: string;
  creation_goal: string;
}

export interface OpeningPlanResponse {
  book_hook: string;
  chapter_1_hook: string;
  chapter_3_hook: string;
  chapter_10_payoff: string;
  chapter_20_climax: string;
  opening_notes: string[];
}

export interface VolumeItem {
  id: string;
  title: string;
  summary: string;
  goal: string;
  core_conflict: string;
  climax: string;
  ending_hook: string;
  chapter_start: number;
  chapter_end: number;
  linked_phase: string;
}

export interface ChapterGoalCard {
  chapter_number: number;
  goal: string;
  plot_progress: string[];
  relationship_change: string[];
  hook: string;
  payoff: string;
  scene_suggestions: string[];
}

export type ConsistencyIssueSeverity = 'high' | 'medium' | 'low' | string;

export interface ConsistencyIssue {
  type: string;
  severity: ConsistencyIssueSeverity;
  message: string;
  suggestion?: string;
  chapter_number?: number | null;
}

export interface ConsistencyCheckResponse {
  issues: ConsistencyIssue[];
}

export interface WritingMonitorResponse {
  current_stage: string;
  current_volume?: string | null;
  inactive_characters: string[];
  pace_alerts: string[];
  next_recommendations: string[];
}

export interface PublishingPackageResponse {
  titles: string[];
  summary: string;
  selling_points: string[];
  platform_tags: string[];
  submission_notes: string;
}

export type StoryKnowledgeKind = 'resource' | 'entity' | 'fact' | 'plot_thread';

export interface StoryKnowledgeCategory {
  id: number;
  story_id: number;
  knowledge_kind: StoryKnowledgeKind;
  name: string;
  color?: string | null;
  sort_order?: number | null;
  version?: number | null;
}

export interface StoryKnowledgeItem {
  id: number;
  story_id: number;
  kind: StoryKnowledgeKind;
  category_id?: number | null;
  category_name?: string | null;
  resource_type?: string | null;
  resource_key?: string | null;
  title?: string | null;
  summary?: string | null;
  content_json?: unknown;
  content_text?: string | null;
  importance?: number | null;
  valid_from_chapter?: number | null;
  valid_to_chapter?: number | null;
  triggers_json?: string[] | null;
  is_constant?: boolean | null;
  status?: string | null;
  source_type?: string | null;
  source_id?: string | null;
  version?: number | null;
  entity_key?: string | null;
  entity_type?: string | null;
  canonical_name?: string | null;
  aliases_json?: string[] | null;
  profile_json?: Record<string, unknown> | null;
  first_chapter?: number | null;
  last_chapter?: number | null;
  subject_key?: string | null;
  predicate?: string | null;
  object_key?: string | null;
  value_json?: unknown;
  value_text?: string | null;
  confidence?: number | null;
  thread_key?: string | null;
  thread_type?: string | null;
  description?: string | null;
  setup_chapter?: number | null;
  expected_payoff_from?: number | null;
  expected_payoff_to?: number | null;
  actual_payoff_chapter?: number | null;
  related_entity_keys?: string[] | null;
  priority?: number | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export type StoryKnowledgeMutation = Partial<Omit<StoryKnowledgeItem, 'id' | 'story_id' | 'kind' | 'created_at' | 'updated_at' | 'source_type' | 'version'>> & {
  expected_version?: number;
};

export interface StoryKnowledgeResponse {
  story_id: number;
  knowledge_revision: number;
  story_bible?: StoryBible;
  categories?: StoryKnowledgeCategory[];
  counts?: Partial<Record<StoryKnowledgeKind | 'story_bible', number>>;
  resources: StoryKnowledgeItem[];
  entities: StoryKnowledgeItem[];
  facts: StoryKnowledgeItem[];
  plot_threads: StoryKnowledgeItem[];
  ai_sync_status?: BackgroundTaskStatus | null;
  next_unwritten_chapter_number?: number;
}

export interface ChapterContextPack {
  schema_version: number;
  story_id: number;
  chapter_id: number;
  chapter_number: number;
  chapter_title?: string;
  content: string;
  version: number;
  content_hash: string;
  source_hash?: string | null;
  current_source_hash?: string | null;
  is_manual: boolean;
  is_stale: boolean;
  updated_at?: string | null;
  refresh_task?: BackgroundTaskStatus | null;
}

export interface ChapterContextSummary {
  chapter_id: number | null;
  chapter_number: number;
  title: string;
  has_pack: boolean;
  has_novel: boolean;
  is_manual: boolean;
  is_current: boolean;
  version: number;
  pack_updated_at?: string | null;
  word_count: number;
  refresh_task?: BackgroundTaskStatus | null;
}

export interface ChapterContextListResponse {
  story_id: number;
  next_unwritten_chapter_number: number;
  chapters: ChapterContextSummary[];
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

export type AgentWorkflowType = 'novel' | 'manga' | 'video' | 'video_canvas';

export interface AgentWorkflowContext {
  workflow_type?: AgentWorkflowType | null;
  workflow_id?: number | null;
  shot_id?: number | null;
}

export interface MangaImage {
  id: number;
  chapter_id: number;
  image_number: number;
  image_path: string;
  prompt: string | null;
  created_at: string;
}

export interface MangaExportManifestImage {
  image_number: number;
  filename: string;
  download_url: string;
}

export interface MangaExportManifest {
  images: MangaExportManifestImage[];
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
  alipay_app_private_key_configured?: boolean;
  alipay_app_private_key_last_four?: string;
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
  billing_cycle: 'monthly' | 'yearly' | 'one_time' | string;
  expires_at: string;
  qr_code_text: string;
  payment_url: string;
  can_mock_confirm: boolean;
}

export interface AdminOrderItem {
  order_no: string;
  user_id: number;
  user_name?: string | null;
  plan_id?: number | null;
  points_product_id?: number | null;
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
  monthly_paid_users: number;
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
  points_available: number;
  points_reserved: number;
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
    allow_all_users_api_key_override?: boolean;
    enable_user_url_override?: boolean;
    oss_enabled?: boolean;
    oss_access_key_id?: string;
    oss_access_key_id_configured?: boolean;
    oss_access_key_id_last_four?: string;
    oss_access_key_secret?: string;
    oss_access_key_secret_configured?: boolean;
    oss_access_key_secret_last_four?: string;
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
    quota_deconstruction_run: number;
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
    video_base_url?: string;
    video_model?: string;
  };
  auth?: {
    require_email_code_for_register?: boolean;
    require_email_code_for_login?: boolean;
    email_code_expire_minutes?: number;
  };
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

export interface HealthStatus {
  ok: boolean;
  ready: boolean;
  installed: boolean;
  system_ready?: boolean;
  database_reachable?: boolean | null;
}

/**
 * 探测后端服务是否存活。
 *
 * `/api/health` 不依赖 AI 上游，仅反映后端进程与数据库是否就绪，因此是
 * 区分「后端未启动/不可达」与「AI 上游故障」的可靠探针。返回 null 表示后端不可达。
 */
export async function checkHealth(): Promise<HealthStatus | null> {
  try {
    const res = await fetch(`${BASE}/api/health`);
    if (!res.ok) {
      // 后端返回错误本身已说明「后端响应了但未就绪」。
      return { ok: false, ready: false, installed: false, system_ready: false, database_reachable: null };
    }
    const body = await res.json().catch(() => null);
    if (!body) return { ok: false, ready: false, installed: false, system_ready: false, database_reachable: null };
    const ready = Boolean(body.ready ?? body.system_ready);
    return {
      ok: Boolean(body.ok),
      ready,
      installed: Boolean(body.installed),
      system_ready: Boolean(body.system_ready),
      database_reachable: body.database_reachable ?? null,
    };
  } catch {
    // fetch 抛错（超时、连接被拒、网关 502 HTML 页）视为后端不可达。
    return null;
  }
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
  const session = await res.json() as AuthSession;
  applyApiUrlOverrideCapability(session.user);
  return session;
}

export async function login(payload: { email: string; password: string; verification_code?: string }): Promise<AuthSession> {
  const res = await fetch(`${BASE}/api/auth/login`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '登录失败，请检查账号或密码。'));
  const session = await res.json() as AuthSession;
  applyApiUrlOverrideCapability(session.user);
  return session;
}

export async function logout(): Promise<void> {
  const res = await fetch(`${BASE}/api/auth/logout`, { method: 'POST', headers: apiHeaders() });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  localStorage.removeItem(LS_AUTH_USER_ID);
}

export async function me(): Promise<AuthUser> {
  const res = await fetch(`${BASE}/api/auth/me`, { headers: apiHeaders() });
  if (!res.ok) {
    localStorage.removeItem(LS_AUTH_USER_ID);
    throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  }
  return applyApiUrlOverrideCapability(await res.json() as AuthUser);
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

export async function resetPassword(email: string, verification_code: string, new_password: string): Promise<{ ok: boolean; message: string }> {
  const res = await fetch(`${BASE}/api/auth/reset-password`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify({ email, verification_code, new_password }),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '密码重置失败'));
  return res.json();
}

export async function getMyOrders(): Promise<AdminOrderItem[]> {
  const res = await fetch(`${BASE}/api/me/orders`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
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
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function confirmMyOrderMock(orderNo: string): Promise<{
  ok: boolean;
  status: string;
  order: AdminOrderItem;
}> {
  const res = await fetch(`${BASE}/api/me/orders/${orderNo}/mock-confirm`, {
    method: 'POST',
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
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
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function syncMyOrder(orderNo: string): Promise<{
  ok: boolean;
  status: string;
  order: AdminOrderItem;
  checkout?: BillingCheckout | null;
}> {
  const res = await fetch(`${BASE}/api/me/orders/${orderNo}/sync`, {
    method: 'POST',
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function getAdminUserStories(userId: number): Promise<AdminReviewStory[]> {
  const res = await fetch(`${BASE}/api/admin/users/${userId}/stories`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function getAdminStoryChapters(storyId: number): Promise<AdminReviewStoryChaptersResponse> {
  const res = await fetch(`${BASE}/api/admin/stories/${storyId}/chapters`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}



export async function getAdminOrders(): Promise<AdminOrderItem[]> {
  const res = await fetch(`${BASE}/api/admin/orders`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
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
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
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
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function getAdminRevenueSummary(): Promise<AdminRevenueSummary> {
  const res = await fetch(`${BASE}/api/admin/revenue/summary`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function getAdminRevenueMonthly(months = 12): Promise<AdminRevenueMonthlyItem[]> {
  const res = await fetch(`${BASE}/api/admin/revenue/monthly?months=${months}`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
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
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
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
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
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
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
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
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
}

export async function deleteAdminUser(userId: number): Promise<void> {
  const res = await fetch(`${BASE}/api/admin/users/${userId}`, {
    method: 'DELETE',
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
}

export async function getAdminPlatformSettings(): Promise<PlatformSettings> {
  const res = await fetch(`${BASE}/api/admin/platform/settings`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function updateAdminPlatformSettings(payload: PlatformSettings): Promise<PlatformSettings> {
  const res = await fetch(`${BASE}/api/admin/platform/settings`, {
    method: 'PUT',
    headers: apiHeaders(true),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  const data = await res.json();
  return data.settings;
}

export async function getAdminAnnouncement(): Promise<PlatformAnnouncement> {
  const res = await fetch(`${BASE}/api/admin/platform/announcement`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function updateAdminAnnouncement(payload: PlatformAnnouncement): Promise<{ ok: boolean; announcement: PlatformAnnouncement }> {
  const res = await fetch(`${BASE}/api/admin/platform/announcement`, {
    method: 'PUT',
    headers: apiHeaders(true),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function getPublicAnnouncement(): Promise<PlatformAnnouncement> {
  const res = await fetch(`${BASE}/api/platform/announcement`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function getPublicPlatformSettings(): Promise<PublicPlatformSettings> {
  const res = await fetch(`${BASE}/api/platform/settings/public`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

// ─── Story ──────────────────────────────────────────────────

export async function createStory(title: string = '未命名故事', description: string = ''): Promise<Story> {
  const res = await fetch(`${BASE}/api/stories`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify({ title, description }),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function listStories(): Promise<Story[]> {
  const res = await fetch(`${BASE}/api/stories`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function getStory(storyId: number): Promise<Story> {
  const res = await fetch(`${BASE}/api/stories/${storyId}`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
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
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function deleteStory(storyId: number): Promise<void> {
  const res = await fetch(`${BASE}/api/stories/${storyId}`, { method: 'DELETE', headers: apiHeaders() });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
}

export async function getStoryKnowledge(storyId: number): Promise<StoryKnowledgeResponse> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/knowledge`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await readErrorMessage(res, '加载作品知识失败'));
  return res.json();
}

export async function getStoryChapterContexts(storyId: number): Promise<ChapterContextListResponse> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/knowledge/chapter-contexts`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await readErrorMessage(res, '加载章节创作包列表失败'));
  return res.json();
}

export async function getStoryChapterContext(storyId: number, chapterNumber?: number): Promise<ChapterContextPack> {
  const params = new URLSearchParams();
  if (chapterNumber != null) params.set('chapter_number', String(chapterNumber));
  const suffix = params.size > 0 ? `?${params}` : '';
  const res = await fetch(`${BASE}/api/stories/${storyId}/knowledge/chapter-context${suffix}`, { headers: apiHeaders() });
  if (!res.ok) {
    const message = await readErrorMessage(res, '加载本章创作包失败');
    const error = new Error(message) as Error & { status?: number };
    error.status = res.status;
    throw error;
  }
  return res.json();
}

export async function updateStoryChapterContext(storyId: number, chapterNumber: number, content: string, expectedVersion: number): Promise<ChapterContextPack> {
  const params = new URLSearchParams({ chapter_number: String(chapterNumber) });
  const res = await fetch(`${BASE}/api/stories/${storyId}/knowledge/chapter-context?${params}`, {
    method: 'PUT',
    headers: apiHeaders(true),
    body: JSON.stringify({ content, expected_version: expectedVersion }),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '保存本章创作包失败'));
  return res.json();
}

export async function regenerateStoryChapterContext(storyId: number, chapterNumber: number, expectedVersion: number): Promise<KnowledgeTaskSubmitResult> {
  const params = new URLSearchParams({ chapter_number: String(chapterNumber), expected_version: String(expectedVersion) });
  const res = await fetch(`${BASE}/api/stories/${storyId}/knowledge/chapter-context/regenerate?${params}`, {
    method: 'POST',
    headers: apiHeaders(true),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '重新提取本章创作包失败'));
  return res.json();
}

export type StoryKnowledgeSyncScope = 'all' | 'entities' | 'facts' | 'plot_threads';
export type StoryKnowledgeSyncMode = 'incremental' | 'full';

export interface KnowledgeTaskSubmitResult {
  task_id: string;
  status: string;
  message: string;
  scope?: StoryKnowledgeSyncScope;
  mode?: StoryKnowledgeSyncMode;
}

export async function syncStoryKnowledgeWithAI(
  storyId: number,
  options: { mode?: StoryKnowledgeSyncMode; scope?: StoryKnowledgeSyncScope } = {},
): Promise<KnowledgeTaskSubmitResult> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/knowledge/ai-sync`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify({ mode: options.mode || 'incremental', scope: options.scope || 'all' }),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '提交 AI 同步任务失败'));
  return res.json();
}

export async function createStoryKnowledge(
  storyId: number,
  kind: StoryKnowledgeKind,
  payload: StoryKnowledgeMutation,
): Promise<{ item: StoryKnowledgeItem; knowledge_revision: number }> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/knowledge/${kind}`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '新增作品知识失败'));
  return res.json();
}

export async function updateStoryKnowledge(
  storyId: number,
  kind: StoryKnowledgeKind,
  itemId: number,
  payload: StoryKnowledgeMutation,
): Promise<{ item: StoryKnowledgeItem; knowledge_revision: number }> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/knowledge/${kind}/${itemId}`, {
    method: 'PUT',
    headers: apiHeaders(true),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '更新作品知识失败'));
  return res.json();
}

export async function deleteStoryKnowledge(
  storyId: number,
  kind: StoryKnowledgeKind,
  itemId: number,
  expectedVersion: number,
): Promise<{ ok: boolean; knowledge_revision: number }> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/knowledge/${kind}/${itemId}?expected_version=${expectedVersion}`, {
    method: 'DELETE',
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '删除作品知识失败'));
  return res.json();
}

export async function createStoryKnowledgeCategory(
  storyId: number,
  payload: Pick<StoryKnowledgeCategory, 'knowledge_kind' | 'name'> & Partial<Pick<StoryKnowledgeCategory, 'color' | 'sort_order'>>,
): Promise<{ category: StoryKnowledgeCategory; knowledge_revision?: number }> {
  const { knowledge_kind: knowledgeKind, ...body } = payload;
  const res = await fetch(`${BASE}/api/stories/${storyId}/knowledge/categories/${knowledgeKind}`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '新增知识分类失败'));
  return res.json();
}

export async function updateStoryKnowledgeCategory(
  storyId: number,
  categoryId: number,
  payload: Partial<Pick<StoryKnowledgeCategory, 'name' | 'color' | 'sort_order'>> & { expected_version?: number },
): Promise<{ category: StoryKnowledgeCategory; knowledge_revision?: number }> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/knowledge/categories/${categoryId}`, {
    method: 'PUT',
    headers: apiHeaders(true),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '更新知识分类失败'));
  return res.json();
}

export async function deleteStoryKnowledgeCategory(
  storyId: number,
  categoryId: number,
  expectedVersion: number,
): Promise<{ ok: boolean; knowledge_revision?: number }> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/knowledge/categories/${categoryId}?expected_version=${expectedVersion}`, {
    method: 'DELETE',
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '删除知识分类失败'));
  return res.json();
}

export async function uploadStoryCover(storyId: number, base64: string): Promise<string> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/upload-cover`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify({ image: base64 }),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
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
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function listChapters(storyId: number): Promise<Chapter[]> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/chapters`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function createNextChapter(storyId: number): Promise<Chapter> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/chapters`, { method: 'POST', headers: apiHeaders() });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function deleteChapter(chapterId: number): Promise<void> {
  const res = await fetch(`${BASE}/api/chapters/${chapterId}`, { method: 'DELETE', headers: apiHeaders() });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
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
        onError(await readErrorMessage(res, '对话请求失败，请稍后重试'));
        return;
      }
      const reader = res.body?.getReader();
      if (!reader) {
        onError('对话连接未返回可读取内容，请稍后重试');
        return;
      }
      const decoder = new TextDecoder();
      let buffer = '';
      let currentEvent = 'message';
      let terminalEventReceived = false;
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
              terminalEventReceived = true;
              _onDone(data.content);
            } else if (currentEvent === 'error' || data.error) {
              terminalEventReceived = true;
              onError(normalizeErrorMessage(data.error, '对话生成失败，请稍后重试'));
            }
          } catch {
            terminalEventReceived = true;
            onError('对话任务返回了无法解析的数据，请刷新后重试');
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
      if (!terminalEventReceived && !controller.signal.aborted) {
        onError('对话连接意外中断，请重试');
      }
    })
    .catch((err) => {
      if (err.name !== 'AbortError') {
        onError(normalizeErrorMessage(err, '对话请求失败，请稍后重试'));
      }
    });

  return controller;
}

// ─── Generate Novel ─────────────────────────────────────────

export interface ChapterGenerationTaskSubmitResult {
  task_id: string;
  status: string;
  chapter_id: number;
  message: string;
}

type ChapterGenerationAction = 'generate_novel' | 'adjust_content' | 'expand_chapter';

interface TrackedChapterGenerationTask {
  task_id: string;
  chapter_id: number;
  action: ChapterGenerationAction;
  updated_at: number;
}

function readTrackedChapterGenerationTasks(): Record<string, TrackedChapterGenerationTask> {
  try {
    const raw = localStorage.getItem(LS_CHAPTER_GENERATION_TASKS);
    const parsed = raw ? JSON.parse(raw) : {};
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch {
    return {};
  }
}

function writeTrackedChapterGenerationTasks(tasks: Record<string, TrackedChapterGenerationTask>): void {
  try {
    localStorage.setItem(LS_CHAPTER_GENERATION_TASKS, JSON.stringify(tasks));
  } catch {
    // localStorage 不可用时仅影响刷新恢复，当前轮询仍继续。
  }
}

function trackChapterGenerationTask(task: ChapterGenerationTaskSubmitResult, action: ChapterGenerationAction): void {
  const tasks = readTrackedChapterGenerationTasks();
  tasks[String(task.chapter_id)] = {
    task_id: task.task_id,
    chapter_id: task.chapter_id,
    action,
    updated_at: Date.now(),
  };
  writeTrackedChapterGenerationTasks(tasks);
}

function clearTrackedChapterGenerationTask(chapterId: number, taskId?: string): void {
  const tasks = readTrackedChapterGenerationTasks();
  const key = String(chapterId);
  if (!tasks[key]) return;
  if (taskId && tasks[key].task_id !== taskId) return;
  delete tasks[key];
  writeTrackedChapterGenerationTasks(tasks);
}

function isActiveChapterGenerationStatus(status: string): boolean {
  return ['pending', 'running', 'retrying', 'cancel_requested'].includes(status);
}

function isTransientTaskPollingError(error: unknown): boolean {
  const status = typeof error === 'object' && error !== null && 'status' in error
    ? Number((error as { status?: number }).status)
    : 0;
  if (status === 408 || status === 429 || status >= 500) return true;
  const message = normalizeErrorMessage(error, '');
  return /网络|连接|超时|暂时|稍后|Failed to fetch|NetworkError/i.test(message);
}

async function restoreTrackedChapterGeneration(chapterId: number): Promise<Chapter | null> {
  const tracked = readTrackedChapterGenerationTasks()[String(chapterId)];
  if (!tracked?.task_id) return null;
  try {
    const status = await getBackgroundTaskStatus(tracked.task_id);
    if (status.status === 'succeeded') {
      clearTrackedChapterGenerationTask(chapterId, tracked.task_id);
      const resultChapterId = Number(status.result_json?.chapter_id || tracked.chapter_id || chapterId);
      return getChapter(resultChapterId);
    }
    if (status.status === 'failed' || status.status === 'cancelled') {
      clearTrackedChapterGenerationTask(chapterId, tracked.task_id);
      return null;
    }
    if (isActiveChapterGenerationStatus(status.status)) {
      return waitForChapterGeneration({
        task_id: tracked.task_id,
        status: status.status,
        chapter_id: tracked.chapter_id || chapterId,
        message: status.message || '正在恢复章节正文生成任务',
      }, tracked.action);
    }
    clearTrackedChapterGenerationTask(chapterId, tracked.task_id);
    return null;
  } catch (error) {
    if (isTransientTaskPollingError(error)) {
      return waitForChapterGeneration({
        task_id: tracked.task_id,
        status: 'running',
        chapter_id: tracked.chapter_id || chapterId,
        message: '正在恢复章节正文生成任务',
      }, tracked.action);
    }
    clearTrackedChapterGenerationTask(chapterId, tracked.task_id);
    return null;
  }
}

async function waitForChapterGeneration(
  task: ChapterGenerationTaskSubmitResult,
  action: ChapterGenerationAction = 'generate_novel',
): Promise<Chapter> {
  const deadline = Date.now() + 15 * 60 * 1000;
  trackChapterGenerationTask(task, action);
  while (Date.now() < deadline) {
    let status: BackgroundTaskStatus;
    try {
      status = await getBackgroundTaskStatus(task.task_id);
    } catch (error) {
      if (isTransientTaskPollingError(error)) {
        await new Promise((resolve) => globalThis.setTimeout(resolve, 2000));
        continue;
      }
      throw error;
    }
    if (status.status === 'succeeded') {
      const resultChapterId = Number(status.result_json?.chapter_id || task.chapter_id);
      clearTrackedChapterGenerationTask(task.chapter_id, task.task_id);
      return getChapter(resultChapterId);
    }
    if (status.status === 'failed' || status.status === 'cancelled') {
      clearTrackedChapterGenerationTask(task.chapter_id, task.task_id);
      throw new Error(status.error_message || status.message || '章节正文生成失败');
    }
    await new Promise((resolve) => globalThis.setTimeout(resolve, 1200));
  }
  throw new Error(`章节正文生成等待超时，任务 ${task.task_id} 仍在后台运行；后续再次调用会优先恢复该任务`);
}

export async function generateNovel(chapterId: number): Promise<Chapter> {
  const restored = await restoreTrackedChapterGeneration(chapterId);
  if (restored) return restored;
  const res = await fetch(`${BASE}/api/chapters/${chapterId}/generation-task`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify({ action: 'generate_novel' }),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return waitForChapterGeneration(await res.json(), 'generate_novel');
}

export async function importNovel(chapterId: number, content: string): Promise<Chapter> {
  const res = await fetch(`${BASE}/api/chapters/${chapterId}/import-novel`, {
    method: 'POST',
    headers: { ...apiHeaders(), 'Content-Type': 'application/json' },
    body: JSON.stringify({ content }),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function saveChapterContent(chapterId: number, content: string): Promise<Chapter> {
  const res = await fetch(`${BASE}/api/chapters/${chapterId}/content`, {
    method: 'PUT',
    headers: apiHeaders(true),
    body: JSON.stringify({ content }),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function adjustChapterContent(chapterId: number, instruction: string): Promise<Chapter> {
  const restored = await restoreTrackedChapterGeneration(chapterId);
  if (restored) return restored;
  const res = await fetch(`${BASE}/api/chapters/${chapterId}/generation-task`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify({ action: 'adjust_content', instruction }),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return waitForChapterGeneration(await res.json(), 'adjust_content');
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
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

// ─── Scenes ─────────────────────────────────────────────────

export interface ScenesPayload {
  scenes: string[];
  sanitized_indices?: number[];
}

export type MangaStoryboardImportSource = 'paste' | 'chapter_content';

export interface MangaStoryboardImportResult {
  ok?: boolean;
  changed?: boolean;
  scenes: string[];
  scene_count: number;
  count?: number;
  revision: string;
  canonical_hash: string;
  hash?: string;
  warnings: string[];
  errors: string[];
  generated_image_indices: number[];
  stale_image_indices: number[];
  can_commit: boolean;
}

export async function generateScenes(
  chapterId: number,
  signal?: AbortSignal,
  presetId?: number,
  imageCountHint?: number,
): Promise<ScenesPayload> {
  const hasPreset = presetId != null;
  const body = hasPreset || imageCountHint != null ? JSON.stringify({
    ...(hasPreset ? { preset_id: presetId } : {}),
    ...(imageCountHint != null ? { image_count_hint: imageCountHint } : {}),
  }) : undefined;
  const res = await fetch(`${BASE}/api/chapters/${chapterId}/generate-scenes`, {
    method: 'POST',
    headers: apiHeaders(hasPreset || imageCountHint != null),
    body,
    signal,
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function getScenes(chapterId: number): Promise<ScenesPayload> {
  const res = await fetch(`${BASE}/api/chapters/${chapterId}/scenes`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function updateScenes(chapterId: number, scenes: string[]): Promise<void> {
  const res = await fetch(`${BASE}/api/chapters/${chapterId}/scenes`, {
    method: 'PUT',
    headers: apiHeaders(true),
    body: JSON.stringify({ scenes }),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
}

export async function previewMangaStoryboardImport(
  chapterId: number,
  payload: { source_kind: MangaStoryboardImportSource; content?: string },
): Promise<MangaStoryboardImportResult> {
  const res = await fetch(`${BASE}/api/chapters/${chapterId}/manga-storyboard/import/preview`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '分镜脚本解析失败，请检查格式后重试'));
  return res.json();
}

export async function previewMangaStoryboardImportFile(
  chapterId: number,
  file: File,
): Promise<MangaStoryboardImportResult> {
  const form = new FormData();
  form.append('file', file);
  const res = await fetch(`${BASE}/api/chapters/${chapterId}/manga-storyboard/import/preview-file`, {
    method: 'POST',
    headers: apiHeaders(),
    body: form,
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '分镜文件解析失败，请检查格式后重试'));
  return res.json();
}

export async function commitMangaStoryboardImport(
  chapterId: number,
  payload: { scenes: string[]; expected_revision: string; canonical_hash: string },
): Promise<MangaStoryboardImportResult> {
  const res = await fetch(`${BASE}/api/chapters/${chapterId}/manga-storyboard/import/commit`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '导入分镜失败，请重新预览后再试'));
  return res.json();
}

// ─── Character Profiles ─────────────────────────────────────

// Story-level (global)
export async function getStoryCharacters(storyId: number): Promise<string> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/characters`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  const data = await res.json();
  return data.characters;
}

export async function saveStoryCharacters(storyId: number, characters: string): Promise<void> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/characters`, {
    method: 'PUT',
    headers: apiHeaders(true),
    body: JSON.stringify({ characters }),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
}

// Chapter-level (with source info)
export async function getCharacters(chapterId: number): Promise<{ characters: string; source: 'chapter' | 'story' | 'none' }> {
  const res = await fetch(`${BASE}/api/chapters/${chapterId}/characters`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return await res.json();
}

export async function saveCharacters(chapterId: number, characters: string): Promise<void> {
  const res = await fetch(`${BASE}/api/chapters/${chapterId}/characters`, {
    method: 'PUT',
    headers: apiHeaders(true),
    body: JSON.stringify({ characters }),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
}

export async function resetChapterCharacters(chapterId: number): Promise<void> {
  const res = await fetch(`${BASE}/api/chapters/${chapterId}/characters`, {
    method: 'DELETE',
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
}

export async function generateStoryCharactersFromFramework(storyId: number): Promise<{ characters: string }> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/characters/generate`, {
    method: 'POST',
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
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
  return toPublicMangaAssetUrl(imagePath) || '';
}

// Story-level
export async function getStoryRefImages(storyId: number): Promise<RefImagesPayload> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/ref-images`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function addStoryRefImage(storyId: number, base64: string): Promise<RefImagesPayload> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/ref-images`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify({ image: base64 }),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function deleteStoryRefImage(storyId: number, filename: string): Promise<RefImagesPayload> {
  const res = await fetch(
    `${BASE}/api/stories/${storyId}/ref-images/${encodeURIComponent(filename)}`,
    { method: 'DELETE', headers: apiHeaders() },
  );
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
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
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

// Chapter-level (with story fallback)
export async function getChapterRefImages(chapterId: number): Promise<RefImagesPayload> {
  const res = await fetch(`${BASE}/api/chapters/${chapterId}/ref-images`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function addChapterRefImage(chapterId: number, base64: string): Promise<RefImagesPayload> {
  const res = await fetch(`${BASE}/api/chapters/${chapterId}/ref-images`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify({ image: base64 }),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function deleteChapterRefImage(chapterId: number, filename: string): Promise<RefImagesPayload> {
  const res = await fetch(
    `${BASE}/api/chapters/${chapterId}/ref-images/${encodeURIComponent(filename)}`,
    { method: 'DELETE', headers: apiHeaders() },
  );
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
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
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

// ─── Color Mode ─────────────────────────────────────────────

export type ColorMode = 'bw' | 'color';

export async function getColorMode(chapterId: number): Promise<ColorMode> {
  const res = await fetch(`${BASE}/api/chapters/${chapterId}/color-mode`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  const data = await res.json();
  return data.color_mode || 'bw';
}

export async function setColorMode(chapterId: number, mode: ColorMode): Promise<void> {
  const res = await fetch(`${BASE}/api/chapters/${chapterId}/color-mode`, {
    method: 'PUT',
    headers: apiHeaders(true),
    body: JSON.stringify({ color_mode: mode }),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
}

export type MangaAspectRatio = '9:16' | '3:4' | '2:3' | '1:1' | '3:2' | '4:3' | '16:9';

export async function getMangaAspectRatio(chapterId: number): Promise<MangaAspectRatio> {
  const res = await fetch(`${BASE}/api/chapters/${chapterId}/manga-aspect-ratio`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  const data = await res.json();
  return data.aspect_ratio || '9:16';
}

export async function setMangaAspectRatio(chapterId: number, ratio: MangaAspectRatio): Promise<void> {
  const res = await fetch(`${BASE}/api/chapters/${chapterId}/manga-aspect-ratio`, {
    method: 'PUT',
    headers: apiHeaders(true),
    body: JSON.stringify({ aspect_ratio: ratio }),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
}

// ─── Image Count ─────────────────────────────────────────────

export const ALLOWED_IMAGE_COUNTS = Array.from({ length: 20 }, (_, index) => index + 1);

export async function getImageCount(chapterId: number): Promise<number> {
  const res = await fetch(`${BASE}/api/chapters/${chapterId}/image-count`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  const data = await res.json();
  return data.image_count || 10;
}

export async function setImageCount(chapterId: number, count: number): Promise<number> {
  const res = await fetch(`${BASE}/api/chapters/${chapterId}/image-count`, {
    method: 'PUT',
    headers: apiHeaders(true),
    body: JSON.stringify({ image_count: count }),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  const data = await res.json();
  return data.image_count;
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
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

// ─── Generate Manga (SSE with progress) ─────────────────────

export interface MangaProgress {
  type: 'status' | 'scenes' | 'progress' | 'image' | 'done' | 'error';
  data: any;
}

export interface MangaGenStatusResponse {
  task_id: string | null;
  status: 'none' | 'pending' | 'running' | 'succeeded' | 'failed' | 'retrying' | 'cancel_requested' | 'cancelled';
  progress: number;
  total: number;
  error_message: string | null;
  stage?: string | null;
  message?: string | null;
  retry_count?: number;
  max_retries?: number;
  next_retry_at?: string | null;
  error_code?: string | null;
  retryable?: boolean;
  suggestion?: string | null;
  asset_total?: number;
  asset_completed?: number;
  asset_generated?: number;
  asset_failed?: number;
  created_at: string | null;
  completed_at: string | null;
}

export async function getMangaGenerationStatus(chapterId: number): Promise<MangaGenStatusResponse> {
  const response = await fetch(`${BASE}/api/chapters/${chapterId}/manga-generation-status`, {
    headers: apiHeaders(),
  });
  if (!response.ok) {
    throw new Error(await readErrorMessage(response, '获取漫画生成状态失败，请稍后重试'));
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
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
}

export function generateMangaStream(
  chapterId: number,
  onEvent: (event: MangaProgress) => void,
  size?: string,
  stylePresetName?: string,
  styleRefUrl?: string,
  assetExtraction?: { enabled: boolean; types: Array<'character' | 'scene' | 'prop'> },
): AbortController {
  const controller = new AbortController();

  const body: Record<string, unknown> = {};
  if (size) body.size = size;
  if (stylePresetName) body.style_preset_name = stylePresetName;
  if (styleRefUrl) body.style_ref_url = styleRefUrl;
  if (assetExtraction) {
    body.auto_asset_extraction = assetExtraction;
  }

  fetch(`${BASE}/api/chapters/${chapterId}/generate-manga-stream`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify(body),
    signal: controller.signal,
  })
    .then(async (res) => {
      if (!res.ok) {
        onEvent({ type: 'error', data: { error: await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE) } });
        return;
      }
      const reader = res.body?.getReader();
      if (!reader) {
        onEvent({ type: 'error', data: { error: '漫画生成连接未返回数据，请稍后重试' } });
        return;
      }
      const decoder = new TextDecoder();
      let buffer = '';
      let currentEvent = 'message';
      let terminalReceived = false;
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
            if (eventType === 'done' || eventType === 'error') terminalReceived = true;
            onEvent({ type: eventType, data });
          } catch {
            terminalReceived = true;
            onEvent({ type: 'error', data: { error: '漫画任务返回了无法解析的数据，请刷新后重试' } });
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
      if (!terminalReceived) {
        onEvent({ type: 'error', data: { error: '漫画生成连接意外中断，请稍后重试' } });
      }
    })
    .catch((err) => {
      if (err.name !== 'AbortError') {
        onEvent({ type: 'error', data: { error: normalizeErrorMessage(err, '漫画生成连接失败，请稍后重试') } });
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
        onEvent({ type: 'error', data: { error: await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE) } });
        return;
      }
      const reader = res.body?.getReader();
      if (!reader) {
        onEvent({ type: 'error', data: { error: '角色参考图连接未返回数据，请稍后重试' } });
        return;
      }
      const decoder = new TextDecoder();
      let buffer = '';
      let currentEvent = 'message';
      let terminalReceived = false;
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
            if (eventType === 'done' || eventType === 'error') terminalReceived = true;
            onEvent({ type: eventType, data: parsed });
          } catch {
            terminalReceived = true;
            onEvent({ type: 'error', data: { error: '角色参考图任务返回了无法解析的数据，请刷新后重试' } });
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
      if (!terminalReceived) {
        onEvent({ type: 'error', data: { error: '角色参考图连接意外中断，请稍后重试' } });
      }
    })
    .catch((err) => {
      if (err.name !== 'AbortError') {
        onEvent({ type: 'error', data: { error: normalizeErrorMessage(err, '角色参考图生成连接失败，请稍后重试') } });
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
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
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
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
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
  // Story Bible 与开书框架会串行生成，超时需覆盖后端最慢的合法执行窗口。
  const timer = setTimeout(() => controller.abort(), 1_200_000);
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
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function updateStoryBible(storyId: number, storyBible: Partial<StoryBible>, expectedKnowledgeRevision?: number): Promise<{ story_bible: StoryBible; knowledge_revision?: number }> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/story-bible`, {
    method: 'PATCH',
    headers: apiHeaders(true),
    body: JSON.stringify({ story_bible: storyBible, expected_knowledge_revision: expectedKnowledgeRevision }),
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
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
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
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  const data = await res.json();
  return data.tags ?? data;
}

export async function regenerateCharacters(storyId: number): Promise<Character[]> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/framework/characters`, {
    method: 'POST',
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  const data = await res.json();
  return data.characters ?? data;
}

export async function regenerateOutline(storyId: number): Promise<Outline> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/framework/outline`, {
    method: 'POST',
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
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
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
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
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
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
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function continueFramework(storyId: number): Promise<FrameworkContinueResponse> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/framework/continue`, {
    method: 'POST',
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
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
  const res = await fetch(`${BASE}/api/stories/${storyId}/expand-chapter/task`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return waitForChapterGeneration(await res.json(), 'expand_chapter');
}

export interface ChapterBatchGenerationSubmitResult {
  task_id: string;
  status: string;
  story_id: number;
  total: number;
  chapter_numbers: number[];
  message: string;
}

export interface ChapterBatchProgress {
  stage: string;
  message: string;
  batch_total: number;
  batch_completed: number[];
  batch_failed: Array<{ chapter_number: number; reason: string }>;
  status: string;
  error_message?: string | null;
}

/** 提交批量章节生成任务（串行队列，后台持续执行） */
export async function expandChaptersBatch(storyId: number, chapterNumbers: number[]): Promise<ChapterBatchGenerationSubmitResult> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/expand-chapters/batch`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify({ chapter_numbers: chapterNumbers }),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

/** 查询批量章节生成进度（从任务元数据中提取） */
export async function getChapterBatchProgress(taskId: string): Promise<ChapterBatchProgress> {
  const status = await getBackgroundTaskStatus(taskId);
  const metadata = (status.metadata_json || {}) as Record<string, unknown>;
  return {
    stage: String(metadata.stage || status.status || ''),
    message: String(metadata.message || status.message || ''),
    batch_total: Number(metadata.batch_total || 0),
    batch_completed: Array.isArray(metadata.batch_completed) ? (metadata.batch_completed as number[]) : [],
    batch_failed: Array.isArray(metadata.batch_failed) ? (metadata.batch_failed as Array<{ chapter_number: number; reason: string }>) : [],
    status: status.status,
    error_message: status.error_message ?? null,
  };
}

/** 轮询批量任务直到完成/失败/取消；每章完成时通过 onChapterCompleted 回调通知调用方刷新 UI */
export async function waitForChapterBatch(
  taskId: string,
  onProgress?: (progress: ChapterBatchProgress) => void,
  timeoutMs: number = 3 * 60 * 60 * 1000,
): Promise<ChapterBatchProgress> {
  const deadline = Date.now() + timeoutMs;
  let lastCompletedCount = -1;
  while (Date.now() < deadline) {
    const progress = await getChapterBatchProgress(taskId);
    if (onProgress) onProgress(progress);
    if (progress.batch_completed.length !== lastCompletedCount) {
      lastCompletedCount = progress.batch_completed.length;
    }
    if (
      progress.status === 'succeeded' ||
      progress.status === 'failed' ||
      progress.status === 'cancelled' ||
      progress.stage === 'failed' ||
      progress.stage === 'cancelled' ||
      progress.stage === 'completed'
    ) {
      return progress;
    }
    await new Promise((resolve) => globalThis.setTimeout(resolve, 3000));
  }
  throw new Error(`批量生成等待超时，任务 ${taskId} 仍在后台运行`);
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
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  const data = await res.json();
  return data.rewritten_text ?? data;
}

export async function assessQuality(chapterId: number): Promise<QualityScore> {
  const res = await fetch(`${BASE}/api/chapters/${chapterId}/quality-assess`, {
    method: 'POST',
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  const data = await res.json();
  return data.scores ?? data;
}

export async function scenesFromSelection(
  chapterId: number,
  data: { selected_text: string; character_profiles?: any[]; page_count?: number; preset_id?: number },
): Promise<ScenesPayload & { page_count?: number }> {
  const res = await fetch(`${BASE}/api/chapters/${chapterId}/scenes-from-selection`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export function mangaImageUrl(imagePath: string, cacheBust?: number): string {
  const url = toPublicMangaAssetUrl(imagePath) || '';
  if (!cacheBust || !url) return url;
  const separator = url.includes('?') ? '&' : '?';
  return `${url}${separator}v=${encodeURIComponent(String(cacheBust))}`;
}

/** 获取仅包含当前平台 OSS 图片的浏览器导出清单。 */
export async function getMangaExportManifest(chapterId: number): Promise<MangaExportManifest> {
  const res = await fetch(`${BASE}/api/chapters/${chapterId}/manga-images/export-manifest`, {
    headers: apiHeaders(),
  });
  if (!res.ok) {
    const error = new Error(await readErrorMessage(res, '漫画导出清单获取失败')) as Error & { status?: number };
    error.status = res.status;
    throw error;
  }
  return res.json();
}

export type CanvasPermissionMode = 'plan' | 'auto' | 'ask';
/** 画布变更预览中单个字段的前后对比。 */
export interface CanvasPreviewFieldChange { field: string; before: unknown; after: unknown }
export interface CanvasPreviewNodeItem {
  op: 'add_node' | 'update_node' | 'delete_node';
  node_id: string;
  label: string;
  type?: string;
  changes: CanvasPreviewFieldChange[];
}
export interface CanvasPreviewEdgeItem { op: 'add_edge' | 'delete_edge'; source: string; target: string; source_label: string; target_label: string }
/** 助手提出的画布改动在写入前的预览（由后端按修改前后的图差异生成）。 */
export interface CanvasOpsPreview {
  nodes: CanvasPreviewNodeItem[];
  edges: CanvasPreviewEdgeItem[];
  summary: { added_nodes: number; updated_nodes: number; deleted_nodes: number; added_edges: number; deleted_edges: number };
  errors?: string[];
}
export interface CanvasAgentApproval {
  id: number;
  preview?: CanvasOpsPreview | null;
  canvas_id?: number;
  permission_mode?: CanvasPermissionMode;
  result?: { pending_task?: CanvasAgentPendingTask };
  stage: string;
  summary: string;
  parameters: Record<string, unknown>;
  expected_definition_revision?: number;
  status: string;
}
export interface CanvasAgentPendingTask { canvas_id: number; run_id: number; status: string; permission_mode?: CanvasPermissionMode }
export interface CanvasAgentRequestOptions {
  canvas_permission_mode?: CanvasPermissionMode;
  canvas_approval_id?: number;
  canvas_revision_approval_id?: number;
  canvas_resume_run_id?: number;
  /** 浏览器实时画布图快照（含未保存修改），仅随 video_canvas 工作流上送，后端读取时优先于数据库图 */
  canvas_graph?: VideoCanvasGraph;
  canvas_graph_write_mode?: 'local' | 'server';
  canvas_client_revision?: number;
  /** 用户在画布上当前选中的节点 ID，助手据此定位“这个节点” */
  canvas_selected_node_ids?: string[];
}
export async function getCanvasAgentActions(storyId: number, conversationId: number): Promise<{ actions: CanvasAgentApproval[]; pending_task?: CanvasAgentPendingTask | null }> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/agent/canvas-actions?conversation_id=${conversationId}`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await readErrorMessage(res, '读取待审批阶段失败'));
  return res.json();
}

export function agentChatStream(
  storyId: number,
  conversationId: number,
  content: string,
  chapterId?: number,
  workflowType?: string,
  workflowId?: number,
  shotId?: number,
  enabledSkills?: string[],
  attachmentIds?: string[],
  callbacks?: {
    onToken?: (token: string) => void;
    onToolCall?: (toolCall: { id: string; name: string; args: any; status: 'running' }) => void;
    onToolResult?: (toolCall: { id: string; name: string; args: any; status: 'success' | 'error'; summary?: string }) => void;
    onDone?: (content: string, pendingChanges?: any[], runId?: string) => void;
    onStagePending?: (approval: CanvasAgentApproval) => void;
    onWaiting?: (task: CanvasAgentPendingTask) => void;
    onStatus?: (message: string) => void;
    onCanvasUpdated?: (payload?: { canvas_id?: number; write_mode?: 'local' | 'server'; graph?: VideoCanvasGraph; operations?: unknown[]; client_revision?: number; source?: string }) => void;
    onError?: (error: { message: string; code?: string }) => void;
  },
  canvasOptions?: CanvasAgentRequestOptions,
): AbortController {
  const controller = new AbortController();
  const toolCalls = new Map<string, { id: string; name: string; args: any; status: 'running' | 'success' | 'error'; summary?: string }>();

  fetch(`${BASE}/api/stories/${storyId}/agent/chat`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify({ conversation_id: conversationId, message: content, chapter_id: chapterId, workflow_type: workflowType, workflow_id: workflowId, shot_id: shotId, enabled_skills: enabledSkills, attachment_ids: attachmentIds, ...(workflowType === 'video_canvas' ? canvasOptions : {}) }),
    signal: controller.signal,
  })
    .then(async (res) => {
      if (!res.ok) {
        callbacks?.onError?.({ message: await readErrorMessage(res, 'AI 助手请求失败，请稍后重试') });
        return;
      }
      const reader = res.body?.getReader();
      if (!reader) {
        callbacks?.onError?.({ message: 'AI 助手连接未返回可读取内容，请稍后重试' });
        return;
      }
      const decoder = new TextDecoder();
      let buffer = '';
      let currentEvent = 'message';
      let terminalEventReceived = false;
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
            } else if (currentEvent === 'stage_pending' && data.approval) {
              callbacks?.onStagePending?.(data.approval);
            } else if (currentEvent === 'status' && typeof data.message === 'string') {
              callbacks?.onStatus?.(data.message);
            } else if (currentEvent === 'waiting' && data.pending_task) {
              callbacks?.onWaiting?.(data.pending_task);
            } else if (currentEvent === 'canvas_updated') {
              callbacks?.onCanvasUpdated?.(data);
            } else if (currentEvent === 'done') {
              terminalEventReceived = true;
              if (data.approval) callbacks?.onStagePending?.(data.approval);
              if (data.pending_task) callbacks?.onWaiting?.(data.pending_task);
              callbacks?.onDone?.(data.content ?? '', data.pending_changes, data.run_id);
            } else if (currentEvent === 'error' || data.error) {
              terminalEventReceived = true;
              callbacks?.onError?.({
                message: normalizeErrorMessage(data.error, 'AI 助手执行失败，请稍后重试'),
                code: typeof data.code === 'string' ? data.code : undefined,
              });
            }
          } catch {
            terminalEventReceived = true;
            callbacks?.onError?.({ message: 'AI 助手返回了无法解析的数据，请刷新后重试' });
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
      if (!terminalEventReceived && !controller.signal.aborted) {
        callbacks?.onError?.({ message: 'AI 助手连接意外中断，请重试' });
      }
    })
    .catch((err) => {
      if (err.name !== 'AbortError') {
        callbacks?.onError?.({ message: normalizeErrorMessage(err, 'AI 助手连接失败，请稍后重试') });
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

export async function getAgentPendingChanges(
  storyId: number,
  conversationId: number,
): Promise<{ changes: any[] }> {
  const query = new URLSearchParams({ conversation_id: String(conversationId) });
  const res = await fetch(`${BASE}/api/stories/${storyId}/agent/pending-changes?${query.toString()}`, {
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '获取助手修改记录失败'));
  return res.json();
}

export async function agentConfirmChanges(storyId: number, conversationId?: number | null, runId?: string | null): Promise<void> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/agent/confirm`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify({ ...(conversationId ? { conversation_id: conversationId } : {}), ...(runId ? { run_id: runId } : {}) }),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
}

export interface AgentRollbackResult {
  ok: boolean;
  pending_retained?: boolean;
  results?: Array<{ ok?: boolean; conflict?: boolean; error?: string }>;
}

export async function agentRollbackChanges(storyId: number, conversationId?: number | null, runId?: string | null): Promise<AgentRollbackResult> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/agent/rollback`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify({ ...(conversationId ? { conversation_id: conversationId } : {}), ...(runId ? { run_id: runId } : {}) }),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
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
  storyboard_prompt_stale: boolean;
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
  screenplay_scene_id?: string | null;
  screenplay_beat_id?: string | null;
  narrative_purpose?: string | null;
  beat_density?: string | null;
  transition_to_next?: string | null;
  continuity_json?: Record<string, unknown> | null;
}

export interface AgentAttachment {
  id: string;
  filename: string;
  content_type: string;
  size: number;
  url?: string | null;
}

export async function uploadAgentAttachments(storyId: number, files: File[]): Promise<AgentAttachment[]> {
  const form = new FormData();
  files.forEach((file) => form.append('files', file));
  const res = await fetch(`${BASE}/api/stories/${storyId}/agent/attachments`, {
    method: 'POST',
    headers: apiHeaders(false),
    body: form,
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '附件上传失败'));
  const data = await res.json();
  return data.attachments || [];
}

export interface ChapterVideoShotCreate {
  story_summary: string;
  source_text_span?: string;
  scene_location?: string;
  time_of_day?: string;
  characters?: string[];
  dialogue_or_narration?: string;
  camera_plan?: string;
  motion_plan?: string;
  emotion_plan?: string;
  continuity_notes?: string;
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
  screenplay_text?: string | null;
  screenplay_json?: Record<string, unknown> | null;
  screenplay_status?: string | null;
  screenplay_updated_at?: string | null;
  screenplay_approved_at?: string | null;
  screenplay_version?: number | null;
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

export interface VideoCanvasPort {
  key: string;
  type: string;
  required?: boolean;
  multiple?: boolean;
}

export interface VideoCanvasNodeCatalogItem {
  type: string;
  label: string;
  category: string;
  icon?: string;
  inputs: VideoCanvasPort[];
  outputs: VideoCanvasPort[];
  executable?: boolean;
}

export interface VideoCanvasGraphNode {
  id: string;
  type: string;
  position: { x: number; y: number };
  data: {
    label?: string;
    config?: Record<string, unknown>;
    origin?: Record<string, unknown>;
    [key: string]: unknown;
  };
}

export interface VideoCanvasGraphEdge {
  id: string;
  source: string;
  target: string;
  sourceHandle?: string | null;
  targetHandle?: string | null;
  data?: Record<string, unknown>;
}

export interface VideoCanvasGraph {
  schema_version: number;
  nodes: VideoCanvasGraphNode[];
  edges: VideoCanvasGraphEdge[];
  groups?: unknown[];
  metadata?: Record<string, unknown>;
}

export interface VideoCanvasRunNode {
  id: number;
  node_id: string;
  node_type: string;
  attempt: number;
  status: string;
  input_snapshot?: Record<string, unknown> | null;
  output_snapshot?: Record<string, unknown> | null;
  error_message?: string | null;
}

export interface VideoCanvasRun {
  id: number;
  canvas_id: number;
  canvas_version_id: number;
  status: string;
  scope: Record<string, unknown>;
  plan: { topological_order?: string[]; warnings?: Array<{ message?: string }> };
  error_message?: string | null;
  created_at: string;
  completed_at?: string | null;
  nodes: VideoCanvasRunNode[];
}

export interface VideoCanvas {
  id: number;
  story_id: number;
  default_chapter_id?: number | null;
  name: string;
  description?: string | null;
  status: 'draft' | 'archived';
  definition_revision: number;
  layout_revision: number;
  created_at: string;
  updated_at: string;
  version: { id: number; version_no: number; graph: VideoCanvasGraph; source: string };
  layout: { nodes?: Record<string, { x: number; y: number }>; viewport?: { x: number; y: number; zoom: number } };
  runs?: VideoCanvasRun[];
}

export interface VideoCanvasPlan {
  id: number;
  canvas_id: number;
  story_id: number;
  chapter_id?: number | null;
  status: 'draft' | 'ready' | 'approved' | 'applied';
  revision: number;
  source_snapshot: Record<string, unknown>;
  screenplay: Record<string, unknown>;
  shots: Record<string, unknown>;
  assets: Record<string, unknown>;
  canvas: Record<string, unknown>;
  execution: Record<string, unknown>;
  workflow_id?: number | null;
  applied_canvas_revision?: number | null;
  workflow_sync_revision?: number | null;
  created_at: string;
  updated_at: string;
}

export async function listVideoCanvasNodeCatalog(): Promise<{ node_types: VideoCanvasNodeCatalogItem[] }> {
  const res = await fetch(`${BASE}/api/video-canvas/node-catalog`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

/* ─── 漫剧创作项目（story_type=video） ─── */

export interface MangaDramaProject {
  story_id: number;
  title: string;
  description?: string | null;
  cover_image?: string | null;
  created_at?: string | null;
  canvases: VideoCanvas[];
}

export async function listMangaDramaProjects(): Promise<{ projects: MangaDramaProject[] }> {
  const res = await fetch(`${BASE}/api/manga-drama/projects`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function createMangaDramaProject(payload: {
  title?: string;
  description?: string | null;
  canvas_name?: string;
  idempotency_key?: string;
}): Promise<{ story_id: number; story_title: string; canvas: VideoCanvas }> {
  const res = await fetch(`${BASE}/api/manga-drama/projects`, {
    method: 'POST', headers: apiHeaders(true), body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export interface ScreenplaySplitUnit {
  unit_index: number;
  scene_id: number;
  title: string;
  location: string;
  time_of_day: string;
  characters: string[];
  scene_purpose: string;
  visual_anchors: string;
  beats: Record<string, unknown>[];
  transition_to_next_scene: string;
  duration_seconds: number;
  duration_reason: string;
}

export async function screenplaySplit(canvasId: number, nodeId: string): Promise<{
  ok: boolean;
  node_id: string;
  content_hash: string;
  stale_detected: boolean;
  unit_count: number;
  truncated: boolean;
  units: ScreenplaySplitUnit[];
}> {
  const res = await fetch(`${BASE}/api/video-canvas/canvases/${canvasId}/screenplay-split`, {
    method: 'POST', headers: apiHeaders(true), body: JSON.stringify({ node_id: nodeId }),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export interface DirectorPlanUnit {
  unit_id: string;
  sequence: number;
  title?: string;
  narrative_purpose?: string;
  story_summary?: string;
  duration_seconds: number;
  duration_reason?: string;
  dialogue_or_narration?: string;
  characters?: string[];
  visual_anchors?: { type: string; description: string }[];
  transition_in?: string;
  transition_out?: string;
  continuity?: { from_previous?: string; to_next?: string; anchor?: string };
  storyboard_prompt?: string;
  storyboard_json?: Record<string, unknown> | null;
  beat_ids?: string[];
  scene_ids?: Array<string | number>;
  warnings?: string[];
  video_prompt?: string;
  [key: string]: unknown;
}

export interface DirectorPlan {
  plan_version?: number;
  pacing_strategy?: string;
  units: DirectorPlanUnit[];
  warnings?: string[];
  meta?: { source_screenplay_hash?: string; source_scene_node_id?: string; source_scene_revision?: string };
  [key: string]: unknown;
}

export interface DirectorPlanResult {
  ok: boolean;
  plan: DirectorPlan;
  plan_hash: string;
  unit_count: number;
  total_duration_seconds: number;
  source_screenplay_hash: string;
  source_scene_node_id: string;
  source_scene_revision: string;
  definition_revision: number;
}

export interface CanvasSceneAsset {
  role: 'character' | 'scene' | 'prop';
  name: string;
  prompt: string;
  scene_ids: Array<string | number>;
  unit_count: number;
  /** 角色档案（仅角色） */
  profile?: string;
}

/** 未入选的场景/道具：出现次数少，默认在分镜提示词里一句带过，用户可按需单独生成 */
export interface AssetCandidate {
  role: 'character' | 'scene' | 'prop';
  name: string;
  scene_ids: Array<string | number>;
  desc: string;
}

export async function analyzeCanvasAssets(canvasId: number, sceneNodeId: string, expectedDefinitionRevision?: number): Promise<{
  ok: boolean;
  scene_node_id: string;
  assets: CanvasSceneAsset[];
  candidates?: AssetCandidate[];
  warnings: string[];
  failed_calls: number;
  definition_revision: number;
}> {
  const res = await fetch(`${BASE}/api/video-canvas/canvases/${canvasId}/asset-analysis`, {
    method: 'POST', headers: apiHeaders(true),
    body: JSON.stringify({ scene_node_id: sceneNodeId, ...(expectedDefinitionRevision ? { expected_definition_revision: expectedDefinitionRevision } : {}) }),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function generateDirectorPlan(canvasId: number, payload: {
  scene_node_id: string;
  user_constraints?: string;
  expected_definition_revision?: number;
}): Promise<DirectorPlanResult> {
  const res = await fetch(`${BASE}/api/video-canvas/canvases/${canvasId}/director-plan`, {
    method: 'POST', headers: apiHeaders(true), body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export interface CompiledSceneUnit {
  reference_mode?: string;
  source_beats?: unknown[];
  scene_node_id: string;
  unit_id: string;
  sequence: number;
  title: string;
  video_prompt: string;
  storyboard_prompt?: string;
  storyboard_json?: Record<string, unknown> | null;
  duration_seconds: number;
  duration_requested?: number | null;
  duration_reason?: string;
  duration_policy?: string;
  characters?: unknown[];
  visual_anchors?: unknown[];
  transition_in?: string;
  transition_out?: string;
  continuity?: Record<string, unknown>;
  source_scene_ids?: Array<string | number>;
  source_beat_ids?: string[];
  director_plan_hash?: string;
}

export async function compileScenes(canvasId: number, sceneNodeIds: string[], options?: {
  directorPlan?: DirectorPlan | null;
  directorPlanHash?: string | null;
  expectedDefinitionRevision?: number;
}): Promise<{
  ok: boolean;
  compiled_count: number;
  skipped: { node_id: string; reason: string }[];
  compiled: CompiledSceneUnit[];
}> {
  const res = await fetch(`${BASE}/api/video-canvas/canvases/${canvasId}/compile-scenes`, {
    method: 'POST', headers: apiHeaders(true),
    body: JSON.stringify({
      scene_node_ids: sceneNodeIds,
      ...(options?.directorPlan ? { director_plan: options.directorPlan } : {}),
      ...(options?.directorPlanHash ? { director_plan_hash: options.directorPlanHash } : {}),
      ...(options?.expectedDefinitionRevision ? { expected_definition_revision: options.expectedDefinitionRevision } : {}),
    }),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export interface ImportableNovelChapter {
  chapter_id: number;
  chapter_number: number;
  title: string;
  content_chars: number;
  has_content: boolean;
}

export interface ImportableNovelStory {
  story_id: number;
  title: string;
  chapter_count: number;
  chapters: ImportableNovelChapter[];
}

export async function listImportableNovelStories(): Promise<{ stories: ImportableNovelStory[] }> {
  const res = await fetch(`${BASE}/api/manga-drama/importable-stories`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function importScreenplay(canvasId: number, sources: { story_id: number; chapter_id: number }[]): Promise<{
  ok: boolean;
  screenplay_text: string;
  source_refs: { story_id: number; chapter_id: number; title: string; content_hash: string }[];
  batch_count: number;
  content_chars: number;
}> {
  const res = await fetch(`${BASE}/api/video-canvas/canvases/${canvasId}/import-screenplay`, {
    method: 'POST', headers: apiHeaders(true), body: JSON.stringify({ sources }),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function createVideoCanvas(payload: {
  story_id: number;
  default_chapter_id?: number | null;
  name?: string;
  description?: string | null;
  idempotency_key?: string;
}): Promise<VideoCanvas> {
  const res = await fetch(`${BASE}/api/video-canvas/canvases`, {
    method: 'POST', headers: apiHeaders(true), body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function listVideoCanvases(storyId: number, chapterId?: number): Promise<{ canvases: VideoCanvas[] }> {
  const params = chapterId ? `?chapter_id=${chapterId}` : '';
  const res = await fetch(`${BASE}/api/video-canvas/stories/${storyId}/canvases${params}`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export interface CanvasCostItem {
  node_id: string;
  label: string;
  modality: 'image' | 'video';
  model_id: number | null;
  model_name: string | null;
  video_seconds: number | null;
  points: number | null;
  priced: boolean;
}

export interface CanvasCostEstimate {
  /** platform=平台积分；user_key=自带 API Key（平台不扣积分） */
  credential_mode: 'platform' | 'user_key';
  image_count: number;
  video_count: number;
  video_seconds: number;
  reused_count: number;
  items: CanvasCostItem[];
  warnings: string[];
  total_points: number | null;
  available_points: number | null;
  sufficient: boolean | null;
}

/** 生成前的成本预估（只读）；可带浏览器当前图以包含未保存修改。 */
export interface CanvasPipelineStep {
  stage: string;
  label: string;
  target: string;
  status: 'running' | 'succeeded' | 'failed';
  attempts: number;
  error: string | null;
}

/** 服务端自动编排任务：拆分 → 导演 → 资产 → 分镜编排，在后台运行，失败自动重试。 */
export interface CanvasPipelineTask {
  task_id: string;
  status: string;
  stage: string | null;
  message: string | null;
  error: string | null;
  steps: CanvasPipelineStep[];
  auto_fixes: string[];
  created_at: string | null;
  completed_at: string | null;
}

export async function getCanvasPipeline(canvasId: number): Promise<{ task: CanvasPipelineTask | null }> {
  const res = await fetch(`${BASE}/api/video-canvas/canvases/${canvasId}/pipeline`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await readErrorMessage(res, '获取自动编排进度失败'));
  return res.json();
}

export async function startCanvasPipeline(canvasId: number, userConstraints?: string): Promise<{ task: CanvasPipelineTask | null; already_running: boolean }> {
  const res = await fetch(`${BASE}/api/video-canvas/canvases/${canvasId}/pipeline`, {
    method: 'POST', headers: apiHeaders(true), body: JSON.stringify(userConstraints ? { user_constraints: userConstraints } : {}),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '启动自动编排失败'));
  return res.json();
}

export async function cancelCanvasPipeline(canvasId: number): Promise<{ task: CanvasPipelineTask | null }> {
  const res = await fetch(`${BASE}/api/video-canvas/canvases/${canvasId}/pipeline/cancel`, { method: 'POST', headers: apiHeaders(true) });
  if (!res.ok) throw new Error(await readErrorMessage(res, '取消自动编排失败'));
  return res.json();
}

export type ReviewCheckpointKey = 'script' | 'assets' | 'storyboard';
export type RedoStage = 'director' | 'assets' | 'compile';

export interface CanvasReviewIssue {
  id: string;
  checkpoint: ReviewCheckpointKey;
  code: string;
  severity: 'error' | 'warning';
  message: string;
  node_ids: string[];
  scene_node_id: string | null;
  /** 能靠"从该阶段重做这个场景"修复的问题才有值 */
  redo_stage: RedoStage | null;
  /** 一键即可修好、不需要重做阶段的问题；bind_references = 给视频节点补连角色参考图 */
  action?: 'bind_references' | null;
}

export interface CanvasReviewCheckpoint {
  key: ReviewCheckpointKey;
  label: string;
  status: 'pending' | 'blocked' | 'ready' | 'approved';
  error_count: number;
  warning_count: number;
  issues: CanvasReviewIssue[];
  fingerprint: string;
  approved_at: string | null;
}

export interface CanvasReview {
  checkpoints: Record<ReviewCheckpointKey, CanvasReviewCheckpoint>;
  issue_count: number;
  error_count: number;
  ready_to_generate: boolean;
}

export interface CanvasRedoPreview {
  scene_node_id: string;
  scene_label: string;
  from_stage: RedoStage;
  asset_count: number;
  shot_count: number;
  /** 其中已生成过图片/视频、重做后需要重新生成（重新计费）的数量 */
  generated_count: number;
  kept_locked_count: number;
  node_ids: string[];
}

export async function getCanvasReview(canvasId: number): Promise<{ review: CanvasReview; definition_revision: number }> {
  const res = await fetch(`${BASE}/api/video-canvas/canvases/${canvasId}/review`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await readErrorMessage(res, '获取质检结果失败'));
  return res.json();
}

export async function approveCanvasCheckpoint(canvasId: number, checkpoint: ReviewCheckpointKey): Promise<{ review: CanvasReview; definition_revision: number }> {
  const res = await fetch(`${BASE}/api/video-canvas/canvases/${canvasId}/review/approve`, { method: 'POST', headers: apiHeaders(true), body: JSON.stringify({ checkpoint }) });
  if (!res.ok) throw new Error(await readErrorMessage(res, '确认失败'));
  return res.json();
}

export interface SmartConnectEdge { key: string; edge_id: string | null; source: string; target: string; source_handle: string; target_handle: string; source_label: string; target_label: string }
export interface SmartConnectIssue { severity: 'error' | 'warning' | 'info'; code: string; message: string; node_ids: string[] }
export interface SmartConnectResult { applied: boolean; changed: boolean; risky_removal?: boolean; added: SmartConnectEdge[]; removed: SmartConnectEdge[]; issues: SmartConnectIssue[]; definition_revision: number }

/** 智能连线：apply=false 只预览，apply=true 才写入新版本。不触发生成、不扣费。 */
export async function smartConnectCanvas(canvasId: number, apply: boolean, skip: { added?: string[]; removed?: string[]; confirmRisky?: boolean } = {}): Promise<SmartConnectResult> {
  const res = await fetch(`${BASE}/api/video-canvas/canvases/${canvasId}/smart-connect`, { method: 'POST', headers: apiHeaders(true), body: JSON.stringify({ apply, skip_added: skip.added ?? [], skip_removed: skip.removed ?? [], confirm_risky: skip.confirmRisky === true }) });
  if (!res.ok) throw new Error(await readErrorMessage(res, '智能连线失败'));
  return res.json();
}

/** 每个节点最近一次成功生成的产出（不受“最近 20 次运行”限制），用于补全节点图片 / 视频回显。 */
export async function getCanvasNodeResults(canvasId: number): Promise<{ results: Record<string, { asset_id?: number; file_path?: string; url: string; duration_seconds?: number; reused?: boolean }> }> {
  const res = await fetch(`${BASE}/api/video-canvas/canvases/${canvasId}/node-results`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await readErrorMessage(res, '获取节点结果失败'));
  return res.json();
}

export async function bindCanvasReferences(canvasId: number): Promise<{ added: number; definition_revision: number; review: CanvasReview }> {
  const res = await fetch(`${BASE}/api/video-canvas/canvases/${canvasId}/bind-references`, { method: 'POST', headers: apiHeaders(true) });
  if (!res.ok) throw new Error(await readErrorMessage(res, '补连参考图失败'));
  return res.json();
}

export async function previewCanvasRedo(canvasId: number, sceneNodeId: string, fromStage: RedoStage): Promise<CanvasRedoPreview> {
  const query = new URLSearchParams({ scene_node_id: sceneNodeId, from_stage: fromStage });
  const res = await fetch(`${BASE}/api/video-canvas/canvases/${canvasId}/redo-preview?${query}`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await readErrorMessage(res, '获取重做影响失败'));
  return res.json();
}

export async function redoCanvasScene(canvasId: number, sceneNodeId: string, fromStage: RedoStage, userConstraints?: string, videoModelId?: number | null): Promise<{ task: CanvasPipelineTask | null; summary: CanvasRedoPreview; definition_revision: number }> {
  const res = await fetch(`${BASE}/api/video-canvas/canvases/${canvasId}/redo`, {
    method: 'POST', headers: apiHeaders(true),
    body: JSON.stringify({ scene_node_id: sceneNodeId, from_stage: fromStage, ...(userConstraints ? { user_constraints: userConstraints } : {}), ...(videoModelId ? { video_model_id: videoModelId } : {}) }),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '局部重做失败'));
  return res.json();
}

export async function estimateVideoCanvasCost(canvasId: number, payload: { target_node_ids?: string[]; rerun_node_ids?: string[]; graph?: VideoCanvasGraph }, signal?: AbortSignal): Promise<CanvasCostEstimate> {
  const res = await fetch(`${BASE}/api/video-canvas/canvases/${canvasId}/cost-estimate`, {
    method: 'POST', headers: apiHeaders(true), body: JSON.stringify({ target_node_ids: payload.target_node_ids ?? [], rerun_node_ids: payload.rerun_node_ids ?? [], graph: payload.graph ?? null }), signal,
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '成本预估失败'));
  return res.json();
}

export interface CanvasNodeCandidate {
  asset_id: number;
  url: string;
  run_id: number;
  created_at: string | null;
  duration_seconds?: number | null;
  is_current: boolean;
}

/** 节点的历史生成结果（候选）。 */
export async function listVideoCanvasNodeCandidates(canvasId: number, nodeId: string): Promise<{ node_id: string; candidates: CanvasNodeCandidate[] }> {
  const res = await fetch(`${BASE}/api/video-canvas/canvases/${canvasId}/nodes/${encodeURIComponent(nodeId)}/candidates`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await readErrorMessage(res, '获取候选结果失败'));
  return res.json();
}

export async function getVideoCanvas(canvasId: number): Promise<VideoCanvas> {
  const res = await fetch(`${BASE}/api/video-canvas/canvases/${canvasId}`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function deleteVideoCanvas(canvasId: number): Promise<{ ok: boolean; canvas_id: number }> {
  const res = await fetch(`${BASE}/api/video-canvas/canvases/${canvasId}`, {
    method: 'DELETE', headers: apiHeaders(true),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function updateVideoCanvas(canvasId: number, payload: { name?: string; description?: string | null }): Promise<VideoCanvas> {
  const res = await fetch(`${BASE}/api/video-canvas/canvases/${canvasId}`, {
    method: 'PATCH', headers: apiHeaders(true), body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function listVideoCanvasPlans(canvasId: number): Promise<{ plans: VideoCanvasPlan[] }> {
  const res = await fetch(`${BASE}/api/video-canvas/canvases/${canvasId}/plans`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function getVideoCanvasPlan(canvasId: number, planId: number): Promise<VideoCanvasPlan> {
  const res = await fetch(`${BASE}/api/video-canvas/canvases/${canvasId}/plans/${planId}`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function updateVideoCanvasPlan(canvasId: number, planId: number, payload: {
  expected_revision: number;
  status?: 'draft' | 'ready';
  source_snapshot_json?: Record<string, unknown>;
  screenplay_json?: Record<string, unknown>;
  shot_json?: Record<string, unknown>;
  asset_json?: Record<string, unknown>;
  canvas_json?: Record<string, unknown>;
  execution_json?: Record<string, unknown>;
}): Promise<VideoCanvasPlan> {
  const res = await fetch(`${BASE}/api/video-canvas/canvases/${canvasId}/plans/${planId}`, {
    method: 'PUT', headers: apiHeaders(true), body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function confirmVideoCanvasPlan(canvasId: number, planId: number, expectedRevision: number): Promise<VideoCanvasPlan> {
  const res = await fetch(`${BASE}/api/video-canvas/canvases/${canvasId}/plans/${planId}/confirm`, {
    method: 'POST', headers: apiHeaders(true), body: JSON.stringify({ confirmed: true, expected_revision: expectedRevision }),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function applyVideoCanvasPlan(canvasId: number, planId: number, payload: {
  expected_plan_revision: number;
  expected_definition_revision: number;
}): Promise<{ canvas: VideoCanvas; plan: VideoCanvasPlan; validation: { warnings?: Array<{ message?: string }> } }> {
  const res = await fetch(`${BASE}/api/video-canvas/canvases/${canvasId}/plans/${planId}/apply`, {
    method: 'POST', headers: apiHeaders(true), body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function syncVideoCanvasPlanWorkflow(canvasId: number, planId: number, expectedPlanRevision: number): Promise<{
  plan: VideoCanvasPlan;
  workflow_id: number;
  shot_count: number;
}> {
  const res = await fetch(`${BASE}/api/video-canvas/canvases/${canvasId}/plans/${planId}/sync-workflow`, {
    method: 'POST', headers: apiHeaders(true), body: JSON.stringify({ expected_plan_revision: expectedPlanRevision }),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function saveVideoCanvasSnapshot(canvasId: number, payload: {
  graph: VideoCanvasGraph;
  layout: VideoCanvas['layout'];
  expected_definition_revision: number;
  expected_layout_revision: number;
  client_revision?: number;
  idempotency_key?: string;
}): Promise<VideoCanvas> {
  const res = await fetch(`${BASE}/api/video-canvas/canvases/${canvasId}/snapshot`, {
    method: 'PUT', headers: apiHeaders(true), body: JSON.stringify(payload),
  });
  if (!res.ok) {
    // 带上 HTTP 状态码：调用方要区分“版本冲突 409”（可以自动重发）和其他失败
    const error = new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE)) as Error & { status?: number };
    error.status = res.status;
    throw error;
  }
  return res.json();
}

/** 改写所用的小说原文（章节归属在服务端重新校验，只读）。 */
export interface SourceChapter {
  story_id: number;
  chapter_id: number;
  title: string;
  content: string;
  truncated: boolean;
  content_hash: string;
}

export async function getCanvasSourceChapters(canvasId: number, sources: { story_id: number; chapter_id: number }[]): Promise<{ chapters: SourceChapter[] }> {
  const res = await fetch(`${BASE}/api/video-canvas/canvases/${canvasId}/source-chapters`, {
    method: 'POST', headers: apiHeaders(true), body: JSON.stringify({ sources }),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

/** 画布版本历史条目。 */
export interface VideoCanvasVersionSummary {
  id: number;
  version_no: number;
  source: string;
  change_summary: string | null;
  created_by_user_id: number | null;
  created_at: string | null;
  node_count: number;
  edge_count: number;
  is_current: boolean;
}

export async function listVideoCanvasVersions(canvasId: number, limit = 30): Promise<{ definition_revision: number; versions: VideoCanvasVersionSummary[] }> {
  const res = await fetch(`${BASE}/api/video-canvas/canvases/${canvasId}/versions?limit=${limit}`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await readErrorMessage(res, '读取画布版本历史失败'));
  return res.json();
}

/** 预览“恢复到某版本”会带来的变化（前=当前图，后=目标版本）。 */
export async function diffVideoCanvasVersion(canvasId: number, versionNo: number): Promise<{ version_no: number; current_version_no: number; diff: CanvasOpsPreview }> {
  const res = await fetch(`${BASE}/api/video-canvas/canvases/${canvasId}/versions/${versionNo}/diff`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await readErrorMessage(res, '读取版本差异失败'));
  return res.json();
}

/** 恢复到历史版本：以目标版本内容追加新版本，不改写历史。 */
export async function restoreVideoCanvasVersion(canvasId: number, versionNo: number, expectedDefinitionRevision: number): Promise<VideoCanvas> {
  const res = await fetch(`${BASE}/api/video-canvas/canvases/${canvasId}/versions/${versionNo}/restore`, {
    method: 'POST', headers: apiHeaders(true), body: JSON.stringify({ expected_definition_revision: expectedDefinitionRevision }),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '恢复画布版本失败'));
  return res.json();
}

export async function saveVideoCanvasGraph(canvasId: number, payload: {
  graph: VideoCanvasGraph;
  expected_definition_revision: number;
  change_summary?: string;
  source?: 'manual' | 'import' | 'agent';
}): Promise<VideoCanvas & { validation?: { warnings?: Array<{ message?: string }> } }> {
  const res = await fetch(`${BASE}/api/video-canvas/canvases/${canvasId}/graph`, {
    method: 'PUT', headers: apiHeaders(true), body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function saveVideoCanvasLayout(canvasId: number, payload: {
  layout: VideoCanvas['layout'];
  expected_layout_revision: number;
}): Promise<{ layout: VideoCanvas['layout']; layout_revision: number }> {
  const res = await fetch(`${BASE}/api/video-canvas/canvases/${canvasId}/layout`, {
    method: 'PUT', headers: apiHeaders(true), body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function importVideoCanvasListWorkflow(canvasId: number, payload: {
  source_workflow_id: number;
  mode: 'preview' | 'merge';
  expected_definition_revision?: number;
  idempotency_key?: string;
}): Promise<{ canvas?: VideoCanvas; result?: { added_node_count: number; added_edge_count: number }; graph?: VideoCanvasGraph; node_count?: number; edge_count?: number }> {
  const res = await fetch(`${BASE}/api/video-canvas/canvases/${canvasId}/imports/list-workflow`, {
    method: 'POST', headers: apiHeaders(true), body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function validateVideoCanvas(canvasId: number): Promise<{ valid: boolean; errors: Array<{ message: string }>; warnings: Array<{ message: string }> }> {
  const res = await fetch(`${BASE}/api/video-canvas/canvases/${canvasId}/validate`, {
    method: 'POST', headers: apiHeaders(true),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function runVideoCanvas(canvasId: number, payload: {
  target_node_ids: string[];
  expected_definition_revision: number;
  idempotency_key?: string;
  rerun_node_ids?: string[];
}): Promise<{ idempotent?: boolean; run: VideoCanvasRun; validation: { warnings?: Array<{ message?: string }> } }> {
  const res = await fetch(`${BASE}/api/video-canvas/canvases/${canvasId}/runs`, {
    method: 'POST', headers: apiHeaders(true), body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function confirmVideoCanvasRun(canvasId: number, runId: number): Promise<{ run: VideoCanvasRun }> {
  const res = await fetch(`${BASE}/api/video-canvas/canvases/${canvasId}/runs/${runId}/confirm`, {
    method: 'POST', headers: apiHeaders(true), body: JSON.stringify({ confirmed: true }),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function cancelVideoCanvasRun(canvasId: number, runId: number): Promise<{ run: VideoCanvasRun }> {
  const res = await fetch(`${BASE}/api/video-canvas/canvases/${canvasId}/runs/${runId}/cancel`, {
    method: 'POST', headers: apiHeaders(true),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function getVideoCanvasRun(canvasId: number, runId: number): Promise<{ run: VideoCanvasRun }> {
  const res = await fetch(`${BASE}/api/video-canvas/canvases/${canvasId}/runs/${runId}`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
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
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
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
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
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
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function listSceneShots(sceneId: number): Promise<{ scene_id: number; shots: VideoShot[] }> {
  const res = await fetch(`${BASE}/api/video/scenes/${sceneId}/shots`, {
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function updateVideoShot(shotId: number, payload: Partial<VideoShot>): Promise<VideoShot> {
  const res = await fetch(`${BASE}/api/shots/${shotId}`, {
    method: 'PATCH',
    headers: apiHeaders(true),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function generateShotPrompts(shotId: number, payload: { style?: string; provider?: string; include_references?: boolean; instruction?: string; continuity_notes?: string }): Promise<{ shot: VideoShot }> {
  const res = await fetch(`${BASE}/api/shots/${shotId}/prompts/generate`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
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
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function generateShotCharacterAsset(shotId: number, payload: {
  character_name: string;
  prompt: string;
  style_preset?: string;
  reference_asset_ids?: number[];
  source_asset_ids?: number[];
}): Promise<VideoAsset> {
  const res = await fetch(`${BASE}/api/shots/${shotId}/character-assets/generate`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  const data = await res.json();
  return data.asset;
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
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  const data = await res.json();
  return data.asset;
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
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  const data = await res.json();
  return data.asset;
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
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
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
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function getChapterVideoWorkflow(workflowId: number): Promise<ChapterVideoWorkflow> {
  const res = await fetch(`${BASE}/api/video/chapter-workflows/${workflowId}`, {
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function listChapterVideoWorkflows(chapterId: number): Promise<{ workflows: ChapterVideoWorkflow[]; total: number }> {
  const res = await fetch(`${BASE}/api/video/chapter-workflows/by-chapter/${chapterId}`, {
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function getChapterVideoWorkflowStatus(workflowId: number): Promise<ChapterVideoWorkflowStatus> {
  const res = await fetch(`${BASE}/api/video/chapter-workflows/${workflowId}/status`, {
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
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
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
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
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
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
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function concatChapterVideoWorkflow(workflowId: number): Promise<{ video_url: string; shot_count: number; duration_seconds: number; message?: string }> {
  const res = await fetch(`${BASE}/api/video/chapter-workflows/${workflowId}/concat`, {
    method: 'POST',
    headers: apiHeaders(true),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function listStoryVideoCharacters(storyId: number): Promise<{ characters: StoryVideoCharacter[]; video_character_profiles: string }> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/video-characters`, {
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function generateStoryVideoCharacters(storyId: number): Promise<{ characters: StoryVideoCharacter[]; video_character_profiles: string }> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/video-characters/generate`, {
    method: 'POST',
    headers: apiHeaders(true),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function parseChapterWorkflowShots(workflowId: number): Promise<Record<string, unknown>> {
  const res = await fetch(`${BASE}/api/video/chapter-workflows/${workflowId}/parse`, {
    method: 'POST',
    headers: apiHeaders(true),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
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
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
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
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
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
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
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
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function runAllChapterWorkflowStages(workflowId: number): Promise<Record<string, unknown>> {
  const res = await fetch(`${BASE}/api/video/chapter-workflows/${workflowId}/run-all`, {
    method: 'POST',
    headers: apiHeaders(true),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
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
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
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
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
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
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  const data = await res.json();
  return { job: data.job || data };
}

export async function approveShotStoryboard(shotId: number): Promise<{ storyboard_locked: boolean; storyboard_asset_id: number }> {
  const res = await fetch(`${BASE}/api/shots/${shotId}/storyboard/approve`, {
    method: 'POST',
    headers: apiHeaders(true),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
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
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
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
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
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
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
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
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function createSceneShot(sceneId: number, payload?: Partial<VideoShot>): Promise<VideoShot> {
  const res = await fetch(`${BASE}/api/video/scenes/${sceneId}/shots`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify(payload || {}),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function reorderSceneShots(sceneId: number, payload: { shot_ids: number[] }): Promise<{ scene_id: number; shots: VideoShot[] }> {
  const res = await fetch(`${BASE}/api/video/scenes/${sceneId}/shots/reorder`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
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
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function retryVideoJob(jobId: number, payload?: { provider?: string; model?: string; duration_seconds?: number; aspect_ratio?: string; seed?: number; request_payload?: Record<string, unknown> }): Promise<VideoGenerationJob> {
  const res = await fetch(`${BASE}/api/video-jobs/${jobId}/retry`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify(payload || {}),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  const data = await res.json();
  return data.job;
}

export type MangaAssetType = 'character_reference' | 'scene_reference' | 'prop_reference' | 'style_reference';

export interface MangaAsset {
  id: number;
  story_id: number;
  chapter_id: number | null;
  asset_type: MangaAssetType;
  name: string;
  storage_path: string;
  source_type: string;
  status: string;
  metadata?: Record<string, unknown> | null;
}

export interface MangaAssetBinding {
  id: number;
  asset_id: number;
  binding_role: string;
  label?: string | null;
  priority: number;
  is_required: boolean;
  asset?: MangaAsset;
}

export interface MangaAssetAnalysisSuggestion {
  asset_type: MangaAssetType;
  name: string;
  description: string;
  evidence: string;
  prompt: string;
  candidates: Array<Pick<MangaAsset, 'id' | 'name' | 'asset_type' | 'storage_path'> & { match_score: number; match_reason: string }>;
}

export interface MangaAssetAnalysisResult {
  chapter_id: number;
  suggestions: MangaAssetAnalysisSuggestion[];
  revision: string;
}

export async function listMangaAssets(storyId: number): Promise<{ assets: MangaAsset[] }> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/manga-assets`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

// ── 跨作品资产中心 API ──────────────────────────────────────

/** 跨作品资产类型：漫画图片 / 漫画素材 / 视频素材 / 视频分镜 / 视频成片 */
export type CrossStoryAssetKind =
  | 'manga_image'
  | 'manga_asset'
  | 'video_asset'
  | 'video_storyboard'
  | 'video_shot';

/** 跨作品资产的媒体类型 */
export type CrossStoryAssetMediaType = 'image' | 'video';

/** 跨作品资产中心中的单个资产项（url 可直接用于 <img>/<video> 的 src） */
export interface CrossStoryAsset {
  id: number;
  kind: CrossStoryAssetKind;
  media_type: CrossStoryAssetMediaType;
  story_id: number;
  chapter_id: number | null;
  name: string;
  url: string;
  created_at: string;
  meta: Record<string, unknown>;
}

/** 跨作品资产中心响应：作品列表（用于筛选下拉）+ 资产列表 + 总数 */
export interface CrossStoryAssetList {
  stories: { id: number; title: string }[];
  assets: CrossStoryAsset[];
  total: number;
}

/**
 * 分页查询跨作品资产列表。
 * 支持按类型 kind / 作品 story_id 过滤，limit/offset 分页。
 */
export async function listAssets(params?: { kind?: string; story_id?: number; limit?: number; offset?: number }): Promise<CrossStoryAssetList> {
  const query = new URLSearchParams();
  if (params?.kind) query.set('kind', params.kind);
  if (params?.story_id != null) query.set('story_id', String(params.story_id));
  if (params?.limit != null) query.set('limit', String(params.limit));
  if (params?.offset != null) query.set('offset', String(params.offset));
  const queryString = query.toString();
  const res = await fetch(`${BASE}/api/assets${queryString ? `?${queryString}` : ''}`, {
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function createChapterWorkflowShot(
  workflowId: number,
  payload: ChapterVideoShotCreate,
): Promise<ChapterVideoShot> {
  const res = await fetch(`${BASE}/api/video/chapter-workflows/${workflowId}/shots`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function listMangaAssetBindings(chapterId: number): Promise<{ bindings: MangaAssetBinding[] }> {
  const res = await fetch(`${BASE}/api/chapters/${chapterId}/manga-asset-bindings`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function analyzeChapterMangaAssets(chapterId: number): Promise<MangaAssetAnalysisResult> {
  const res = await fetch(`${BASE}/api/chapters/${chapterId}/manga-assets/analyze`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify({}),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '分析当前章节资产失败'));
  return res.json();
}

export async function getMangaAssetAnalysis(chapterId: number): Promise<MangaAssetAnalysisResult> {
  const res = await fetch(`${BASE}/api/chapters/${chapterId}/manga-assets/analysis`, {
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '读取漫画资产分析失败'));
  return res.json();
}

export async function saveMangaAssetAnalysis(
  chapterId: number,
  suggestions: MangaAssetAnalysisSuggestion[],
  expectedRevision: string,
): Promise<MangaAssetAnalysisResult> {
  const res = await fetch(`${BASE}/api/chapters/${chapterId}/manga-assets/analysis`, {
    method: 'PUT',
    headers: apiHeaders(true),
    body: JSON.stringify({ suggestions, expected_revision: expectedRevision }),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '保存漫画资产提示词失败'));
  return res.json();
}

export async function generateMangaAsset(
  chapterId: number,
  payload: Pick<MangaAssetAnalysisSuggestion, 'asset_type' | 'name' | 'prompt'>,
): Promise<MangaAsset> {
  const res = await fetch(`${BASE}/api/chapters/${chapterId}/manga-assets/generate`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '生成漫画资产失败'));
  return res.json();
}

export interface MangaAssetBatchSubmitResult {
  task_id: string;
  status: string;
  total: number;
  message: string;
}

export interface BackgroundTaskStatus {
  task_id: string;
  task_type: string;
  status: 'pending' | 'running' | 'retrying' | 'succeeded' | 'failed' | 'cancelled' | 'cancel_requested' | string;
  error_message?: string | null;
  result_json?: {
    status?: string;
    message?: string;
    story_id?: number;
    chapter_id?: number;
    chapter_number?: number;
    version?: number;
    content_hash?: string;
    sync_mode?: StoryKnowledgeSyncMode;
    sync_scope?: StoryKnowledgeSyncScope;
    changed_sources?: number;
    successful_sources?: number;
    failed_sources?: number;
    counts?: {
      entities?: number;
      facts?: number;
      plot_threads?: number;
      archived_facts?: number;
    };
    total?: number;
    completed?: number;
    failed?: number;
    items?: Array<Record<string, unknown>>;
  } | null;
  metadata_json?: Record<string, unknown> | null;
  stage?: string | null;
  message?: string | null;
  created_at?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
}

export async function generateMangaAssetsBatch(
  chapterId: number,
  items: Array<Pick<MangaAssetAnalysisSuggestion, 'asset_type' | 'name' | 'prompt'>>,
): Promise<MangaAssetBatchSubmitResult> {
  const res = await fetch(`${BASE}/api/chapters/${chapterId}/manga-assets/generate-batch`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify({ items }),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '提交漫画资产批量生成失败'));
  return res.json();
}

export async function getBackgroundTaskStatus(taskId: string): Promise<BackgroundTaskStatus> {
  const res = await fetch(`${BASE}/api/tasks/${encodeURIComponent(taskId)}`, { headers: apiHeaders() });
  if (!res.ok) {
    const error = new Error(await readErrorMessage(res, '查询后台任务状态失败')) as Error & { status?: number };
    error.status = res.status;
    throw error;
  }
  return res.json();
}

export async function cancelBackgroundTask(taskId: string): Promise<{ ok: boolean; message?: string }> {
  const res = await fetch(`${BASE}/api/tasks/${encodeURIComponent(taskId)}/cancel`, {
    method: 'POST',
    headers: apiHeaders(true),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '停止后台任务失败'));
  return res.json();
}

export async function saveMangaAssetBindings(chapterId: number, bindings: Array<Pick<MangaAssetBinding, 'asset_id' | 'binding_role' | 'label' | 'priority' | 'is_required'>>): Promise<{ bindings: MangaAssetBinding[] }> {
  const res = await fetch(`${BASE}/api/chapters/${chapterId}/manga-asset-bindings`, { method: 'PUT', headers: apiHeaders(true), body: JSON.stringify({ bindings }) });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function uploadMangaAsset(
  storyId: number,
  payload: { file: File; asset_type: MangaAssetType; name: string; chapter_id?: number | null; bind_to_chapter?: boolean; binding_label?: string },
): Promise<MangaAsset> {
  const form = new FormData();
  form.append('file', payload.file);
  form.append('asset_type', payload.asset_type);
  form.append('name', payload.name);
  if (payload.chapter_id != null) form.append('chapter_id', String(payload.chapter_id));
  if (payload.bind_to_chapter) form.append('bind_to_chapter', 'true');
  if (payload.binding_label) form.append('binding_label', payload.binding_label);
  const res = await fetch(`${BASE}/api/stories/${storyId}/manga-assets/upload`, {
    method: 'POST',
    headers: apiHeaders(),
    body: form,
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '上传漫画资产失败'));
  return res.json();
}

export async function updateMangaAsset(assetId: number, payload: Partial<Pick<MangaAsset, 'name' | 'asset_type' | 'chapter_id'>>): Promise<MangaAsset> {
  const res = await fetch(`${BASE}/api/manga-assets/${assetId}`, {
    method: 'PATCH',
    headers: apiHeaders(true),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '更新漫画资产失败'));
  return res.json();
}

export async function redrawMangaAsset(
  assetId: number,
  payload: { prompt: string; mode: ImageRedrawMode; mask?: string; chapter_id?: number; analysis_name?: string },
): Promise<MangaAsset> {
  const res = await fetch(`${BASE}/api/manga-assets/${assetId}/redraw`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '重绘漫画资产失败'));
  return res.json();
}

export async function deleteMangaAsset(assetId: number): Promise<{ ok: boolean }> {
  const res = await fetch(`${BASE}/api/manga-assets/${assetId}/managed`, {
    method: 'DELETE',
    headers: apiHeaders(true),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '删除漫画资产失败'));
  return res.json();
}

export async function listShotClips(shotId: number): Promise<{ shot_id: number; clips: RenderedClip[]; active_clip_id?: number }> {
  const res = await fetch(`${BASE}/api/shots/${shotId}/clips`, {
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function activateShotClip(shotId: number, clipId: number): Promise<{ active_clip_id: number }> {
  const res = await fetch(`${BASE}/api/shots/${shotId}/clips/${clipId}/activate`, {
    method: 'POST',
    headers: apiHeaders(true),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return { active_clip_id: clipId };
}

export async function listStoryVideoAssets(storyId: number, assetType?: string): Promise<{ story_id: number; assets: VideoAsset[] }> {
  const params = assetType ? `?asset_type=${encodeURIComponent(assetType)}` : '';
  const res = await fetch(`${BASE}/api/stories/${storyId}/video-assets${params}`, {
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function createStoryVideoAsset(storyId: number, payload: {
  asset_type: string;
  name: string;
  file_path: string;
  provider?: string;
  prompt?: string;
  meta?: Record<string, unknown>;
}): Promise<VideoAsset> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/video-assets`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function listVideoAssets(chapterId: number, assetType?: string): Promise<{ chapter_id: number; assets: VideoAsset[] }> {
  const params = assetType ? `?asset_type=${encodeURIComponent(assetType)}` : '';
  const res = await fetch(`${BASE}/api/chapters/${chapterId}/video-assets${params}`, {
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
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
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function deleteVideoAsset(assetId: number): Promise<{ ok: boolean; asset_id: number }> {
  const res = await fetch(`${BASE}/api/video-assets/${assetId}`, {
    method: 'DELETE',
    headers: apiHeaders(true),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function updateVideoAsset(assetId: number, payload: { name: string }): Promise<void> {
  const res = await fetch(`${BASE}/api/video-assets/${assetId}`, {
    method: 'PUT',
    headers: apiHeaders(true),
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || '更新资产失败');
  }
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
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function clearShotStoryboard(shotId: number): Promise<{ ok: boolean; shot: ChapterVideoShot }> {
  const res = await fetch(`${BASE}/api/video/chapter-workflows/shots/${shotId}/clear-storyboard`, {
    method: 'POST',
    headers: apiHeaders(true),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function clearShotVideo(shotId: number): Promise<{ ok: boolean; shot: ChapterVideoShot }> {
  const res = await fetch(`${BASE}/api/video/chapter-workflows/shots/${shotId}/clear-video`, {
    method: 'POST',
    headers: apiHeaders(true),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function resetChapterWorkflow(workflowId: number): Promise<{ ok: boolean; workflow_status: string }> {
  const res = await fetch(`${BASE}/api/video/chapter-workflows/${workflowId}/reset`, {
    method: 'POST',
    headers: apiHeaders(true),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function replaceVideoAsset(assetId: number, file: File): Promise<{ ok: boolean; asset: { id: number; file_path: string; revision: number } }> {
  let direct: { object_key: string; url: string } | null = null;
  try {
    direct = await uploadMediaDirectly(file, 'video_asset');
  } catch (error) {
    // 本地开发常因 OSS 未配置 CORS 而无法直传，此时退回后端 multipart 上传。
    console.warn('浏览器直传不可用，已改用服务端上传', error);
  }
  if (direct) {
    try {
      const res = await fetch(`${BASE}/api/video-assets/${assetId}/replace`, {
        method: 'POST',
        headers: apiHeaders(true),
        body: JSON.stringify({ object_key: direct.object_key, filename: file.name }),
      });
      if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
      return res.json();
    } catch (error) {
      // 直传对象已完成但绑定失败时，同样回退到服务端 multipart 上传。
      console.warn('直传资产绑定失败，已改用服务端上传', error);
    }
  }
  const formData = new FormData();
  formData.append('file', file);
  const res = await fetch(`${BASE}/api/video-assets/${assetId}/replace`, {
    method: 'POST',
    headers: apiHeaders(),
    body: formData,
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

type DirectUploadScope = 'video_asset' | 'manga_asset' | 'style_reference' | 'storyboard' | 'video' | 'creation_studio';

async function uploadMediaDirectly(file: File, scope: DirectUploadScope): Promise<{ object_key: string; url: string } | null> {
  const intent = await fetch(`${BASE}/api/media-uploads/presign`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify({ scope, filename: file.name, content_type: file.type, size: file.size }),
  });
  // 兼容尚未部署直传路由的后端，继续使用原有服务端 multipart 上传。
  if (intent.status === 404) return null;
  if (!intent.ok) throw new Error(await readErrorMessage(intent, '获取直传凭证失败'));
  const data = await intent.json() as { mode: 'direct' | 'server'; object_key?: string; upload_url?: string };
  if (data.mode !== 'direct' || !data.object_key || !data.upload_url) return null;
  const upload = await fetch(data.upload_url, { method: 'PUT', body: file });
  if (!upload.ok) throw new Error('文件直传对象存储失败');
  const complete = await fetch(`${BASE}/api/media-uploads/complete`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify({ scope, object_key: data.object_key }),
  });
  if (!complete.ok) throw new Error(await readErrorMessage(complete, '确认直传文件失败'));
  const result = await complete.json() as { object_key: string; public_url: string };
  return { object_key: result.object_key, url: result.public_url };
}

export async function regenerateVideoAsset(assetId: number, prompt?: string, mask?: string, stylePreset?: string): Promise<{ ok: boolean; asset: { id: number; file_path: string; revision: number; style_preset?: string | null } }> {
  const body: Record<string, unknown> = {};
  if (prompt) body.prompt = prompt;
  if (mask) { body.mask = mask; body.mode = 'partial'; }
  if (stylePreset) body.style_preset = stylePreset;
  const res = await fetch(`${BASE}/api/video-assets/${assetId}/regen`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
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
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
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
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function saveChapterShotPrompts(shotId: number, prompts: { storyboard_prompt?: string | null; video_prompt?: string | null; scene_prompt?: string | null; prop_prompts?: Array<{ name: string; prompt: string }> | null }): Promise<{ ok: boolean; shot: ChapterVideoShot }> {
  const res = await fetch(`${BASE}/api/video/chapter-workflows/shots/${shotId}/save-prompts`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify(prompts),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
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
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function getVideoProject(projectId: number): Promise<VideoProject> {
  const res = await fetch(`${BASE}/api/video/projects/${projectId}`, {
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function updateVideoProject(projectId: number, payload: Partial<VideoProject>): Promise<VideoProject> {
  const res = await fetch(`${BASE}/api/video/projects/${projectId}`, {
    method: 'PATCH',
    headers: apiHeaders(true),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
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
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
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
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
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
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function getShotFrames(shotId: number): Promise<ShotFramesResponse> {
  const res = await fetch(`${BASE}/api/shots/${shotId}/frames`, {
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function listChapterShotFrames(chapterId: number): Promise<ChapterShotFramesResponse> {
  const res = await fetch(`${BASE}/api/video/chapters/${chapterId}/frames`, {
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
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

export interface StoryboardPromptPreset {
  id: number;
  preset_key: string | null;
  name: string;
  description: string | null;
  prompt_template: string;
  system_prompt: string | null;
  is_system: boolean;
  story_id: number | null;
  author_user_id: number | null;
  scope: 'system' | 'user';
  is_owner: boolean;
  sort_order: number;
}

export async function listStoryboardPresets(storyId: number): Promise<{ presets: StoryboardPromptPreset[] }> {
  const res = await fetch(`${BASE}/api/storyboard-presets?story_id=${storyId}`, {
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function createStoryboardPreset(data: {
  name: string;
  description?: string;
  prompt_template: string;
  system_prompt?: string;
  story_id: number;
}): Promise<StoryboardPromptPreset> {
  const res = await fetch(`${BASE}/api/storyboard-presets`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function updateStoryboardPreset(
  presetId: number,
  data: Partial<{ name: string; description: string; prompt_template: string; system_prompt: string }>,
): Promise<StoryboardPromptPreset> {
  const res = await fetch(`${BASE}/api/storyboard-presets/${presetId}`, {
    method: 'PUT',
    headers: apiHeaders(true),
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function deleteStoryboardPreset(presetId: number): Promise<{ ok: boolean }> {
  const res = await fetch(`${BASE}/api/storyboard-presets/${presetId}`, {
    method: 'DELETE',
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function duplicateStoryboardPreset(presetId: number, storyId: number): Promise<StoryboardPromptPreset> {
  const res = await fetch(`${BASE}/api/storyboard-presets/${presetId}/duplicate`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify({ story_id: storyId }),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function getStoryStoryboardPreset(storyId: number): Promise<{ preset_id: number | null; preset: StoryboardPromptPreset | null }> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/storyboard-preset`, {
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function setStoryStoryboardPreset(
  storyId: number,
  presetId: number | null,
): Promise<{ preset_id: number | null; preset: StoryboardPromptPreset | null }> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/storyboard-preset`, {
    method: 'PUT',
    headers: apiHeaders(true),
    body: JSON.stringify({ preset_id: presetId }),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function getStoryVideoStylePreset(storyId: number): Promise<{ story_id: number; style_preset_id: number | null; style_preset: VideoStylePreset | null }> {
  const res = await fetch(`${BASE}/api/video/stories/${storyId}/style-preset`, {
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function setStoryVideoStylePreset(storyId: number, stylePresetId: number): Promise<{ story_id: number; style_preset_id: number }> {
  const res = await fetch(`${BASE}/api/video/stories/${storyId}/style-preset`, {
    method: 'PUT',
    headers: apiHeaders(true),
    body: JSON.stringify({ style_preset_id: stylePresetId }),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function setShotVideoStylePreset(shotId: number, stylePreset: string): Promise<{ shot_id: number; style_preset: string }> {
  const res = await fetch(`${BASE}/api/shots/${shotId}/video-style-preset`, {
    method: 'PUT',
    headers: apiHeaders(true),
    body: JSON.stringify({ style_preset: stylePreset }),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function deleteShotVideoStylePreset(shotId: number): Promise<{ shot_id: number; style_preset: null }> {
  const res = await fetch(`${BASE}/api/shots/${shotId}/video-style-preset`, {
    method: 'DELETE',
    headers: apiHeaders(true),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
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
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function updateAssetScope(assetId: number, payload: { usage_scope: string; inherit_to_next_shot?: boolean }): Promise<{ asset_id: number; usage_scope: string; inherit_to_next_shot: boolean }> {
  const res = await fetch(`${BASE}/api/video-assets/${assetId}/scope`, {
    method: 'PUT',
    headers: apiHeaders(true),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function promoteAsset(assetId: number, payload: { level: string; inherit_to_next_shot?: boolean }): Promise<{ asset_id: number; level: string }> {
  const res = await fetch(`${BASE}/api/video-assets/${assetId}/promote`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function listStylePresets(): Promise<{ presets: VideoStylePreset[] }> {
  const res = await fetch(`${BASE}/api/video-style-presets`, {
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
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
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
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
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
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
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function deleteStylePreset(presetId: number): Promise<void> {
  const res = await fetch(`${BASE}/api/video-style-presets/${presetId}`, {
    method: 'DELETE',
    headers: apiHeaders(true),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
}

// ── 搜书 ──────────────────────────────────────────

export interface NovelSearchResult {
  book_id: string;
  title: string;
  author: string;
  genre: string;
  desc: string;
  status: string;
  platform: string;
  url: string;
}

export interface NovelSearchResponse {
  results: NovelSearchResult[];
  total: number;
}

// ── 爬取 ──────────────────────────────────────────

export interface CrawlStatus {
  status: 'not_started' | 'crawling' | 'completed' | 'failed';
  platform: string;
  total_chapters: number | null;
  crawled_chapters: number;
  word_count: number | null;
  source_url: string | null;
}

// ── 拆书 ──────────────────────────────────────────

export interface DeconstructionStatus {
  status: string;
  current_stage: number | null;
  stages_completed: number[];
  progress: string | null;
  result_id: number | null;
}

export interface DeconstructionResult {
  id: number;
  status: string;
  summary: Record<string, any> | null;
  golden_chapters: Record<string, any> | null;
  chapter_summaries: Record<string, any>[] | null;
  characters: Record<string, any>[] | null;
  character_relations: Record<string, any>[] | null;
  plot_lines: Record<string, any>[] | null;
  rhythm: Record<string, any> | null;
  emotion_modules: Record<string, any> | null;
  worldbuilding: Record<string, any> | null;
  report_markdown: string | null;
  writing_style: Record<string, any> | null;
  writing_techniques: Record<string, any>[] | null;
  created_at: string | null;
  updated_at: string | null;
  progress_markdown: string | null;
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
  const res = await fetch(`${BASE}/api/stories/${storyId}/video-characters`, {
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function generateVideoCharacters(storyId: number): Promise<VideoCharactersResponse> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/video-characters/generate`, {
    method: 'POST',
    headers: apiHeaders(true),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function createCharacterVersion(
  storyId: number,
  characterName: string,
  payload: { version_label: string; appearance_card?: string; set_default?: boolean },
): Promise<{ version: CharacterVersion }> {
  const encodedName = encodeURIComponent(characterName);
  const res = await fetch(`${BASE}/api/stories/${storyId}/video-characters/${encodedName}/versions`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  const data = await res.json();
  const raw = data.version ?? {};
  const version: CharacterVersion = {
    id: raw.id ?? Date.now(),
    version: raw.version ?? raw.label ?? payload.version_label,
    label: raw.label ?? raw.version_label ?? payload.version_label,
    appearance_card: raw.appearance_card ?? payload.appearance_card ?? '',
    ref_asset: raw.ref_asset ?? null,
    ref_asset_id: raw.ref_asset_id ?? null,
    ref_asset_url: raw.ref_asset_url ?? raw.ref_asset?.file_path,
    is_default: raw.is_default ?? false,
    sort_order: raw.sort_order ?? 0,
  };
  return { version };
}

export async function deleteCharacterVersion(
  storyId: number,
  characterName: string,
  versionLabel: string | number,
): Promise<{ ok: boolean }> {
  const versionId = String(versionLabel);
  const encodedName = encodeURIComponent(characterName);
  const res = await fetch(`${BASE}/api/stories/${storyId}/video-characters/${encodedName}/versions/${versionId}`, {
    method: 'DELETE',
    headers: apiHeaders(true),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function generateCharacterRefImage(
  storyId: number,
  characterName: string,
  versionId: number,
  stylePreset?: string,
): Promise<VideoAsset> {
  void stylePreset;
  const encodedName = encodeURIComponent(characterName);
  const res = await fetch(`${BASE}/api/stories/${storyId}/video-characters/${encodedName}/versions/${versionId}/generate-ref`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify({}),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  const data = await res.json();
  return { id: data.ref_asset_id, file_path: data.file_path } as VideoAsset;
}

export async function deleteVideoCharacterRefImage(
  storyId: number,
  characterName: string,
  versionId: number,
): Promise<{ ok: boolean }> {
  const encodedName = encodeURIComponent(characterName);
  const res = await fetch(`${BASE}/api/stories/${storyId}/video-characters/${encodedName}/versions/${versionId}/ref`, {
    method: 'DELETE',
    headers: apiHeaders(true),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function redrawCharacterRefImage(
  storyId: number,
  characterName: string,
  versionId: number,
  payload: { prompt: string; mode: ImageRedrawMode; mask?: string },
): Promise<VideoAsset> {
  const encodedName = encodeURIComponent(characterName);
  const res = await fetch(`${BASE}/api/stories/${storyId}/video-characters/${encodedName}/versions/${versionId}/ref/redraw`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  const data = await res.json();
  return { id: data.ref_asset_id, file_path: data.file_path } as VideoAsset;
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

// ── 写作方法论管理 ──

export interface AdminMethodologyResponse {
  [key: string]: { content: string; length: number };
}

export async function getAdminMethodology(): Promise<AdminMethodologyResponse> {
  const res = await fetch(`${BASE}/api/admin/methodology`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await readErrorMessage(res, '获取写作方法论失败'));
  return res.json();
}

export async function updateAdminMethodology(key: string, content: string): Promise<{ ok: boolean; key: string; length: number }> {
  const res = await fetch(`${BASE}/api/admin/methodology`, {
    method: 'PUT',
    headers: apiHeaders(true),
    body: JSON.stringify({ key, content }),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '保存写作方法论失败'));
  return res.json();
}


export async function generateWorkflowScreenplay(workflowId: number): Promise<{ screenplay_status: string; scene_count: number }> {
  const res = await fetch(`${BASE}/api/video/chapter-workflows/${workflowId}/screenplay/generate`, {
    method: 'POST',
    headers: apiHeaders(true),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function saveWorkflowScreenplay(workflowId: number, data: { screenplay_text: string }): Promise<ChapterVideoWorkflow> {
  const res = await fetch(`${BASE}/api/video/chapter-workflows/${workflowId}/screenplay`, {
    method: 'PUT',
    headers: apiHeaders(true),
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function approveWorkflowScreenplay(workflowId: number): Promise<ChapterVideoWorkflow> {
  const res = await fetch(`${BASE}/api/video/chapter-workflows/${workflowId}/screenplay/approve`, {
    method: 'POST',
    headers: apiHeaders(true),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

export async function regenerateWorkflowScreenplay(workflowId: number): Promise<ChapterVideoWorkflow> {
  const res = await fetch(`${BASE}/api/video/chapter-workflows/${workflowId}/screenplay/regenerate`, {
    method: 'POST',
    headers: apiHeaders(true),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}

// ── 搜书 API ──────────────────────────────────────

export async function searchNovels(keyword: string, platform: string = 'qidian', limit: number = 10): Promise<NovelSearchResponse> {
  const params = new URLSearchParams({ keyword, platform, limit: String(limit) });
  const res = await fetch(`${BASE}/api/novels/search?${params}`, {
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error('搜索失败');
  return res.json();
}

// ── 爬取 API ──────────────────────────────────────

export async function startCrawl(storyId: number, bookId: string, platform: string = 'qidian', maxChapters: number = 100): Promise<{ task_id: string; message: string }> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/crawl`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify({ book_id: bookId, platform, max_chapters: maxChapters }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: '爬取失败' }));
    throw new Error(err.detail || '爬取失败');
  }
  return res.json();
}

export async function getCrawlStatus(storyId: number): Promise<CrawlStatus> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/crawl/status`, {
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error('获取状态失败');
  return res.json();
}

// ── 拆书 API ──────────────────────────────────────

export async function startDeconstruction(storyId: number, maxChapters?: number): Promise<{ task_id: string; message: string }> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/deconstruct/start`, {
    method: 'POST',
    headers: apiHeaders(),
    body: JSON.stringify(maxChapters ? { max_chapters: maxChapters } : {}),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: '启动失败' }));
    throw new Error(err.detail || '启动失败');
  }
  return res.json();
}

export async function resumeDeconstruction(storyId: number, mode: 'full' | 'partial' | 'quick_report' = 'full'): Promise<{ task_id: string; message: string }> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/deconstruct/resume`, {
    method: 'POST',
    headers: apiHeaders(),
    body: JSON.stringify({ mode }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: '续跑失败' }));
    throw new Error(err.detail || '续跑失败');
  }
  return res.json();
}

export async function getDeconstructionStatus(storyId: number): Promise<DeconstructionStatus> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/deconstruct/status`, {
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error('获取状态失败');
  return res.json();
}

export async function getDeconstructionResult(storyId: number): Promise<DeconstructionResult> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/deconstruct/result`, {
    headers: apiHeaders(),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: '获取结果失败' }));
    throw new Error(err.detail || '获取结果失败');
  }
  return res.json();
}

export async function cancelDeconstruction(storyId: number): Promise<{ message: string }> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/deconstruct/cancel`, {
    method: 'POST',
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error('取消失败');
  return res.json();
}

export async function applyDeconstructionToBible(storyId: number): Promise<{ message: string }> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/deconstruct/apply-to-bible`, {
    method: 'POST',
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error('注入失败');
  return res.json();
}

// ── 独立拆书库 API ─────────────────────────────────

export interface DeconstructionWorkItem {
  id: number;
  title: string;
  author: string | null;
  platform: string;
  genre: string | null;
  status_label: string | null;
  crawl_status: string;
  decon_status: string;
  total_chapters: number | null;
  crawled_chapters: number;
  word_count: number | null;
  task_id: string | null;
  created_at: string | null;
  updated_at: string | null;
  progress_markdown: string | null;
}

export interface DeconstructionWorkResult {
  id: number;
  title: string;
  author: string | null;
  status: string;
  summary: Record<string, any> | null;
  golden_chapters: Record<string, any> | null;
  chapter_summaries: Record<string, any>[] | null;
  characters: Record<string, any>[] | null;
  character_relations: Record<string, any>[] | null;
  plot_lines: Record<string, any>[] | null;
  rhythm: Record<string, any> | null;
  emotion_modules: Record<string, any> | null;
  worldbuilding: Record<string, any> | null;
  report_markdown: string | null;
  writing_style: Record<string, any> | null;
  writing_techniques: Record<string, any>[] | null;
  created_at: string | null;
  updated_at: string | null;
  progress_markdown: string | null;
}

export interface DeconstructionRefItem {
  id: number;
  work_id: number;
  title: string;
  author: string | null;
  genre: string | null;
  applied_at: string | null;
}

// 通过文件上传创建拆书工作
export async function importDeconstructionFile(file: File, title?: string, author?: string): Promise<{ work_id: number; task_id: string; message: string }> {
  const formData = new FormData();
  formData.append('file', file);
  if (title) formData.append('title', title);
  if (author) formData.append('author', author);

  const keys = getApiKeySettings();
  const token = getAuthToken();
  const mode = getLocalCredentialMode();
  const upstreamBaseUrl = keys.upstreamBaseUrl.trim();
  const headers: Record<string, string> = {};
  if (API_TOKEN) headers['X-API-Token'] = API_TOKEN;
  if (token) headers['Authorization'] = `Bearer ${token}`;
  headers['X-Credential-Mode'] = mode;
  if (mode === 'user_key' && keys.deepseekApiKey) headers['X-DeepSeek-API-Key'] = keys.deepseekApiKey;
  if (mode === 'user_key' && (upstreamBaseUrl || keys.deepseekBaseUrl)) headers['X-DeepSeek-Base-URL'] = upstreamBaseUrl || keys.deepseekBaseUrl;
  if (mode === 'user_key' && keys.deepseekModel) headers['X-DeepSeek-Model'] = keys.deepseekModel;
  if (mode === 'user_key' && keys.imageApiKey) headers['X-Image-API-Key'] = keys.imageApiKey;
  if (mode === 'user_key' && (upstreamBaseUrl || keys.imageBaseUrl)) headers['X-Image-Base-URL'] = upstreamBaseUrl || keys.imageBaseUrl;
  if (mode === 'user_key' && keys.imageModel) headers['X-Image-Model'] = keys.imageModel;
  if (mode === 'user_key' && (upstreamBaseUrl || keys.videoBaseUrl)) headers['X-Video-Base-URL'] = upstreamBaseUrl || keys.videoBaseUrl;
  if (mode === 'user_key' && keys.videoModel) headers['X-Video-Model'] = keys.videoModel;

  const res = await fetch(`${BASE}/api/deconstruct/works/import-file`, {
    method: 'POST',
    headers,
    body: formData,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: '上传失败' }));
    throw new Error(err.detail || '上传失败');
  }
  return res.json();
}

// 搜书（独立拆书库）
export async function searchDeconstructNovels(keyword: string, platform: string = 'qidian', limit: number = 10): Promise<NovelSearchResponse> {
  const params = new URLSearchParams({ keyword, platform, limit: String(limit) });
  const res = await fetch(`${BASE}/api/deconstruct/search?${params}`, {
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error('搜索失败');
  return res.json();
}

// 拆书库列表
export async function listDeconstructionWorks(): Promise<DeconstructionWorkItem[]> {
  const res = await fetch(`${BASE}/api/deconstruct/works`, {
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error('获取拆书库失败');
  return res.json();
}

// 通过上传原文创建拆书工作
export async function importDeconstructionText(data: {
  title: string;
  text: string;
  author?: string;
  platform?: string;
  genre?: string;
}): Promise<{ work_id: number; message: string }> {
  const res = await fetch(`${BASE}/api/deconstruct/works/import-text`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: '导入失败' }));
    throw new Error(err.detail || '导入失败');
  }
  return res.json();
}

// 创建拆书工作 + 爬取
export async function createDeconstructionWork(data: { title: string; book_id: string; platform?: string; author?: string; genre?: string; status_label?: string; max_chapters?: number }): Promise<{ work_id: number; task_id: string; message: string }> {
  const res = await fetch(`${BASE}/api/deconstruct/works`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: '创建失败' }));
    throw new Error(err.detail || '创建失败');
  }
  return res.json();
}

// 爬取状态
export async function getDeconstructWorkCrawlStatus(workId: number): Promise<CrawlStatus> {
  const res = await fetch(`${BASE}/api/deconstruct/works/${workId}/crawl/status`, {
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error('获取状态失败');
  return res.json();
}

// 启动拆书
export async function startDeconstructWork(workId: number, maxChapters?: number): Promise<{ task_id: string; message: string }> {
  const res = await fetch(`${BASE}/api/deconstruct/works/${workId}/start`, {
    method: 'POST',
    headers: apiHeaders(),
    body: JSON.stringify(maxChapters ? { max_chapters: maxChapters } : {}),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: '启动失败' }));
    throw new Error(err.detail || '启动失败');
  }
  return res.json();
}

// 拆书状态
export async function getDeconstructWorkStatus(workId: number): Promise<DeconstructionStatus & { work_id: number }> {
  const res = await fetch(`${BASE}/api/deconstruct/works/${workId}/status`, {
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error('获取状态失败');
  return res.json();
}

// 拆书结果
export async function resumeDeconstructWork(workId: number, mode: 'full' | 'partial' | 'quick_report' = 'full', maxChapters?: number): Promise<{ task_id: string; message: string }> {
  const res = await fetch(`${BASE}/api/deconstruct/works/${workId}/resume`, {
    method: 'POST',
    headers: apiHeaders(),
    body: JSON.stringify({ mode, max_chapters: maxChapters }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: '续跑失败' }));
    throw new Error(err.detail || '续跑失败');
  }
  return res.json();
}

export async function getDeconstructWorkResult(workId: number): Promise<DeconstructionWorkResult> {
  const res = await fetch(`${BASE}/api/deconstruct/works/${workId}/result`, {
    headers: apiHeaders(),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: '获取结果失败' }));
    throw new Error(err.detail || '获取结果失败');
  }
  return res.json();
}

// ── 作者风格/套路提取 ─────────────────────────────

export interface AuthorStyleStatus {
  status: 'not_started' | 'pending' | 'running' | 'completed' | 'failed';
  progress?: string | null;
  task_id?: string | null;
  work_id: number;
}

export interface AuthorStyleResult {
  work_id: number;
  title: string;
  author?: string | null;
  status: string;
  profile?: Record<string, unknown> | null;
  report_markdown?: string | null;
  progress?: string | null;
}

export async function startAuthorStyleAnalysis(workId: number): Promise<{ task_id: string; message: string }> {
  const res = await fetch(`${BASE}/api/deconstruct/works/${workId}/author-style/start`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify({}),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '启动作者画像失败'));
  return res.json();
}

export async function getAuthorStyleStatus(workId: number): Promise<AuthorStyleStatus> {
  const res = await fetch(`${BASE}/api/deconstruct/works/${workId}/author-style/status`, {
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '获取作者画像状态失败'));
  return res.json();
}

export async function getAuthorStyleResult(workId: number): Promise<AuthorStyleResult> {
  const res = await fetch(`${BASE}/api/deconstruct/works/${workId}/author-style/result`, {
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '获取作者画像结果失败'));
  return res.json();
}

export async function updateDeconstructionReport(
  workId: number,
  data: { report_markdown: string }
): Promise<{ ok: boolean; report_markdown: string }> {
  const res = await fetch(`${BASE}/api/deconstruct/works/${workId}/report`, {
    method: 'PATCH',
    headers: apiHeaders(true),
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '保存报告失败'));
  return res.json();
}

export async function updateAuthorStyleReport(
  workId: number,
  data: { report_markdown: string }
): Promise<{ ok: boolean; report_markdown: string }> {
  const res = await fetch(`${BASE}/api/deconstruct/works/${workId}/author-style/report`, {
    method: 'PATCH',
    headers: apiHeaders(true),
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '保存作者画像报告失败'));
  return res.json();
}

// 取消拆书
export async function cancelDeconstructWork(workId: number): Promise<{ message: string }> {
  const res = await fetch(`${BASE}/api/deconstruct/works/${workId}/cancel`, {
    method: 'POST',
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error('取消失败');
  return res.json();
}

// 删除拆书工作
export async function deleteDeconstructionWork(workId: number): Promise<{ message: string }> {
  const res = await fetch(`${BASE}/api/deconstruct/works/${workId}`, {
    method: 'DELETE',
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error('删除失败');
  return res.json();
}

// 引用拆书结果到作品
export async function addDeconstructionRef(storyId: number, workId: number): Promise<{ message: string }> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/deconstruct/refs`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify({ work_id: workId }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: '引用失败' }));
    throw new Error(err.detail || '引用失败');
  }
  return res.json();
}

// 查看作品引用的拆书结果
export async function listDeconstructionRefs(storyId: number): Promise<DeconstructionRefItem[]> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/deconstruct/refs`, {
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error('获取引用列表失败');
  return res.json();
}

// 取消引用
export async function removeDeconstructionRef(storyId: number, refId: number): Promise<{ message: string }> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/deconstruct/refs/${refId}`, {
    method: 'DELETE',
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error('取消引用失败');
  return res.json();
}

export type CredentialMode = 'platform' | 'user_key';

export interface PointsAccount {
  user_id: number;
  available_points: number;
  reserved_points: number;
  updated_at?: string | null;
}

export interface PointsLedgerItem {
  id: number;
  entry_type: string;
  amount: number;
  balance_after?: number | null;
  created_at?: string | null;
  metadata?: Record<string, unknown>;
  usage_event_id?: number | null;
  usage_detail?: {
    request_id?: string | null;
    model_key?: string | null;
    task_type?: string | null;
    status?: string | null;
    input_tokens?: number;
    output_tokens?: number;
    settled_points?: number;
    stream_charged_points?: number | null;
    billing_type?: string | null;
    points_per_1m_tokens?: number | null;
    input_points_per_1m?: number | null;
    output_points_per_1m?: number | null;
    streaming?: boolean;
  } | null;
}

export interface PointsLedgerParams {
  page?: number;
  page_size?: number;
  start_date?: string;
  end_date?: string;
  entry_type?: string;
  direction?: 'income' | 'expense';
}

export interface PointsLedgerResponse {
  items: PointsLedgerItem[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface PointsProduct {
  id: number;
  code: string;
  name: string;
  description: string;
  price_cny: number;
  points: number;
  bonus_points: number;
  is_visible: boolean;
  is_recommended: boolean;
  sort_order: number;
}

export interface AiModelItem {
  id: number;
  model_key: string;
  display_name: string;
  intro_tag: string;
  modality: string;
  channel_id: number;
  sort_order: number;
  video_capabilities?: VideoModelCapabilities;
  image_capabilities?: ImageModelCapabilities;
  estimated_points?: number | null;
  platform_configured: boolean;
  price?: {
    billing_type: string;
    price_config: Record<string, unknown>;
    estimated_points?: number;
  } | null;
}

export interface VideoModelCapabilities {
  input_modes?: string[];
  defaults?: {
    duration_seconds?: number;
    aspect_ratio?: string;
    resolution?: string;
  };
  limits?: {
    duration_seconds?: { min?: number; max?: number; allowed?: number[] };
    aspect_ratios?: string[];
    resolutions?: string[];
    max_reference_images?: number;
  };
}

export interface ImageModelCapabilities {
  defaults?: { quality?: 'auto' | 'high' | 'medium' | 'low' };
  limits?: { qualities?: Array<'auto' | 'high' | 'medium' | 'low'> };
}

export interface AiCredentialStatus {
  modality?: AiModality;
  configured: boolean;
  status: string;
  last_four?: string | null;
  last_validated_at?: string | null;
}

export type AiModality = 'text' | 'image' | 'video';

export interface AiModalityCredentialsStatus {
  credentials: Record<AiModality, AiCredentialStatus>;
  configured_count: number;
}

export interface AiPreferences {
  credential_mode: CredentialMode;
  default_text_model_id?: number | null;
  default_image_model_id?: number | null;
  default_video_model_id?: number | null;
}

export interface AiChannelAdmin {
  id: number;
  code: string;
  name: string;
  adapter_type: VideoAdapterType | string;
  base_url: string;
  modality: string;
  enabled: boolean;
  timeout_seconds: number;
  extra_config_json?: Record<string, unknown>;
  has_platform_key?: boolean;
  last_four?: string | null;
}

export interface AiChannelItem {
  id: number;
  code: string;
  name: string;
  base_url: string;
  modality: string;
}

export interface AiModelAdmin {
  id: number;
  channel_id: number;
  model_key: string;
  display_name: string;
  intro_tag: string;
  modality: string;
  enabled: boolean;
  user_visible: boolean;
  sort_order: number;
  capabilities_json?: Record<string, unknown>;
  active_price?: {
    id: number;
    billing_type: string;
    price_config_json: Record<string, unknown>;
    valid_from?: string | null;
  } | null;
}

export interface PointsSettings {
  yuan_to_points: number;
  register_grant_enabled: boolean;
  register_grant_amount: number;
  dual_track_enabled: boolean;
  allow_all_users_api_key_override: boolean;
}

export function getLocalCredentialMode(): CredentialMode {
  const v = getScopedApiSetting(LS_CREDENTIAL_MODE);
  return v === 'user_key' ? 'user_key' : 'platform';
}

export function setLocalCredentialMode(mode: CredentialMode): void {
  setScopedApiSetting(LS_CREDENTIAL_MODE, mode);
}

export type VideoAdapterType = 'openai_video' | 'lingdong_video';

export interface AdminAiChannelPayload {
  code?: string;
  name: string;
  adapter_type?: VideoAdapterType;
  base_url: string;
  modality: string;
  platform_api_key?: string;
  extra_config_json: Record<string, unknown>;
}

export function apiHeadersWithCredentialMode(json = false, mode?: CredentialMode): HeadersInit {
  const headers = { ...apiHeaders(json) } as Record<string, string>;
  const m = mode || getLocalCredentialMode();
  headers['X-Credential-Mode'] = m;
  return headers;
}

export async function getPointsAccount(): Promise<PointsAccount> {
  const res = await fetch(`${BASE}/api/points/account`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await readErrorMessage(res, '获取积分账户失败'));
  return res.json();
}

export async function getPointsLedger(
  params: PointsLedgerParams | number = {},
  signal?: AbortSignal,
): Promise<PointsLedgerResponse> {
  const normalized: PointsLedgerParams = typeof params === 'number' ? { page_size: params } : params;
  const search = new URLSearchParams();
  if (normalized.page != null) search.set('page', String(normalized.page));
  if (normalized.page_size != null) search.set('page_size', String(normalized.page_size));
  if (normalized.start_date) search.set('start_date', normalized.start_date);
  if (normalized.end_date) search.set('end_date', normalized.end_date);
  if (normalized.entry_type) search.set('entry_type', normalized.entry_type);
  if (normalized.direction) search.set('direction', normalized.direction);
  const query = search.toString();
  const res = await fetch(`${BASE}/api/points/ledger${query ? `?${query}` : ''}`, { headers: apiHeaders(), signal });
  if (!res.ok) throw new Error(await readErrorMessage(res, '获取积分流水失败'));
  return res.json();
}

export async function getPointsProducts(): Promise<{ products: PointsProduct[] }> {
  const res = await fetch(`${BASE}/api/points/products`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await readErrorMessage(res, '获取积分套餐失败'));
  return res.json();
}

export async function purchasePoints(productId: number, paymentMethod?: string): Promise<{
  ok: boolean;
  order_no: string;
  amount: number;
  status: string;
  product_id: number;
  points: number;
  checkout: BillingCheckout;
}> {
  const res = await fetch(`${BASE}/api/points/purchase`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify({ product_id: productId, payment_method: paymentMethod }),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '创建充值订单失败'));
  return res.json();
}

export async function getAiCredential(): Promise<AiCredentialStatus> {
  const res = await fetch(`${BASE}/api/ai/credential`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await readErrorMessage(res, '获取 API Key 状态失败'));
  return res.json();
}

export async function saveAiCredential(apiKey: string): Promise<AiCredentialStatus> {
  const res = await fetch(`${BASE}/api/ai/credential`, {
    method: 'PUT',
    headers: apiHeaders(true),
    body: JSON.stringify({ api_key: apiKey }),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '保存 API Key 失败'));
  return res.json();
}

export async function deleteAiCredential(): Promise<void> {
  const res = await fetch(`${BASE}/api/ai/credential`, {
    method: 'DELETE',
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '清除 API Key 失败'));
}

export async function testAiCredential(apiKey?: string): Promise<{ ok: boolean; status_code?: number }> {
  const draftKey = apiKey?.trim();
  const res = await fetch(`${BASE}/api/ai/credential/test`, {
    method: 'POST',
    headers: apiHeaders(Boolean(draftKey)),
    ...(draftKey ? { body: JSON.stringify({ api_key: draftKey }) } : {}),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '测试 API Key 失败'));
  return res.json();
}

export async function getAiCredentials(): Promise<AiModalityCredentialsStatus> {
  const res = await fetch(`${BASE}/api/ai/credentials`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await readErrorMessage(res, '获取分类 API Key 状态失败'));
  return res.json();
}

export async function saveAiModalityCredential(modality: AiModality, apiKey: string): Promise<AiCredentialStatus> {
  const res = await fetch(`${BASE}/api/ai/credentials/${modality}`, {
    method: 'PUT',
    headers: apiHeaders(true),
    body: JSON.stringify({ api_key: apiKey }),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, `保存${modality} API Key 失败`));
  return res.json();
}

export async function deleteAiModalityCredential(modality: AiModality): Promise<void> {
  const res = await fetch(`${BASE}/api/ai/credentials/${modality}`, {
    method: 'DELETE',
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, `清除${modality} API Key 失败`));
}

export async function testAiModalityCredential(
  modality: AiModality,
  apiKey?: string,
): Promise<{ ok: boolean; verified: boolean; modality: AiModality; status_code?: number; message?: string }> {
  const draftKey = apiKey?.trim();
  const res = await fetch(`${BASE}/api/ai/credentials/${modality}/test`, {
    method: 'POST',
    headers: apiHeaders(Boolean(draftKey)),
    ...(draftKey ? { body: JSON.stringify({ api_key: draftKey }) } : {}),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, `测试${modality} API Key 失败`));
  return res.json();
}

export async function getAiPreferences(): Promise<AiPreferences> {
  const res = await fetch(`${BASE}/api/ai/preferences`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await readErrorMessage(res, '获取 AI 偏好失败'));
  return res.json();
}

export async function saveAiPreferences(payload: Partial<AiPreferences>): Promise<AiPreferences> {
  const res = await fetch(`${BASE}/api/ai/preferences`, {
    method: 'PUT',
    headers: apiHeaders(true),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '保存 AI 偏好失败'));
  return res.json();
}

export async function getAiModels(modality?: string): Promise<{ models: AiModelItem[] }> {
  const q = modality ? `?modality=${encodeURIComponent(modality)}` : '';
  const res = await fetch(`${BASE}/api/ai/models${q}`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await readErrorMessage(res, '获取模型列表失败'));
  return res.json();
}

/** 模型广场展示用的模型信息（不含渠道与密钥配置状态） */
export type PublicAiModelItem = Omit<AiModelItem, 'channel_id' | 'platform_configured'>;

/** 获取公开模型广场数据（无需登录） */
export async function getPublicAiModels(modality?: string): Promise<{ models: PublicAiModelItem[] }> {
  const q = modality ? `?modality=${encodeURIComponent(modality)}` : '';
  const res = await fetch(`${BASE}/api/public/ai-models${q}`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await readErrorMessage(res, '获取模型列表失败'));
  return res.json();
}

export async function getAiChannels(): Promise<{ channels: AiChannelItem[] }> {
  const res = await fetch(`${BASE}/api/ai/channels`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await readErrorMessage(res, '获取 AI 渠道失败'));
  return res.json();
}

export async function estimateAiPoints(payload: {
  model_id: number;
  input_tokens?: number;
  output_tokens?: number;
  image_count?: number;
  video_seconds?: number;
}): Promise<{ model_id: number; estimated_points: number; available_points: number; sufficient: boolean }> {
  const res = await fetch(`${BASE}/api/ai/estimate`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '费用预估失败'));
  return res.json();
}

export async function getAdminAiChannels(): Promise<{ channels: AiChannelAdmin[] }> {
  const res = await fetch(`${BASE}/api/admin/ai/channels`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await readErrorMessage(res, '获取渠道失败'));
  return res.json();
}

export async function createAdminAiChannel(payload: AdminAiChannelPayload & { code: string }): Promise<AiChannelAdmin> {
  const res = await fetch(`${BASE}/api/admin/ai/channels`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '创建渠道失败'));
  return res.json();
}

export async function updateAdminAiChannel(id: number, payload: AdminAiChannelPayload): Promise<AiChannelAdmin> {
  const res = await fetch(`${BASE}/api/admin/ai/channels/${id}`, {
    method: 'PUT',
    headers: apiHeaders(true),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '更新渠道失败'));
  return res.json();
}

export async function deleteAdminAiChannel(id: number): Promise<{ ok: boolean; channel_id: number }> {
  const res = await fetch(`${BASE}/api/admin/ai/channels/${id}`, {
    method: 'DELETE',
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '删除渠道失败'));
  return res.json();
}

export async function getAdminAiModels(channelId?: number): Promise<{ models: AiModelAdmin[] }> {
  const q = channelId ? `?channel_id=${channelId}` : '';
  const res = await fetch(`${BASE}/api/admin/ai/models${q}`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await readErrorMessage(res, '获取模型失败'));
  return res.json();
}

export async function createAdminAiModel(payload: Record<string, unknown>): Promise<AiModelAdmin> {
  const res = await fetch(`${BASE}/api/admin/ai/models`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '创建模型失败'));
  return res.json();
}

export async function updateAdminAiModel(id: number, payload: Record<string, unknown>): Promise<AiModelAdmin> {
  const res = await fetch(`${BASE}/api/admin/ai/models/${id}`, {
    method: 'PUT',
    headers: apiHeaders(true),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '更新模型失败'));
  return res.json();
}

export async function deleteAdminAiModel(id: number): Promise<{ ok: boolean }> {
  const res = await fetch(`${BASE}/api/admin/ai/models/${id}`, {
    method: 'DELETE',
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '删除模型失败'));
  return res.json();
}

export interface UpstreamAiModelCandidate {
  key: string;
  display_name: string;
  capabilities: Record<string, unknown> | null;
}

export interface AiPriceSyncItem {
  model_id: number;
  model_key: string;
  display_name: string;
  modality: string;
  status: 'ready' | 'unchanged' | 'skipped';
  reason?: string | null;
  current_price: {
    id: number;
    billing_type: string;
    price_config_json: Record<string, unknown>;
  } | null;
  proposed_price: {
    billing_type: string;
    price_config_json: Record<string, unknown>;
  } | null;
  upstream_price: Record<string, unknown> | null;
  cache_ignored?: boolean;
}

export interface AiPriceSyncPreview {
  channel: { id: number; code: string; name: string; modality: string };
  yuan_to_points: number;
  yuan_per_point: number;
  upstream: {
    currency: string;
    quota_per_unit: number;
    group: string;
    group_ratio: number;
    pricing_version: string;
  };
  summary: {
    total: number;
    ready: number;
    unchanged: number;
    skipped: number;
  };
  items: AiPriceSyncItem[];
}

export async function discoverAdminAiChannelModels(channelId: number): Promise<{ upstream_count: number; candidates: UpstreamAiModelCandidate[] }> {
  const res = await fetch(`${BASE}/api/admin/ai/channels/${channelId}/models/sync`, {
    method: 'POST',
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '获取上游模型失败'));
  return res.json();
}

export async function addAdminAiChannelModels(
  channelId: number,
  models: UpstreamAiModelCandidate[],
): Promise<{ added: string[]; existing: string[] }> {
  const res = await fetch(`${BASE}/api/admin/ai/channels/${channelId}/models`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify({ models }),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '添加上游模型失败'));
  return res.json();
}

export async function previewAdminAiChannelPrices(channelId: number): Promise<AiPriceSyncPreview> {
  const res = await fetch(`${BASE}/api/admin/ai/channels/${channelId}/prices/preview`, {
    method: 'POST',
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '获取上游定价失败'));
  return res.json();
}

export async function syncAdminAiChannelPrices(
  channelId: number,
  payload: {
    model_ids: number[];
    expected_price_ids: Record<string, number | null>;
    expected_pricing_version: string;
    expected_yuan_to_points: number;
  },
): Promise<{ updated: number[]; unchanged: number[]; skipped: Array<{ model_id: number; reason: string }> }> {
  const res = await fetch(`${BASE}/api/admin/ai/channels/${channelId}/prices/sync`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '同步模型定价失败'));
  return res.json();
}

export async function setAdminAiModelPrice(
  modelId: number,
  payload: { billing_type: string; price_config_json: Record<string, unknown> },
): Promise<{ id: number; model_id: number; billing_type: string }> {
  const res = await fetch(`${BASE}/api/admin/ai/models/${modelId}/prices`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '设置积分价失败'));
  return res.json();
}

export async function getAdminPointsSettings(): Promise<PointsSettings> {
  const res = await fetch(`${BASE}/api/admin/points/settings`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await readErrorMessage(res, '获取积分设置失败'));
  return res.json();
}

export async function saveAdminPointsSettings(payload: Partial<PointsSettings>): Promise<PointsSettings> {
  const res = await fetch(`${BASE}/api/admin/points/settings`, {
    method: 'PUT',
    headers: apiHeaders(true),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '保存积分设置失败'));
  return res.json();
}

export async function adminAdjustPoints(payload: {
  user_id: number;
  amount: number;
  note?: string;
  request_id: string;
}): Promise<PointsAccount> {
  const res = await fetch(`${BASE}/api/admin/points/adjust`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '调账失败'));
  return res.json();
}

export async function grantAdminUserPoints(
  userId: number,
  payload: { amount: number; note?: string; request_id: string },
): Promise<PointsAccount> {
  const res = await fetch(`${BASE}/api/admin/users/${userId}/points`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '添加积分失败'));
  return res.json();
}

export async function getAdminPointsProducts(): Promise<{ products: PointsProduct[] }> {
  const res = await fetch(`${BASE}/api/admin/points/products`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await readErrorMessage(res, '获取积分套餐失败'));
  return res.json();
}

export async function createAdminPointsProduct(
  payload: Omit<PointsProduct, 'id'>,
): Promise<PointsProduct> {
  const res = await fetch(`${BASE}/api/admin/points/products`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '创建积分套餐失败'));
  return res.json();
}

export async function updateAdminPointsProduct(
  productId: number,
  payload: Partial<Omit<PointsProduct, 'id'>>,
): Promise<PointsProduct> {
  const res = await fetch(`${BASE}/api/admin/points/products/${productId}`, {
    method: 'PUT',
    headers: apiHeaders(true),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '更新积分套餐失败'));
  return res.json();
}

export async function deleteAdminPointsProduct(productId: number): Promise<{ ok: boolean; archived: boolean }> {
  const res = await fetch(`${BASE}/api/admin/points/products/${productId}`, {
    method: 'DELETE',
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '删除积分套餐失败'));
  return res.json();
}

export type CreationStudioMediaKind = 'image' | 'video';
export type CreationStudioJobStatus =
  | 'queued'
  | 'running'
  | 'cancel_requested'
  | 'cancelled'
  | 'succeeded'
  | 'failed';

export interface CreationStudioAsset {
  id: number;
  job_id: number | null;
  media_type: CreationStudioMediaKind;
  role: 'upload' | 'output';
  public_url: string;
  original_name: string | null;
  mime_type: string | null;
  file_size: number | null;
  width: number | null;
  height: number | null;
  duration_seconds: number | null;
  status: string;
  created_at: string;
}

export interface CreationStudioJob {
  id: number;
  media_kind: CreationStudioMediaKind;
  generation_mode: string;
  prompt: string;
  negative_prompt: string | null;
  model_id: number | null;
  model_key: string | null;
  model_display_name: string | null;
  parameters: Record<string, string | number | boolean | null>;
  status: CreationStudioJobStatus;
  stage: string;
  progress: number;
  background_task_id: string | null;
  provider_job_id: string | null;
  error_message: string | null;
  retry_of_job_id: number | null;
  inputs: CreationStudioAsset[];
  output: CreationStudioAsset | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  updated_at: string;
}

export interface CreationStudioJobCreate {
  media_kind: CreationStudioMediaKind;
  prompt: string;
  negative_prompt?: string;
  model_id?: number;
  asset_ids?: number[];
  count?: number;
  width?: number;
  height?: number;
  quality?: 'auto' | 'high' | 'medium' | 'low';
  reference_mode?: 'character' | 'style';
  aspect_ratio?: '16:9' | '9:16' | '1:1' | '4:3' | '3:4';
  resolution?: '480P' | '720P' | '1080P' | '1K' | '2K' | '4K';
  duration_seconds?: number;
}

export async function listCreationStudioAssets(): Promise<{ assets: CreationStudioAsset[] }> {
  const res = await fetch(`${BASE}/api/creation-studio/assets`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await readErrorMessage(res, '获取参考素材失败'));
  return res.json();
}

export async function uploadCreationStudioAsset(file: File): Promise<{ asset: CreationStudioAsset; deduplicated: boolean }> {
  const form = new FormData();
  form.append('file', file);
  form.append('media_type', 'image');
  const res = await fetch(`${BASE}/api/creation-studio/assets`, {
    method: 'POST',
    headers: apiHeaders(),
    body: form,
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '上传参考图片失败'));
  return res.json();
}

export async function analyzeCreationStudioAssets(
  assetIds: number[],
  instruction?: string,
): Promise<{ analysis: string; asset_ids: number[] }> {
  const res = await fetch(`${BASE}/api/creation-studio/assets/analyze`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify({ asset_ids: assetIds, instruction }),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '参考素材分析失败'));
  return res.json();
}

export async function deleteCreationStudioAsset(assetId: number): Promise<{ ok: boolean }> {
  const res = await fetch(`${BASE}/api/creation-studio/assets/${assetId}`, {
    method: 'DELETE',
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '删除参考图片失败'));
  return res.json();
}

export async function listCreationStudioJobs(
  mediaKind?: CreationStudioMediaKind,
): Promise<{ jobs: CreationStudioJob[] }> {
  const query = mediaKind ? `?media_kind=${encodeURIComponent(mediaKind)}` : '';
  const res = await fetch(`${BASE}/api/creation-studio/jobs${query}`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await readErrorMessage(res, '获取生成记录失败'));
  return res.json();
}

export async function createCreationStudioJobs(
  payload: CreationStudioJobCreate,
): Promise<{ jobs: CreationStudioJob[] }> {
  const res = await fetch(`${BASE}/api/creation-studio/jobs`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '提交生成任务失败'));
  return res.json();
}

export async function cancelCreationStudioJob(jobId: number): Promise<{ job: CreationStudioJob }> {
  const res = await fetch(`${BASE}/api/creation-studio/jobs/${jobId}/cancel`, {
    method: 'POST',
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '取消生成任务失败'));
  return res.json();
}

export async function retryCreationStudioJob(jobId: number): Promise<{ job: CreationStudioJob }> {
  const res = await fetch(`${BASE}/api/creation-studio/jobs/${jobId}/retry`, {
    method: 'POST',
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '重试生成任务失败'));
  return res.json();
}

export async function deleteCreationStudioJob(jobId: number): Promise<{ ok: boolean }> {
  const res = await fetch(`${BASE}/api/creation-studio/jobs/${jobId}`, {
    method: 'DELETE',
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '删除生成记录失败'));
  return res.json();
}

export interface CanvasContainerTab {
  title: string;
  color: string;
  nodes: string[];
}

export async function createNodeContainer(canvasId: number, payload: {
  name: string;
  node_ids: string[];
  expected_definition_revision: number;
}): Promise<{ ok: boolean; container_id: string; tab_count: number; node_count: number }> {
  const res = await fetch(`${BASE}/api/video-canvas/canvases/${canvasId}/containers/create`, {
    method: 'POST', headers: apiHeaders(true), body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, DEFAULT_API_ERROR_MESSAGE));
  return res.json();
}
