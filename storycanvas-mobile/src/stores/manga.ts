import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { mangaApi, chaptersApi } from '@/api'
import { useSSE } from '@/composables/useSSE'
import { getToken } from '@/utils/storage'
import type { MangaImage, MangaGenerationStatus } from '@/api/types'

interface RefImage {
  filename: string
  image_path: string
  size_kb: number
  label?: string
  kind?: string
}

export type MangaPhase = 'idle' | 'generating-scenes' | 'editing-scenes' | 'generating-images'

export const useMangaStore = defineStore('manga', () => {
  const scenes = ref<string[]>([])
  const sanitizedIndices = ref<number[]>([])
  const images = ref<MangaImage[]>([])
  const phase = ref<MangaPhase>('idle')
  const progress = ref({ current: 0, total: 0, statusMsg: '' })
  const colorMode = ref<'color' | 'bw'>('color')
  const imageCount = ref(8)
  const characterProfiles = ref('')
  const refImages = ref<RefImage[]>([])
  const loading = ref(false)
  const aspectRatio = ref('9:16')
  const stylePresetName = ref('')
  const styleReferenceImageUrl = ref('')
  const backendTaskStatus = ref<MangaGenerationStatus | null>(null)
  const activeChapterContext = ref<number | null>(null)
  const imageCacheBust = ref(0)
  let activeSSE: ReturnType<typeof useSSE> | null = null

  const isGenerating = computed(() => phase.value !== 'idle')

  const progressPercent = computed(() => {
    if (progress.value.total === 0) return 0
    return Math.round((progress.value.current / progress.value.total) * 100)
  })

  async function loadScenes(chapterId: number) {
    loading.value = true
    try {
      const result = await mangaApi.getScenes(chapterId)
      if (activeChapterContext.value !== null && activeChapterContext.value !== chapterId) return
      scenes.value = result.scenes || []
      sanitizedIndices.value = result.sanitized_indices || []
    } catch {
      if (activeChapterContext.value === null || activeChapterContext.value === chapterId) {
        scenes.value = []
      }
    } finally {
      loading.value = false
    }
  }

  /** 加载章节已有漫画图片（回显已生成的图片） */
  async function loadImages(chapterId: number) {
    try {
      const chapter = await chaptersApi.getChapter(chapterId)
      if (activeChapterContext.value !== null && activeChapterContext.value !== chapterId) return
      images.value = chapter.images || []
      imageCacheBust.value = Date.now()
    } catch {
      if (activeChapterContext.value === null || activeChapterContext.value === chapterId) {
        images.value = []
      }
    }
  }

  /** 同时加载已有分镜和图片 */
  async function loadChapterManga(chapterId: number) {
    await Promise.all([
      loadScenes(chapterId),
      loadImages(chapterId)
    ])
  }

  async function generateScenes(chapterId: number) {
    phase.value = 'generating-scenes'
    try {
      const result = await mangaApi.generateScenes(chapterId)
      scenes.value = result.scenes || []
      sanitizedIndices.value = result.sanitized_indices || []
      return result
    } finally {
      phase.value = 'idle'
    }
  }

  async function updateScenes(chapterId: number, newScenes: string[]) {
    await mangaApi.updateScenes(chapterId, newScenes)
    scenes.value = newScenes
  }

  async function startMangaGeneration(chapterId: number) {
    if (scenes.value.length === 0) {
      throw new Error('请先生成并确认分镜脚本')
    }
    if (scenes.value.length !== imageCount.value) {
      throw new Error(`分镜数量需与生成张数一致（当前 ${scenes.value.length}/${imageCount.value}）`)
    }

    phase.value = 'generating-images'
    progress.value = { current: 0, total: 0, statusMsg: '准备中...' }

    const token = getToken()
    const headers: Record<string, string> = {}
    if (token) headers['Authorization'] = `Bearer ${token}`

    const sse = useSSE()
    activeSSE = sse

    const sizeByAspectRatio: Record<string, string> = {
      '9:16': '1024x1792',
      '3:4': '1024x1365',
      '2:3': '1024x1536',
      '1:1': '1024x1024',
      '3:2': '1536x1024',
      '4:3': '1365x1024',
      '16:9': '1792x1024'
    }
    const body: Record<string, any> = {
      size: sizeByAspectRatio[aspectRatio.value] || sizeByAspectRatio['9:16']
    }
    if (stylePresetName.value) body.style_preset_name = stylePresetName.value
    if (styleReferenceImageUrl.value) body.style_ref_url = styleReferenceImageUrl.value

    sse.start({
      url: mangaApi.mangaStreamUrl(chapterId),
      method: 'POST',
      headers,
      body: Object.keys(body).length > 0 ? body : undefined,
      onEvent: (event) => {
        if (activeChapterContext.value !== chapterId) return
        switch (event.type) {
          case 'scenes':
            scenes.value = event.data.scenes || []
            break
          case 'progress':
            progress.value = {
              current: event.data.current,
              total: event.data.total,
              statusMsg: `正在生成 ${event.data.current}/${event.data.total}...`
            }
            break
          case 'image':
            {
              const nextImage = event.data as MangaImage
              const existingIndex = images.value.findIndex(image =>
                image.id === nextImage.id || image.image_number === nextImage.image_number
              )
              if (existingIndex >= 0) {
                images.value[existingIndex] = nextImage
              } else {
                images.value.push(nextImage)
              }
              images.value.sort((a, b) => a.image_number - b.image_number)
              imageCacheBust.value = Date.now()
            }
            break
          case 'done':
            phase.value = 'idle'
            progress.value.statusMsg = '生成完成'
            activeSSE = null
            break
          case 'error':
            phase.value = 'idle'
            progress.value.statusMsg = event.data.error || '生成失败'
            activeSSE = null
            break
        }
      },
      onError: () => {
        if (activeChapterContext.value !== chapterId) return
        phase.value = 'idle'
        progress.value.statusMsg = '网络错误'
        activeSSE = null
      },
      onComplete: () => {
        if (activeChapterContext.value !== chapterId) return
        if (phase.value !== 'idle') phase.value = 'idle'
        activeSSE = null
        void loadImages(chapterId)
      }
    })
  }

  async function stopGeneration(chapterId?: number) {
    activeSSE?.stop()
    activeSSE = null
    if (chapterId) {
      await mangaApi.cancelMangaGeneration(chapterId)
    }
    phase.value = 'idle'
    progress.value.statusMsg = '已取消'
  }

  async function regenerateImage(chapterId: number, imageNumber: number, prompt: string) {
    return await mangaApi.regenerateImage(chapterId, imageNumber, prompt)
  }

  async function loadColorMode(chapterId: number) {
    const result = await mangaApi.getColorMode(chapterId)
    if (activeChapterContext.value !== null && activeChapterContext.value !== chapterId) return
    colorMode.value = (result.color_mode as 'color' | 'bw') || 'color'
  }

  async function saveColorMode(chapterId: number, mode: 'color' | 'bw') {
    await mangaApi.setColorMode(chapterId, mode)
    colorMode.value = mode
  }

  async function loadImageCount(chapterId: number) {
    const result = await mangaApi.getImageCount(chapterId)
    if (activeChapterContext.value !== null && activeChapterContext.value !== chapterId) return
    imageCount.value = result.image_count || 8
  }

  async function saveImageCount(chapterId: number, count: number) {
    await mangaApi.setImageCount(chapterId, count)
    imageCount.value = count
  }

  async function loadCharacterProfiles(storyId: number) {
    const result = await mangaApi.getStoryCharacters(storyId)
    characterProfiles.value = result.characters || ''
  }

  async function loadRefImages(storyId: number) {
    const result = await mangaApi.getStoryRefImages(storyId)
    refImages.value = result.images || []
  }

  async function uploadRefImage(storyId: number, base64: string) {
    const result = await mangaApi.uploadStoryRefImage(storyId, base64)
    refImages.value = result.images || []
  }

  async function deleteRefImage(storyId: number, filename: string) {
    const result = await mangaApi.deleteStoryRefImage(storyId, filename)
    refImages.value = result.images || []
  }

  async function loadAspectRatio(chapterId: number) {
    if (activeChapterContext.value !== null && activeChapterContext.value !== chapterId) return
    const saved = uni.getStorageSync(`manga_aspect_${chapterId}`)
    aspectRatio.value = saved || '9:16'
  }

  async function saveAspectRatio(chapterId: number, ratio: string) {
    aspectRatio.value = ratio
    uni.setStorageSync(`manga_aspect_${chapterId}`, ratio)
  }

  function setStylePreset(name: string) {
    stylePresetName.value = name
  }

  async function loadStylePreset(chapterId: number) {
    if (activeChapterContext.value !== null && activeChapterContext.value !== chapterId) return
    const saved = uni.getStorageSync(`manga_style_${chapterId}`)
    const savedReference = uni.getStorageSync(`manga_style_ref_${chapterId}`)
    stylePresetName.value = saved || ''
    styleReferenceImageUrl.value = savedReference || ''
  }

  function saveStylePreset(chapterId: number, name: string) {
    stylePresetName.value = name
    if (name) {
      uni.setStorageSync(`manga_style_${chapterId}`, name)
      uni.removeStorageSync(`manga_style_ref_${chapterId}`)
      styleReferenceImageUrl.value = ''
    } else {
      uni.removeStorageSync(`manga_style_${chapterId}`)
    }
  }

  function saveStyleReferenceImageUrl(chapterId: number, url: string | null) {
    setStyleReferenceImageUrl(url)
    if (url) {
      uni.setStorageSync(`manga_style_ref_${chapterId}`, url)
      uni.removeStorageSync(`manga_style_${chapterId}`)
      stylePresetName.value = ''
    } else {
      uni.removeStorageSync(`manga_style_ref_${chapterId}`)
    }
  }

  function setStyleReferenceImageUrl(url: string | null) {
    styleReferenceImageUrl.value = url ?? ''
  }

  function setBackendTaskStatus(status: MangaGenerationStatus) {
    backendTaskStatus.value = status
  }

  function refreshImageCache() {
    imageCacheBust.value = Date.now()
  }

  function clearBackendTaskStatus() {
    backendTaskStatus.value = null
  }

  function detachActiveStream() {
    activeSSE?.stop()
    activeSSE = null
  }

  function setActiveChapterContext(chapterId: number) {
    activeChapterContext.value = chapterId
  }

  return {
    scenes,
    sanitizedIndices,
    images,
    phase,
    progress,
    colorMode,
    imageCount,
    characterProfiles,
    refImages,
    loading,
    isGenerating,
    progressPercent,
    loadScenes,
    loadImages,
    loadChapterManga,
    generateScenes,
    updateScenes,
    startMangaGeneration,
    stopGeneration,
    detachActiveStream,
    regenerateImage,
    loadColorMode,
    saveColorMode,
    loadImageCount,
    saveImageCount,
    loadCharacterProfiles,
    loadRefImages,
    uploadRefImage,
    deleteRefImage,
    aspectRatio,
    stylePresetName,
    styleReferenceImageUrl,
    loadAspectRatio,
    saveAspectRatio,
    setStylePreset,
    loadStylePreset,
    saveStylePreset,
    setStyleReferenceImageUrl,
    saveStyleReferenceImageUrl,
    backendTaskStatus,
    imageCacheBust,
    setBackendTaskStatus,
    refreshImageCache,
    clearBackendTaskStatus,
    setActiveChapterContext
  }
})
