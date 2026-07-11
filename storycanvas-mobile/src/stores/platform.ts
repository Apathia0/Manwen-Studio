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

  function sanitizeAnnouncementContent(content: string): string {
    return content
      .replace(/<(script|style|iframe)\b[^>]*>[\s\S]*?<\/\1\s*>/gi, '')
      .replace(/\s+on[a-z]+\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+)/gi, '')
      .replace(/\s+style\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+)/gi, '')
      .replace(/\s+(?:href|src)\s*=\s*(["'])\s*javascript:[\s\S]*?\1/gi, '')
  }

  function normalizeAnnouncement(data?: PlatformAnnouncement | null): PlatformAnnouncement | null {
    if (!data?.enabled || !data.content?.trim()) return null

    const content = sanitizeAnnouncementContent(data.content).trim()
    return content ? { ...data, content } : null
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
