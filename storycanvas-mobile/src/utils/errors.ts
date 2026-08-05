const rules: Array<[RegExp, string]> = [
  [/\b402\b|payment required|insufficient (balance|credits?)/i, '上游 AI 服务余额不足，请充值或更换可用渠道后重试'],
  [/\b401\b|unauthorized|invalid api[ _-]?key/i, '身份验证失败，请重新登录或检查 API Key'],
  [/\b403\b|forbidden|permission denied/i, '当前账号没有执行此操作的权限'],
  [/\b404\b|not found/i, '请求的资源不存在或已被删除'],
  [/\b408\b|timed? out|timeout/i, '请求超时，请稍后重试'],
  [/\b409\b|conflict|already running|duplicate/i, '已有相同任务正在执行或任务状态冲突，请稍后刷新'],
  [/\b413\b|payload too large/i, '提交内容过大，请缩短内容或减少文件大小'],
  [/\b422\b|validation error|unprocessable entity/i, '提交参数不正确，请检查输入内容'],
  [/\b429\b|too many requests|rate limit/i, '请求过于频繁，请稍后重试'],
  [/\b500\b|internal server error/i, '服务器处理失败，请稍后重试'],
  [/\b502\b|bad gateway/i, '上游 AI 服务暂时不可用，请稍后重试'],
  [/\b503\b|service unavailable|overloaded/i, '服务暂时不可用或繁忙，请稍后重试'],
  [/\b504\b|gateway timeout/i, '上游服务响应超时，请稍后重试'],
  [/request:fail|network error|connection (refused|reset|error)/i, '网络连接失败，请检查网络后重试'],
]

// 网关/网络层错误（后端未启动、不可达）的通俗提示。
// 匹配到的既有文本如 "502 Bad Gateway"、"request:fail" 等，说明是反向代理或网络层
// 连不上后端服务，而非 AI 上游故障——避免误报「上游 AI 服务不可用」。
const gatewayPatterns: Array<[RegExp, string]> = [
  [/\b502\b/i, '后端服务暂不可用或正在重启，请稍后重试，必要时联系管理员检查服务状态'],
  [/\b504\b|\btimeout\b/i, '后端服务响应超时，请稍后重试'],
  [/\b503\b/i, '后端服务繁忙或正在初始化，请稍后重试'],
  [/\brequest:fail|\bnetwork error\b|connection (refused|reset)/i, '无法连接到后端服务，请确认网络或服务状态后重试'],
]

function gatewayStatusMessage(message: string): string | undefined {
  for (const [pattern, translated] of gatewayPatterns) {
    if (pattern.test(message)) return translated
  }
  return undefined
}

function extractMessage(value: unknown): string {
  if (typeof value === 'string') return value.trim()
  if (!value || typeof value !== 'object') return ''
  if (Array.isArray(value)) return value.map(extractMessage).filter(Boolean).join('；')
  const payload = value as Record<string, unknown>
  for (const key of ['detail', 'message', 'error', 'error_message', 'user_message']) {
    const message = extractMessage(payload[key])
    if (message) return message
  }
  return typeof payload.msg === 'string' ? payload.msg.trim() : ''
}

export function normalizeErrorMessage(error: unknown, fallback = '操作失败，请稍后重试'): string {
  const message = error instanceof Error ? error.message.trim() : extractMessage(error)
  if (!message) return fallback
  const gatewayMessage = gatewayStatusMessage(message)
  if (gatewayMessage) return gatewayMessage
  const text = message.toLowerCase()
  for (const [pattern, translated] of rules) {
    if (pattern.test(text)) return translated
  }
  return /[一-鿿]/.test(message) ? message.slice(0, 300) : fallback
}
