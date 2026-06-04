<template>
  <view class="story-detail">
    <lv-navbar title="故事详情" show-back />

    <view class="story-detail__content">
      <lv-loading v-if="loading" />

      <template v-else-if="story">
        <!-- 封面 -->
        <view class="story-detail__cover" @tap="goCoverEdit">
          <image
            v-if="coverUrl"
            :src="coverUrl"
            class="story-detail__cover-img"
            mode="aspectFill"
            lazy-load
          />
          <view v-else class="story-detail__cover-placeholder">
            <Image :size="40" color="#2563eb" />
            <text class="story-detail__cover-hint">点击设置封面</text>
          </view>
        </view>

        <!-- 基本信息 -->
        <view class="story-detail__info">
          <text class="story-detail__title">{{ story.title }}</text>
          <text v-if="story.description" class="story-detail__desc">{{ story.description }}</text>
        </view>

        <!-- 统计信息 -->
        <view class="story-detail__stats">
          <view v-if="story.chapter_count != null" class="story-detail__stat">
            <text class="story-detail__stat-value">{{ story.chapter_count }}</text>
            <text class="story-detail__stat-label">章节</text>
          </view>
          <view class="story-detail__stat">
            <text class="story-detail__stat-value">{{ formatDate(story.created_at, 'date') }}</text>
            <text class="story-detail__stat-label">创建日期</text>
          </view>
          <view class="story-detail__stat">
            <text class="story-detail__stat-value">{{ story.onboarding_completed ? '已完成' : '未完成' }}</text>
            <text class="story-detail__stat-label">引导状态</text>
          </view>
        </view>

        <!-- 操作按钮 -->
        <view class="story-detail__actions">
          <lv-button block @tap="goWorkspace">进入工作台</lv-button>
          <lv-button block secondary @tap="goOnboarding">
            <lv-icon name="Sparkles" :size="16" color="#2563eb" style="margin-right: 8rpx;" />
            引导创作
          </lv-button>
          <lv-button block secondary @tap="goCoverEdit">编辑封面</lv-button>
        </view>
      </template>

      <lv-empty v-else title="故事不存在" description="未找到该故事" />
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { useStoriesStore } from '@/stores/stories'
import { Image } from '@lucide/vue'
import { coverImageUrl } from '@/utils/url'
import { formatDate } from '@/utils/format'
import type { Story } from '@/api/types'
import LvNavbar from '@/components/lv-navbar/lv-navbar.vue'
import LvButton from '@/components/lv-button/lv-button.vue'
import LvLoading from '@/components/lv-loading/lv-loading.vue'
import LvEmpty from '@/components/lv-empty/lv-empty.vue'
import LvIcon from '@/components/lv-icon/lv-icon.vue'

const storyStore = useStoriesStore()
const loading = ref(true)
const story = ref<Story | null>(null)

const coverUrl = computed(() => {
  if (!story.value?.cover_image) return null
  return coverImageUrl(story.value.cover_image)
})

onLoad(async (options) => {
  const storyId = parseInt(options?.storyId || options?.id || String(storyStore.activeStoryId || '0'))

  if (storyId) {
    story.value = storyStore.list.find((s: Story) => s.id === storyId) || null

    if (!story.value) {
      try {
        const { storiesApi } = await import('@/api')
        story.value = await storiesApi.getStory(storyId)
      } catch (e) {
        console.error('加载故事失败:', e)
      }
    }
  }
  loading.value = false
})

function goWorkspace() {
  if (!story.value) return
  storyStore.setActiveStory(story.value.id)
  uni.navigateTo({ url: `/pages/workspace/chapter-view?storyId=${story.value.id}` })
}

function goOnboarding() {
  if (!story.value) return
  uni.navigateTo({ url: `/pages/story/onboarding?storyId=${story.value.id}` })
}

function goCoverEdit() {
  if (!story.value) return
  uni.navigateTo({ url: `/pages/story/cover-edit?storyId=${story.value.id}` })
}
</script>

<style lang="scss" scoped>
.story-detail {
  min-height: 100vh;
  background: linear-gradient(180deg, $lv-bg-start 0%, $lv-bg-end 100%);

  &__content {
    padding: calc(var(--status-bar-height) + 88rpx) $lv-page-padding $lv-page-padding;
  }

  &__cover {
    width: 100%;
    height: 400rpx;
    border-radius: $lv-radius-lg;
    overflow: hidden;
    margin-bottom: $lv-section-gap;
    background: $lv-primary-lighter;
  }

  &__cover-img {
    width: 100%;
    height: 100%;
  }

  &__cover-placeholder {
    width: 100%;
    height: 100%;
    @include flex-center;
    flex-direction: column;
    gap: 16rpx;

    // iconfont 已替换为 Lucide Image 组件
  }

  &__cover-hint {
    font-size: $lv-font-sm;
    color: $lv-text-muted;
  }

  &__info {
    margin-bottom: $lv-section-gap;
  }

  &__title {
    display: block;
    font-size: $lv-font-2xl;
    font-weight: 700;
    color: $lv-text-primary;
    margin-bottom: 12rpx;
  }

  &__desc {
    display: block;
    font-size: $lv-font-base;
    color: $lv-text-secondary;
    line-height: 1.6;
  }

  &__stats {
    display: flex;
    background: $lv-surface-solid;
    border-radius: $lv-radius-lg;
    padding: 32rpx;
    margin-bottom: $lv-section-gap;
    box-shadow: $lv-shadow-sm;
  }

  &__stat {
    flex: 1;
    text-align: center;
    border-right: 1rpx solid $lv-border-light;

    &:last-child {
      border-right: none;
    }
  }

  &__stat-value {
    display: block;
    font-size: $lv-font-lg;
    font-weight: 600;
    color: $lv-primary;
    margin-bottom: 8rpx;
  }

  &__stat-label {
    display: block;
    font-size: $lv-font-xs;
    color: $lv-text-muted;
  }

  &__actions {
    display: flex;
    flex-direction: column;
    gap: 16rpx;
  }
}
</style>
