import { get, post, patch } from '@/utils/request'

interface OnboardingMessage {
  role: 'user' | 'assistant'
  content: string
}

interface Understanding {
  concept?: string
  setting?: string
  tone?: string
  goals?: string
  synthesis?: string
}

interface OnboardingResponse {
  reply: string
  collected_info: Record<string, string>
  understanding?: Understanding
  understanding_depth?: number
  has_brief?: boolean
  step: number
  total_steps: number
  is_complete: boolean
  creative_brief?: Record<string, any>
}

interface StoryBible {
  concept?: string
  genre?: string
  tone?: string
  audience?: string
  selling_point?: string
  [key: string]: any
}

// 超时常量（毫秒）
const TIMEOUT = {
  /** 普通请求：5 分钟 */
  NORMAL: 300000,
  /** AI 对话（DeepSeek 调用）：5 分钟 */
  AI_CHAT: 300000,
  /** 框架生成（多轮 DeepSeek + 数据写入）：5 分钟 */
  FRAMEWORK: 300000,
}

/** 引导对话 */
export function sendMessage(storyId: number, data: {
  messages: OnboardingMessage[]
  collected_info?: Record<string, string>
  step?: number
}): Promise<OnboardingResponse> {
  return post<OnboardingResponse>(`/api/stories/${storyId}/onboarding/message`, data, undefined, TIMEOUT.AI_CHAT)
}

/** 确认引导（框架生成） */
export function confirmOnboarding(storyId: number, data: {
  collected_info: Record<string, string>
  understanding?: Record<string, string>
  messages: OnboardingMessage[]
  creative_brief?: Record<string, any>
}): Promise<{ story_id: number; story_bible: StoryBible; creative_brief: Record<string, any> }> {
  return post(`/api/stories/${storyId}/onboarding/confirm`, data, undefined, TIMEOUT.FRAMEWORK)
}

/** 跳过引导 */
export function skipOnboarding(storyId: number): Promise<{ story_id: number; onboarding_completed: boolean }> {
  return post(`/api/stories/${storyId}/onboarding/skip`, undefined, undefined, TIMEOUT.NORMAL)
}

/** 导入引导对话 */
export function sendImportMessage(storyId: number, data: {
  messages: OnboardingMessage[]
  collected_info?: Record<string, string>
  step?: number
}): Promise<OnboardingResponse> {
  return post<OnboardingResponse>(`/api/stories/${storyId}/import-context/message`, data, undefined, TIMEOUT.AI_CHAT)
}

/** 确认导入引导 */
export function confirmImport(storyId: number, data: {
  collected_info: Record<string, string>
  messages: OnboardingMessage[]
}): Promise<any> {
  return post(`/api/stories/${storyId}/import-context/confirm`, data, undefined, TIMEOUT.AI_CHAT)
}

/** 跳过导入引导 */
export function skipImport(storyId: number): Promise<{ ok: boolean; story_id: number }> {
  return post(`/api/stories/${storyId}/import-context/skip`, undefined, undefined, TIMEOUT.NORMAL)
}

/** 获取故事圣经 */
export function getStoryBible(storyId: number): Promise<{ story_bible: StoryBible }> {
  return get(`/api/stories/${storyId}/story-bible`)
}

/** 更新故事圣经 */
export function updateStoryBible(storyId: number, storyBible: Partial<StoryBible>): Promise<{ story_bible: StoryBible }> {
  return patch(`/api/stories/${storyId}/story-bible`, { story_bible: storyBible })
}
