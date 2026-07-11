<script setup lang="ts">
import { onLaunch, onShow } from '@dcloudio/uni-app'
import { useAuthStore } from '@/stores/auth'
import { usePlatformStore } from '@/stores/platform'

const DEFAULT_SITE_NAME = 'StoryCanvas'
const DEFAULT_SITE_SLOGAN = 'AI 小说与漫画创作平台'

function syncWebsiteTitle() {
  // #ifdef H5
  const platformStore = usePlatformStore()
  const siteName = platformStore.settings?.site_name?.trim() || DEFAULT_SITE_NAME
  const siteSlogan = platformStore.settings
    ? platformStore.settings.site_slogan?.trim()
    : DEFAULT_SITE_SLOGAN
  document.title = siteSlogan ? `${siteName} - ${siteSlogan}` : siteName
  // #endif
}

async function fetchPlatformSettingsAndSyncTitle() {
  const platformStore = usePlatformStore()
  await platformStore.fetchSettings()
  syncWebsiteTitle()
}

onLaunch(async () => {
  // 注入状态栏高度 CSS 变量，供所有页面 padding-top 计算使用
  try {
    const { statusBarHeight } = uni.getSystemInfoSync()
    let effectiveStatusBarHeight = statusBarHeight || 0
    // H5 浏览器工具栏不属于页面视口，不能重复计入应用顶部间距
    // #ifdef H5
    effectiveStatusBarHeight = 0
    // #endif
    const sbh = effectiveStatusBarHeight + 'px'
    // #ifdef H5
    document.documentElement.style.setProperty('--status-bar-height', sbh)
    // #endif
    // #ifdef APP-PLUS
    const wv = plus.webview.currentWebview()
    wv?.evalJS?.("document.documentElement.style.setProperty('--status-bar-height','" + sbh + "')")
    // #endif
    // #ifdef MP-WEIXIN
    // 微信小程序：通过 page-meta 的 page-style 注入（需在页面中使用 page-meta 组件配合）
    // 此处将值存入全局 getApp()，页面可通过 getApp().globalData.statusBarHeight 获取
    const app = getApp()
    if (app) {
      app.globalData = app.globalData || {}
      app.globalData.statusBarHeight = effectiveStatusBarHeight
    }
    // #endif
  } catch {
    // 忽略：极端情况下 getSystemInfoSync 可能失败
  }

  const authStore = useAuthStore()
  authStore.checkSession()
  await fetchPlatformSettingsAndSyncTitle()
})

onShow(() => {
  syncWebsiteTitle()
})
</script>

<style>
@import '@/styles/base.scss';

/* 全局 CSS 变量兜底：确保 calc(var(--status-bar-height) + X) 不会因变量缺失而失效 */
page {
  --status-bar-height: 0px;
}
</style>
