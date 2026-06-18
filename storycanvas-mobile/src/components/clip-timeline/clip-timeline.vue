<template>
  <!-- 视频片段时间轴（T22） -->
  <view class="clip-timeline">
    <!-- 头部 -->
    <view class="clip-timeline__header">
      <text class="clip-timeline__title">渲染片段（{{ clips.length }}）</text>
      <view
        :class="['clip-timeline__refresh', { 'clip-timeline__refresh--spin': loading }]"
        @tap="loadClips"
      >
        <text>⟳ 刷新</text>
      </view>
    </view>

    <!-- 加载中 -->
    <view v-if="loading" class="clip-timeline__loading">
      <text>加载片段中…</text>
    </view>

    <!-- 空状态 -->
    <view v-else-if="clips.length === 0" class="clip-timeline__empty">
      <text class="clip-timeline__empty-icon">🎞</text>
      <text class="clip-timeline__empty-text">暂无渲染片段</text>
      <text class="clip-timeline__empty-desc">渲染视频后将在这里显示片段</text>
    </view>

    <!-- 片段列表 -->
    <view v-else class="clip-timeline__list">
      <view
        v-for="clip in clips"
        :key="clip.id"
        :class="['clip-timeline__item', { 'clip-timeline__item--active': clip.is_active }]"
      >
        <!-- 缩略图 -->
        <view class="clip-timeline__thumb-wrap">
          <image
            v-if="clip.thumbnail_path"
            :src="thumbUrl(clip.thumbnail_path)"
            class="clip-timeline__thumb"
            mode="aspectFill"
          />
          <view v-else class="clip-timeline__thumb-placeholder">
            <text>🎬</text>
          </view>
          <!-- 激活标记 -->
          <view v-if="clip.is_active" class="clip-timeline__active-badge">
            <text>活跃</text>
          </view>
        </view>

        <!-- 信息 -->
        <view class="clip-timeline__info">
          <view class="clip-timeline__info-row">
            <text class="clip-timeline__info-label">片段 #{{ clip.version || clip.id }}</text>
            <view :class="['clip-timeline__status-dot', { 'clip-timeline__status-dot--active': clip.is_active }]" />
          </view>
          <text v-if="clip.duration_seconds" class="clip-timeline__info-duration">
            时长 {{ formatDuration(clip.duration_seconds) }}
          </text>
          <text v-if="clip.resolution" class="clip-timeline__info-meta">
            分辨率 {{ clip.resolution }}
          </text>
          <text v-if="clip.quality_score" class="clip-timeline__info-meta">
            质量评分 {{ clip.quality_score }}
          </text>
        </view>

        <!-- 操作 -->
        <view class="clip-timeline__actions">
          <view
            v-if="!clip.is_active"
            :class="['clip-timeline__activate-btn', { 'clip-timeline__activate-btn--busy': busyClipId === clip.id }]"
            @tap="handleActivate(clip.id)"
          >
            <text>{{ busyClipId === clip.id ? '激活中…' : '激活' }}</text>
          </view>
          <view v-else class="clip-timeline__active-label">
            <text>使用中</text>
          </view>
        </view>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, watch, onMounted } from 'vue'
import { videoApi } from '@/api'
import type { RenderedClip } from '@/api/types'

// ── Props ──
interface ClipTimelineProps {
  /** 镜头 ID */
  shotId: number
}

const props = defineProps<ClipTimelineProps>()

// ── Emits ──
const emit = defineEmits<{
  (e: 'updated'): void
}>()

// ── 状态 ──
/** 片段列表 */
const clips = ref<RenderedClip[]>([])
/** 加载中 */
const loading = ref(false)
/** 激活操作中的片段 ID */
const busyClipId = ref<number | null>(null)

// ── 加载 ──

/** 加载片段列表（T22） */
async function loadClips() {
  if (!props.shotId) return
  loading.value = true
  try {
    const result = await videoApi.listShotClips(props.shotId)
    clips.value = result.clips || []
  } catch (e: any) {
    uni.showToast({ title: e?.message || '加载片段列表失败', icon: 'none' })
    clips.value = []
  } finally {
    loading.value = false
  }
}

/** 激活片段（T22） */
async function handleActivate(clipId: number) {
  if (busyClipId.value || !props.shotId) return
  busyClipId.value = clipId
  try {
    await videoApi.activateShotClip(props.shotId, clipId)
    // 更新本地激活状态
    clips.value = clips.value.map((c) => ({
      ...c,
      is_active: c.id === clipId,
    }))
    uni.showToast({ title: '已激活片段', icon: 'success' })
    emit('updated')
  } catch (e: any) {
    uni.showToast({ title: e?.message || '激活片段失败', icon: 'none' })
  } finally {
    busyClipId.value = null
  }
}

// ── 工具 ──

