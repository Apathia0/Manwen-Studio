export interface AuthUser {
  id: number
  name: string
  email: string
  role: 'user' | 'admin'
  can_override_api_key?: boolean
  can_override_api_url?: boolean
}

export interface LoginRequest {
  email: string
  password: string
}

export interface RegisterRequest {
  name: string
  email: string
  password: string
}

export interface AuthResponse {
  token: string
  user: AuthUser
}

export interface Story {
  id: number
  title: string
  description: string | null
  cover_image: string | null
  chapter_count?: number | null
  tags: Record<string, any> | null
  outline: Record<string, any> | null
  characters: Record<string, any>[] | null
  story_bible: Record<string, any> | null
  story_memory: Record<string, any> | null
  onboarding_completed: boolean
  source_type: 'manual' | 'import'
  import_context_completed: boolean
  has_character_profiles: boolean
  has_ref_image: boolean
  created_at: string
}

export interface Chapter {
  id: number
  story_id: number
  chapter_number: number
  title: string | null
  novel_content: string | null
  content_source: 'chat' | 'import' | null
  act: string | null
  key_events: any[] | null
  quality_score: Record<string, number> | null
  memory_summary: Record<string, any> | null
  status: string
  word_count: number | null
  created_at: string
  messages: ChatMessageOut[]
  images: MangaImageOut[]
}

export interface ChatMessageOut {
  id: number
  chapter_id: number
  role: string
  content: string
  created_at: string
}

export interface MangaImageOut {
  id: number
  chapter_id: number
  image_number: number
  image_path: string
  prompt: string | null
  created_at: string
}

export interface Framework {
  tags: string[]
  characters: Character[]
  outline: OutlineAct[]
}

export interface Character {
  id?: number
  name: string
  role: string
  description?: string
  personality?: string
  motivation?: string
  fear?: string
  big_five?: Record<string, any>
  arc?: Record<string, any>
  relationships?: Record<string, any>[]
}

export interface OutlineAct {
  act: number | string
  title: string
  chapters: OutlineChapter[]
}

export interface OutlineChapter {
  chapter_number: number
  title: string
  summary: string
  is_current: boolean
}

export interface MangaImage {
  id: number
  chapter_id: number
  image_number: number
  image_path: string
  prompt: string | null
  created_at: string
}

/** 漫画生成状态 */
export interface MangaGenerationStatus {
  task_id: string | null
  status: 'none' | 'pending' | 'running' | 'succeeded' | 'failed' | 'retrying'
  progress: number
  total: number
  error_message: string | null
  stage?: string | null
  message?: string | null
  retry_count?: number
  max_retries?: number
  next_retry_at?: string | null
  created_at: string | null
  completed_at: string | null
}

/** 参考图重绘模式 */
export type ImageRedrawMode = 'regenerate' | 'full' | 'partial'

export interface AgentConversationSummary {
  id: number
  story_id: number
  chapter_id: number | null
  title: string
  last_message_preview: string
  message_count: number
  created_at: string
  updated_at: string
}

export interface AgentMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  toolCalls?: ToolCallInfo[]
}

export interface ToolCallInfo {
  id: string
  name: string
  args: Record<string, any>
  status: 'running' | 'success' | 'error'
  summary?: string
}

export interface PendingChange {
  id: string
  type: string
  description: string
  diff: string
}

export interface PublicPlan {
  id: number
  code: string
  name: string
  description: string | null
  monthly_price: number
  yearly_price: number | null
  currency: string
  is_recommended: boolean
  features: Record<string, any>
}

export interface SubscriptionSummary {
  status: string
  billing_cycle: string
  current_period_start?: string | null
  current_period_end?: string | null
  expires_at?: string | null
  plan: {
    id: number
    code: string
    name: string
    monthly_price: number
    yearly_price?: number | null
    currency: string
  }
}

export interface UsageItem {
  feature_key: string
  base_limit: number
  granted: number
  limit: number
  used: number
  remaining: number
}

