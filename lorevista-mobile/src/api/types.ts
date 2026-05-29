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
