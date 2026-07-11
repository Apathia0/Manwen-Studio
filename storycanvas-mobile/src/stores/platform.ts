import { defineStore } from 'pinia'
import { ref } from 'vue'
import { platformApi } from '@/api'

interface PublicPlatformSettings {
  site_name: string
  site_slogan: string
  site_description: string
  [key: string]: any
}

interface PlatformAnnouncement {
  title: string
  content: string
  updated_at: string
}

export const usePlatformStore = defineStore('platform', () => {
  const settings = ref<PublicPlatformSettings | null>(null)
  const announcement = ref<PlatformAnnouncement | null>(null)
  const loading = ref(false)

  async function fetchSettings() {
    loading.value = true
    try {
      settings.value = await platformApi.getPublicSettings()
    } catch {
      settings.value = null
    } finally {
      loading.value = false
    }
  }

  async function fetchAnnouncement() {
    try {
      announcement.value = await platformApi.getAnnouncement()
    } catch {
      announcement.value = null
    }
  }

  return {
    settings,
    announcement,
    loading,
    fetchSettings,
    fetchAnnouncement
  }
})
