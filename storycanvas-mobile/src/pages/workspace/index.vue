<template>
  <view class="workspace-page">
    <lv-navbar title="创作中心" />

    <view class="workspace-page__content">
      <view v-if="!storyStore.activeStory" class="workspace-page__empty">
        <lv-empty title="请选择故事" description="请先从作品列表选择一个故事">
          <template #action>
            <lv-button @tap="goStoryList">选择故事</lv-button>
          </template>
        </lv-empty>
      </view>

      <view v-else class="workspace-page__info">
        <lv-card>
          <view class="workspace-page__story">
            <view class="workspace-page__cover">
              <image
                v-if="storyStore.activeStory.cover_image"
                :src="coverUrl"
                class="workspace-page__cover-image"
                mode="aspectFill"
                lazy-load
              />
              <view v-else class="workspace-page__cover-placeholder">
                <BookOpen :size="32" color="#94a3b8" />
              </view>
            </view>
            <view class="workspace-page__details">
              <text class="workspace-page__title">{{ storyStore.activeStory.title }}</text>
              <text class="workspace-page__desc">{{ storyStore.activeStory.description || '暂无描述' }}</text>
              <text class="workspace-page__meta">{{ storyStore.activeStory.chapter_count ?? '' }}{{ storyStore.activeStory.chapter_count != null ? ' 章' : '' }}</text>
            </view>
          </view>
        </lv-card>

        <view class="workspace-page__actions">
          <lv-button block @tap="goWorkspace">进入工作台</lv-button>
          <lv-button block secondary @tap="goVideoWorkflow">
            <lv-icon name="Video" :size="16" color="#2563eb" style="margin-right: 8rpx;" />视频创作
          </lv-button>
          <!-- 导入上下文引导（优先级高于创作引导） -->
          <lv-button
            v-if="storyStore.activeStory.source_type === 'import' && !storyStore.activeStory.import_context_completed"
            secondary block
            @tap="goImportGuidance"
          >
            <lv-icon name="FileText" :size="16" color="#2563eb" style="margin-right: 8rpx;" />导入作品引导
          </lv-button>
          <!-- 创作引导 -->
          <lv-button v-if="!storyStore.activeStory.onboarding_completed" secondary block @tap="goOnboarding">
            <lv-icon name="Sparkles" :size="16" color="#2563eb" style="margin-right: 8rpx;" />引导创作
          </lv-button>
        </view>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useStoriesStore } from '@/stores/stories'
import { coverImageUrl } from '@/utils/url'
import LvNavbar from '@/components/lv-navbar/lv-navbar.vue'
import LvCard from '@/components/lv-card/lv-card.vue'
import LvEmpty from '@/components/lv-empty/lv-empty.vue'
import LvButton from '@/components/lv-button/lv-button.vue'
import LvIcon from '@/components/lv-icon/lv-icon.vue'
import { BookOpen } from '@lucide/vue'

const storyStore = useStoriesStore()

const coverUrl = computed(() => {
  return coverImageUrl(storyStore.activeStory?.cover_image ?? null) || ''
})

function goStoryList() {
  uni.switchTab({ url: '/pages/index/index' })
}

function goWorkspace() {
  if (!storyStore.activeStory) return
  const story = storyStore.activeStory
  // 先检查是否需要引导（与 Web 端 openWorkspace 逻辑对齐）
  if (story.source_type === 'import' && !story.import_context_completed) {
    uni.navigateTo({ url: `/pages/story/import-guidance?storyId=${story.id}` })
    return
  }
  if (!story.onboarding_completed) {
    uni.navigateTo({ url: `/pages/story/onboarding?storyId=${story.id}` })
    return
  }
  uni.navigateTo({ url: `/pages/workspace/chapter-view?storyId=${story.id}` })
}

function goVideoWorkflow() {
  if (storyStore.activeStory) {
    uni.navigateTo({ url: `/pages/workspace/chapter-view?storyId=${storyStore.activeStory.id}&tabIndex=3` })
  }
}

function goImportGuidance() {
  if (storyStore.activeStory) {
    uni.navigateTo({ url: `/pages/story/import-guidance?storyId=${storyStore.activeStory.id}` })
  }
}

function goOnboarding() {
  if (storyStore.activeStory) {
    uni.navigateTo({ url: `/pages/story/onboarding?storyId=${storyStore.activeStory.id}` })
  }
}
</script>

<style lang="scss" scoped>
.workspace-page {
  min-height: 100vh;
  background: linear-gradient(180deg, $lv-bg-start 0%, $lv-bg-end 100%);

  &__content {
    padding: calc(var(--status-bar-height) + 88rpx) $lv-page-padding $lv-page-padding;
  }

  &__empty {
    padding-top: 200rpx;
  }

  &__story {
    display: flex;
  }

  &__cover {
    width: 160rpx;
    height: 160rpx;
    border-radius: $lv-radius-sm;
    overflow: hidden;
    flex-shrink: 0;
    margin-right: 24rpx;
  }

  &__cover-image {
    width: 100%;
    height: 100%;
  }

  &__cover-placeholder {
    width: 100%;
    height: 100%;
    background: $lv-primary-lighter;
    @include flex-center;
    color: $lv-text-muted;
    font-size: 64rpx;
  }

  &__details {
    flex: 1;
    display: flex;
    flex-direction: column;
  }

  &__title {
    font-size: $lv-font-lg;
    font-weight: 600;
    color: $lv-text-primary;
    margin-bottom: 8rpx;
  }

  &__desc {
    font-size: $lv-font-sm;
    color: $lv-text-secondary;
    @include text-ellipsis(2);
    margin-bottom: 12rpx;
  }

  &__meta {
    font-size: $lv-font-xs;
    color: $lv-text-muted;
  }

  &__actions {
    margin-top: $lv-section-gap;
    display: flex;
    flex-direction: column;
    gap: $lv-item-gap;
  }
}
</style>
