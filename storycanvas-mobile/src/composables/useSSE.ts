import { ref } from 'vue'
import { BASE_URL } from '@/utils/constants'
import { normalizeErrorMessage } from '@/utils/errors'

interface SSEEvent {
  type: string
  data: any
}

interface SSEOptions {
  url: string
  method?: 'GET' | 'POST'
  headers?: Record<string, string>
  body?: any
  onEvent: (event: SSEEvent) => void
  onError?: (error: Error) => void
  onComplete?: () => void
}

interface SSEHandle {
  abort: () => void
}

export function useSSE() {
  const streaming = ref(false)
  let handle: SSEHandle | null = null

  function start(options: SSEOptions) {
    streaming.value = true
    handle = createSSE({
      ...options,
      onComplete: () => {
        streaming.value = false
        options.onComplete?.()
      },
      onError: (err) => {
        streaming.value = false
        options.onError?.(new Error(normalizeErrorMessage(err, '连接失败，请稍后重试')))
      }
    })
  }

  function stop() {
    handle?.abort()
    streaming.value = false
  }

  return { streaming, start, stop }
}

function createSSE(options: SSEOptions): SSEHandle {
  // #ifdef MP-WEIXIN
  return createWxSSE(options)
  // #endif

  // #ifdef APP-PLUS || H5
  return createFetchSSE(options)
  // #endif

  // 默认回退到 fetch
  return createFetchSSE(options)
}

function createFetchSSE(options: SSEOptions): SSEHandle {
  const controller = new AbortController()

  fetch(options.url.startsWith('http') ? options.url : `${BASE_URL}${options.url}`, {
    method: options.method || 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...options.headers
    },
    body: options.body ? JSON.stringify(options.body) : undefined,
    signal: controller.signal
  }).then(async (res) => {
    if (!res.ok) {
      const body = await res.text().catch(() => '')
      const detail = (() => {
        try { return JSON.parse(body).detail } catch { return body }
      })()
      throw new Error(normalizeErrorMessage(
        detail || `HTTP ${res.status}: ${res.statusText}`,
        '请求失败，请稍后重试'
      ))
    }
    const reader = res.body!.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let currentEvent = 'message'

    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''

      for (const line of lines) {
        parseSSELine(line, currentEvent, (evt, data) => {
          options.onEvent({ type: evt, data: normalizeSSEEventData(evt, data) })
        }, (evt) => { currentEvent = evt })
      }
    }
    options.onComplete?.()
  }).catch((err) => {
    if (err.name !== 'AbortError') {
      options.onError?.(err)
    }
  })

  return { abort: () => controller.abort() }
}

function createWxSSE(options: SSEOptions): SSEHandle {
  let buffer = ''
  let currentEvent = 'message'
  let requestFailed = false

  const task = uni.request({
    url: options.url.startsWith('http') ? options.url : `${BASE_URL}${options.url}`,
    method: (options.method || 'POST') as any,
    header: { ...options.headers, 'Accept': 'text/event-stream' },
    data: options.body,
    enableChunkedTransfer: true,
    responseType: 'arraybuffer',
    success: (res) => {
      if (res.statusCode < 200 || res.statusCode >= 300) {
        requestFailed = true
        let data: any = res.data
        if (data instanceof ArrayBuffer) {
          const text = arrayBufferToString(data)
          try {
            data = JSON.parse(text)
          } catch {
            data = text
          }
        }
        const detail = data?.detail || data?.message
        const message = typeof detail === 'string'
          ? detail
          : detail
            ? JSON.stringify(detail)
            : `请求失败 (${res.statusCode})`
        options.onError?.(new Error(normalizeErrorMessage(message, '请求失败，请稍后重试')))
        return
      }
      options.onComplete?.()
    },
    fail: (err: any) => options.onError?.(new Error(normalizeErrorMessage(err?.errMsg, '网络连接失败，请稍后重试')))
  })

  ;(task as any).onChunkReceived((res: { data: ArrayBuffer }) => {
    if (requestFailed) return
    const chunk = arrayBufferToString(res.data)
    buffer += chunk
    const lines = buffer.split('\n')
    buffer = lines.pop() || ''

    for (const line of lines) {
      parseSSELine(line, currentEvent, (evt, data) => {
        options.onEvent({ type: evt, data: normalizeSSEEventData(evt, data) })
      }, (evt) => { currentEvent = evt })
    }
  })

  return { abort: () => task.abort() }
}

function normalizeSSEEventData(event: string, data: any): any {
  if (event !== 'error') return data
  const rawMessage = data?.error || data?.detail || data?.message || data?.raw || data
  return {
    ...(data && typeof data === 'object' ? data : {}),
    error: normalizeErrorMessage(rawMessage, '任务执行失败，请稍后重试')
  }
}

function arrayBufferToString(buf: ArrayBuffer): string {
  if (typeof TextDecoder !== 'undefined') {
    return new TextDecoder().decode(buf)
  }
  const bytes = new Uint8Array(buf)
  let str = ''
  for (let i = 0; i < bytes.length; i++) {
    str += String.fromCharCode(bytes[i])
  }
  return decodeURIComponent(escape(str))
}

function parseSSELine(
  line: string,
  currentEvent: string,
  onData: (event: string, data: any) => void,
  onEventType: (event: string) => void
): void {
  const trimmed = line.trim()

  if (trimmed === '' || trimmed.startsWith(':')) return

  if (trimmed.startsWith('event:')) {
    onEventType(trimmed.slice(6).trim())
    return
  }

  if (trimmed.startsWith('data:')) {
    const raw = trimmed.slice(5).trim()
    try {
      const parsed = JSON.parse(raw)
      onData(currentEvent, parsed)
    } catch {
      onData(currentEvent, { raw })
    }
    onEventType('message')
  }
}
