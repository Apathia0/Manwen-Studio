<template>
  <view class="wf">
    <!-- 无工作流 - 展示创建入口 -->
    <template v-if="!hasWorkflow && !loading">
      <view class="wf__create-card">
        <view class="wf__create-icon">
          <lv-icon name="Video" :size="48" color="#2563eb" />
        </view>
        <text class="wf__create-title">视频工作流</text>
        <text class="wf__create-desc">AI 将本章内容自动拆分为镜头，生成故事版和视频</text>
        <lv-button block @tap="showStyleModal = true" :loading="creating">
          {{ creating ? '创建中...' : '新建视频工作流' }}
        </lv-button>
      </view>
    </template>

    <!-- 加载中 -->
    <view v-else-if="loading" class="wf__loading">
      <lv-loading />
    </view>

    <!-- 有工作流 - 显示操作栏 + 镜头列表 -->
    <template v-else-if="workflow">
      <!-- 顶部工具栏 -->
      <view class="wf__toolbar">
        <scroll-view scroll-x class="wf__toolbar-scroll" show-scrollbar="false">
          <view class="wf__toolbar-inner">
            <view class="wf__toolbar-btn" :class="toolbarBtnClass(!canParse)" @tap="handleParseShots">
              <text class="wf__toolbar-icon">⇄</text>
              <text class="wf__toolbar-label">{{ parsing ? '拆镜中…' : '拆镜' }}</text>
            </view>
            <view class="wf__toolbar-btn" :class="toolbarBtnClass(!canGenerateDetails)" @tap="handleGenerateDetails">
              <text class="wf__toolbar-icon">✦</text>
              <text class="wf__toolbar-label">生成详情</text>
            </view>
            <view class="wf__toolbar-btn" :class="toolbarBtnClass(!canStoryboard)" @tap="handleBatchStoryboard">
              <text class="wf__toolbar-icon">🖼</text>
              <text class="wf__toolbar-label">故事版</text>
            </view>
            <view class="wf__toolbar-btn" :class="toolbarBtnClass(!canVideo)" @tap="handleBatchVideo">
              <text class="wf__toolbar-icon">▶</text>
              <text class="wf__toolbar-label">视频</text>
            </view>
            <view class="wf__toolbar-btn" :class="toolbarBtnClass(!canConcat)" @tap="showConcatModal = true">
              <text class="wf__toolbar-icon">⏹</text>
              <text class="wf__toolbar-label">拼接</text>
            </view>
          </view>
        </scroll-view>
      </view>

      <!-- 状态栏 -->
      <view class="wf__status-bar" v-if="store.workflowRunning || workflowStatusText">
        <lv-loading v-if="store.workflowRunning" :size="14" />
        <text :class="['wf__status-text', { 'wf__status-text--running': store.workflowRunning }]">
          {{ store.workflowRunning ? '任务执行中...' : workflowStatusText }}
        </text>
        <text class="wf__status-hint" v-if="retryHint">{{ retryHint }}</text>
      </view>

      <!-- 拆镜遮罩 -->
      <view v-if="parsing" class="wf__overlay">
        <view class="wf__overlay-body">
          <lv-loading :size="36" />
          <text class="wf__overlay-text">{{ workflow.message || '正在拆镜...' }}</text>
          <text class="wf__overlay-hint" v-if="retryHint">{{ retryHint }}</text>
        </view>
      </view>

      <!-- 选择操作栏 -->
      <view v-if="sortedShots.length > 0" class="wf__selection-bar">
        <view class="wf__selection-left">
          <view class="wf__checkbox-row" @tap="handleSelectAll">
            <view :class="['wf__checkbox', { 'wf__checkbox--checked': allSelected }]" />
            <text class="wf__selection-text">{{ allSelected ? '取消全选' : '全选' }}</text>
          </view>
          <text class="wf__selection-count">已选 {{ store.selectedShotIds.length }}/{{ sortedShots.length }}</text>
          <text v-if="store.skippedShotIds.length > 0" class="wf__selection-skip">跳过 {{ store.skippedShotIds.length }}</text>
        </view>
        <view class="wf__selection-right" v-if="activeShots.length > 0">
          <view v-if="canStoryboard" class="wf__batch-btn" @tap="handleBatchStoryboard">生成故事版</view>
          <view v-if="canVideo" class="wf__batch-btn wf__batch-btn--video" @tap="handleBatchVideo">生成视频</view>
        </view>
      </view>

      <!-- 镜头列表 -->
      <view class="wf__shot-list" v-if="sortedShots.length > 0">
        <view
          v-for="shot in sortedShots"
          :key="shot.id"
          :class="['wf__shot-card', { 'wf__shot-card--selected': store.selectedShotIds.includes(shot.id) }]"
        >
          <view class="wf__shot-header">
            <view class="wf__shot-header-left">
              <view class="wf__checkbox-row" @tap="store.toggleShotSelection(shot.id)">
                <view :class="['wf__checkbox', { 'wf__checkbox--checked': store.selectedShotIds.includes(shot.id) }]" />
              </view>
              <text class="wf__shot-index">镜头 {{ shot.shot_index }}</text>
              <view :class="['wf__shot-badge', `wf__shot-badge--${badgeType(shot)}`]">
                <text>{{ badgeLabel(shot) }}</text>
              </view>
            </view>
            <view
              :class="['wf__shot-skip-btn', { 'wf__shot-skip-btn--active': store.skippedShotIds.includes(shot.id) }]"
              @tap="store.toggleShotSkip(shot.id)"
            >
              <text>{{ store.skippedShotIds.includes(shot.id) ? '已跳过' : '跳过' }}</text>
            </view>
          </view>

          <text class="wf__shot-summary">{{ shot.story_summary || '暂无情节摘要' }}</text>

          <view class="wf__shot-meta" v-if="shot.scene_location || shot.time_of_day || shot.camera_plan">
            <text v-if="shot.scene_location" class="wf__meta-item">场景: {{ shot.scene_location }}</text>
            <text v-if="shot.time_of_day" class="wf__meta-item">时间: {{ shot.time_of_day }}</text>
            <text v-if="shot.camera_plan" class="wf__meta-item">运镜: {{ shot.camera_plan }}</text>
          </view>

          <view class="wf__shot-chars" v-if="shot.characters && shot.characters.length > 0">
            <view class="wf__char-tag" v-for="ch in shot.characters" :key="ch">{{ ch }}</view>
          </view>

          <view class="wf__shot-error" v-if="shot.error_message">{{ shot.error_message }}</view>

          <view class="wf__shot-previews" v-if="shot.storyboard_image_url || shot.video_url">
            <view class="wf__preview" v-if="shot.storyboard_image_url">
              <text class="wf__preview-label">故事版</text>
              <image :src="assetUrl(shot.storyboard_image_url)" class="wf__preview-img" mode="aspectFill" />
            </view>
            <view class="wf__preview" v-if="shot.video_url">
              <text class="wf__preview-label">视频</text>
              <video :src="assetUrl(shot.video_url)" class="wf__preview-video" controls />
            </view>
          </view>

          <!-- 单镜按钮行 -->
          <view class="wf__shot-actions">
            <view class="wf__shot-action-btn" :class="{ 'wf__shot-action-btn--disabled': !canGenerateDetails }" @tap="handleDetailForShot(shot.id)">
              生成详情
            </view>
            <view
              :class="['wf__shot-action-btn', { 'wf__shot-action-btn--disabled': !canStoryboardSingle }]"
              @tap="handleStoryboardForShot(shot.id)"
            >
              {{ shot.storyboard_image_url ? '重绘' : '生成故事版' }}
            </view>
            <view
              :class="['wf__shot-action-btn', { 'wf__shot-action-btn--disabled': !canVideoSingle }]"
              @tap="handleVideoForShot(shot.id)"
            >
              {{ shot.video_url ? '重绘' : '生成视频' }}
            </view>
            <view
              class="wf__shot-action-btn wf__shot-action-btn--workbench"
              @tap="handleOpenWorkbench(shot)"
            >
              工作台
            </view>
          </view>
        </view>
      </view>

      <!-- 空镜头 -->
      <lv-empty
        v-if="sortedShots.length === 0 && !parsing"
        title="暂无镜头"
        description="点击顶部「拆镜」按钮将本章内容拆分为镜头"
      />

      <!-- 拼接结果 -->
      <view class="wf__concat-result" v-if="store.concatVideoUrl">
        <text class="wf__concat-title">拼接视频</text>
        <video :src="assetUrl(store.concatVideoUrl)" controls class="wf__concat-video" />
        <lv-button size="sm" @tap="store.concatVideoUrl = null">关闭</lv-button>
      </view>
    </template>

    <!-- 创建工作流弹窗 - 风格预设选择 -->
    <lv-modal v-model:show="showStyleModal" title="新建视频工作流" @confirm="handleCreateWorkflow" :confirm-loading="creating">
      <view class="wf__modal-body">
        <view class="wf__field">
          <text class="wf__field-label">视频风格</text>
          <scroll-view scroll-x class="wf__style-scroll" show-scrollbar="false">
            <view class="wf__style-list">
              <view
                v-for="preset in store.stylePresets"
                :key="preset.id"
                :class="['wf__style-item', { 'wf__style-item--active': selectedStylePresetId === preset.id }]"
                @tap="selectedStylePresetId = preset.id; store.selectedStyle = preset.name"
              >
                <image v-if="preset.image_url" :src="mangaImageUrl(preset.image_url)" class="wf__style-image" mode="aspectFill" />
                <view v-else class="wf__style-placeholder"><lv-icon name="Palette" :size="20" color="#94a3b8" /></view>
                <text class="wf__style-name">{{ preset.name }}</text>
              </view>
            </view>
          </scroll-view>
        </view>
        <view class="wf__field">
          <text class="wf__field-label">视频比例</text>
          <view class="wf__ratio-group">
            <view
              :class="['wf__ratio-btn', { 'wf__ratio-btn--active': store.videoAspectRatio === '16:9' }]"
              @tap="store.videoAspectRatio = '16:9'"
            >16:9 横屏</view>
            <view
              :class="['wf__ratio-btn', { 'wf__ratio-btn--active': store.videoAspectRatio === '9:16' }]"
              @tap="store.videoAspectRatio = '9:16'"
            >9:16 竖屏</view>
          </view>
        </view>
      </view>
    </lv-modal>

    <!-- 拼接确认弹窗 -->
    <lv-modal v-model:show="showConcatModal" title="拼接视频" @confirm="handleConcat" :confirm-loading="concating">
      <view class="wf__modal-body">
        <text class="wf__modal-text">确认将所有已完成视频拼接为完整章节视频？</text>
        <text class="wf__modal-hint">已完成 {{ videoReadyCount }}/{{ sortedShots.length }} 个镜头</text>
      </view>
    </lv-modal>

    <!-- 视频卡片工作台 -->
    <VideoCardWorkbench
      :visible="store.workbenchVisible"
      :shot-id="store.workbenchShotId ?? 0"
      :shot-data="store.workbenchShotData"
      :workflow-id="workflowId ?? 0"
      :chapter-id="props.chapterId"
      :initial-type="store.workbenchInitialType ?? undefined"
      @close="handleCloseWorkbench"
      @updated="handleWorkbenchUpdated"
    />
  </view>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useVideoWorkflowStore } from '@/stores/videoWorkflow'
