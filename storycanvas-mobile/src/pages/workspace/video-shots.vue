<template>
  <view class="vs">
    <lv-navbar :title="'镜头列表'" show-back />

    <!-- 顶部操作工具栏 -->
    <view class="vs__toolbar">
      <view class="vs__toolbar-row">
        <text class="vs__toolbar-status" v-if="store.workflowRunning">
          <lv-loading :size="14" /> 任务执行中...
        </text>
        <text class="vs__toolbar-status vs__toolbar-status--idle" v-else-if="workflowStatusText">
          {{ workflowStatusText }}
        </text>
        <text class="vs__toolbar-hint" v-if="retryHint">{{ retryHint }}</text>
      </view>
      <scroll-view scroll-x class="vs__toolbar-actions" show-scrollbar="false">
        <view class="vs__toolbar-actions-inner">
          <view class="vs__toolbar-btn" :class="{ 'vs__toolbar-btn--disabled': !canParse }" @tap="handleParseShots">
            <text class="vs__toolbar-btn-icon">⇄</text>
            <text class="vs__toolbar-btn-label">{{ parsing ? '拆镜中...' : '拆镜' }}</text>
          </view>
          <view class="vs__toolbar-btn" :class="{ 'vs__toolbar-btn--disabled': !canGenerateDetails }" @tap="handleGenerateDetails">
            <text class="vs__toolbar-btn-icon">✦</text>
            <text class="vs__toolbar-btn-label">生成详情</text>
          </view>
          <view class="vs__toolbar-btn" :class="{ 'vs__toolbar-btn--disabled': !canStoryboard }" @tap="handleBatchStoryboard">
            <text class="vs__toolbar-btn-icon">🖼</text>
            <text class="vs__toolbar-btn-label">故事版</text>
          </view>
          <view class="vs__toolbar-btn" :class="{ 'vs__toolbar-btn--disabled': !canVideo }" @tap="handleBatchVideo">
            <text class="vs__toolbar-btn-icon">▶</text>
            <text class="vs__toolbar-btn-label">视频</text>
          </view>
          <view class="vs__toolbar-btn" :class="{ 'vs__toolbar-btn--disabled': !canConcat }" @tap="showConcatModal = true">
            <text class="vs__toolbar-btn-icon">⏹</text>
            <text class="vs__toolbar-btn-label">拼接</text>
          </view>
          <view class="vs__toolbar-btn" :class="{ 'vs__toolbar-btn--disabled': store.workflowRunning }" @tap="handleRefresh">
            <text class="vs__toolbar-btn-icon">↻</text>
            <text class="vs__toolbar-btn-label">刷新</text>
          </view>
          <view class="vs__toolbar-btn vs__toolbar-btn--danger" @tap="handleReset">
            <text class="vs__toolbar-btn-icon">✕</text>
            <text class="vs__toolbar-btn-label">重置</text>
          </view>
        </view>
      </scroll-view>
    </view>

    <view class="vs__content">
      <!-- 加载中 -->
      <view v-if="loading" class="vs__loading"><lv-loading /></view>

      <!-- 空状态 -->
      <view v-else-if="!workflow" class="vs__empty">
        <lv-empty title="暂无工作流" description="请返回工作流页面创建" />
      </view>

      <!-- 拆镜中遮罩 -->
      <view v-if="parsing && workflow" class="vs__overlay">
        <view class="vs__overlay-body">
          <lv-loading :size="32" />
          <text class="vs__overlay-text">{{ workflow.message || '正在拆镜...' }}</text>
        </view>
      </view>

      <template v-else-if="workflow">
        <!-- 选择操作栏 -->
        <view v-if="sortedShots.length > 0" class="vs__selection-bar">
          <view class="vs__selection-bar-left">
            <view class="vs__checkbox-inline" @tap="handleSelectAll">
              <view :class="['vs__checkbox', { 'vs__checkbox--checked': allSelected }]" />
              <text class="vs__selection-text">{{ allSelected ? '取消全选' : '全选' }}</text>
            </view>
            <text class="vs__selection-count">已选 {{ store.selectedShotIds.length }}/{{ sortedShots.length }}</text>
            <text v-if="store.skippedShotIds.length > 0" class="vs__selection-skip">跳过 {{ store.skippedShotIds.length }}</text>
          </view>
          <view class="vs__selection-bar-right" v-if="activeShotIds.length > 0">
            <view v-if="canStoryboard" class="vs__batch-btn" @tap="handleBatchStoryboard">故事版</view>
            <view v-if="canVideo" class="vs__batch-btn vs__batch-btn--video" @tap="handleBatchVideo">视频</view>
          </view>
        </view>

        <!-- 镜头列表 -->
        <view class="vs__shot-list">
          <view
            v-for="shot in sortedShots"
            :key="shot.id"
            :class="['vs__shot-card', { 'vs__shot-card--selected': store.selectedShotIds.includes(shot.id) }]"
          >
            <!-- 镜头头部 -->
            <view class="vs__shot-header">
              <view class="vs__shot-header-left">
                <view class="vs__checkbox-inline" @tap="store.toggleShotSelection(shot.id)">
                  <view :class="['vs__checkbox', { 'vs__checkbox--checked': store.selectedShotIds.includes(shot.id) }]" />
                </view>
                <text class="vs__shot-index">镜头 {{ shot.shot_index }}</text>
                <view :class="['vs__shot-status', `vs__shot-status--${shotStatusType(shot)}`]">
                  <text>{{ shotStatusLabel(shot) }}</text>
                </view>
              </view>
              <view class="vs__shot-reorder" v-if="sceneId">
                <view
                  class="vs__reorder-btn"
                  :class="{ 'vs__reorder-btn--disabled': isFirstShot(shot) }"
                  @tap="handleMoveShot(shot, 'up')"
                >
                  <text>▲</text>
                </view>
                <view
                  class="vs__reorder-btn"
                  :class="{ 'vs__reorder-btn--disabled': isLastShot(shot) }"
                  @tap="handleMoveShot(shot, 'down')"
                >
                  <text>▼</text>
                </view>
              </view>
              <view class="vs__shot-header-right">
                <view class="vs__shot-skip" :class="{ 'vs__shot-skip--active': store.skippedShotIds.includes(shot.id) }" @tap="store.toggleShotSkip(shot.id)">
                  <text>{{ store.skippedShotIds.includes(shot.id) ? '已跳过' : '跳过' }}</text>
                </view>
              </view>
            </view>

            <!-- 镜头摘要 -->
            <view class="vs__shot-summary">
              <text class="vs__shot-summary-text">{{ shot.story_summary || '暂无情节摘要' }}</text>
            </view>

            <!-- 镜头元信息 -->
            <view class="vs__shot-meta" v-if="shot.scene_location || shot.time_of_day || shot.camera_plan">
              <text v-if="shot.scene_location" class="vs__shot-meta-item">场景：{{ shot.scene_location }}</text>
              <text v-if="shot.time_of_day" class="vs__shot-meta-item">时间：{{ shot.time_of_day }}</text>
              <text v-if="shot.camera_plan" class="vs__shot-meta-item">运镜：{{ shot.camera_plan }}</text>
            </view>

            <!-- 角色标签 -->
            <view class="vs__shot-characters" v-if="shot.characters && shot.characters.length > 0">
              <view class="vs__shot-character-tag" v-for="ch in shot.characters" :key="ch">
                <text>{{ ch }}</text>
              </view>
            </view>

            <!-- 连续性笔记 -->
            <view class="vs__shot-continuity" v-if="shot.continuity_notes">
              <text>连续性：{{ shot.continuity_notes }}</text>
            </view>

            <!-- 错误信息 -->
            <view class="vs__shot-error" v-if="shot.error_message">
              <text>{{ shot.error_message }}</text>
            </view>

            <!-- 故事版/视频预览 -->
            <view class="vs__shot-previews" v-if="shot.storyboard_image_url || shot.video_url">
              <view class="vs__shot-preview" v-if="shot.storyboard_image_url">
                <text class="vs__shot-preview-label">故事版</text>
                <image :src="assetUrl(shot.storyboard_image_url)" class="vs__shot-preview-image" mode="aspectFill" />
              </view>
              <view class="vs__shot-preview" v-if="shot.video_url">
                <text class="vs__shot-preview-label">视频</text>
                <video :src="assetUrl(shot.video_url)" class="vs__shot-preview-video" controls />
              </view>
            </view>

            <!-- 操作按钮 -->
            <view class="vs__shot-actions">
              <view class="vs__shot-action-btn" :class="{ 'vs__shot-action-btn--disabled': !canGenerateDetails }" @tap="handleGenerateDetailsForShot(shot.id)">
                <text>生成详情</text>
              </view>
              <view class="vs__shot-action-btn" :class="{ 'vs__shot-action-btn--disabled': !canGenerateStoryboardForShot(shot) }" @tap="handleGenerateStoryboardForShot(shot.id)">
                <text>{{ shot.storyboard_image_url ? '重绘' : '生成故事版' }}</text>
              </view>
              <view class="vs__shot-action-btn" :class="{ 'vs__shot-action-btn--disabled': !canGenerateVideoForShot(shot) }" @tap="handleGenerateVideoForShot(shot.id)">
                <text>{{ shot.video_url ? '重绘' : '生成视频' }}</text>
              </view>
            </view>
          </view>
        </view>

        <!-- 新建镜头 -->
        <view v-if="sceneId" class="vs__create-shot">
          <lv-button block @tap="handleCreateShot" :loading="creating">
            + 新建镜头
          </lv-button>
        </view>

        <!-- 拼接结果 -->
        <view class="vs__concat-result" v-if="store.concatVideoUrl">
          <text class="vs__concat-result-title">拼接视频</text>
          <video :src="assetUrl(store.concatVideoUrl)" controls class="vs__concat-result-video" />
          <lv-button size="sm" @tap="store.concatVideoUrl = null">关闭</lv-button>
        </view>
      </template>
    </view>

    <!-- 拼接确认弹窗 -->
    <lv-modal v-model:show="showConcatModal" title="拼接视频" @confirm="handleConcat" :confirm-loading="concating">
      <view class="vs__modal-body">
        <text class="vs__modal-text">确认将所有已完成视频拼接为完整章节视频？</text>
        <text class="vs__modal-hint">已完成 {{ videoReadyCount }}/{{ sortedShots.length }} 个镜头</text>
      </view>
    </lv-modal>
  </view>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useVideoWorkflowStore } from '@/stores/videoWorkflow'
