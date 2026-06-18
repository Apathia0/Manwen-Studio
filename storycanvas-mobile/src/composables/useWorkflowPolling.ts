import { ref, watch, onUnmounted, type Ref } from 'vue'
import { videoApi } from '@/api'
import { useVideoWorkflowStore } from '@/stores/videoWorkflow'
import { useVideoGenStore } from '@/stores/videoGen'

const ACTIVE_STATUSES = new Set([
  'parsing_shots',
  'generating_storyboards',
  'generating_videos',
  'reanalyzing_prompts',
  'generating_details',
])

/**
 * 工作流状态轮询 composable
 * 对标 web 端 pollWorkflowUntilSettled
 */
export function useWorkflowPolling(workflowId: Ref<number | null>) {
  const videoWorkflowStore = useVideoWorkflowStore()
  const videoGenStore = useVideoGenStore()
  const timerRef = ref<ReturnType<typeof setTimeout> | null>(null)
  const isPolling = ref(false)

  async function tick() {
    if (!workflowId.value) return
    isPolling.value = true
    try {
      const status = await videoApi.getChapterVideoWorkflowStatus(workflowId.value)
      const detail = await videoApi.getChapterVideoWorkflow(workflowId.value)
      videoWorkflowStore.currentWorkflow = detail
      videoWorkflowStore.currentShots = detail.shots || []
      videoWorkflowStore.workflowRunning = ACTIVE_STATUSES.has(status.workflow_status)

      if (ACTIVE_STATUSES.has(status.workflow_status)) {
        timerRef.value = setTimeout(() => tick(), 4000)
        return
      }

      detail.shots.forEach(shot => {
        if (shot.status === 'storyboard_ready') {
          videoGenStore.markSucceeded(shot.id, 'storyboard')
        }
        if (shot.status === 'video_ready') {
          videoGenStore.markSucceeded(shot.id)
        }
        if (shot.status === 'failed') {
          const sbState = videoGenStore.get(shot.id, 'storyboard')
          if (sbState?.active) {
            videoGenStore.markFailed(shot.id, shot.error_message || '故事版生成失败', 'storyboard')
          }
          videoGenStore.markFailed(shot.id, shot.error_message || '视频生成失败')
        }
      })

      if (detail.chapter_id) {
        videoWorkflowStore.loadChapterAssets(detail.chapter_id)
      }
    } catch (error: any) {
      console.error('工作流轮询失败:', error)
      videoWorkflowStore.workflowRunning = false
    } finally {
      isPolling.value = false
    }
  }

  function start() {
    stop()
    if (workflowId.value) tick()
  }

  function stop() {
    if (timerRef.value) {
      clearTimeout(timerRef.value)
      timerRef.value = null
    }
    isPolling.value = false
  }

  watch(workflowId, (newId) => {
    if (newId) start()
    else stop()
  })

  onUnmounted(stop)

  return { isPolling, start, stop }
}
