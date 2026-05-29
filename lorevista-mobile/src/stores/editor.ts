import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { chaptersApi } from '@/api'

export const useEditorStore = defineStore('editor', () => {
  const content = ref('')
  const draftContent = ref('')
  const editing = ref(false)
  const saving = ref(false)
  const loading = ref(false)
  const lastSavedAt = ref<string | null>(null)

  const wordCount = computed(() => {
    const text = editing.value ? draftContent.value : content.value
    return text ? text.replace(/\s/g, '').length : 0
  })

  const hasUnsavedChanges = computed(() => {
    return editing.value && draftContent.value !== content.value
  })

  async function loadContent(chapterId: number) {
    loading.value = true
    try {
      const chapter = await chaptersApi.getChapter(chapterId)
      content.value = chapter.novel_content || ''
      draftContent.value = content.value
      editing.value = false
      return chapter
    } finally {
      loading.value = false
    }
  }

  function startEditing() {
    draftContent.value = content.value
    editing.value = true
  }

  function cancelEditing() {
    draftContent.value = content.value
    editing.value = false
  }

  async function saveContent(chapterId: number) {
    saving.value = true
    try {
      await chaptersApi.saveContent(chapterId, draftContent.value)
      content.value = draftContent.value
      editing.value = false
      lastSavedAt.value = new Date().toISOString()
    } finally {
      saving.value = false
    }
  }

  function updateDraft(text: string) {
    draftContent.value = text
  }

  function setContentDirectly(text: string) {
    content.value = text
    draftContent.value = text
  }

  return {
    content,
    draftContent,
    editing,
    saving,
    loading,
    lastSavedAt,
    wordCount,
    hasUnsavedChanges,
    loadContent,
    startEditing,
    cancelEditing,
    saveContent,
    updateDraft,
    setContentDirectly
  }
})