import { useVideoGenStore } from '@/stores/videoGen'
import { useWorkflowPolling } from '@/composables/useWorkflowPolling'
import { mangaImageUrl, videoAssetUrl } from '@/utils/url'
import LvButton from '@/components/lv-button/lv-button.vue'
import LvLoading from '@/components/lv-loading/lv-loading.vue'
import LvEmpty from '@/components/lv-empty/lv-empty.vue'
import LvIcon from '@/components/lv-icon/lv-icon.vue'
import LvModal from '@/components/lv-modal/lv-modal.vue'
import VideoCardWorkbench from '@/components/video-card-workbench/video-card-workbench.vue'
import type { ChapterVideoShot } from '@/api/types'
import type { WorkbenchCardType } from '@/stores/videoWorkflow'

interface Props {
  chapterId: number
  storyId: number
}

const props = defineProps<Props>()
const store = useVideoWorkflowStore()
const videoGenStore = useVideoGenStore()

const workflowId = ref<number | null>(null)
const { start: startPolling, stop: stopPolling } = useWorkflowPolling(workflowId)

const loading = ref(false)
const creating = ref(false)
const parsing = ref(false)
const concating = ref(false)
const showStyleModal = ref(false)
const showConcatModal = ref(false)
const selectedStylePresetId = ref<number | null>(null)

