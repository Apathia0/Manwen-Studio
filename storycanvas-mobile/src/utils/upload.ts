import { BASE_URL } from './constants'
import { getToken } from './storage'

/**
 * 上传文件到后端（跨平台：H5 / 小程序 / App）
 * 使用 uni.uploadFile 实现 multipart/form-data 上传
 *
 * @param url API 路径（相对路径，如 /api/video/chapter-workflows/1/style-reference）
 * @param filePath 本地文件路径（来自 uni.chooseImage 的 tempFilePaths）
 * @param name 文件字段名（默认 'file'）
 * @param formData 额外的表单字段
 * @returns 解析后的 JSON 响应
 */
export function uploadFile<T = any>(
  url: string,
  filePath: string,
  name: string = 'file',
  formData?: Record<string, string>
): Promise<T> {
  const fullUrl = url.startsWith('http') ? url : `${BASE_URL}${url}`
  const token = getToken()
  const headers: Record<string, string> = {}
  if (token) {
    headers['Authorization'] = `Bearer ${token}`
  }

  return new Promise((resolve, reject) => {
    uni.uploadFile({
      url: fullUrl,
      filePath,
      name,
      formData,
      header: headers,
      success: (res) => {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          try {
            resolve(JSON.parse(res.data) as T)
          } catch {
            reject(new Error('响应解析失败'))
          }
        } else {
          try {
            const data = JSON.parse(res.data)
            reject(new Error(data.detail || data.message || '上传失败'))
          } catch {
            reject(new Error(`上传失败 (${res.statusCode})`))
          }
        }
      },
      fail: (err) => {
        reject(new Error(err.errMsg || '文件上传失败'))
      }
    })
  })
}

/**
 * 选择图片并上传
 *
 * @param count 最多选择图片数量
 * @returns 选中的图片临时路径数组
 */
export function chooseImages(count: number = 1): Promise<string[]> {
  return new Promise((resolve, reject) => {
    uni.chooseImage({
      count,
      success: (res) => {
        resolve(res.tempFilePaths as string[])
      },
      fail: (err) => {
        reject(new Error(err.errMsg || '选择图片失败'))
      }
    })
  })
}
