import { get, post, put, del, request } from '@/utils/request'
import type { Story } from './types'

interface CoverResult {
  cover_image: string
  prompt?: string
}

const COVER_RECOVERY_INTERVAL_MS = 5000
const COVER_RECOVERY_TIMEOUT_MS = 300000
const COVER_STATUS_REQUEST_TIMEOUT_MS = 8000

function isRecoverableCoverRequestError(error: unknown): boolean {
  const message = error instanceof Error ? error.message.toLowerCase() : String(error).toLowerCase()
  return message.includes('request:fail')
    || message.includes('timeout')
    || message.includes('timed out')
    || message.includes('abort')
    || message.includes('network')
    || message.includes('网络')
}

function delay(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms))
}

async function getStoryForCoverRecovery(id: number): Promise<Story> {
  return get<Story>(
    `/api/stories/${id}`,
    undefined,
    undefined,
    COVER_STATUS_REQUEST_TIMEOUT_MS
  )
}

async function waitForCoverUpdate(id: number, previousCover: string | null): Promise<CoverResult | null> {
  const deadline = Date.now() + COVER_RECOVERY_TIMEOUT_MS
  while (Date.now() < deadline) {
    await delay(COVER_RECOVERY_INTERVAL_MS)
    try {
      const story = await getStoryForCoverRecovery(id)
      if (story.cover_image && story.cover_image !== previousCover) {
        return { cover_image: story.cover_image }
      }
    } catch {
      // 长请求中断后网络可能仍在恢复，继续查询后端最终结果。
    }
  }
  return null
}

async function runCoverGeneration(
  id: number,
  url: string,
  instruction: string
): Promise<CoverResult> {
  let previousCover: string | null | undefined
  try {
    previousCover = (await getStoryForCoverRecovery(id)).cover_image
  } catch {
    // 封面状态读取失败不应阻止正式生成请求。
  }
  try {
    return await request<CoverResult>({
      url,
      method: 'POST',
      data: { instruction },
      timeout: 330000
    })
  } catch (error) {
    if (!isRecoverableCoverRequestError(error)) throw error
    if (previousCover !== undefined) {
      const recovered = await waitForCoverUpdate(id, previousCover)
      if (recovered) return recovered
    }
    throw new Error('封面生成请求已中断，暂未确认生成结果，请刷新页面后重试')
  }
}

export function getStories(): Promise<Story[]> {
  return get<Story[]>('/api/stories')
}

export function createStory(title: string, description?: string): Promise<Story> {
  return post<Story>('/api/stories', { title, description })
}

export function getStory(id: number): Promise<Story> {
  return get<Story>(`/api/stories/${id}`)
}

export function updateStory(id: number, data: Partial<Story>): Promise<Story> {
  return put<Story>(`/api/stories/${id}`, data)
}

export function deleteStory(id: number): Promise<void> {
  return del(`/api/stories/${id}`)
}

export function uploadCover(id: number, base64: string): Promise<{ cover_image: string }> {
  return post(`/api/stories/${id}/upload-cover`, { image: base64 })
}

export function generateCover(id: number, instruction = ''): Promise<CoverResult> {
  return runCoverGeneration(id, `/api/stories/${id}/generate-cover`, instruction)
}

export function adjustCover(id: number, instruction: string): Promise<CoverResult> {
  return runCoverGeneration(id, `/api/stories/${id}/adjust-cover`, instruction)
}
