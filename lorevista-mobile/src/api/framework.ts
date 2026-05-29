import { get, post } from '@/utils/request'
import type { Character, OutlineAct } from './types'

interface FrameworkGenerateResponse {
  tags: Record<string, string>
  characters: Character[]
  outline: { three_acts: OutlineAct[] }
}

interface FrameworkSnapshot {
  id: number
  created_at: string
  description: string
}

/** 生成全部框架 */
export function generateFramework(storyId: number, description: string): Promise<FrameworkGenerateResponse> {
  return post<FrameworkGenerateResponse>(`/api/stories/${storyId}/framework/generate`, { description })
}

/** 重生成标签 */
export function regenerateTags(storyId: number): Promise<{ tags: Record<string, string> }> {
  return post(`/api/stories/${storyId}/framework/tags`)
}

/** 重生成角色 */
export function regenerateCharacters(storyId: number): Promise<{ characters: Character[] }> {
  return post(`/api/stories/${storyId}/framework/characters`)
}

/** 重生成大纲 */
export function regenerateOutline(storyId: number): Promise<{ outline: { three_acts: OutlineAct[] } }> {
  return post(`/api/stories/${storyId}/framework/outline`)
}

/** 手动章节操作 */
export function manualChapters(storyId: number, data: { mode: string; [key: string]: any }): Promise<{ outline: { three_acts: OutlineAct[] } }> {
  return post(`/api/stories/${storyId}/framework/chapters/manual`, data)
}

/** AI 调整框架 (SSE) — 返回 URL */
export function adjustUrl(storyId: number): string {
  return `/api/stories/${storyId}/framework/adjust`
}

/** 继续扩展框架 (JSON) */
export function continueFramework(storyId: number): Promise<{
  reply: string
  chapters: any[]
  applied_operations: string[]
  warnings: string[]
}> {
  return post(`/api/stories/${storyId}/framework/continue`)
}

/** 分析导入素材 */
export function analyze(storyId: number): Promise<any> {
  return post(`/api/stories/${storyId}/framework/analyze`)
}

/** 快照列表 */
export function getSnapshots(storyId: number): Promise<{ snapshots: FrameworkSnapshot[] }> {
  return get(`/api/stories/${storyId}/framework/snapshots`)
}

/** 恢复快照 */
export function restoreSnapshot(storyId: number, snapshotId: number): Promise<any> {
  return post(`/api/stories/${storyId}/framework/snapshots/${snapshotId}/restore`)
}

/** 扩写章节 */
export function expandChapter(storyId: number, data: {
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
}): Promise<any> {
  return post(`/api/stories/${storyId}/expand-chapter`, data)
}

/** 刷新全部连贯性记忆 */
export function refreshAllMemories(storyId: number): Promise<void> {
  return post(`/api/stories/${storyId}/refresh-all-memories`)
}
