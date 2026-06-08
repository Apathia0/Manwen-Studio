import { get, post, del } from '@/utils/request'
import type { AgentConversationSummary } from './types'

interface AgentConversation {
  id: number
  title: string
  messages: AgentMessage[]
  created_at: string
  updated_at: string
}

interface AgentMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  toolCalls?: any[]
  created_at: string
}

/** 获取会话列表 */
export function getConversations(storyId: number): Promise<AgentConversationSummary[]> {
  return get<AgentConversationSummary[]>(`/api/stories/${storyId}/agent/conversations`)
}

/** 创建会话 */
export function createConversation(storyId: number, title?: string, chapterId?: number): Promise<AgentConversation> {
  return post<AgentConversation>(`/api/stories/${storyId}/agent/conversations`, { title, chapter_id: chapterId })
}

/** 获取会话详情 */
export function getConversation(storyId: number, conversationId: number): Promise<AgentConversation> {
  return get<AgentConversation>(`/api/stories/${storyId}/agent/conversations/${conversationId}`)
}

/** 删除会话 */
export function deleteConversation(storyId: number, conversationId: number): Promise<void> {
  return del(`/api/stories/${storyId}/agent/conversations/${conversationId}`)
}

/** Agent 对话 (SSE) — 返回 URL */
export function chatUrl(storyId: number): string {
  return `/api/stories/${storyId}/agent/chat`
}

/** 确认变更 */
export function confirmChanges(storyId: number, conversationId?: number): Promise<{ ok: boolean; message: string }> {
  return post(`/api/stories/${storyId}/agent/confirm`, conversationId ? { conversation_id: conversationId } : {})
}

/** 回滚变更 */
export function rollbackChanges(storyId: number, conversationId?: number): Promise<{ ok: boolean; results: any[] }> {
  return post(`/api/stories/${storyId}/agent/rollback`, conversationId ? { conversation_id: conversationId } : {})
}

/** 获取待确认变更 */
export function getPendingChanges(storyId: number, conversationId?: number): Promise<{ changes: any[] }> {
  const query = conversationId ? `?conversation_id=${encodeURIComponent(String(conversationId))}` : ''
  return get(`/api/stories/${storyId}/agent/pending-changes${query}`)
}
