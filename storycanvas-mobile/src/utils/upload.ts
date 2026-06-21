import { BASE_URL } from './constants'
import { getToken, clearAuth } from './storage'

// ── 向后兼容接口 ──

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

// ── 统一上传 helper ──

/** 统一上传选项 */
export interface UploadAssetOptions {
  url: string
  filePath: string
  name?: string
  formData?: Record<string, string>
  /** 上传进度回调（0-100） */
  onProgress?: (percent: number) => void
}

/** 统一上传结果 */
export interface UploadAssetResult {
  data: any
  statusCode: number
}

/**
 * 统一的文件上传 helper
 *
 * - 自动注入 Authorization 请求头
 * - 自动拼接 BASE_URL
 * - 支持上传进度回调
 * - 401 时自动清除 token 并跳转登录页
 * - 响应 JSON 自动解析
 *
 * @param options 上传选项
 * @returns 上传结果（包含解析后的数据和状态码）
 */
export function uploadAsset(options: UploadAssetOptions): Promise<UploadAssetResult> {
  const {
    url,
    filePath,
    name = 'file',
    formData,
    onProgress
  } = options

  const fullUrl = url.startsWith('http') ? url : `${BASE_URL}${url}`
  const token = getToken()
  const headers: Record<string, string> = {}
  if (token) {
    headers['Authorization'] = `Bearer ${token}`
  }

  return new Promise((resolve, reject) => {
    const uploadTask = uni.uploadFile({
      url: fullUrl,
      filePath,
      name,
      formData,
      header: headers,
      success: (res) => {
        if (res.statusCode === 401) {
          clearAuth()
          uni.navigateTo({ url: '/pages/auth/login' })
          reject(new Error('认证已过期，请重新登录'))
          return
        }

        if (res.statusCode >= 200 && res.statusCode < 300) {
          try {
            resolve({
              data: JSON.parse(res.data),
              statusCode: res.statusCode
            })
          } catch {
            reject(new Error('响应解析失败'))
          }
        } else {
          try {
            const errData = JSON.parse(res.data)
            reject(new Error(errData.detail || errData.message || '上传失败'))
          } catch {
            reject(new Error(`上传失败 (${res.statusCode})`))
          }
        }
      },
      fail: (err) => {
        reject(new Error(err.errMsg || '文件上传失败'))
      }
    })

    // 监听上传进度（部分平台可能不支持）
    if (onProgress && uploadTask && typeof uploadTask.onProgressUpdate === 'function') {
      uploadTask.onProgressUpdate((event: UniApp.OnProgressUpdateResult) => {
        onProgress(event.progress)
      })
    }
  })
}