import { useVideoGenStore } from '@/stores/videoGen'
import { useWorkflowPolling } from '@/composables/useWorkflowPolling'
import { videoApi } from '@/api'
import { videoAssetUrl } from '@/utils/url'
import LvNavbar from '@/components/lv-navbar/lv-navbar.vue'
import LvLoading from '@/components/lv-loading/lv-loading.vue'
import LvEmpty from '@/components/lv-empty/lv-empty.vue'
import LvButton from '@/components/lv-button/lv-button.vue'
import LvModal from '@/components/lv-modal/lv-modal.vue'
import type { ChapterVideoShot } from '@/api/types'

const store = useVideoWorkflowStore()
const videoGenStore = useVideoGenStore()
const workflowId = ref<number | null>(null)
const { isPolling, start: startPolling, stop: stopPolling } = useWorkflowPolling(workflowId)
const loading = ref(false)
const parsing = ref(false)
const concating = ref(false)
const showConcatModal = ref(false)
const creating = ref(false)
const sceneId = ref<number | null>(null)

// 从路由参数读取 workflowId 和 sceneId
onMounted(async () => {
  const pages = getCurrentPages()
  const page = pages[pages.length - 1] as any
  const wid = Number(page.options?.workflowId || 0)
  const sid = Number(page.options?.sceneId || 0)
  if (sid) sceneId.value = sid
  if (wid) {
    workflowId.value = wid
    await loadWorkflow(wid)
    startPolling()
  }
})

