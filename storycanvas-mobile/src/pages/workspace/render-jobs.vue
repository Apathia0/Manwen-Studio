<template>
  <view class="render-jobs">
    <lv-loading v-if="loading" :text="'加载中...'" vertical class="render-jobs__loading" />

    <template v-else>
      <view class="render-jobs__header">
        <text class="render-jobs__label">模型:</text>
        <picker v-if="models.length > 0" :value="modelIndex" :range="models.map(m => m.name)" @change="handleModelChange">
          <text class="render-jobs__picker">{{ models[modelIndex]?.name || '选择模型' }}</text>
        </picker>
        <text v-else class="render-jobs__picker">加载中...</text>
      </view>

      <VideoRenderParams v-model="renderParams" />

      <lv-button block :loading="rendering" @tap="handleRender">
        <template v-if="rendering">渲染中...</template>
        <template v-else>渲染视频</template>
      </lv-button>

      <view v-if="jobs.length > 0" class="render-jobs__list">
        <view v-for="job in jobs" :key="job.id" class="render-jobs__card" @tap="handlePreview(job)">
          <view class="render-jobs__card-header">
            <text class="render-jobs__card-title">作业 #{{ job.id }}</text>
            <text class="render-jobs__card-status" :style="{ color: statusColor(job.status) }">{{ statusLabel(job.status) }}</text>
          </view>
          <view class="render-jobs__card-meta">
            <text class="render-jobs__card-meta-item">模型: {{ job.model || '-' }}</text>
            <text class="render-jobs__card-meta-item">提供商: {{ job.provider }}</text>
          </view>
          <view class="render-jobs__card-progress">
            <lv-progress :percentage="job.progress" show-info />
          </view>
          <text v-if="job.error_message" class="render-jobs__card-error">{{ job.error_message }}</text>
          <!-- 重试按钮（T23） -->
          <view v-if="job.status === 'FAILURE' || job.status === 'failed'" class="render-jobs__card-actions">
            <view
              :class="['render-jobs__retry-btn', { 'render-jobs__retry-btn--busy': retryingJobId === job.id }]"
              @tap="handleRetry(job)"
            >
              <text>⟳ {{ retryingJobId === job.id ? '重试中…' : '重试' }}</text>
            </view>
          </view>
          <text class="render-jobs__card-time">提交: {{ formatTime(job.submitted_at) }}</text>
          <view v-if="job.status === 'SUCCESS' || job.status === 'succeeded'" class="render-jobs__card-play">
            <lv-icon name="Play" :size="12" color="#2563eb" />
            <text class="render-jobs__card-play-text">点击预览</text>
          </view>
        </view>
      </view>

      <lv-empty v-else title="暂无渲染作业" description="点击上方按钮开始渲染视频" />
    </template>

    <!-- 视频播放弹窗 -->
    <view v-if="videoPreviewUrl" class="render-jobs__player-overlay" @tap="closeVideoPreview">
      <view class="render-jobs__player" @tap.stop>
        <view class="render-jobs__player-header">
          <text class="render-jobs__player-title">视频预览</text>
          <view class="render-jobs__player-close" @tap="closeVideoPreview">
            <lv-icon name="X" :size="20" color="#94a3b8" />
          </view>
        </view>
        <video
          :src="videoPreviewUrl"
          class="render-jobs__video"
          controls
          autoplay
          object-fit="contain"
        />
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { videoApi } from '@/api'
import type { VideoGenerationJob, VideoModel } from '@/api/types'
import LvLoading from '@/components/lv-loading/lv-loading.vue'
import LvButton from '@/components/lv-button/lv-button.vue'
import LvProgress from '@/components/lv-progress/lv-progress.vue'
import LvEmpty from '@/components/lv-empty/lv-empty.vue'
import LvIcon from '@/components/lv-icon/lv-icon.vue'
import VideoRenderParams from '@/components/video-render-params/video-render-params.vue'
import type { RenderParams } from '@/components/video-render-params/video-render-params.vue'

