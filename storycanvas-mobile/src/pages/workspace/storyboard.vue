<template>
  <view class="storyboard">
    <lv-navbar title="故事版" show-back />
    <view class="storyboard__content">
      <!-- 加载中 -->
      <view v-if="loading" class="storyboard__loading">
        <lv-loading />
      </view>

      <template v-else-if="shot">
        <!-- 镜头信息 -->
        <view class="storyboard__header">
          <text class="storyboard__shot-title">镜头 {{ shot.shot_index + 1 }}</text>
          <text class="storyboard__shot-status">{{ statusLabel }}</text>
        </view>

        <!-- 故事版图片 -->
        <view class="storyboard__card">
          <image
            v-if="shot.storyboard_image_url"
            :src="shot.storyboard_image_url"
            mode="widthFix"
            class="storyboard__image"
          />
          <view v-else class="storyboard__empty-image">
            <lv-empty title="暂无故事版" description="点击下方按钮生成" />
          </view>
        </view>

        <!-- 镜头详情 -->
        <view class="storyboard__card storyboard__info">
          <view class="storyboard__info-row" v-if="shot.scene_location">
            <text class="storyboard__info-label">场景</text>
            <text class="storyboard__info-value">{{ shot.scene_location }}</text>
          </view>
          <view class="storyboard__info-row" v-if="shot.time_of_day">
            <text class="storyboard__info-label">时间</text>
            <text class="storyboard__info-value">{{ shot.time_of_day }}</text>
          </view>
          <view class="storyboard__info-row" v-if="shot.camera_plan">
            <text class="storyboard__info-label">运镜</text>
            <text class="storyboard__info-value">{{ shot.camera_plan }}</text>
          </view>
          <view class="storyboard__info-row" v-if="shot.story_summary">
            <text class="storyboard__info-label">剧情</text>
            <text class="storyboard__info-value">{{ shot.story_summary }}</text>
          </view>
        </view>

        <!-- 操作按钮 -->
        <view class="storyboard__actions">
          <template v-if="!shot.storyboard_image_url">
            <lv-button block @tap="generateStoryboard" :loading="generating">
              生成故事版
            </lv-button>
          </template>
          <template v-else>
            <lv-button block @tap="regenerateStoryboard" :loading="generating" secondary>
              重新生成故事版
            </lv-button>
            <view class="storyboard__actions-row">
              <lv-button block @tap="handleReject" secondary class="storyboard__btn-reject">
                拒绝
              </lv-button>
              <lv-button block @tap="handleApprove">
                同意
              </lv-button>
            </view>
          </template>
          <lv-button block @tap="handleReanalyzePrompt" :loading="reanalyzingPrompt" secondary>
            分析提示词
          </lv-button>
          <lv-button block @tap="goToRender" class="storyboard__btn-render">
            生成视频
          </lv-button>
        </view>
      </template>

      <lv-empty v-else title="未找到镜头" description="请确认参数是否正确" />
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { videoApi } from '@/api'
import type { ChapterVideoShot } from '@/api/types'
import LvNavbar from '@/components/lv-navbar/lv-navbar.vue'
import LvButton from '@/components/lv-button/lv-button.vue'
import LvLoading from '@/components/lv-loading/lv-loading.vue'
import LvEmpty from '@/components/lv-empty/lv-empty.vue'

const loading = ref(false)
const generating = ref(false)
const reanalyzingPrompt = ref(false)
const shot = ref<ChapterVideoShot | null>(null)

const statusLabel = computed(() => {
  if (!shot.value) return ''
  const labels: Record<string, string> = {
    pending: '待处理',
    generating: '生成中',
    completed: '已完成',
    failed: '失败',
  }
  return labels[shot.value.status] || shot.value.status
})

async function loadShot(shotId: number, workflowId?: number) {
  loading.value = true
  try {
    if (workflowId) {
      const workflow = await videoApi.getChapterVideoWorkflow(workflowId)
      const found = workflow.shots.find(s => s.id === shotId)
      if (found) {
        shot.value = found
        return
      }
    }
    // 通过重新生成获取最新数据（无 workflow 时回退）
    shot.value = await videoApi.regenerateChapterWorkflowStoryboard(shotId)
  } catch (e: any) {
    uni.showToast({ title: e.message || '加载失败', icon: 'none' })
  } finally {
    loading.value = false
  }
}

async function generateStoryboard() {
  const pages = getCurrentPages()
  const page = pages[pages.length - 1] as any
  const shotId = Number(page.options?.shotId || 0)
  if (!shotId) {
    uni.showToast({ title: '参数错误', icon: 'none' })
    return
  }
  generating.value = true
  try {
    const result = await videoApi.regenerateChapterWorkflowStoryboard(shotId)
    shot.value = result
    uni.showToast({ title: '故事版已生成', icon: 'success' })
  } catch (e: any) {
    uni.showToast({ title: e.message || '生成失败', icon: 'none' })
  } finally {
    generating.value = false
  }
}

