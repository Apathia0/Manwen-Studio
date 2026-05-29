import { defineStore } from 'pinia'
import { ref } from 'vue'
import { frameworkApi } from '@/api'
import type { Character, OutlineAct } from '@/api/types'

interface FrameworkSnapshot {
  id: number
  created_at: string
  description: string
}

export const useFrameworkStore = defineStore('framework', () => {
  const tags = ref<Record<string, string> | null>(null)
  const characters = ref<Character[]>([])
  const outline = ref<{ three_acts: OutlineAct[] } | null>(null)
  const snapshots = ref<FrameworkSnapshot[]>([])
  const loading = ref(false)
  const generating = ref(false)

  async function loadFramework(storyId: number) {
    loading.value = true
    try {
      const story = await import('@/api').then(m => m.storiesApi.getStory(storyId))
      if (story) {
        // 从 story 中提取框架数据
        const storyData = story as any
        if (storyData.tags) tags.value = storyData.tags
        if (storyData.characters) characters.value = storyData.characters
        if (storyData.outline) outline.value = storyData.outline
      }
    } finally {
      loading.value = false
    }
  }

  async function generateFramework(storyId: number, description: string) {
    generating.value = true
    try {
      const result = await frameworkApi.generateFramework(storyId, description)
      tags.value = result.tags
      characters.value = result.characters
      outline.value = result.outline
      return result
    } finally {
      generating.value = false
    }
  }

  async function regenerateTags(storyId: number) {
    const result = await frameworkApi.regenerateTags(storyId)
    tags.value = result.tags
    return result
  }

  async function regenerateCharacters(storyId: number) {
    const result = await frameworkApi.regenerateCharacters(storyId)
    characters.value = result.characters
    return result
  }

  async function regenerateOutline(storyId: number) {
    const result = await frameworkApi.regenerateOutline(storyId)
    outline.value = result.outline
    return result
  }

  async function loadSnapshots(storyId: number) {
    const result = await frameworkApi.getSnapshots(storyId)
    snapshots.value = result.snapshots
    return result
  }

  async function restoreSnapshot(storyId: number, snapshotId: number) {
    const result = await frameworkApi.restoreSnapshot(storyId, snapshotId)
    // 恢复后重新加载框架
    await loadFramework(storyId)
    return result
  }

  return {
    tags,
    characters,
    outline,
    snapshots,
    loading,
    generating,
    loadFramework,
    generateFramework,
    regenerateTags,
    regenerateCharacters,
    regenerateOutline,
    loadSnapshots,
    restoreSnapshot
  }
})