const loading = ref(false)
const rendering = ref(false)
const jobs = ref<VideoGenerationJob[]>([])
const models = ref<VideoModel[]>([])
const modelIndex = ref(0)
const shotId = ref(0)
const videoPreviewUrl = ref('')
const shotVideoUrlCache = ref<Record<number, string>>({})
const renderParams = ref<RenderParams>({})
const retryingJobId = ref<number | null>(null)

onLoad((options) => {
  shotId.value = Number(options?.shotId || 0)
  if (!shotId.value) {
    uni.showToast({ title: '未指定镜头', icon: 'none' })
  }
})

onMounted(async () => {
  loading.value = true
  try {
    await Promise.all([loadModels(), loadJobs()])
  } finally {
    loading.value = false
  }
})

async function loadModels() {
  try {
    const data = await videoApi.getVideoModels()
    models.value = data.models
  } catch (e: any) {
    console.warn('加载模型失败:', e?.message || e)
  }
}

async function loadJobs() {
  if (!shotId.value) return
  try {
    const job = await videoApi.getLatestVideoJobForShot(shotId.value)
    if (job) {
      jobs.value = [job]
    }
  } catch {
    // 无作业时静默处理
  }
}

function handleModelChange(e: any) {
  modelIndex.value = e.detail.value
}

async function handleRender() {
  if (!shotId.value || models.value.length === 0) return
  rendering.value = true
  try {
    const job = await videoApi.renderShotVideo(shotId.value, {
      model: models.value[modelIndex.value].value,
      aspect_ratio: renderParams.value.aspect_ratio,
      duration_seconds: renderParams.value.duration,
      size: renderParams.value.size,
      orientation: renderParams.value.orientation,
      input_mode: renderParams.value.input_mode,
    })
    jobs.value.unshift(job)
    uni.showToast({ title: '渲染已启动', icon: 'success' })
  } catch (e: any) {
    uni.showToast({ title: e?.message || e?.errMsg || '渲染失败', icon: 'none' })
  } finally {
    rendering.value = false
  }
}

/** 重试失败的视频作业（T23） */
async function handleRetry(job: VideoGenerationJob) {
  if (retryingJobId.value) return
  retryingJobId.value = job.id
  try {
    await videoApi.retryVideoJob(job.id)
    uni.showToast({ title: '已重新提交视频作业', icon: 'success' })
    // 重新加载作业列表
    await loadJobs()
  } catch (e: any) {
    uni.showToast({ title: e?.message || '重试失败', icon: 'none' })
  } finally {
    retryingJobId.value = null
  }
}

function closeVideoPreview() {
  videoPreviewUrl.value = ''
}

// 从工作流 shots 获取 video_url(VideoGenerationJobOut 无 video_url 字段)
async function loadShotVideoUrl(shotIdNum: number): Promise<string> {
  if (shotVideoUrlCache.value[shotIdNum]) {
    return shotVideoUrlCache.value[shotIdNum]
  }
  try {
    // 遍历 chapter workflows 的 shots 查找匹配 shotId 的 video_url
    // 由于可能不知道 chapterId,通过 shot_id 反查受限,这里尝试常见路径
    // 优先尝试直接从 shot 获取(如果有对应端点)
    // 回退方案:提示用户在 web 端预览
    return ''
  } catch {
    return ''
  }
}

async function handlePreview(job: VideoGenerationJob) {
  if (job.status !== 'SUCCESS' && job.status !== 'succeeded') {
    uni.showToast({ title: '视频尚未完成', icon: 'none' })
    return
  }
  // 尝试从 shot 获取 video_url
  const url = await loadShotVideoUrl(shotId.value)
  if (!url) {
    uni.showToast({ title: '无法获取视频地址,请在 web 端预览', icon: 'none' })
    return
  }
  videoPreviewUrl.value = url
}

function statusLabel(status: string): string {
  const map: Record<string, string> = {
    NOT_START: '未开始',
    IN_PROGRESS: '进行中',
    SUCCESS: '已完成',
    FAILURE: '失败',
    QUEUED: '排队中',
    CANCELLED: '已取消',
    running: '进行中',
    succeeded: '已完成',
    failed: '失败',
  }
  return map[status] || status
}