// 工作流
const workflow = computed(() => store.currentWorkflow)
const hasWorkflow = computed(() => !!workflow.value)

const sortedShots = computed(() =>
  [...(store.currentShots || [])].sort((a, b) => a.shot_index - b.shot_index)
)

const allSelected = computed(() =>
  sortedShots.value.length > 0 && store.selectedShotIds.length === sortedShots.value.length
)

const activeShots = computed(() =>
  store.selectedShotIds.filter(id => !store.skippedShotIds.includes(id))
)

const status = computed(() => workflow.value?.workflow_status ?? 'idle')

const workflowStatusText = computed(() => {
  const labels: Record<string, string> = {
    idle: '空闲', initial: '初始', parsing_shots: '拆镜中', generating_details: '生成详情中',
    shots_ready: '镜头已就绪', generating_storyboards: '生成故事版中', storyboards_ready: '故事版已就绪',
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
  return !workflow.value || sortedShots.value.length === 0
})

const canGenerateDetails = computed(() => {
  if (store.workflowRunning) return false
  return ['shots_ready', 'generating_details', 'failed'].includes(status.value) && activeShots.value.length > 0
})

const canStoryboard = computed(() => {
  if (store.workflowRunning) return false
  return ['shots_ready', 'generating_storyboards', 'failed'].includes(status.value) && activeShots.value.length > 0
})

const canVideo = computed(() => {
  if (store.workflowRunning) return false
  return ['storyboards_ready', 'generating_videos', 'failed'].includes(status.value) && activeShots.value.length > 0
})

const canConcat = computed(() => {
  if (store.workflowRunning) return false
  return ['completed', 'videos_ready', 'storyboards_ready', 'generating_videos', 'shots_ready'].includes(status.value)
})

const canStoryboardSingle = computed(() => !store.workflowRunning && ['shots_ready', 'failed', 'storyboards_ready'].includes(status.value))
const canVideoSingle = computed(() => !store.workflowRunning && ['storyboards_ready', 'failed', 'videos_ready'].includes(status.value))

function badgeType(shot: ChapterVideoShot): string {
  if (shot.status === 'failed') return 'failed'
  if (shot.status === 'video_ready') return 'video-ready'
  if (shot.status === 'storyboard_ready') return 'storyboard-ready'
  if (!shot.camera_plan) return 'pending-detail'
  return 'pending'
}

function badgeLabel(shot: ChapterVideoShot): string {
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

function toolbarBtnClass(disabled: boolean): Record<string, boolean> {
  return { 'wf__toolbar-btn--disabled': disabled }
}

function assetUrl(path?: string | null): string {
  return videoAssetUrl(path || null) || ''
}

// 初始化
onMounted(async () => {
  await store.loadStylePresets()
  if (props.chapterId) {
    await loadWorkflowForChapter(props.chapterId)
  }
})

onUnmounted(stopPolling)

watch(() => props.chapterId, async (newId) => {
  if (newId) {
    stopPolling()
    store.currentWorkflow = null
    store.currentShots = []
    await loadWorkflowForChapter(newId)
  }
})

async function loadWorkflowForChapter(chapterId: number) {
  loading.value = true
  try {
    await store.fetchWorkflows(chapterId)
    const latestWorkflow = store.workflows[store.workflows.length - 1]
    if (latestWorkflow) {
      workflowId.value = latestWorkflow.id
      await store.loadWorkflowDetail(latestWorkflow.id)
      startPolling()
    }
  } finally {
    loading.value = false
  }
}

// 操作
async function handleCreateWorkflow() {
  if (!props.chapterId) return
  creating.value = true
  try {
    const result = await store.createWorkflow({
      chapter_id: props.chapterId,
      video_style: store.selectedStyle,
    })
    showStyleModal.value = false
    workflowId.value = result.id
    await store.loadWorkflowDetail(result.id)
  } catch (e: any) {
    uni.showToast({ title: e.message || '创建失败', icon: 'none' })
  } finally {
    creating.value = false
  }
}

async function handleParseShots() {
  if (!canParse.value || !workflowId.value) return
  parsing.value = true
  try {
    await store.parseShots(workflowId.value)
    startPolling()
  } finally {
    parsing.value = false
  }
}

async function handleGenerateDetails() {
  if (!canGenerateDetails.value || !workflowId.value) return
  try {
    await store.generateShotDetails(workflowId.value, activeShots.value)
    startPolling()
  } catch (e: any) {
    uni.showToast({ title: e.message || '操作失败', icon: 'none' })
  }
}

async function handleDetailForShot(shotId: number) {
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
    await store.generateStoryboards(workflowId.value, activeShots.value)
    startPolling()
  } catch (e: any) {
    uni.showToast({ title: e.message || '操作失败', icon: 'none' })
  }
}

async function handleStoryboardForShot(shotId: number) {
  if (!canStoryboardSingle.value || !workflowId.value) return
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
    await store.generateVideos(workflowId.value, activeShots.value)
    startPolling()
  } catch (e: any) {
    uni.showToast({ title: e.message || '操作失败', icon: 'none' })
  }
}

