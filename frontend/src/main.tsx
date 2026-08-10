import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import './index.css'
import App from './App.tsx'
import { ToastContainer } from './components/ui/ToastContainer'
import { ConfirmDialog } from './components/ui/ConfirmDialog'
import { MobileActionSheet } from './components/mobile/MobileActionSheet'
import PwaInstallPrompt from './components/PwaInstallPrompt'
import TaskNotifier from './components/TaskNotifier'
import { registerServiceWorker, setupInstallPromptCapture } from './pwa'

// PWA：注册 Service Worker + 捕获安装事件（仅生产构建执行，开发模式跳过避免缓存干扰）
if (import.meta.env.PROD) {
  registerServiceWorker();
  setupInstallPromptCapture();
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <App />
      <ToastContainer />
      <ConfirmDialog />
      <MobileActionSheet />
      <PwaInstallPrompt />
      <TaskNotifier />
    </BrowserRouter>
  </StrictMode>,
)
