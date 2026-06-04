import { BASE_URL } from './constants'

export function mangaImageUrl(imagePath: string, cacheBust?: number): string {
  const clean = imagePath.replace('manga_outputs/', '')
  const url = `${BASE_URL}/static/manga/${clean}`
  return cacheBust ? `${url}?t=${cacheBust}` : url
}

export function coverImageUrl(coverPath: string | null): string | null {
  if (!coverPath) return null
  return mangaImageUrl(coverPath)
}

export function refImageUrl(imagePath: string): string {
  return mangaImageUrl(imagePath)
}