async function regenerateStoryboard() {
  await generateStoryboard()
}

async function handleApprove() {
  const pages = getCurrentPages()
  const page = pages[pages.length - 1] as any
  const shotId = Number(page.options?.shotId || 0)
  if (!shotId) return
  try {
    await videoApi.approveShotStoryboard(shotId)
    uni.showToast({ title: '已同意', icon: 'success' })
  } catch (e: any) {
    uni.showToast({ title: e.message || '操作失败', icon: 'none' })
  }
}

async function handleReject() {
  const pages = getCurrentPages()
  const page = pages[pages.length - 1] as any
  const shotId = Number(page.options?.shotId || 0)
  if (!shotId) return
  try {
    await videoApi.rejectShotStoryboard(shotId)
    uni.showToast({ title: '已拒绝', icon: 'success' })
  } catch (e: any) {
    uni.showToast({ title: e.message || '操作失败', icon: 'none' })
  }
}

async function handleReanalyzePrompt() {
  const pages = getCurrentPages()
  const page = pages[pages.length - 1] as any
  const shotId = Number(page.options?.shotId || 0)
  const workflowId = Number(page.options?.workflowId || 0)
  if (!shotId || !workflowId) {
    uni.showToast({ title: '缺少镜头或工作流参数', icon: 'none' })
    return
  }
  reanalyzingPrompt.value = true
  try {
    await videoApi.reanalyzeChapterWorkflowStoryboardPrompt(workflowId, { shot_ids: [shotId] })
    uni.showToast({ title: '提示词分析已提交', icon: 'success' })
    // 刷新镜头数据
    await loadShot(shotId, workflowId)
  } catch (e: any) {
    uni.showToast({ title: e.message || '分析提示词失败', icon: 'none' })
  } finally {
    reanalyzingPrompt.value = false
  }
}

function goToRender() {
  const pages = getCurrentPages()
  const page = pages[pages.length - 1] as any
  const shotId = page.options?.shotId || 0
  uni.navigateTo({ url: `/pages/workspace/render-jobs?shotId=${shotId}` })
}

onMounted(() => {
  const pages = getCurrentPages()
  const page = pages[pages.length - 1] as any
  const shotId = Number(page.options?.shotId || 0)
  const workflowId = Number(page.options?.workflowId || 0)
  if (!shotId) {
    uni.showToast({ title: '参数错误', icon: 'none' })
    return
  }
  loadShot(shotId, workflowId || undefined)
})
</script>

<style lang="scss" scoped>
.storyboard {
  min-height: 100vh;
  background: linear-gradient(180deg, $lv-bg-start 0%, $lv-bg-end 100%);

  &__content {
    padding: calc(var(--status-bar-height) + 88rpx + $lv-page-padding) $lv-page-padding $lv-page-padding;
  }

  &__loading {
    display: flex;
    justify-content: center;
    padding: 80rpx 0;
  }

  &__header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 20rpx;
  }

  &__shot-title {
    font-size: $lv-font-lg;
    font-weight: 600;
    color: $lv-text-primary;
  }

  &__shot-status {
    font-size: $lv-font-sm;
    color: $lv-text-muted;
    padding: 4rpx 16rpx;
    background: $lv-primary-light;
    border-radius: $lv-radius-full;
  }

  &__card {
    background: $lv-surface-solid;
    border-radius: 24rpx;
    overflow: hidden;
    margin-bottom: 20rpx;
  }

  &__image {
    width: 100%;
    display: block;
  }

  &__empty-image {
    padding: 60rpx 0;
    display: flex;
    justify-content: center;
  }

  &__info {
    padding: 24rpx;
  }

  &__info-row {
    display: flex;
    gap: 16rpx;
    margin-bottom: 12rpx;
    &:last-child { margin-bottom: 0; }
  }

  &__info-label {
    font-size: $lv-font-sm;
    color: $lv-text-muted;
    flex-shrink: 0;
    min-width: 60rpx;
  }

  &__info-value {
    font-size: $lv-font-sm;
    color: $lv-text-primary;
    flex: 1;
    line-height: 1.5;
  }

  &__actions {
    display: flex;
    flex-direction: column;
    gap: 16rpx;
  }

  &__actions-row {
    display: flex;
    gap: 16rpx;
  }

  &__btn-reject {
    flex: 1;
  }

  &__btn-render {
    margin-top: 8rpx;
  }
}
</style>
