import { get } from '@/utils/request'

interface PublicPlatformSettings {
  site_name: string
  site_description: string
  [key: string]: any
}

interface PlatformAnnouncement {
  title: string
  content: string
  updated_at: string
}

/** 获取公开平台设置 */
export function getPublicSettings(): Promise<PublicPlatformSettings> {
  return get<PublicPlatformSettings>('/api/platform/settings/public')
}

/** 获取平台公告 */
export function getAnnouncement(): Promise<PlatformAnnouncement> {
  return get<PlatformAnnouncement>('/api/platform/announcement')
}

/** 获取站点图标 URL */
export function iconUrl(): string {
  return '/api/platform/icon'
}
