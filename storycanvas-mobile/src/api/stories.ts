import { get, post, put, del, request } from '@/utils/request'
import type { Story } from './types'

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

export function generateCover(id: number, instruction?: string): Promise<{ cover_image: string }> {
  return request({
    url: `/api/stories/${id}/generate-cover`,
    method: 'POST',
    data: { instruction: instruction || '' },
    timeout: 300000
  })
}

export function adjustCover(id: number, prompt: string): Promise<{ cover_image: string }> {
  return post(`/api/stories/${id}/adjust-cover`, { prompt })
}
