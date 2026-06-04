<script setup lang="ts">
import { onLaunch } from '@dcloudio/uni-app'
import { useAuthStore } from '@/stores/auth'

onLaunch(() => {
  // 注入状态栏高度 CSS 变量，供所有页面 padding-top 计算使用
  try {
    const { statusBarHeight } = uni.getSystemInfoSync()
    const sbh = (statusBarHeight || 0) + 'px'
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
      app.globalData.statusBarHeight = statusBarHeight || 0
    }
    // #endif
  } catch {
    // 忽略：极端情况下 getSystemInfoSync 可能失败
  }

  const authStore = useAuthStore()
  authStore.checkSession()
})
</script>

<style>
@import '@/styles/base.scss';

/* 全局 CSS 变量兜底：确保 calc(var(--status-bar-height) + X) 不会因变量缺失而失效 */
page {
  --status-bar-height: 0px;
}
</style>
