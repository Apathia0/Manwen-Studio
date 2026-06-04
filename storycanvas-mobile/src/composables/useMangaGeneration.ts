import { ref } from 'vue'
import { useSSE } from './useSSE'
import { getToken } from '@/utils/storage'
import type { MangaImage } from '@/api/types'

export function useMangaGeneration(chapterId: () => number) {
  const { streaming, start, stop } = useSSE()
  const progress = ref({ current: 0, total: 0, statusMsg: '' })
  const images = ref<MangaImage[]>([])

  function generate() {
    progress.value = { current: 0, total: 0, statusMsg: '准备中...' }
    images.value = []

    start({
      url: `/api/chapters/${chapterId()}/generate-manga-stream`,
      headers: {
        'Authorization': `Bearer ${getToken()}`
      },
      onEvent: (event) => {
        switch (event.type) {
          case 'scenes':
            break
          case 'progress':
            progress.value = {
              current: event.data.current,
              total: event.data.total,
              statusMsg: `正在生成 ${event.data.current}/${event.data.total}...`
            }
            break
          case 'image':
            images.value.push(event.data)
            break
          case 'done':
            progress.value.statusMsg = '生成完成'
            break
          case 'error':
            uni.showToast({ title: event.data.error, icon: 'none' })
            break
        }
      }
    })
  }

  function clearImages() {
    images.value = []
    progress.value = { current: 0, total: 0, statusMsg: '' }
  }

  return {
    streaming,
    progress,
    images,
    generate,
    clearImages,
    stopGeneration: stop
  }
}