onUnmounted(stopPolling)

async function loadWorkflow(wid: number) {
  loading.value = true
  try {
    await store.loadWorkflowDetail(wid)
  } finally {
    loading.value = false
  }
}

// 计算属性
const workflow = computed(() => store.currentWorkflow)

const sortedShots = computed(() =>
  [...(store.currentShots || [])].sort((a, b) => a.shot_index - b.shot_index)
)

const allSelected = computed(() =>
  sortedShots.value.length > 0 &&
  store.selectedShotIds.length === sortedShots.value.length
)

const activeShotIds = computed(() =>
  store.selectedShotIds.filter(id => !store.skippedShotIds.includes(id))
)

const status = computed(() => workflow.value?.workflow_status ?? 'idle')

const workflowStatusText = computed(() => {
  const labels: Record<string, string> = {
    idle: '空闲', initial: '初始', parsing_shots: '拆镜中',
    generating_details: '生成详情中', shots_ready: '镜头已就绪',
    generating_storyboards: '生成故事版中', storyboards_ready: '故事版已就绪',
    generating_videos: '生成视频中', videos_ready: '视频已就绪',
    completed: '已完成', failed: '处理失败',
  }
  return labels[status.value] || ''
})

const retryHint = computed(() => {
  if (!workflow.value) return ''
  const rc = workflow.value.retry_count ?? 0
  const mr = workflow.value.max_retries ?? 0
  return rc > 0 ? `自动重试 ${rc}/${mr}` : ''
})

