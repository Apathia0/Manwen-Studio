import { BASE_URL } from './constants'

/** 判断是否为绝对 URL（OSS / CDN 等远程地址） */
function isAbsoluteUrl(value: string): boolean {
  return /^https?:\/\//.test(value)
}

/**
 * 漫画/封面/参考图资源的公网 URL
 * - OSS/CDN 的绝对 URL → 直接返回
 * - /static/ 前缀的 → 直接返回
 * - 本地路径（manga_outputs/xxx）→ 通过 /static/manga/ 代理
 */
export function mangaImageUrl(imagePath: string, cacheBust?: number): string {
  if (isAbsoluteUrl(imagePath) || imagePath.startsWith('/static/')) {
    return cacheBust ? `${imagePath}?t=${cacheBust}` : imagePath
  }
  const clean = imagePath.replace('manga_outputs/', '')
  const url = `${BASE_URL}/static/manga/${clean}`
  return cacheBust ? `${url}?t=${cacheBust}` : url
}

export function coverImageUrl(coverPath: string | null): string | null {
  if (!coverPath) return null
  if (isAbsoluteUrl(coverPath) || coverPath.startsWith('/static/')) return coverPath
  return mangaImageUrl(coverPath)
}

export function refImageUrl(imagePath: string): string {
  if (isAbsoluteUrl(imagePath) || imagePath.startsWith('/static/')) return imagePath
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
  if (isAbsoluteUrl(filePath) || filePath.startsWith('/static/')) return filePath
  const clean = filePath.replace(/\\/g, '/').replace(/^video_outputs[/\\]/, '')
  return `${BASE_URL}/static/video/${clean}`
}
