import { get, post, put, del } from '@/utils/request'
import { uploadFile } from '@/utils/upload'
import type { MangaImage, MangaGenerationStatus, ImageRedrawMode } from './types'

interface RefImage {
  filename: string
  image_path: string
  size_kb: number
  label?: string
  kind?: string
}

interface RefImagesPayload {
  images: RefImage[]
  max: number
  source?: string
}

/** 生成分镜 */
export function generateScenes(chapterId: number): Promise<{ scenes: string[]; sanitized_indices?: number[] }> {
  return post(`/api/chapters/${chapterId}/generate-scenes`)
}

/** 获取分镜 */
export function getScenes(chapterId: number): Promise<{ scenes: string[]; sanitized_indices?: number[] }> {
  return get(`/api/chapters/${chapterId}/scenes`)
}

/** 更新分镜 */
export function updateScenes(chapterId: number, scenes: string[]): Promise<{ ok: boolean; image_count: number }> {
  return put(`/api/chapters/${chapterId}/scenes`, { scenes })
}

/** 选段生成分镜 */
export function scenesFromSelection(chapterId: number, selectedText: string, characterProfiles?: string, pageCount?: number): Promise<{ scenes: string[]; page_count?: number }> {
  return post(`/api/chapters/${chapterId}/scenes-from-selection`, { selected_text: selectedText, character_profiles: characterProfiles, page_count: pageCount })
}

/** 漫画流式生成 (SSE) — 返回 URL */
export function mangaStreamUrl(chapterId: number): string {
  return `/api/chapters/${chapterId}/generate-manga-stream`
}

/** 清除漫画图片 */
export function clearMangaImages(chapterId: number): Promise<void> {
  return del(`/api/chapters/${chapterId}/manga-images`)
}

/** 重绘单图（支持局部重绘蒙版） */
export function regenerateImage(
  chapterId: number,
  imageNumber: number,
  prompt: string,
  mode?: string,
  options?: { size?: string; stylePresetName?: string; styleRefUrl?: string; mask?: string }
): Promise<MangaImage> {
  const body: Record<string, any> = { prompt, mode: mode || 'regenerate' }
  if (options?.size) body.size = options.size
  if (options?.stylePresetName) body.style_preset_name = options.stylePresetName
  if (options?.styleRefUrl) body.style_ref_url = options.styleRefUrl
  if (options?.mask) body.mask = options.mask
  return post<MangaImage>(`/api/chapters/${chapterId}/regenerate-image/${imageNumber}`, body)
}

/** 获取色彩模式 */
export function getColorMode(chapterId: number): Promise<{ color_mode: string }> {
  return get(`/api/chapters/${chapterId}/color-mode`)
}

/** 设置色彩模式 */
export function setColorMode(chapterId: number, colorMode: string): Promise<void> {
  return put(`/api/chapters/${chapterId}/color-mode`, { color_mode: colorMode })
}

/** 获取图片数量 */
export function getImageCount(chapterId: number): Promise<{ image_count: number }> {
  return get(`/api/chapters/${chapterId}/image-count`)
}

/** 设置图片数量 */
export function setImageCount(chapterId: number, imageCount: number): Promise<void> {
  return put(`/api/chapters/${chapterId}/image-count`, { image_count: imageCount })
}

/** 获取故事级角色 */
export function getStoryCharacters(storyId: number): Promise<{ characters: string }> {
  return get(`/api/stories/${storyId}/characters`)
}

/** 更新故事级角色 */
export function updateStoryCharacters(storyId: number, characters: string): Promise<void> {
  return put(`/api/stories/${storyId}/characters`, { characters })
}

/** 从框架生成角色 */
export function generateStoryCharacters(storyId: number): Promise<{ characters: string }> {
  return post(`/api/stories/${storyId}/characters/generate`)
}

/** 获取章节级角色 */
export function getChapterCharacters(chapterId: number): Promise<{ characters: string; source: string }> {
  return get(`/api/chapters/${chapterId}/characters`)
}

