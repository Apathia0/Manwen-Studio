import { get, post, patch } from '@/utils/request'

interface OnboardingMessage {
  role: 'user' | 'assistant'
  content: string
}

interface OnboardingResponse {
  reply: string
  collected_info: Record<string, string>
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

/** 引导对话 */
export function sendMessage(storyId: number, data: {
  messages: OnboardingMessage[]
  collected_info?: Record<string, string>
  step?: number
}): Promise<OnboardingResponse> {
  return post<OnboardingResponse>(`/api/stories/${storyId}/onboarding/message`, data)
}

/** 确认引导 */
export function confirmOnboarding(storyId: number, data: {
  collected_info: Record<string, string>
  messages: OnboardingMessage[]
}): Promise<{ story_id: number; story_bible: StoryBible; creative_brief: Record<string, any> }> {
  return post(`/api/stories/${storyId}/onboarding/confirm`, data)
}

/** 跳过引导 */
export function skipOnboarding(storyId: number): Promise<{ story_id: number; onboarding_completed: boolean }> {
  return post(`/api/stories/${storyId}/onboarding/skip`)
}

/** 导入引导对话 */
export function sendImportMessage(storyId: number, data: {
  messages: OnboardingMessage[]
  collected_info?: Record<string, string>
  step?: number
}): Promise<OnboardingResponse> {
  return post<OnboardingResponse>(`/api/stories/${storyId}/import-context/message`, data)
}

/** 确认导入引导 */
export function confirmImport(storyId: number, data: {
  collected_info: Record<string, string>
  messages: OnboardingMessage[]
}): Promise<any> {
  return post(`/api/stories/${storyId}/import-context/confirm`, data)
}

/** 跳过导入引导 */
export function skipImport(storyId: number): Promise<{ ok: boolean; story_id: number }> {
  return post(`/api/stories/${storyId}/import-context/skip`)
}

/** 获取故事圣经 */
export function getStoryBible(storyId: number): Promise<{ story_bible: StoryBible }> {
  return get(`/api/stories/${storyId}/story-bible`)
}

/** 更新故事圣经 */
export function updateStoryBible(storyId: number, storyBible: Partial<StoryBible>): Promise<{ story_bible: StoryBible }> {
  return patch(`/api/stories/${storyId}/story-bible`, { story_bible: storyBible })
}