const videoReadyCount = computed(() =>
  sortedShots.value.filter(s => s.status === 'video_ready').length
)

// 阶段可用性
const canParse = computed(() => {
  if (parsing.value || store.workflowRunning) return false
  if (!workflow.value) return false
  return sortedShots.value.length === 0
})

const canGenerateDetails = computed(() => {
  if (store.workflowRunning) return false
  return ['shots_ready', 'generating_details', 'failed'].includes(status.value)
})

const canStoryboard = computed(() => {
  if (store.workflowRunning) return false
  return ['shots_ready', 'generating_storyboards', 'failed'].includes(status.value) && activeShotIds.value.length > 0
})

const canVideo = computed(() => {
  if (store.workflowRunning) return false
  return ['storyboards_ready', 'generating_videos', 'failed'].includes(status.value) && activeShotIds.value.length > 0
})

const canConcat = computed(() => {
  if (store.workflowRunning) return false
  return ['completed', 'videos_ready', 'storyboards_ready', 'generating_videos', 'shots_ready'].includes(status.value)
})

// 镜头状态
function shotStatusType(shot: ChapterVideoShot): string {
  if (shot.status === 'failed') return 'failed'
  if (shot.status === 'video_ready') return 'video-ready'
  if (shot.status === 'storyboard_ready') return 'storyboard-ready'
  if (!shot.camera_plan) return 'pending-detail'
  return 'pending'
}

function shotStatusLabel(shot: ChapterVideoShot): string {
  const labels: Record<string, string> = {
    pending: '待处理',
    storyboard_generating: '故事版生成中',
    storyboard_ready: '故事版已完成',
    video_generating: '视频生成中',
    video_ready: '视频已完成',
    failed: '失败',
  }
  if (shot.status === 'pending' && !shot.camera_plan) return '待生成详情'
  return labels[shot.status] || shot.status
}

function canGenerateStoryboardForShot(shot: ChapterVideoShot): boolean {
  if (store.workflowRunning) return false
  return ['shots_ready', 'failed', 'storyboards_ready'].includes(status.value)
}

function canGenerateVideoForShot(shot: ChapterVideoShot): boolean {
  if (store.workflowRunning) return false
  return ['storyboards_ready', 'failed', 'videos_ready'].includes(status.value)
}

// URL helper
function assetUrl(path?: string | null): string {
  return videoAssetUrl(path ?? null) || ''
}

// 操作处理
function handleSelectAll() {
  if (allSelected.value) store.clearSelection()
  else store.selectAllShots()
}

async function handleParseShots() {
  if (!canParse.value || !workflowId.value) return
  parsing.value = true
  try {
    await store.parseShots(workflowId.value)
  } finally {
    parsing.value = false
  }
}

async function handleGenerateDetails() {
  if (!canGenerateDetails.value || !workflowId.value || activeShotIds.value.length === 0) return
  try {
    await store.generateShotDetails(workflowId.value, activeShotIds.value)
    startPolling()
  } catch (e: any) {
    uni.showToast({ title: e.message || '操作失败', icon: 'none' })
  }
}

async function handleGenerateDetailsForShot(shotId: number) {
  if (!canGenerateDetails.value || !workflowId.value) return
  try {
    await store.generateShotDetails(workflowId.value, [shotId])
    startPolling()
  } catch (e: any) {
    uni.showToast({ title: e.message || '操作失败', icon: 'none' })
  }
}

async function handleBatchStoryboard() {
  if (!canStoryboard.value || !workflowId.value) return
  try {
    await store.generateStoryboards(workflowId.value, activeShotIds.value)
    startPolling()
  } catch (e: any) {
    uni.showToast({ title: e.message || '操作失败', icon: 'none' })
  }
}

async function handleGenerateStoryboardForShot(shotId: number) {
  if (!canGenerateStoryboardForShot(sortedShots.value.find(s => s.id === shotId)!) || !workflowId.value) return
  try {
    await store.generateStoryboards(workflowId.value, [shotId])
    startPolling()
  } catch (e: any) {
    uni.showToast({ title: e.message || '操作失败', icon: 'none' })
  }
}