async function handleVideoForShot(shotId: number) {
  if (!canVideoSingle.value || !workflowId.value) return
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
  } catch (e: any) {
    uni.showToast({ title: e.message || '拼接失败', icon: 'none' })
  } finally {
    concating.value = false
  }
}

function handleOpenWorkbench(shot: ChapterVideoShot, initialType?: WorkbenchCardType) {
  if (!workflowId.value) return
  store.openWorkbench(shot.id, shot, initialType)
}

function handleCloseWorkbench() {
  store.closeWorkbench()
}

async function handleWorkbenchUpdated() {
  if (workflowId.value) {
    await store.loadWorkflowDetail(workflowId.value)
  }
}

function handleSelectAll() {
  if (allSelected.value) store.clearSelection()
  else store.selectAllShots()
}
</script>

<style lang="scss" scoped>
.wf {
  min-height: 60vh;

  // 创建入口
  &__create-card {
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 80rpx 40rpx;
    gap: 16rpx;
  }

  &__create-icon {
    width: 100rpx;
    height: 100rpx;
    border-radius: 50%;
    background: #eff6ff;
    display: flex;
    align-items: center;
    justify-content: center;
    margin-bottom: 8rpx;
  }

  &__create-title {
    font-size: $lv-font-lg;
    font-weight: 600;
    color: $lv-text-primary;
  }

  &__create-desc {
    font-size: $lv-font-sm;
    color: $lv-text-muted;
    text-align: center;
    line-height: 1.5;
    margin-bottom: 16rpx;
  }

  // 加载
  &__loading {
    display: flex;
    justify-content: center;
    padding: 80rpx 0;
  }

  // 工具栏
  &__toolbar {
    position: sticky;
    top: 0;
    z-index: 5;
    background: #fff;
    border-radius: 24rpx;
    padding: 16rpx;
    margin-bottom: 12rpx;
    box-shadow: 0 2rpx 8rpx rgba(0,0,0,0.04);

    &-scroll {
      white-space: nowrap;
    }

    &-inner {
      display: inline-flex;
      gap: 8rpx;
    }

    &-btn {
      display: inline-flex;
      flex-direction: column;
      align-items: center;
      gap: 4rpx;
      padding: 10rpx 20rpx;
      border-radius: $lv-radius-md;
      background: #f8fafc;
      border: 1rpx solid #e2e8f0;
      min-width: 80rpx;

      &--disabled {
        opacity: 0.35;
      }

      &-icon { font-size: 20rpx; }
      &-label { font-size: $lv-font-xs; color: $lv-text-primary; }
    }
  }

  // 状态栏
  &__status-bar {
    display: flex;
    align-items: center;
    gap: 6rpx;
    padding: 8rpx 12rpx;
    background: #f0f5ff;
    border-radius: $lv-radius-sm;
    margin-bottom: 12rpx;
  }

  &__status-text {
    font-size: $lv-font-xs;
    color: $lv-text-muted;

    &--running { color: $lv-primary; }
  }

  &__status-hint {
    font-size: $lv-font-xs;
    color: #d97706;
  }

  // 遮罩
  &__overlay {
    position: absolute;
    top: 0; left: 0; right: 0; bottom: 0;
    z-index: 10;
    display: flex;
    align-items: center;
    justify-content: center;
    background: rgba(255,255,255,0.85);
    backdrop-filter: blur(4px);

    &-body {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 12rpx;
    }

    &-text {
      font-size: $lv-font-sm;
      color: $lv-text-secondary;
    }

    &-hint {
      font-size: $lv-font-xs;
      color: #d97706;
    }
  }

  // 选择栏
  &__selection-bar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 8rpx 0;
    gap: 8rpx;
  }

  &__selection-left {
    display: flex;
    align-items: center;
    gap: 8rpx;
    flex-wrap: wrap;
  }

  &__selection-right {
    display: flex;
    gap: 8rpx;
  }

  &__checkbox-row {
    display: flex;
    align-items: center;
    gap: 6rpx;
  }

  &__checkbox {
    width: 20rpx;
    height: 20rpx;
    border: 2rpx solid #cbd5e1;
    border-radius: 4rpx;

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

  &__selection-text { font-size: $lv-font-sm; color: $lv-primary; }
  &__selection-count { font-size: $lv-font-xs; color: $lv-text-muted; }
  &__selection-skip { font-size: $lv-font-xs; color: #d97706; }

  &__batch-btn {
    padding: 6rpx 16rpx;
    background: $lv-primary;
    color: #fff;
    border-radius: $lv-radius-full;
    font-size: $lv-font-xs;
    white-space: nowrap;

    &--video { background: #7c3aed; }
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

    &--selected { border-color: $lv-primary; }
  }

  &__shot-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 8rpx;

    &-left { display: flex; align-items: center; gap: 8rpx; }
  }

  &__shot-index {
    font-size: $lv-font-base;
    font-weight: 600;
    color: $lv-text-primary;
  }

  &__shot-badge {
    padding: 2rpx 12rpx;
    border-radius: $lv-radius-full;
    font-size: $lv-font-xs;

    &--pending { background: #f1f5f9; color: #64748b; }
    &--pending-detail { background: #fef3c7; color: #d97706; }
    &--storyboard-ready { background: #f3e8ff; color: #7c3aed; }
    &--video-ready { background: #dcfce7; color: #16a34a; }
    &--failed { background: #fee2e2; color: #dc2626; }
  }

  &__shot-skip-btn {
    padding: 2rpx 12rpx;
    border-radius: $lv-radius-full;
    font-size: $lv-font-xs;
    background: #f1f5f9;
    color: #94a3b8;

    &--active { background: #fef3c7; color: #d97706; }
  }

  &__shot-summary {
    font-size: $lv-font-sm;
    color: $lv-text-secondary;
    line-height: 1.5;
    margin-bottom: 8rpx;
  }

  &__shot-meta {
    display: flex;
    flex-wrap: wrap;
    gap: 12rpx;
    margin-bottom: 8rpx;

    &-item { font-size: $lv-font-xs; color: $lv-text-muted; }
  }

  &__shot-chars {
    display: flex;
    flex-wrap: wrap;
    gap: 6rpx;
    margin-bottom: 8rpx;
  }

  &__char-tag {
    padding: 2rpx 10rpx;
    background: #eff6ff;
    border-radius: $lv-radius-full;
    font-size: $lv-font-xs;
    color: $lv-primary;
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

    .wf__preview {
      flex: 1;
      &-label { font-size: $lv-font-xs; color: $lv-text-muted; margin-bottom: 4rpx; display: block; }
      &-img { width: 100%; height: 160rpx; border-radius: $lv-radius-sm; background: #f1f5f9; }
      &-video { width: 100%; height: 160rpx; border-radius: $lv-radius-sm; background: #0f172a; }
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

    &--disabled { opacity: 0.4; }

    &--workbench {
      background: $lv-primary-lighter;
      border-color: $lv-primary-light;
      color: $lv-primary;
      font-weight: 500;
    }
  }

  // 拼接结果
  &__concat-result {
    margin-top: 24rpx;
    padding: 16rpx;
    background: #fff;
    border-radius: 24rpx;
    border: 1rpx solid #e5edf8;

    &-title { font-size: $lv-font-base; font-weight: 600; margin-bottom: 8rpx; display: block; }
    &-video { width: 100%; height: 300rpx; border-radius: $lv-radius-sm; background: #0f172a; margin-bottom: 12rpx; }
  }

  // 弹窗
  &__modal-body { padding: 8rpx 0; }

  &__field { margin-bottom: 24rpx; }
  &__field-label { font-size: $lv-font-sm; color: $lv-text-secondary; margin-bottom: 12rpx; display: block; }

  &__style-scroll {
    white-space: nowrap;
  }

  &__style-list {
    display: inline-flex;
    gap: 12rpx;
  }

  &__style-item {
    display: inline-flex;
    flex-direction: column;
    width: 140rpx;
    border-radius: $lv-radius-md;
    overflow: hidden;
    border: 2rpx solid transparent;
    background: $lv-surface-solid;

    &--active { border-color: $lv-primary; }
  }

  &__style-image { width: 140rpx; height: 100rpx; display: block; }
  &__style-placeholder { width: 140rpx; height: 100rpx; display: flex; align-items: center; justify-content: center; background: $lv-primary-lighter; }
  &__style-name { font-size: $lv-font-xs; color: $lv-text-primary; padding: 8rpx; text-align: center; display: block; }

  &__ratio-group {
    display: flex;
    gap: 12rpx;
  }

  &__ratio-btn {
    flex: 1;
    padding: 16rpx;
    text-align: center;
    background: $lv-surface-solid;
    border-radius: $lv-radius-md;
    border: 2rpx solid transparent;

    &--active { border-color: $lv-primary; background: $lv-primary-light; }
  }

  &__modal-text { font-size: $lv-font-sm; color: $lv-text-primary; margin-bottom: 8rpx; display: block; }
  &__modal-hint { font-size: $lv-font-xs; color: $lv-text-muted; }
}
</style>
