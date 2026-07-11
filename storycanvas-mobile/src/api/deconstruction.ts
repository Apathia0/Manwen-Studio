import { del, get, patch, post } from '@/utils/request'
import { BASE_URL } from '@/utils/constants'
import { getToken } from '@/utils/storage'

export interface DeconstructionWorkItem {
  id: number
  title: string
  author?: string | null
  platform: string
  genre?: string | null
  status_label?: string | null
  crawl_status: string
  decon_status: string
  total_chapters?: number | null
  crawled_chapters: number
  word_count?: number | null
  progress_markdown?: string | null
  created_at?: string | null
  updated_at?: string | null
}

export interface DeconstructionWorkResult {
  id: number
  title: string
  author?: string | null
  status: string
  report_markdown?: string | null
  summary?: Record<string, any> | null
  writing_style?: Record<string, any> | null
  writing_techniques?: Record<string, any>[] | null
  progress_markdown?: string | null
}

export interface DeconstructionRefItem {
  id: number
  work_id: number
  title: string
  author?: string | null
  genre?: string | null
  applied_at?: string | null
}

export interface AuthorStyleStatus {
  status: 'not_started' | 'pending' | 'running' | 'completed' | 'failed'
  progress?: string | null
  task_id?: string | null
  work_id: number
}

export interface AuthorStyleResult {
  work_id: number
  title: string
  author?: string | null
  status: string
  profile?: Record<string, any> | null
  report_markdown?: string | null
  progress?: string | null
}

export function importFile(filePath: string, title?: string, author?: string): Promise<{ work_id: number; task_id: string; message: string }> {
  return new Promise((resolve, reject) => {
    const token = getToken()
    uni.uploadFile({
      url: `${BASE_URL}/api/deconstruct/works/import-file`,
      filePath,
      name: 'file',
      formData: {
        ...(title ? { title } : {}),
        ...(author ? { author } : {})
      },
      header: token ? { Authorization: `Bearer ${token}` } : {},
      timeout: 300000,
      success: (response) => {
        let data: any
        try {
          data = JSON.parse(response.data)
        } catch {
          reject(new Error('上传响应解析失败'))
          return
        }
        if (response.statusCode >= 200 && response.statusCode < 300) resolve(data)
        else reject(new Error(data?.detail || data?.message || '上传失败'))
      },
      fail: (error) => reject(new Error(error.errMsg || '上传失败'))
    })
  })
}

export function listWorks(): Promise<DeconstructionWorkItem[]> {
  return get('/api/deconstruct/works')
}

export function importText(data: {
  title: string
  text: string
  author?: string
  platform?: string
  genre?: string
}): Promise<{ work_id: number; message: string }> {
  return post('/api/deconstruct/works/import-text', data)
}

export function createWork(data: {
  title: string
  book_id: string
  platform?: string
  author?: string
  genre?: string
  max_chapters?: number
}): Promise<{ work_id: number; task_id: string; message: string }> {
  return post('/api/deconstruct/works', data)
}

export function searchNovels(keyword: string, platform = 'qidian', limit = 10): Promise<any> {
  return get('/api/deconstruct/search', { keyword, platform, limit })
}

export function startWork(workId: number, maxChapters?: number): Promise<{ task_id: string; message: string }> {
  return post(`/api/deconstruct/works/${workId}/start`, maxChapters ? { max_chapters: maxChapters } : {})
}

export function resumeWork(workId: number, mode: 'full' | 'partial' | 'quick_report' = 'full'): Promise<{ task_id: string; message: string }> {
  return post(`/api/deconstruct/works/${workId}/resume`, { mode })
}

export function getStatus(workId: number): Promise<any> {
  return get(`/api/deconstruct/works/${workId}/status`)
}

export function getResult(workId: number): Promise<DeconstructionWorkResult> {
  return get(`/api/deconstruct/works/${workId}/result`)
}

export function updateReport(workId: number, reportMarkdown: string): Promise<{ ok: boolean; report_markdown: string }> {
  return patch(`/api/deconstruct/works/${workId}/report`, { report_markdown: reportMarkdown })
}

export function cancelWork(workId: number): Promise<{ message: string }> {
  return post(`/api/deconstruct/works/${workId}/cancel`)
}

export function deleteWork(workId: number): Promise<{ message: string }> {
  return del(`/api/deconstruct/works/${workId}`)
}

export function startAuthorStyle(workId: number): Promise<{ task_id: string; message: string }> {
  return post(`/api/deconstruct/works/${workId}/author-style/start`, {})
}

export function getAuthorStyle(workId: number): Promise<any> {
  return get(`/api/deconstruct/works/${workId}/author-style/result`)
}

export function getAuthorStyleStatus(workId: number): Promise<AuthorStyleStatus> {
  return get(`/api/deconstruct/works/${workId}/author-style/status`)
}

export function updateAuthorStyleReport(workId: number, reportMarkdown: string): Promise<{ ok: boolean; report_markdown: string }> {
  return patch(`/api/deconstruct/works/${workId}/author-style/report`, { report_markdown: reportMarkdown })
}

export function listRefs(storyId: number): Promise<DeconstructionRefItem[]> {
  return get(`/api/stories/${storyId}/deconstruct/refs`)
}

export function addRef(storyId: number, workId: number): Promise<{ message: string }> {
  return post(`/api/stories/${storyId}/deconstruct/refs`, { work_id: workId })
}

export function removeRef(storyId: number, refId: number): Promise<{ message: string }> {
  return del(`/api/stories/${storyId}/deconstruct/refs/${refId}`)
}
