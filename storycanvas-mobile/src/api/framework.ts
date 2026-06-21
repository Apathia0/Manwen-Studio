import { get, post } from '@/utils/request'
import type { Character, OutlineAct } from './types'

// 超时常量（毫秒）
const TIMEOUT = {
  /** 普通请求：5 分钟 */
  NORMAL: 300000,
  /** AI 调用：5 分钟 */
  AI_CHAT: 300000,
  /** 框架全量生成（多轮 DeepSeek + 数据写入）：5 分钟 */
  FRAMEWORK: 300000,
}

interface FrameworkGenerateResponse {
  tags: Record<string, string>
  characters: Character[]
  outline: { three_acts: OutlineAct[] }
}

/** 框架续写/调整响应（对齐 Web 端 FrameworkAdjustResponse） */
export interface FrameworkContinueResponse {
  reply: string
  story?: {
    description?: string
    tags?: Record<string, any>
    characters?: Character[]
    outline?: { three_acts: OutlineAct[] }
  }
  chapters?: any[]
  applied_operations?: string[]
  warnings?: string[]
  validation_errors?: string[]
}

interface FrameworkSnapshot {
  id: number
  created_at: string
  description: string
}

/** 生成全部框架（多轮 DeepSeek） */
export function generateFramework(storyId: number, description: string): Promise<FrameworkGenerateResponse> {
  return post<FrameworkGenerateResponse>(`/api/stories/${storyId}/framework/generate`, { description }, undefined, TIMEOUT.FRAMEWORK)
}

/** 重生成标签（AI 调用） */
export function regenerateTags(storyId: number): Promise<{ tags: Record<string, string> }> {
  return post(`/api/stories/${storyId}/framework/tags`, undefined, undefined, TIMEOUT.AI_CHAT)
}

/** 重生成角色（AI 调用） */
export function regenerateCharacters(storyId: number): Promise<{ characters: Character[] }> {
  return post(`/api/stories/${storyId}/framework/characters`, undefined, undefined, TIMEOUT.AI_CHAT)
}

/** 重生成大纲（AI 调用） */
export function regenerateOutline(storyId: number): Promise<{ outline: { three_acts: OutlineAct[] } }> {
  return post(`/api/stories/${storyId}/framework/outline`, undefined, undefined, TIMEOUT.AI_CHAT)
}

/** 手动章节操作 */
export function manualChapters(storyId: number, data: { mode: string; [key: string]: any }): Promise<{ outline: { three_acts: OutlineAct[] } }> {
  return post(`/api/stories/${storyId}/framework/chapters/manual`, data)
}

/** AI 调整框架 (SSE) — 返回 URL */
export function adjustUrl(storyId: number): string {
  return `/api/stories/${storyId}/framework/adjust`
}

/** 继续扩展框架 (JSON) — AI 调用 */
export function continueFramework(storyId: number): Promise<FrameworkContinueResponse> {
  return post<FrameworkContinueResponse>(`/api/stories/${storyId}/framework/continue`, undefined, undefined, TIMEOUT.FRAMEWORK)
}

/** 分析导入素材（AI 调用） */
export function analyze(storyId: number): Promise<any> {
  return post(`/api/stories/${storyId}/framework/analyze`, undefined, undefined, TIMEOUT.AI_CHAT)
}

/** 快照列表 */
export function getSnapshots(storyId: number): Promise<{ snapshots: FrameworkSnapshot[] }> {
  return get(`/api/stories/${storyId}/framework/snapshots`)
}

/** 恢复快照 */
export function restoreSnapshot(storyId: number, snapshotId: number): Promise<any> {
  return post(`/api/stories/${storyId}/framework/snapshots/${snapshotId}/restore`)
}

/** 扩写章节（AI 调用） */
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
  return post(`/api/stories/${storyId}/expand-chapter`, data, undefined, TIMEOUT.AI_CHAT)
}

/** 刷新全部连贯性记忆（AI 调用） */
export function refreshAllMemories(storyId: number): Promise<void> {
  return post(`/api/stories/${storyId}/refresh-all-memories`, undefined, undefined, TIMEOUT.AI_CHAT)
}
