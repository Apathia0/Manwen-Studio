import { BASE_URL } from './constants'
import { getToken, clearAuth } from './storage'

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
          const message = errorData?.detail || errorData?.message || '请求失败'
          reject(new Error(message))
        }
      },
      fail: (err) => {
        reject(new Error(err.errMsg || '网络请求失败'))
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