export interface OrderItem {
  order_no: string
  user_id: number
  user_name?: string | null
  plan_id: number
  plan_name: string
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

export interface CheckoutInfo {
  order_no: string
  qr_code_text?: string
  prepay?: Record<string, string>
}

/** 框架AI对话消息 */
export interface FrameworkChatMessage {
  role: 'user' | 'assistant'
  content: string
}

/** 框架快照 */
export interface FrameworkSnapshotItem {
  id: number
  created_at: string
  description?: string
  reply_summary?: string
  source?: string
}

/** 展开章节参数 */
export interface ExpandChapterData {
  act: string
  chapter_number: number
  chapter_title: string
  key_events?: string[]
  summary?: string
  goal?: string
  conflict?: string
  hook?: string
  payoff?: string
  highlight?: string
}

// ── 视频创作管线类型 ──

export interface ScriptScene {
  id: number
  chapter_id: number
  scene_number: number
  title: string
  location?: string | null
  time_of_day?: string | null
  characters: string[]
  summary: string
  dialogue: { speaker: string; text: string }[]
  voiceover?: string | null
  mood?: string | null
  estimated_duration_seconds?: number | null
  source_type: string
  status: string
  created_at: string
  updated_at: string
}

export interface VideoShot {
  id: number
  scene_id: number
  shot_number: number
  title: string
  shot_type?: string | null
  camera_angle?: string | null
  camera_movement?: string | null
  composition?: string | null
  action_description?: string | null
  dialogue?: string | null
  sound_design?: string | null
  duration_seconds?: number | null
  storyboard_prompt?: string | null
  video_prompt?: string | null
  negative_prompt?: string | null
  character_prompts_json?: Array<{ name: string; prompt: string }> | null
  scene_prompt?: string | null
  prop_prompts_json?: Array<{ name: string; prompt: string }> | null
  continuity_notes?: string | null
  status: string
  style_preset?: string | null
  storyboard_asset_id?: number | null
  storyboard_locked: boolean
  created_at: string
  updated_at: string
}

export interface VideoAsset {
  id: number
  story_id?: number | null
  chapter_id?: number | null
  scene_id?: number | null
  shot_id?: number | null
  asset_type: string
  name: string
  file_path: string
  provider?: string | null
  prompt?: string | null
  meta_json?: Record<string, unknown> | null
  asset_subtype?: string | null
  source_asset_ids_json?: number[] | null
  style_preset?: string | null
  locked: boolean
  revision: number
  is_master: boolean
  status: string
  hash_key?: string | null
  usage_scope?: string | null
  created_at: string
}

export interface VideoGenerationJob {
  id: number
  shot_id: number
  provider: string
  provider_job_id?: string | null
  model?: string | null
  status: string
  progress: number
  duration_seconds?: number | null
  aspect_ratio?: string | null
  error_message?: string | null
  stage?: string | null
  message?: string | null
  provider_status?: string | null
  retry_count?: number
  max_retries?: number
  input_mode?: string | null
  submitted_at: string
  completed_at?: string | null
}

export interface StoryVideoCharacter {
  name: string
  versions: Array<{
    id: number
    label: string
    is_default: boolean
    ref_asset_id?: number | null
    ref_asset_url?: string | null
    appearance_card: string
    sort_order: number
  }>
}

export interface ChapterVideoShot {
  id: number
  workflow_id: number
  shot_index: number
  source_text_span?: string | null
  scene_location?: string | null
  time_of_day?: string | null
  characters?: string[] | null
  story_summary?: string | null
  dialogue_or_narration?: string | null
  camera_plan?: string | null
  motion_plan?: string | null
  emotion_plan?: string | null
  continuity_notes?: string | null
  storyboard_prompt?: string | null
  video_prompt?: string | null
  character_prompts?: Array<{ name: string; prompt: string }> | null
  scene_prompt?: string | null
  prop_prompts?: Array<{ name: string; prompt: string }> | null
  storyboard_image_url?: string | null
  video_url?: string | null
  status: string
  error_message?: string | null
  created_at: string
}

export interface ChapterVideoWorkflow {
  id: number
  chapter_id: number
  story_id: number
  workflow_status: string
  character_reference_ids?: number[] | null
  video_style?: string | null
  style_reference_image_url?: string | null
  duration_per_shot: number
  total_shots: number
  completed_shots: number
  failed_shots: number
  error_message?: string | null
  retry_count?: number
  max_retries?: number
  stage?: string | null
  message?: string | null
  created_at: string
  shots: ChapterVideoShot[]
}

export interface VideoModel {
  name: string
  value: string
  description: string
}

/** 章节视频工作流状态 */
export interface ChapterVideoWorkflowStatus {
  id: number
  chapter_id: number
  workflow_status: string
  total_shots: number
  completed_shots: number
  failed_shots: number
  error_message?: string | null
  task_id?: string | null
  stage?: string | null
  message?: string | null
  retry_count?: number
  max_retries?: number
  next_retry_at?: string | null
}

/** 视频风格预设 */
export interface VideoStylePreset {
  id: number
  name: string
  category: string
  image_url?: string | null
  prompt_template?: string | null
  image_style_params?: Record<string, unknown> | null
  video_style_params?: Record<string, unknown> | null
  sort_order: number
}

/** 重新分析镜头提示词响应 */
export interface ReanalyzeShotPromptsResponse {
  shot_id: number
  storyboard_prompt: string
  video_prompt: string
  character_prompts: Array<{ name: string; prompt: string }>
  scene_prompt?: string
  prop_prompts?: Array<{ name: string; prompt: string }>
}

/** 预览视频提示词响应 */
export interface PreviewVideoPromptResponse {
  assembled_prompt: string
  parts: { part1: string; part2: string; part3: string | null }
}

/** 渲染的视频片段 */
export interface RenderedClip {
  id: number
  shot_id: number
  job_id?: number | null
  video_path: string
  thumbnail_path?: string | null
  duration_seconds?: number | null
  resolution?: string | null
  version: number
  is_active: boolean
  meta?: Record<string, any> | null
  source_storyboard_asset_id?: number | null
  style_preset?: string | null
  continuity_score?: number | null
  quality_score?: number | null
  review_status?: string
  created_at: string
}

/** 视频角色版本（新架构） */
export interface CharacterVersion {
  id: number
  version: string
  label: string
  appearance_card: string
  ref_asset?: VideoAsset | null
  ref_asset_id?: number | null
  ref_asset_url?: string | undefined
  is_default: boolean
  sort_order: number
  created_at?: string
}

/** 视频角色（新架构） */
export interface VideoCharacter {
  name: string
  versions: CharacterVersion[]
}

/** 视频角色列表响应（新架构） */
export interface VideoCharactersResponse {
  characters: VideoCharacter[]
  video_character_profiles: string
}