/** 更新章节级角色 */
export function updateChapterCharacters(chapterId: number, characters: string): Promise<void> {
  return put(`/api/chapters/${chapterId}/characters`, { characters })
}

/** 删除章节级角色 */
export function deleteChapterCharacters(chapterId: number): Promise<void> {
  return del(`/api/chapters/${chapterId}/characters`)
}

/** 获取故事参考图 */
export function getStoryRefImages(storyId: number): Promise<RefImagesPayload> {
  return get(`/api/stories/${storyId}/ref-images`)
}

/** 上传故事参考图 */
export function uploadStoryRefImage(storyId: number, base64: string): Promise<RefImagesPayload> {
  return post(`/api/stories/${storyId}/ref-images`, { image: base64 })
}

/** 删除故事参考图 */
export function deleteStoryRefImage(storyId: number, filename: string): Promise<RefImagesPayload> {
  return del(`/api/stories/${storyId}/ref-images/${filename}`)
}

/** 获取章节参考图 */
export function getChapterRefImages(chapterId: number): Promise<RefImagesPayload> {
  return get(`/api/chapters/${chapterId}/ref-images`)
}

/** 上传章节参考图 */
export function uploadChapterRefImage(chapterId: number, base64: string): Promise<RefImagesPayload> {
  return post(`/api/chapters/${chapterId}/ref-images`, { image: base64 })
}

/** 删除章节参考图 */
export function deleteChapterRefImage(chapterId: number, filename: string): Promise<RefImagesPayload> {
  return del(`/api/chapters/${chapterId}/ref-images/${filename}`)
}

/** 角色参考图生成 (SSE) — 返回 URL */
export function characterRefImagesUrl(storyId: number): string {
  return `/api/stories/${storyId}/character-ref-images/generate`
}

/** 上传漫画章节的自定义风格参考图（multipart FormData） */
export function uploadStyleReferenceImage(
  chapterId: number,
  filePath: string
): Promise<{ success: boolean; style_reference_image_url: string }> {
  return uploadFile(
    `/api/chapters/${chapterId}/upload-style-reference`,
    filePath,
    'file'
  )
}

/** 获取漫画生成状态 */
export function getMangaGenerationStatus(chapterId: number): Promise<MangaGenerationStatus> {
  return get(`/api/chapters/${chapterId}/manga-generation-status`)
}

/** 取消漫画生成 */
export function cancelMangaGeneration(chapterId: number): Promise<{ ok: boolean; message: string }> {
  return post(`/api/chapters/${chapterId}/cancel-manga-generation`)
}

/** 重绘故事参考图 */
export function redrawStoryRefImage(
  storyId: number,
  filename: string,
  payload: { prompt: string; mode: ImageRedrawMode; mask?: string }
): Promise<RefImagesPayload> {
  return post(`/api/stories/${storyId}/ref-images/${encodeURIComponent(filename)}/redraw`, payload)
}

/** 重绘章节参考图 */
export function redrawChapterRefImage(
  chapterId: number,
  filename: string,
  payload: { prompt: string; mode: ImageRedrawMode; mask?: string }
): Promise<RefImagesPayload> {
  return post(`/api/chapters/${chapterId}/ref-images/${encodeURIComponent(filename)}/redraw`, payload)
}

/** 上传角色参考图 */
export function uploadCharacterRefImage(
  storyId: number,
  file: string,
  characterName: string,
  replaceExisting?: boolean
): Promise<RefImagesPayload> {
  return post(`/api/stories/${storyId}/character-ref-images/upload`, {
    image: file,
    character_name: characterName,
    replace_existing: replaceExisting,
  })
}

/** 删除角色参考图 */
export function deleteCharacterRefImage(storyId: number, filename: string): Promise<RefImagesPayload> {
  return del(`/api/stories/${storyId}/character-ref-images/${encodeURIComponent(filename)}`)
}
