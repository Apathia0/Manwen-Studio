import { post } from '@/utils/request'

interface ImportChapter {
  chapter_number: number
  title: string
  content: string
  detection_method: string
}

interface ImportParseResponse {
  detected_title: string
  chapters: ImportChapter[]
  total_word_count: number
}

/** 解析导入文件 */
export function parseImport(file: File): Promise<ImportParseResponse> {
  // 注意: 此端点使用 multipart/form-data
  // 在 UniApp 中需要使用 uni.uploadFile
  return new Promise((resolve, reject) => {
    const token = uni.getStorageSync('lv_auth_token')
    uni.uploadFile({
      url: '/api/import/parse',
      filePath: (file as any).path || file,
      name: 'file',
      header: {
        'Authorization': token ? `Bearer ${token}` : ''
      },
      success: (res) => {
        if (res.statusCode === 200) {
          resolve(JSON.parse(res.data))
        } else {
          reject(new Error('文件解析失败'))
        }
      },
      fail: (err) => {
        reject(new Error(err.errMsg || '文件上传失败'))
      }
    })
  })
}

/** 从导入创建故事 */
export function createFromImport(data: {
  title: string
  chapters: ImportChapter[]
  analyze_framework?: boolean
}): Promise<any> {
  return post('/api/import/create', data)
}