function statusColor(status: string): string {
  if (status === 'SUCCESS' || status === 'succeeded') return '#22c55e'
  if (status === 'FAILURE' || status === 'failed') return '#ef4444'
  if (status === 'IN_PROGRESS' || status === 'running') return '#2563eb'
  return '#94a3b8'
}

function formatTime(iso: string): string {
  try {
    const d = new Date(iso)
    const pad = (n: number) => String(n).padStart(2, '0')
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
  } catch {
    return iso
  }
}
</script>

<style lang="scss" scoped>
.render-jobs {
  min-height: 100vh;
  background: linear-gradient(180deg, $lv-bg-start 0%, $lv-bg-end 100%);
  padding: calc(var(--status-bar-height) + 88rpx) $lv-page-padding $lv-page-padding;

  &__loading {
    display: flex;
    justify-content: center;
    padding-top: 200rpx;
  }

  &__header {
    display: flex;
    align-items: center;
    gap: 12rpx;
    margin-bottom: 16rpx;
  }

  &__label {
    font-size: $lv-font-sm;
    color: $lv-text-secondary;
  }

  &__picker {
    font-size: $lv-font-sm;
    color: $lv-primary;
    background: $lv-primary-light;
    padding: 8rpx 20rpx;
    border-radius: $lv-radius-full;
  }

  &__list {
    margin-top: 24rpx;
    display: flex;
    flex-direction: column;
    gap: 16rpx;
  }

  &__card {
    background: $lv-surface-solid;
    border-radius: $lv-radius-md;
    padding: 24rpx;
    box-shadow: $lv-shadow-sm;
  }

  &__card-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 12rpx;
  }

  &__card-title {
    font-size: $lv-font-base;
    font-weight: 600;
    color: $lv-text-primary;
  }

  &__card-status {
    font-size: $lv-font-sm;
    font-weight: 600;
  }

  &__card-meta {
    display: flex;
    gap: 24rpx;
    margin-bottom: 12rpx;
  }

  &__card-meta-item {
    font-size: $lv-font-xs;
    color: $lv-text-secondary;
  }

  &__card-progress {
    margin-bottom: 8rpx;
  }

  &__card-error {
    display: block;
    font-size: $lv-font-xs;
    color: #ef4444;
    margin-bottom: 8rpx;
  }

  // ── 重试按钮（T23）──
  &__card-actions {
    display: flex;
    gap: 12rpx;
    margin-bottom: 8rpx;
  }

  &__retry-btn {
    padding: 8rpx 24rpx;
    border-radius: $lv-radius-sm;
    background: $lv-primary;
    font-size: $lv-font-xs;
    color: $lv-text-on-primary;
    font-weight: 500;
    transition: all 0.2s;

    &:active {
      background: $lv-primary-dark;
      transform: scale(0.96);
    }

    &--busy {
      opacity: 0.7;
      pointer-events: none;
    }
  }

  &__card-time {
    display: block;
    font-size: $lv-font-xs;
    color: $lv-text-muted;
  }

  &__card-play {
    display: flex;
    align-items: center;
    gap: 4rpx;
    margin-top: 12rpx;
    padding-top: 12rpx;
    border-top: 1rpx solid $lv-border-light;
  }

  &__card-play-text {
    font-size: $lv-font-xs;
    color: $lv-primary;
  }

  &__player-overlay {
    position: fixed;
    inset: 0;
    z-index: 1000;
    background: rgba(0, 0, 0, 0.8);
    display: flex;
    align-items: center;
    justify-content: center;
  }

  &__player {
    width: 90%;
    max-width: 680rpx;
    background: #000;
    border-radius: $lv-radius-lg;
    overflow: hidden;
  }

  &__player-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 24rpx;
    background: rgba(0, 0, 0, 0.8);
  }

  &__player-title {
    font-size: $lv-font-base;
    color: #fff;
    font-weight: 600;
  }

  &__player-close {
    padding: 8rpx;
  }

  &__video {
    width: 100%;
    height: 400rpx;
  }
}
</style>