async function handleBatchVideo() {
  if (!canVideo.value || !workflowId.value) return
  try {
    await store.generateVideos(workflowId.value, activeShotIds.value)
    startPolling()
  } catch (e: any) {
    uni.showToast({ title: e.message || '操作失败', icon: 'none' })
  }
}

async function handleGenerateVideoForShot(shotId: number) {
  if (!canGenerateVideoForShot(sortedShots.value.find(s => s.id === shotId)!) || !workflowId.value) return
  try {
    await store.generateVideos(workflowId.value, [shotId])
    startPolling()
  } catch (e: any) {
    uni.showToast({ title: e.message || '操作失败', icon: 'none' })
  }
}

async function handleConcat() {
  if (!workflowId.value) return
  concating.value = true
  try {
    await store.concatVideo(workflowId.value)
    showConcatModal.value = false
    if (store.concatVideoUrl) {
      uni.showToast({ title: '拼接完成', icon: 'success' })
    }
  } catch (e: any) {
    uni.showToast({ title: e.message || '拼接失败', icon: 'none' })
  } finally {
    concating.value = false
  }
}

async function handleRefresh() {
  if (!workflowId.value) return
  try {
    await store.loadWorkflowDetail(workflowId.value)
    startPolling()
  } catch (e: any) {
    uni.showToast({ title: e.message || '刷新失败', icon: 'none' })
  }
}

async function handleReset() {
  if (!workflowId.value) return
  uni.showModal({
    title: '确认重置',
    content: '重置将清除所有镜头和生成数据，此操作不可撤销，是否继续？',
    success: async (res) => {
      if (res.confirm) {
        try {
          await store.resetWorkflow(workflowId.value!)
          uni.showToast({ title: '已重置', icon: 'success' })
        } catch (e: any) {
          uni.showToast({ title: e.message || '重置失败', icon: 'none' })
        }
      }
    },
  })
}

// ── T24a: 新建镜头 ──

async function handleCreateShot() {
  const sid = sceneId.value
  if (!sid) return
  uni.showModal({
    title: '新建镜头',
    content: '',
    placeholderText: '输入镜头标题',
    editable: true,
    success: async (res) => {
      if (!res.confirm || !res.content?.trim()) return
      creating.value = true
      try {
        await videoApi.createSceneShot(sid, { title: res.content.trim() })
        uni.showToast({ title: '镜头已创建', icon: 'success' })
        // 刷新场景镜头
        await store.fetchShots(sid)
      } catch (e: any) {
        uni.showToast({ title: e.message || '创建失败', icon: 'none' })
      } finally {
        creating.value = false
      }
    },
  })
}

// ── T24a: 镜头重排 ──

function isFirstShot(shot: ChapterVideoShot): boolean {
  return sortedShots.value.length > 0 && sortedShots.value[0].id === shot.id
}

function isLastShot(shot: ChapterVideoShot): boolean {
  return sortedShots.value.length > 0 && sortedShots.value[sortedShots.value.length - 1].id === shot.id
}

async function handleMoveShot(shot: ChapterVideoShot, direction: 'up' | 'down') {
  const sid = sceneId.value
  if (!sid) return
  const idx = sortedShots.value.findIndex(s => s.id === shot.id)
  if (idx < 0) return
  if (direction === 'up' && idx === 0) return
  if (direction === 'down' && idx === sortedShots.value.length - 1) return

  const swapIdx = direction === 'up' ? idx - 1 : idx + 1
  const ids = sortedShots.value.map(s => s.id)
  // swap the two positions
  ;[ids[idx], ids[swapIdx]] = [ids[swapIdx], ids[idx]]

  try {
    await videoApi.reorderSceneShots(sid, ids)
    // Refresh both scene shots and workflow shots
    await store.fetchShots(sid)
    if (workflowId.value) {
      await store.loadWorkflowDetail(workflowId.value)
    }
  } catch (e: any) {
    uni.showToast({ title: e.message || '重排失败', icon: 'none' })
  }
}
</script>

