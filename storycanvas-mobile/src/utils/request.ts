import { BASE_URL } from './constants'
import { getToken, clearAuth } from './storage'
import { normalizeErrorMessage } from './errors'

interface RequestOptions {
  url: string
  method: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
  data?: any
  header?: Record<string, string>
  timeout?: number
  json?: boolean // true=JSON body, false=FormData (仅 uni.uploadFile)
}

function getAuthHeaders(): Record<string, string> {
  const headers: Record<string, string> = {}
  const token = getToken()
  if (token) {
    headers['Authorization'] = `Bearer ${token}`
  }
  return headers
}

export async function request<T = any>(options: RequestOptions): Promise<T> {
  const { url, method, data, header = {}, timeout = 300000, json = true } = options

  const fullUrl = url.startsWith('http') ? url : `${BASE_URL}${url}`

  const headers: Record<string, string> = {
    ...getAuthHeaders(),
    ...header
  }

  if (json) {
    headers['Content-Type'] = 'application/json'
  }

  return new Promise((resolve, reject) => {
    uni.request({
      url: fullUrl,
      method: method as any,
      data: data,
      header: headers,
      timeout,
      success: (res) => {
        if (res.statusCode === 401) {
          clearAuth()
          uni.navigateTo({ url: '/pages/auth/login' })
          reject(new Error('认证已过期，请重新登录'))
          return
        }

        if (res.statusCode >= 200 && res.statusCode < 300) {
          resolve(res.data as T)
        } else {
          const errorData = res.data as any
          if (res.statusCode === 502 || res.statusCode === 503 || res.statusCode === 504) {
            // 网关类状态码 + 非 JSON 响应体＝反向代理连不上后端服务（后端未启动/重启），
            // 而非 AI 上游故障。直接给后端服务可操作提示，避免误报「上游 AI 服务不可用」。
            const message = errorData && (errorData.message || errorData.detail)
            if (!message || typeof message !== 'string') {
              reject(new Error(
                res.statusCode === 503
                  ? '后端服务繁忙或正在初始化，请稍后重试'
                  : '后端服务暂不可用或正在重启，请稍后重试，必要时联系管理员检查服务状态',
              ))
              return
            }
          }
          const handled = normalizeErrorMessage(errorData, '请求失败，请稍后重试')
          reject(new Error(handled))
        }
      },
      fail: (err) => {
        reject(new Error(normalizeErrorMessage(err?.errMsg, '网络请求失败，请检查网络后重试')))
      }
    })
  })
}

export function get<T = any>(url: string, data?: any, header?: Record<string, string>, timeout?: number): Promise<T> {
  return request<T>({ url, method: 'GET', data, header, timeout })
}

export function post<T = any>(url: string, data?: any, header?: Record<string, string>, timeout?: number): Promise<T> {
  return request<T>({ url, method: 'POST', data, header, timeout })
}

export function put<T = any>(url: string, data?: any, header?: Record<string, string>, timeout?: number): Promise<T> {
  return request<T>({ url, method: 'PUT', data, header, timeout })
}

export function del<T = any>(url: string, data?: any, header?: Record<string, string>, timeout?: number): Promise<T> {
  return request<T>({ url, method: 'DELETE', data, header, timeout })
}

export function patch<T = any>(url: string, data?: any, header?: Record<string, string>, timeout?: number): Promise<T> {
  return request<T>({ url, method: 'PATCH', data, header, timeout })
}
