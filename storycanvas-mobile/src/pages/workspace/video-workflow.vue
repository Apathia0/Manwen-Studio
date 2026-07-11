<template>
  <view class="video-workflow">
    <lv-navbar title="视频工作流" show-back />

    <view class="video-workflow__content">
      <view v-if="loading" class="video-workflow__loading">
        <lv-loading />
      </view>

      <template v-else-if="activeChapterId">
        <view class="video-workflow__section">
          <text class="video-workflow__section-title">工作流列表</text>
          <view v-if="workflows.length === 0" class="video-workflow__empty">
            <lv-empty title="暂无工作流" description="点击右下角按钮创建" />
          </view>

          <view v-else class="video-workflow__list">
            <view v-for="wf in workflows" :key="wf.id" class="video-workflow__card" @tap="goToShots(wf.id)">
              <view class="video-workflow__card-header">
                <text class="video-workflow__card-title">工作流 #{{ wf.id }}</text>
                <view :class="['video-workflow__status-badge', `video-workflow__status-badge--${wf.workflow_status}`]">
                  <text>{{ statusLabel(wf.workflow_status) }}</text>
                </view>
              </view>
              <view class="video-workflow__card-stats">
                <view class="video-workflow__stat"><text class="video-workflow__stat-value">{{ wf.total_shots }}</text><text class="video-workflow__stat-label">总镜头</text></view>
                <view class="video-workflow__stat"><text class="video-workflow__stat-value">{{ wf.completed_shots }}</text><text class="video-workflow__stat-label">已完成</text></view>
                <view class="video-workflow__stat"><text class="video-workflow__stat-value">{{ wf.failed_shots }}</text><text class="video-workflow__stat-label">失败</text></view>
              </view>
              <view class="video-workflow__card-actions" @tap.stop>
                <lv-button size="sm" @tap="goToShots(wf.id)">继续</lv-button>
                <lv-button size="sm" secondary @tap="handleReset(wf.id)">重置</lv-button>
              </view>
            </view>
          </view>
        </view>
      </template>

      <view v-else class="video-workflow__empty">
        <lv-empty title="未选择章节" description="请从章节工作台进入" />
      </view>
    </view>

    <lv-fab v-if="activeChapterId" @tap="showCreateModal = true" />

    <lv-modal v-model:show="showCreateModal" title="新建视频工作流" @confirm="handleCreateWorkflow" :confirm-loading="creating">
      <view class="video-workflow__modal-content">
        <view class="video-workflow__field">
          <text class="video-workflow__field-label">视频风格</text>
          <view class="video-workflow__style-grid">
            <view v-for="preset in store.stylePresets" :key="preset.id"
              :class="['video-workflow__style-item', { 'video-workflow__style-item--active': selectedStylePresetId === preset.id }]"
              @tap="selectedStylePresetId = preset.id; store.selectedStyle = preset.name">
              <image v-if="preset.image_url" :src="mangaImageUrl(preset.image_url)" class="video-workflow__style-image" mode="aspectFill" />
              <view v-else class="video-workflow__style-placeholder"><lv-icon name="Palette" :size="20" color="#94a3b8" /></view>
              <text class="video-workflow__style-name">{{ preset.name }}</text>
            </view>
          </view>
        </view>
        <view class="video-workflow__field">
          <text class="video-workflow__field-label">视频比例</text>
          <view class="video-workflow__ratio-group">
            <view :class="['video-workflow__ratio-btn', { 'video-workflow__ratio-btn--active': store.videoAspectRatio === '16:9' }]" @tap="store.videoAspectRatio = '16:9'"><text>16:9 横屏</text></view>
            <view :class="['video-workflow__ratio-btn', { 'video-workflow__ratio-btn--active': store.videoAspectRatio === '9:16' }]" @tap="store.videoAspectRatio = '9:16'"><text>9:16 竖屏</text></view>
          </view>
        </view>
      </view>
    </lv-modal>
  </view>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useVideoWorkflowStore } from '@/stores/videoWorkflow'
import { useWorkspaceStore } from '@/stores/workspace'
import { mangaImageUrl } from '@/utils/url'
import LvNavbar from '@/components/lv-navbar/lv-navbar.vue'
import LvButton from '@/components/lv-button/lv-button.vue'
import LvLoading from '@/components/lv-loading/lv-loading.vue'
import LvEmpty from '@/components/lv-empty/lv-empty.vue'
import LvFab from '@/components/lv-fab/lv-fab.vue'
import LvModal from '@/components/lv-modal/lv-modal.vue'
import LvIcon from '@/components/lv-icon/lv-icon.vue'

const store = useVideoWorkflowStore()
const workspaceStore = useWorkspaceStore()

const activeChapterId = ref<number>(0)
const loading = ref(false)
const showCreateModal = ref(false)
const creating = ref(false)
const selectedStylePresetId = ref<number | null>(null)

const workflows = computed(() => store.workflows)

