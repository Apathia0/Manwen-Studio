import { ref, onUnmounted, type Ref } from 'vue'
import { mangaApi } from '@/api'
import { useMangaStore } from '@/stores/manga'
import { useUiStore } from '@/stores/ui'
import type { MangaGenerationStatus } from '@/api/types'

/** 后端任务活跃状态集合：这些状态需要持续轮询 */
const ACTIVE_STATUSES = new Set<MangaGenerationStatus['status']>([
  'pending',
  'running',
  'retrying',
])

/** 轮询间隔（毫秒） */
const POLL_INTERVAL = 3000

/** 安全超时（10 分钟），防止轮询永不停止 */
const SAFETY_TIMEOUT = 10 * 60 * 1000

/**
 * 漫画生成后台任务状态轮询 composable
 * 提供断点续传功能：页面刷新后检测到后端运行中的任务，自动恢复进度显示
 */
export function useMangaGenerationStatus(chapterId: Ref<number | null>) {
  const mangaStore = useMangaStore()
  const uiStore = useUiStore()

  /** 轮询定时器 */
  const timerRef = ref<ReturnType<typeof setInterval> | null>(null)

  /** 安全超时定时器 */
  const safetyTimerRef = ref<ReturnType<typeof setTimeout> | null>(null)

  /** 当前是否正在轮询 */
  const isPolling = ref(false)

  /** 最近一次从服务端获取的状态 */
  const backendStatus = ref<MangaGenerationStatus | null>(null)

  /** 清除所有定时器 */
  function clearTimers() {
    if (timerRef.value !== null) {
      clearInterval(timerRef.value)
      timerRef.value = null
    }
    if (safetyTimerRef.value !== null) {
      clearTimeout(safetyTimerRef.value)
      safetyTimerRef.value = null
    }
  }

  /** 同步服务端最新图片到本地 */
  async function syncImagesFromServer() {
    if (!chapterId.value) return
    try {
      await mangaStore.loadImages(chapterId.value)
    } catch {
      // 图片同步失败不阻塞流程
    }
  }

  /** 单次轮询：查询后端状态并更新 UI */
  async function tick() {
    if (!chapterId.value) return

    try {
      const status = await mangaApi.getMangaGenerationStatus(chapterId.value)
      backendStatus.value = status

      // 更新 store 中的后端任务状态
      mangaStore.setBackendTaskStatus(status)

      if (status.status === 'succeeded') {
        // 后台任务完成：停止轮询、同步图片、清除状态
        clearTimers()
        isPolling.value = false
        await syncImagesFromServer()
        // 延迟清除以便 UI 短暂显示"生成完成"
        setTimeout(() => mangaStore.clearBackendTaskStatus(), 800)
        return
      }

      if (status.status === 'failed') {
        // 后台任务失败
        clearTimers()
        isPolling.value = false
        uiStore.error(status.error_message || '后台漫画生成失败')
        return
      }

      if (ACTIVE_STATUSES.has(status.status)) {
        // 后台任务仍在进行，更新进度显示
        const message = status.message || (
          status.status === 'retrying'
            ? `上游较慢，正在自动重试 ${status.retry_count ?? 0}/${status.max_retries ?? 0}`
            : `后台正在生成漫画 (${status.progress}/${status.total})`
        )
        mangaStore.progress = {
          current: status.progress,
          total: status.total,
          statusMsg: message,
        }
        // 确保 phase 更新为生成中
        if (mangaStore.phase === 'idle') {
          mangaStore.phase = 'generating-images'
        }
      }
    } catch {
      // 轮询失败不停止，等服务端恢复
      console.error('漫画后台任务轮询失败')
    }
  }

  /** 启动轮询 */
  function startPolling() {
    stopPolling()
    if (!chapterId.value) return

    isPolling.value = true
    timerRef.value = setInterval(() => tick(), POLL_INTERVAL)

    // 安全超时：10 分钟后强制停止
    safetyTimerRef.value = setTimeout(() => {
      clearTimers()
      isPolling.value = false
      mangaStore.clearBackendTaskStatus()
      console.log('漫画后台任务轮询已超时停止（10 分钟）')
    }, SAFETY_TIMEOUT)

    // 立即执行首次查询
    tick()
  }

  /** 停止轮询 */
  function stopPolling() {
    clearTimers()
    isPolling.value = false
  }

  /**
   * 页面挂载时检查后端是否有正在运行的任务
   * 如果有则自动恢复轮询和进度显示（实现断点续传）
   */
  async function checkAndResume() {
    if (!chapterId.value) return

    try {
      const status = await mangaApi.getMangaGenerationStatus(chapterId.value)
      backendStatus.value = status

      if (ACTIVE_STATUSES.has(status.status)) {
        // 后端有运行中的任务，恢复进度显示并启动轮询
        const message = status.message || (
          status.status === 'retrying'
            ? `上游较慢，正在自动重试 ${status.retry_count ?? 0}/${status.max_retries ?? 0}`
            : `后台正在生成漫画 (${status.progress}/${status.total})`
        )
        mangaStore.progress = {
          current: status.progress,
          total: status.total,
          statusMsg: message,
        }
        mangaStore.phase = 'generating-images'
        mangaStore.setBackendTaskStatus(status)
        startPolling()
      } else if (status.status === 'succeeded') {
        // 后台任务已经完成，同步最新图片
        await syncImagesFromServer()
        mangaStore.clearBackendTaskStatus()
      } else if (status.status === 'failed') {
        // 后台任务失败
        uiStore.error(status.error_message || '后台漫画生成任务失败')
        mangaStore.setBackendTaskStatus(status)
        setTimeout(() => mangaStore.clearBackendTaskStatus(), 3000)
      }
    } catch {
      // 检查失败不阻塞页面加载
      console.error('检查后端漫画状态失败')
    }
  }

  // 组件卸载时自动清理
  onUnmounted(stopPolling)

  return {
    isPolling,
    backendStatus,
    startPolling,
    stopPolling,
    checkAndResume,
    syncImagesFromServer,
  }
}