/** 缩略图 URL */
function thumbUrl(path?: string | null): string {
  if (!path) return ''
  if (path.startsWith('http://') || path.startsWith('https://') || path.startsWith('/static/')) return path
  return `/static/video/${path.replace(/^video_outputs[/\\]/, '')}`
}

/** 格式化时长 */
function formatDuration(seconds: number): string {
  if (!seconds || seconds <= 0) return '-'
  const mins = Math.floor(seconds / 60)
  const secs = Math.floor(seconds % 60)
  if (mins > 0) return `${mins}分${secs}秒`
  return `${secs}秒`
}

// ── 生命周期 ──

onMounted(() => {
  loadClips()
})

watch(
  () => props.shotId,
  (newId) => {
    if (newId) loadClips()
  }
)
</script>

<style lang="scss" scoped>
@use '@/styles/variables' as *;

.clip-timeline {
  display: flex;
  flex-direction: column;
  gap: 12rpx;
}

.clip-timeline__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.clip-timeline__title {
  font-size: $lv-font-base;
  font-weight: 600;
  color: $lv-text-primary;
}

.clip-timeline__refresh {
  display: flex;
  align-items: center;
  gap: 4rpx;
  padding: 6rpx 16rpx;
  border-radius: $lv-radius-full;
  background: $lv-primary-lighter;
  font-size: $lv-font-xs;
  color: $lv-primary;
  transition: all 0.2s;

  &:active {
    background: $lv-primary;
    color: $lv-text-on-primary;
  }

  &--spin {
    opacity: 0.6;
    pointer-events: none;
    animation: clip-spin 0.8s linear infinite;
  }
}

@keyframes clip-spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.clip-timeline__loading {
  display: flex;
  justify-content: center;
  padding: 24rpx 0;
  font-size: $lv-font-sm;
  color: $lv-text-muted;
}

.clip-timeline__empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40rpx 20rpx;
  gap: 12rpx;
  background: $lv-surface-solid;
  border-radius: $lv-radius-sm;
  border: 2rpx dashed $lv-border-light;
}

.clip-timeline__empty-icon {
  font-size: 56rpx;
  opacity: 0.4;
}

.clip-timeline__empty-text {
  font-size: $lv-font-base;
  font-weight: 500;
  color: $lv-text-secondary;
}

.clip-timeline__empty-desc {
  font-size: $lv-font-xs;
  color: $lv-text-muted;
}

.clip-timeline__list {
  display: flex;
  flex-direction: column;
  gap: 12rpx;
}

.clip-timeline__item {
  display: flex;
  align-items: center;
  gap: 16rpx;
  padding: 16rpx;
  background: $lv-surface-solid;
  border-radius: $lv-radius-sm;
  border: 2rpx solid $lv-border-light;
  transition: all 0.2s;

  &--active {
    border-color: $lv-primary;
    background: $lv-primary-lighter;
    box-shadow: 0 0 0 2rpx $lv-primary-light;
  }
}

.clip-timeline__thumb-wrap {
  position: relative;
  width: 120rpx;
  height: 80rpx;
  border-radius: $lv-radius-xs;
  background: $lv-bg-end;
  flex-shrink: 0;
  overflow: hidden;
}

.clip-timeline__thumb {
  width: 100%;
  height: 100%;
}

.clip-timeline__thumb-placeholder {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 40rpx;
  opacity: 0.5;
}

.clip-timeline__active-badge {
  position: absolute;
  top: 4rpx;
  right: 4rpx;
  padding: 2rpx 8rpx;
  border-radius: $lv-radius-full;
  background: $lv-success;
  font-size: 18rpx;
  color: #fff;
  font-weight: 600;
}

.clip-timeline__info {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4rpx;
  min-width: 0;
}

.clip-timeline__info-row {
  display: flex;
  align-items: center;
  gap: 8rpx;
}

.clip-timeline__info-label {
  font-size: $lv-font-sm;
  font-weight: 500;
  color: $lv-text-primary;
}

.clip-timeline__status-dot {
  width: 12rpx;
  height: 12rpx;
  border-radius: $lv-radius-full;
  background: $lv-text-muted;

  &--active {
    background: $lv-success;
  }
}

.clip-timeline__info-duration {
  font-size: $lv-font-xs;
  color: $lv-text-secondary;
}

.clip-timeline__info-meta {
  font-size: $lv-font-xs;
  color: $lv-text-muted;
}

.clip-timeline__actions {
  flex-shrink: 0;
  display: flex;
  align-items: center;
}

.clip-timeline__activate-btn {
  padding: 10rpx 20rpx;
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

.clip-timeline__active-label {
  padding: 6rpx 16rpx;
  border-radius: $lv-radius-full;
  background: $lv-success-bg;
  font-size: $lv-font-xs;
  color: $lv-success;
  font-weight: 500;
}
</style>
