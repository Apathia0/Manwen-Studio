import { BASE_URL } from './constants'

/** 判断是否为可直接展示的远程或内存资源地址 */
function isDirectUrl(value: string): boolean {
  return /^(https?:)?\/\//i.test(value) || /^(data|blob):/i.test(value)
}

/** 规范 OSS/CDN 地址，协议相对地址统一使用 HTTPS */
function normalizeDirectUrl(value: string): string {
  if (value.startsWith('//')) return `https:${value}`
  return value
}

/**
 * 漫画/封面/参考图资源的公网 URL
 * - OSS/CDN 的绝对 URL → 直接返回
 * - /static/ 前缀的 → 直接返回
 * - 本地路径（manga_outputs/xxx）→ 通过 /static/manga/ 代理
 */
export function mangaImageUrl(imagePath: string, cacheBust?: number): string {
  const normalizedPath = imagePath.trim().replace(/\\/g, '/')
  if (isDirectUrl(normalizedPath)) {
    // OSS 地址可能包含签名查询参数，不能追加缓存参数破坏签名。
    return normalizeDirectUrl(normalizedPath)
  }
  if (normalizedPath.startsWith('/static/')) {
    const staticUrl = `${BASE_URL}${normalizedPath}`
    return cacheBust ? appendCacheBust(staticUrl, cacheBust) : staticUrl
  }
  const clean = normalizedPath
    .replace(/^.*\/manga_outputs\//, '')
    .replace(/^manga_outputs\//, '')
    .replace(/^\/+/, '')
  const url = `${BASE_URL}/static/manga/${clean}`
  return cacheBust ? appendCacheBust(url, cacheBust) : url
}

function appendCacheBust(url: string, cacheBust: number): string {
  return `${url}${url.includes('?') ? '&' : '?'}t=${cacheBust}`
}

export function coverImageUrl(coverPath: string | null): string | null {
  if (!coverPath) return null
  return mangaImageUrl(coverPath)
}

export function refImageUrl(imagePath: string): string {
  return mangaImageUrl(imagePath)
}

/**
 * 视频资源的公网 URL
 * - OSS/CDN 的绝对 URL → 直接返回
 * - /static/ 前缀的 → 直接返回
 * - 本地路径（video_outputs/xxx）→ 通过 /static/video/ 代理
 */
export function videoAssetUrl(filePath: string | null): string | null {
  if (!filePath) return null
  const normalizedPath = filePath.trim().replace(/\\/g, '/')
  if (isDirectUrl(normalizedPath)) return normalizeDirectUrl(normalizedPath)
  if (normalizedPath.startsWith('/static/')) return `${BASE_URL}${normalizedPath}`
  const clean = normalizedPath.replace(/^.*\/video_outputs\//, '').replace(/^\/+/, '')
  return `${BASE_URL}/static/video/${clean}`
}
