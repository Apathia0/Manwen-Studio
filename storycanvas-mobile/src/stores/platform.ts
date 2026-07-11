import { defineStore } from 'pinia'
import { ref } from 'vue'
import { platformApi } from '@/api'

interface PublicPlatformSettings {
  site_name: string
  site_slogan: string
  site_description: string
  announcement?: PlatformAnnouncement
  [key: string]: any
}

interface PlatformAnnouncement {
  enabled: boolean
  title: string
  content: string
  updated_at?: string
}

export const usePlatformStore = defineStore('platform', () => {
  const settings = ref<PublicPlatformSettings | null>(null)
  const announcement = ref<PlatformAnnouncement | null>(null)
  const announcementDismissed = ref(false)
  const loading = ref(false)

  function normalizeAnnouncement(data?: PlatformAnnouncement | null): PlatformAnnouncement | null {
    return data?.enabled && data.content?.trim() ? data : null
  }

  async function fetchSettings() {
    loading.value = true
    try {
      settings.value = await platformApi.getPublicSettings()
      announcement.value = normalizeAnnouncement(settings.value.announcement)
    } catch {
      settings.value = null
    } finally {
      loading.value = false
    }
  }

  async function fetchAnnouncement() {
    try {
      const data = await platformApi.getAnnouncement()
      announcement.value = normalizeAnnouncement(data)
    } catch {
      announcement.value = normalizeAnnouncement(settings.value?.announcement)
    }
  }

  function dismissAnnouncement() {
    announcementDismissed.value = true
  }

  return {
    settings,
    announcement,
    announcementDismissed,
    loading,
    fetchSettings,
    fetchAnnouncement,
    dismissAnnouncement
  }
})