<style lang="scss" scoped>
.vs {
  min-height: 100vh;
  background: linear-gradient(180deg, #f0f5ff 0%, $lv-bg-end 100%);

  &__toolbar {
    position: sticky;
    top: calc(var(--status-bar-height) + 88rpx);
    z-index: 10;
    background: rgba(255, 255, 255, 0.95);
    backdrop-filter: blur(10px);
    border-bottom: 1rpx solid #e5edf8;
    padding: 12rpx $lv-page-padding;

    &-row {
      display: flex;
      align-items: center;
      gap: 8rpx;
      margin-bottom: 8rpx;
    }

    &-status {
      font-size: $lv-font-sm;
      color: $lv-primary;
      display: flex;
      align-items: center;
      gap: 6rpx;

      &--idle {
        color: $lv-text-muted;
      }
    }

    &-hint {
      font-size: $lv-font-xs;
      color: #d97706;
    }

    &-actions {
      white-space: nowrap;
      padding-bottom: 4rpx;
    }

    &-actions-inner {
      display: inline-flex;
      gap: 8rpx;
    }

    &-btn {
      display: inline-flex;
      flex-direction: column;
      align-items: center;
      gap: 2rpx;
      padding: 8rpx 16rpx;
      border-radius: $lv-radius-md;
      background: $lv-surface-solid;
      border: 1rpx solid #e5edf8;
      min-width: 72rpx;

      &--disabled {
        opacity: 0.4;
      }

      &--danger {
        border-color: #fecaca;
        color: #dc2626;
      }

      &-icon {
        font-size: 20rpx;
      }

      &-label {
        font-size: $lv-font-xs;
        color: $lv-text-primary;
      }
    }
  }

  &__content {
    padding: $lv-page-padding;
    padding-bottom: 120rpx;
  }

  &__loading {
    display: flex;
    justify-content: center;
    padding: 60rpx 0;
  }

  &__empty {
    padding: 40rpx 0;
  }

  &__overlay {
    position: absolute;
    top: 0; left: 0; right: 0; bottom: 0;
    z-index: 20;
    display: flex;
    align-items: center;
    justify-content: center;
    background: rgba(255, 255, 255, 0.85);
    backdrop-filter: blur(4px);

    &-body {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 16rpx;
    }

    &-text {
      font-size: $lv-font-sm;
      color: $lv-text-secondary;
    }
  }

  // 选择操作栏
  &__selection-bar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 12rpx 0;
    gap: 12rpx;

    &-left {
      display: flex;
      align-items: center;
      gap: 12rpx;
      flex-wrap: wrap;
    }

    &-right {
      display: flex;
      gap: 8rpx;
    }
  }

  &__checkbox-inline {
    display: flex;
    align-items: center;
    gap: 8rpx;
  }

  &__checkbox {
    width: 20rpx;
    height: 20rpx;
    border: 2rpx solid #cbd5e1;
    border-radius: 4rpx;
    transition: all 0.2s;

    &--checked {
      background: $lv-primary;
      border-color: $lv-primary;
      position: relative;

      &::after {
        content: '';
        position: absolute;
        top: 2rpx; left: 5rpx;
        width: 6rpx; height: 10rpx;
        border: solid white;
        border-width: 0 2rpx 2rpx 0;
        transform: rotate(45deg);
      }
    }
  }

  &__selection-text {
    font-size: $lv-font-sm;
    color: $lv-primary;
  }

  &__selection-count {
    font-size: $lv-font-xs;
    color: $lv-text-muted;
  }

  &__selection-skip {
    font-size: $lv-font-xs;
    color: #d97706;
  }

  &__batch-btn {
    padding: 6rpx 16rpx;
    background: $lv-primary;
    color: #fff;
    border-radius: $lv-radius-full;
    font-size: $lv-font-xs;

    &--video {
      background: #7c3aed;
    }
  }

  // 镜头卡片
  &__shot-list {
    display: flex;
    flex-direction: column;
    gap: 16rpx;
    margin-top: 8rpx;
  }

  &__shot-card {
    background: #fff;
    border-radius: 24rpx;
    padding: 20rpx;
    border: 2rpx solid #e5edf8;
    transition: all 0.2s;

    &--selected {
      border-color: $lv-primary;
    }
  }

  &__shot-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 12rpx;

    &-left {
      display: flex;
      align-items: center;
      gap: 8rpx;
    }

    &-right {
      display: flex;
      align-items: center;
    }
  }

  &__shot-index {
    font-size: $lv-font-base;
    font-weight: 600;
    color: $lv-text-primary;
  }

  &__shot-status {
    padding: 2rpx 12rpx;
    border-radius: $lv-radius-full;
    font-size: $lv-font-xs;

    &--pending { background: #f1f5f9; color: #64748b; }
    &--pending-detail { background: #fef3c7; color: #d97706; }
    &--storyboard-ready { background: #f3e8ff; color: #7c3aed; }
    &--video-ready { background: #dcfce7; color: #16a34a; }
    &--failed { background: #fee2e2; color: #dc2626; }
  }

  &__shot-skip {
    padding: 2rpx 12rpx;
    border-radius: $lv-radius-full;
    font-size: $lv-font-xs;
    background: #f1f5f9;
    color: #94a3b8;

    &--active {
      background: #fef3c7;
      color: #d97706;
    }
  }

  &__shot-reorder {
    display: flex;
    gap: 4rpx;
    margin-left: 8rpx;
  }

  &__reorder-btn {
    width: 36rpx;
    height: 36rpx;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: $lv-radius-sm;
    background: #f1f5f9;
    border: 1rpx solid #e2e8f0;
    font-size: 16rpx;
    color: $lv-text-primary;

    &--disabled {
      opacity: 0.3;
    }

    &:active:not(&--disabled) {
      background: #e2e8f0;
    }
  }

  &__create-shot {
    margin-top: 20rpx;
  }

  &__shot-summary {
    margin-bottom: 8rpx;

    &-text {
      font-size: $lv-font-sm;
      color: $lv-text-secondary;
      line-height: 1.5;
    }
  }

  &__shot-meta {
    display: flex;
    flex-wrap: wrap;
    gap: 12rpx;
    margin-bottom: 8rpx;

    &-item {
      font-size: $lv-font-xs;
      color: $lv-text-muted;
    }
  }

  &__shot-characters {
    display: flex;
    flex-wrap: wrap;
    gap: 6rpx;
    margin-bottom: 8rpx;
  }

  &__shot-character-tag {
    padding: 2rpx 10rpx;
    background: #eff6ff;
    border-radius: $lv-radius-full;
    font-size: $lv-font-xs;
    color: $lv-primary;
  }

  &__shot-continuity {
    margin-bottom: 8rpx;
    padding: 6rpx 12rpx;
    background: #f0f9ff;
    border-radius: $lv-radius-sm;
    font-size: $lv-font-xs;
    color: #0369a1;
  }

  &__shot-error {
    margin-bottom: 8rpx;
    padding: 8rpx 12rpx;
    background: #fef2f2;
    border-radius: $lv-radius-sm;
    font-size: $lv-font-xs;
    color: #dc2626;
  }

  &__shot-previews {
    display: flex;
    gap: 12rpx;
    margin-bottom: 12rpx;
  }

  &__shot-preview {
    flex: 1;

    &-label {
      font-size: $lv-font-xs;
      color: $lv-text-muted;
      margin-bottom: 4rpx;
      display: block;
    }

    &-image {
      width: 100%;
      height: 160rpx;
      border-radius: $lv-radius-sm;
      background: #f1f5f9;
    }

    &-video {
      width: 100%;
      height: 160rpx;
      border-radius: $lv-radius-sm;
      background: #0f172a;
    }
  }

  &__shot-actions {
    display: flex;
    gap: 8rpx;
  }

  &__shot-action-btn {
    flex: 1;
    padding: 8rpx 0;
    text-align: center;
    border-radius: $lv-radius-md;
    background: #f8fafc;
    border: 1rpx solid #e2e8f0;
    font-size: $lv-font-xs;
    color: $lv-text-primary;

    &--disabled {
      opacity: 0.4;
    }
  }

  // 拼接结果
  &__concat-result {
    margin-top: 24rpx;
    padding: 16rpx;
    background: #fff;
    border-radius: 24rpx;
    border: 1rpx solid #e5edf8;

    &-title {
      font-size: $lv-font-base;
      font-weight: 600;
      margin-bottom: 8rpx;
      display: block;
    }

    &-video {
      width: 100%;
      height: 300rpx;
      border-radius: $lv-radius-sm;
      background: #0f172a;
      margin-bottom: 12rpx;
    }
  }

  // 弹窗
  &__modal-body {
    padding: 16rpx 0;
  }

  &__modal-text {
    font-size: $lv-font-sm;
    color: $lv-text-primary;
    margin-bottom: 8rpx;
    display: block;
  }

  &__modal-hint {
    font-size: $lv-font-xs;
    color: $lv-text-muted;
  }
}
</style>
