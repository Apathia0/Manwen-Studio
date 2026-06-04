import { createSSRApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'

// H5 路由兼容：旧 /pages/workspace/framework 路由已删除，重定向到 chapter-view
if (typeof window !== 'undefined') {
  const path = window.location.pathname
  if (path.includes('/pages/workspace/framework')) {
    const params = new URLSearchParams(window.location.search)
    const storyId = params.get('storyId')
    window.history.replaceState(
      null,
      '',
      storyId ? `/pages/workspace/chapter-view?storyId=${storyId}` : '/'
    )
  }
}

export function createApp() {
  const app = createSSRApp(App)
  const pinia = createPinia()
  app.use(pinia)
  return { app }
}
