<template>
  <view class="shot-list-page">
    <lv-navbar title="镜头列表" show-back />

    <view class="shot-list-page__header">
      <text class="shot-list-page__header-title">{{ pageTitle }}</text>
      <lv-button size="sm" @tap="handleGenerate" :loading="generating">生成镜头</lv-button>
    </view>

    <scroll-view scroll-y class="shot-list-page__scroll">
      <view class="shot-list-page__content">
        <lv-loading v-if="loading" />

        <lv-empty v-else-if="shots.length === 0" title="暂无镜头" description="点击生成镜头" />

        <view
          v-for="shot in shots"
          :key="shot.id"
          class="shot-list-page__shot-card"
          @tap="goToStoryboard(shot.id)"
        >
          <view class="shot-list-page__shot-header">
            <text class="shot-list-page__shot-number">镜头 #{{ shot.shot_number }}</text>
            <text class="shot-list-page__shot-title">{{ shot.title }}</text>
          </view>

          <view class="shot-list-page__shot-meta">
            <text v-if="shot.shot_type" class="shot-list-page__shot-tag">{{ shot.shot_type }}</text>
            <text v-if="shot.camera_angle" class="shot-list-page__shot-tag">{{ shot.camera_angle }}</text>
            <text v-if="shot.camera_movement" class="shot-list-page__shot-tag">{{ shot.camera_movement }}</text>
            <text v-if="shot.duration_seconds" class="shot-list-page__shot-tag">{{ shot.duration_seconds }}s</text>
          </view>

          <text v-if="shot.action_description" class="shot-list-page__shot-desc">{{ shot.action_description }}</text>

          <view class="shot-list-page__shot-footer">
            <text class="shot-list-page__shot-status" :class="`shot-list-page__shot-status--${shot.status}`">
              {{ shotStatusLabel(shot.status) }}
            </text>
            <text class="shot-list-page__shot-tap-hint">点击查看详情</text>
          </view>
        </view>
      </view>
    </scroll-view>
  </view>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { videoApi } from '@/api'
import type { VideoShot } from '@/api/types'
import LvNavbar from '@/components/lv-navbar/lv-navbar.vue'
import LvButton from '@/components/lv-button/lv-button.vue'
import LvLoading from '@/components/lv-loading/lv-loading.vue'
import LvEmpty from '@/components/lv-empty/lv-empty.vue'

const sceneId = ref(0)
const chapterId = ref(0)
const loading = ref(false)
const generating = ref(false)
const shots = ref<VideoShot[]>([])
const pageTitle = ref('镜头列表')

onLoad((options) => {
  sceneId.value = Number(options?.sceneId || 0)
  chapterId.value = Number(options?.chapterId || 0)
  if (sceneId.value) loadShots()
})

async function loadShots() {
  loading.value = true
  try {
    const data = await videoApi.listSceneShots(sceneId.value)
    shots.value = data.shots
  } catch (e: any) {
    uni.showToast({ title: e.message || '加载失败', icon: 'none' })
  } finally {
    loading.value = false
  }
}

async function handleGenerate() {
  generating.value = true
  try {
    const data = await videoApi.generateSceneShots(sceneId.value, { regenerate: true })
    shots.value = data.shots
    uni.showToast({ title: '镜头生成成功', icon: 'success' })
  } catch (e: any) {
    uni.showToast({ title: e.message || '生成失败', icon: 'none' })
  } finally {
    generating.value = false
  }
}

function shotStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    pending: '待处理',
    generating: '生成中',
    completed: '已完成',
    failed: '失败',
  }
  return labels[status] || status
}

function goToStoryboard(shotId: number) {
  uni.navigateTo({
    url: `/pages/workspace/storyboard?shotId=${shotId}&sceneId=${sceneId.value}&chapterId=${chapterId.value}`
  })
}
</script>

<style lang="scss" scoped>
.shot-list-page {
  min-height: 100vh;
  background: linear-gradient(180deg, $lv-bg-start 0%, $lv-bg-end 100%);

  &__header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: $lv-page-padding;
    padding-top: calc(var(--status-bar-height) + 88rpx + $lv-page-padding);
  }

  &__header-title {
    font-size: $lv-font-lg;
    font-weight: 600;
    color: $lv-text-primary;
    flex: 1;
    margin-right: 16rpx;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  &__scroll {
    flex: 1;
    overflow: hidden;
  }

  &__content {
    padding: 0 $lv-page-padding $lv-page-padding;
  }

  &__shot-card {
    background: $lv-surface-solid;
    border-radius: $lv-radius-md;
    padding: 20rpx;
    margin-bottom: 16rpx;
    &:active { opacity: 0.8; }
  }

  &__shot-header {
    display: flex;
    align-items: center;
    gap: 12rpx;
    margin-bottom: 8rpx;
  }

  &__shot-number {
    font-size: $lv-font-sm;
    font-weight: 700;
    color: $lv-primary;
    flex-shrink: 0;
  }

  &__shot-title {
    font-size: $lv-font-base;
    font-weight: 600;
    color: $lv-text-primary;
  }

  &__shot-meta {
    display: flex;
    flex-wrap: wrap;
    gap: 8rpx;
    margin-bottom: 8rpx;
  }

  &__shot-tag {
    font-size: 20rpx;
    color: $lv-text-secondary;
    background: $lv-bg-start;
    padding: 4rpx 12rpx;
    border-radius: $lv-radius-full;
  }

  &__shot-desc {
    display: block;
    font-size: $lv-font-sm;
    color: $lv-text-secondary;
    line-height: 1.6;
    margin-bottom: 12rpx;
    overflow: hidden;
    text-overflow: ellipsis;
    display: -webkit-box;
    -webkit-line-clamp: 3;
    -webkit-box-orient: vertical;
  }

  &__shot-footer {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }

  &__shot-status {
    font-size: 20rpx;
    padding: 4rpx 12rpx;
    border-radius: $lv-radius-full;
    &--pending {
      color: #92400e;
      background: #fef3c7;
    }
    &--generating {
      color: #1e40af;
      background: #dbeafe;
    }
    &--completed {
      color: #15803d;
      background: #dcfce7;
    }
    &--failed {
      color: #991b1b;
      background: #fee2e2;
    }
  }

  &__shot-tap-hint {
    font-size: 20rpx;
    color: $lv-text-muted;
  }
}
</style>
