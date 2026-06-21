<template>
  <view class="screenplay-page">
    <lv-navbar title="视频剧本" show-back />

    <view class="screenplay-page__header">
      <text class="screenplay-page__header-title">{{ pageTitle }}</text>
      <lv-button size="sm" @tap="handleGenerate" :loading="generating">生成剧本</lv-button>
    </view>

    <scroll-view scroll-y class="screenplay-page__scroll">
      <view class="screenplay-page__content">
        <lv-loading v-if="loading" />

        <template v-else-if="screenplay">
          <view class="screenplay-page__section">
            <text class="screenplay-page__section-title">剧本正文</text>
            <view class="screenplay-page__text">
              <text>{{ screenplay }}</text>
            </view>
          </view>
        </template>

        <view class="screenplay-page__section">
          <text class="screenplay-page__section-title">场景列表（{{ scenes.length }}）</text>

          <lv-empty v-if="!loading && scenes.length === 0" title="暂无场景" description="点击生成剧本" />

          <view v-for="scene in scenes" :key="scene.id" class="screenplay-page__scene-card" @tap="goToShots(scene.id)">
            <view class="screenplay-page__scene-header">
              <text class="screenplay-page__scene-number">#{{ scene.scene_number }}</text>
              <text class="screenplay-page__scene-title">{{ scene.title }}</text>
            </view>
            <view class="screenplay-page__scene-meta">
              <text v-if="scene.characters && scene.characters.length > 0" class="screenplay-page__scene-characters">
                角色：{{ scene.characters.join('、') }}
              </text>
              <text v-if="scene.location" class="screenplay-page__scene-location">
                地点：{{ scene.location }}
              </text>
            </view>
            <text class="screenplay-page__scene-summary">{{ scene.summary }}</text>
            <view class="screenplay-page__scene-footer">
              <lv-button size="sm">生成镜头</lv-button>
            </view>
          </view>
        </view>
      </view>
    </scroll-view>
  </view>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { videoApi } from '@/api'
import type { ScriptScene } from '@/api/types'
import LvNavbar from '@/components/lv-navbar/lv-navbar.vue'
import LvButton from '@/components/lv-button/lv-button.vue'
import LvLoading from '@/components/lv-loading/lv-loading.vue'
import LvEmpty from '@/components/lv-empty/lv-empty.vue'

const chapterId = ref(0)
const loading = ref(false)
const generating = ref(false)
const screenplay = ref('')
const scenes = ref<ScriptScene[]>([])
const pageTitle = ref('视频剧本')

onLoad((options) => {
  chapterId.value = Number(options?.chapterId || 0)
  if (chapterId.value) loadScreenplay()
})

async function loadScreenplay() {
  loading.value = true
  try {
    const data = await videoApi.listScreenplayScenes(chapterId.value)
    screenplay.value = data.screenplay
    scenes.value = data.scenes
  } catch (e: any) {
    uni.showToast({ title: e.message || '加载失败', icon: 'none' })
  } finally {
    loading.value = false
  }
}

async function handleGenerate() {
  generating.value = true
  try {
    const data = await videoApi.generateScreenplay(chapterId.value, { regenerate: true })
    screenplay.value = data.screenplay
    scenes.value = data.scenes
    uni.showToast({ title: '剧本生成成功', icon: 'success' })
  } catch (e: any) {
    uni.showToast({ title: e.message || '生成失败', icon: 'none' })
  } finally {
    generating.value = false
  }
}

function goToShots(sceneId: number) {
  uni.navigateTo({
    url: `/pages/workspace/shot-list?sceneId=${sceneId}&chapterId=${chapterId.value}`
  })
}
</script>

<style lang="scss" scoped>
.screenplay-page {
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

  &__section {
    margin-bottom: 24rpx;
  }

  &__section-title {
    display: block;
    font-size: $lv-font-base;
    font-weight: 600;
    color: $lv-text-primary;
    margin-bottom: 16rpx;
  }

  &__text {
    background: $lv-surface-solid;
    border-radius: $lv-radius-md;
    padding: 24rpx;
    font-size: $lv-font-sm;
    color: $lv-text-primary;
    line-height: 1.8;
    white-space: pre-wrap;
    max-height: 500rpx;
    overflow-y: auto;
  }

  &__scene-card {
    background: $lv-surface-solid;
    border-radius: $lv-radius-md;
    padding: 20rpx;
    margin-bottom: 16rpx;
    &:active { opacity: 0.8; }
  }

  &__scene-header {
    display: flex;
    align-items: center;
    gap: 12rpx;
    margin-bottom: 8rpx;
  }

  &__scene-number {
    font-size: $lv-font-sm;
    font-weight: 700;
    color: $lv-primary;
  }

  &__scene-title {
    font-size: $lv-font-base;
    font-weight: 600;
    color: $lv-text-primary;
  }

  &__scene-meta {
    display: flex;
    flex-wrap: wrap;
    gap: 12rpx;
    margin-bottom: 8rpx;
  }

  &__scene-characters,
  &__scene-location {
    font-size: 20rpx;
    color: $lv-text-secondary;
    background: $lv-bg-start;
    padding: 4rpx 12rpx;
    border-radius: $lv-radius-full;
  }

  &__scene-summary {
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

  &__scene-footer {
    display: flex;
    justify-content: flex-end;
  }
}
</style>
