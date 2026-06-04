/**
 * 格式化工具函数
 */

/**
 * 格式化日期为可读字符串
 * @param dateStr ISO 日期字符串
 * @param format 格式类型
 */
export function formatDate(dateStr: string, format: 'full' | 'date' | 'time' | 'relative' = 'date'): string {
  if (!dateStr) return ''
  const date = new Date(dateStr)
  const now = new Date()

  if (format === 'relative') {
    const diff = now.getTime() - date.getTime()
    const seconds = Math.floor(diff / 1000)
    const minutes = Math.floor(seconds / 60)
    const hours = Math.floor(minutes / 60)
    const days = Math.floor(hours / 24)

    if (seconds < 60) return '刚刚'
    if (minutes < 60) return `${minutes}分钟前`
    if (hours < 24) return `${hours}小时前`
    if (days < 7) return `${days}天前`
    if (days < 30) return `${Math.floor(days / 7)}周前`
    if (days < 365) return `${Math.floor(days / 30)}个月前`
    return `${Math.floor(days / 365)}年前`
  }

  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  const hour = String(date.getHours()).padStart(2, '0')
  const minute = String(date.getMinutes()).padStart(2, '0')

  switch (format) {
    case 'full':
      return `${year}-${month}-${day} ${hour}:${minute}`
    case 'time':
      return `${hour}:${minute}`
    case 'date':
    default:
      return `${year}-${month}-${day}`
  }
}

/**
 * 格式化金额
 * @param amount 金额（分或元）
 * @param isCents 是否为分
 */
export function formatMoney(amount: number, isCents = false): string {
  const yuan = isCents ? amount / 100 : amount
  return `¥${yuan.toFixed(2)}`
}

/**
 * 格式化文件大小
 * @param bytes 字节数
 */
export function formatFileSize(bytes: number): string {
  if (bytes === 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  const k = 1024
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return `${(bytes / Math.pow(k, i)).toFixed(1)} ${units[i]}`
}

/**
 * 格式化数字（添加千分位分隔符）
 */
export function formatNumber(num: number): string {
  return num.toLocaleString('zh-CN')
}

/**
 * 格式化字数
 * @param count 字数
 */
export function formatWordCount(count: number): string {
  if (count >= 10000) {
    return `${(count / 10000).toFixed(1)}万字`
  }
  return `${count}字`
}

/**
 * 截断文本
 * @param text 原始文本
 * @param maxLength 最大长度
 */
export function truncateText(text: string, maxLength: number): string {
  if (!text) return ''
  if (text.length <= maxLength) return text
  return text.slice(0, maxLength) + '...'
}
