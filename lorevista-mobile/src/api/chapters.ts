import { get, post, put, del } from '@/utils/request'
import type { Chapter } from './types'

/** 获取章节列表 */
export function getChapters(storyId: number): Promise<Chapter[]> {
  return get<Chapter[]>(`/api/stories/${storyId}/chapters`)
}

/** 创建章节 */
export function createChapter(storyId: number): Promise<Chapter> {
  return post<Chapter>(`/api/stories/${storyId}/chapters`)
}

/** 获取章节详情 */
export function getChapter(chapterId: number): Promise<Chapter> {
  return get<Chapter>(`/api/chapters/${chapterId}`)
}

/** 删除章节 */
export function deleteChapter(chapterId: number): Promise<void> {
  return del(`/api/chapters/${chapterId}`)
}

/** 保存章节内容 */
export function saveContent(chapterId: number, content: string): Promise<Chapter> {
  return put<Chapter>(`/api/chapters/${chapterId}/content`, { content })
}

/** 章节 AI 对话 (SSE) — 返回 URL，由 useChat composable 处理 */
export function chatUrl(chapterId: number): string {
  return `/api/chapters/${chapterId}/chat`
}

/** AI 生成小说 */
export function generateNovel(chapterId: number): Promise<Chapter> {
  return post<Chapter>(`/api/chapters/${chapterId}/generate-novel`)
}

/** 导入小说文本 */
export function importNovel(chapterId: number, content: string): Promise<Chapter> {
  return post<Chapter>(`/api/chapters/${chapterId}/import-novel`, { content })
}

/** 重写选段 */
export function rewriteSelection(chapterId: number, selectedText: string, chapterContext?: string): Promise<{ rewritten_text: string }> {
  return post(`/api/chapters/${chapterId}/rewrite-selection`, { selected_text: selectedText, chapter_context: chapterContext })
}

/** 调整章节内容 */
export function adjustContent(chapterId: number, instruction: string): Promise<Chapter> {
  return post<Chapter>(`/api/chapters/${chapterId}/adjust-content`, { instruction })
}

/** 更新连贯性记忆 */
export function updateContinuity(chapterId: number, data: { chapter_summary?: string; chapter_handoff?: string }): Promise<Chapter> {
  return put<Chapter>(`/api/chapters/${chapterId}/continuity-memory`, data)
}

/** 质量评估 */
export function qualityAssess(chapterId: number): Promise<{ scores: Record<string, number> }> {
  return post(`/api/chapters/${chapterId}/quality-assess`)
}
