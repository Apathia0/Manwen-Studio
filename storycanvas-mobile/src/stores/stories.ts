import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { storiesApi } from '@/api'
import type { Story } from '@/api/types'
import { getStorage, setStorage } from '@/utils/storage'
import { STORAGE_KEYS } from '@/utils/constants'

export const useStoriesStore = defineStore('stories', () => {
  const list = ref<Story[]>([])
  const loading = ref(false)
  const activeStoryId = ref<number | null>(
    getStorage(STORAGE_KEYS.ACTIVE_STORY) ? Number(getStorage(STORAGE_KEYS.ACTIVE_STORY)) : null
  )

  const activeStory = computed(() => {
    return list.value.find(s => s.id === activeStoryId.value) || null
  })

  const sortedStories = computed(() => {
    return [...list.value].sort((a, b) => 
      new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
    )
  })

  async function fetchStories() {
    loading.value = true
    try {
      list.value = await storiesApi.getStories()
      // 调试: 打印每个故事的 onboarding 状态
      console.log('[Stories] 加载故事列表:', list.value.map(s => ({
        id: s.id,
        title: s.title,
        onboarding_completed: s.onboarding_completed
      })))
    } finally {
      loading.value = false
    }
  }

  async function createStory(title: string, description?: string) {
    const story = await storiesApi.createStory(title, description)
    list.value.unshift(story)
    return story
  }

  async function updateStory(id: number, data: Partial<Story>) {
    const updated = await storiesApi.updateStory(id, data)
    const index = list.value.findIndex(s => s.id === id)
    if (index !== -1) {
      list.value[index] = updated
    }
    return updated
  }

  async function deleteStory(id: number) {
    await storiesApi.deleteStory(id)
    list.value = list.value.filter(s => s.id !== id)
    if (activeStoryId.value === id) {
      activeStoryId.value = null
      setStorage(STORAGE_KEYS.ACTIVE_STORY, '')
    }
  }

  function setActiveStory(id: number) {
    activeStoryId.value = id
    setStorage(STORAGE_KEYS.ACTIVE_STORY, String(id))
  }

  return {
    list,
    loading,
    activeStoryId,
    activeStory,
    sortedStories,
    fetchStories,
    createStory,
    updateStory,
    deleteStory,
    setActiveStory
  }
})