function statusLabel(status: string): string {
  const labels: Record<string, string> = {
    idle: '空闲', parsing_shots: '拆镜中', generating_details: '生成详情中',
    generating_storyboards: '生成故事版中', generating_videos: '生成视频中',
    reanalyzing_prompts: '分析提示词中', completed: '已完成', failed: '失败',
  }
  return labels[status] || status
}

async function loadWorkflows(chapterId: number) {
  loading.value = true
  try { await store.fetchWorkflows(chapterId) } finally { loading.value = false }
}

function goToShots(workflowId: number) {
  uni.navigateTo({ url: `/pages/workspace/video-shots?workflowId=${workflowId}` })
}

async function handleCreateWorkflow() {
  if (!activeChapterId.value) { uni.showToast({ title: '请先选择章节', icon: 'none' }); return }
  creating.value = true
  try {
    const payload: any = { chapter_id: activeChapterId.value, video_style: store.selectedStyle }
    await store.createWorkflow(payload)
    showCreateModal.value = false
    uni.showToast({ title: '工作流已创建', icon: 'success' })
    await loadWorkflows(activeChapterId.value)
    if (store.activeWorkflow) goToShots(store.activeWorkflow.id)
  } catch (e: any) { uni.showToast({ title: e.message || '创建失败', icon: 'none' }) }
  finally { creating.value = false }
}

async function handleReset(workflowId: number) {
  uni.showModal({
    title: '确认重置', content: '重置将清除所有镜头、故事版和视频数据，是否继续？',
    success: async (res) => {
      if (res.confirm) {
        try { await store.resetWorkflow(workflowId); uni.showToast({ title: '已重置', icon: 'success' }); await loadWorkflows(activeChapterId.value) }
        catch (e: any) { uni.showToast({ title: e.message || '重置失败', icon: 'none' }) }
      }
    }
  })
}

onMounted(async () => {
  const pages = getCurrentPages()
  const page = pages[pages.length - 1] as any
  const chapterId = Number(page.options?.chapterId || 0)
  if (chapterId) { activeChapterId.value = chapterId; await loadWorkflows(chapterId) }
  await store.loadStylePresets()
})
</script>

<style lang="scss" scoped>
.video-workflow {
  min-height: 100vh;
  background: linear-gradient(180deg, $lv-bg-start 0%, $lv-bg-end 100%);
  &__content { padding: calc(var(--status-bar-height) + 88rpx + $lv-page-padding) $lv-page-padding 120rpx; }
  &__section { margin-bottom: 32rpx; }
  &__section-title { font-size: $lv-font-lg; font-weight: 600; color: $lv-text-primary; margin-bottom: 16rpx; display: block; }
  &__loading { display: flex; justify-content: center; padding: 60rpx 0; }
  &__empty { padding: 40rpx 0; }
  &__card { background: $lv-surface-solid; border-radius: 24rpx; padding: 24rpx; margin-bottom: 16rpx; }
  &__card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16rpx; }
  &__card-title { font-size: $lv-font-base; font-weight: 600; color: $lv-text-primary; }
  &__status-badge { padding: 4rpx 16rpx; border-radius: $lv-radius-full; font-size: $lv-font-xs;
    &--idle { background: #f1f5f9; color: #64748b; }
    &--parsing_shots, &--generating_details, &--generating_storyboards, &--generating_videos, &--reanalyzing_prompts { background: #dbeafe; color: #2563eb; }
    &--completed { background: #dcfce7; color: #16a34a; }
    &--failed { background: #fee2e2; color: #dc2626; }
  }
  &__card-stats { display: flex; gap: 32rpx; margin-bottom: 16rpx; }
  &__stat { display: flex; flex-direction: column; align-items: center; }
  &__stat-value { font-size: $lv-font-lg; font-weight: 600; color: $lv-text-primary; }
  &__stat-label { font-size: $lv-font-xs; color: $lv-text-muted; }
  &__card-actions { display: flex; gap: 12rpx; }
  &__modal-content { padding: 16rpx 0; }
  &__field { margin-bottom: 24rpx; }
  &__field-label { font-size: $lv-font-sm; color: $lv-text-secondary; margin-bottom: 12rpx; display: block; }
  &__style-grid { display: flex; flex-wrap: wrap; gap: 12rpx; }
  &__style-item { width: 140rpx; border-radius: $lv-radius-md; overflow: hidden; border: 2rpx solid transparent; background: $lv-surface-solid;
    &--active { border-color: $lv-primary; }
  }
  &__style-image { width: 140rpx; height: 100rpx; display: block; }
  &__style-placeholder { width: 140rpx; height: 100rpx; display: flex; align-items: center; justify-content: center; background: $lv-primary-lighter; }
  &__style-name { font-size: $lv-font-xs; color: $lv-text-primary; padding: 8rpx; text-align: center; display: block; }
  &__ratio-group { display: flex; gap: 12rpx; }
  &__ratio-btn { flex: 1; padding: 16rpx; text-align: center; background: $lv-surface-solid; border-radius: $lv-radius-md; border: 2rpx solid transparent;
    &--active { border-color: $lv-primary; background: $lv-primary-light; }
  }
}
</style>
