import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { chaptersApi } from '@/api'
import type { Chapter } from '@/api/types'
import { getStorage, setStorage } from '@/utils/storage'
import { STORAGE_KEYS } from '@/utils/constants'

export type WorkspaceTab = 'framework' | 'editor' | 'manga' | 'agent'

export const useWorkspaceStore = defineStore('workspace', () => {
  const chapters = ref<Chapter[]>([])
  const activeChapterId = ref<number | null>(null)
  const loadingWorkspace = ref(false)
  const activeTab = ref<WorkspaceTab>(
    (getStorage(STORAGE_KEYS.WORKSPACE_TAB) as WorkspaceTab) || 'editor'
  )

  const activeChapter = computed(() => {
    return chapters.value.find(c => c.id === activeChapterId.value) || null
  })

  const sortedChapters = computed(() => {
    return [...chapters.value].sort((a, b) => a.chapter_number - b.chapter_number)
  })

  const activeChapterTitle = computed(() => {
    const ch = activeChapter.value
    return ch ? `第${ch.chapter_number}章 ${ch.title || ''}` : '暂无章节'
  })

  async function loadWorkspace(storyId: number) {
    loadingWorkspace.value = true
    try {
      chapters.value = await chaptersApi.getChapters(storyId)
      if (chapters.value.length > 0 && !activeChapterId.value) {
        activeChapterId.value = chapters.value[0].id
      }
    } finally {
      loadingWorkspace.value = false
    }
  }

  async function createChapter(storyId: number) {
    const chapter = await chaptersApi.createChapter(storyId)
    chapters.value.push(chapter)
    activeChapterId.value = chapter.id
    return chapter
  }

  async function deleteChapter(chapterId: number) {
    await chaptersApi.deleteChapter(chapterId)
    chapters.value = chapters.value.filter(c => c.id !== chapterId)
    if (activeChapterId.value === chapterId) {
      activeChapterId.value = chapters.value.length > 0 ? chapters.value[0].id : null
    }
  }

  function setActiveChapter(id: number) {
    activeChapterId.value = id
  }

  function switchTab(tab: WorkspaceTab) {
    activeTab.value = tab
    setStorage(STORAGE_KEYS.WORKSPACE_TAB, tab)
  }

  function nextChapter() {
    const sorted = sortedChapters.value
    const currentIndex = sorted.findIndex(c => c.id === activeChapterId.value)
    if (currentIndex < sorted.length - 1) {
      activeChapterId.value = sorted[currentIndex + 1].id
    }
  }

  function prevChapter() {
    const sorted = sortedChapters.value
    const currentIndex = sorted.findIndex(c => c.id === activeChapterId.value)
    if (currentIndex > 0) {
      activeChapterId.value = sorted[currentIndex - 1].id
    }
  }

  function updateChapterInList(chapter: Chapter) {
    const index = chapters.value.findIndex(c => c.id === chapter.id)
    if (index !== -1) {
      chapters.value[index] = { ...chapters.value[index], ...chapter }
    }
  }

  return {
    chapters,
    activeChapterId,
    activeChapter,
    sortedChapters,
    activeChapterTitle,
    loadingWorkspace,
    activeTab,
    loadWorkspace,
    createChapter,
    deleteChapter,
    setActiveChapter,
    switchTab,
    nextChapter,
    prevChapter,
    updateChapterInList
  }
})
