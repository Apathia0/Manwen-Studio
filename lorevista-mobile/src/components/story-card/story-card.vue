<template>
  <view class="story-card" @tap="handleTap" @longpress="handleLongPress">
    <view class="story-card__cover" @tap.stop="handleCoverTap">
      <image
        v-if="story.cover_image"
        :src="coverUrl"
        class="story-card__cover-image"
        mode="aspectFill"
      />
      <view v-else class="story-card__cover-placeholder">
        <BookOpen :size="32" />
      </view>
    </view>
    <view class="story-card__info">
      <text class="story-card__title">{{ story.title }}</text>
      <text v-if="story.description" class="story-card__description">
        {{ story.description }}
      </text>
      <view class="story-card__meta">
        <text v-if="story.chapter_count != null" class="story-card__chapters">{{ story.chapter_count }}章</text>
        <text class="story-card__date">{{ formatDate(story.created_at) }}</text>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { Story } from '@/api/types'
import { coverImageUrl } from '@/utils/url'
import { BookOpen } from '@lucide/vue'

interface StoryCardProps {
  story: Story
}

const props = defineProps<StoryCardProps>()

const emit = defineEmits<{
  (e: 'select', story: Story): void
  (e: 'longpress', story: Story): void
  (e: 'cover-click', story: Story): void
}>()

const coverUrl = computed(() => {
  return coverImageUrl(props.story.cover_image) || ''
})

function formatDate(dateStr: string): string {
  const date = new Date(dateStr)
  const month = date.getMonth() + 1
  const day = date.getDate()
  return `${month}月${day}日`
}

function handleTap() {
  emit('select', props.story)
}

function handleLongPress() {
  emit('longpress', props.story)
}

function handleCoverTap() {
  emit('cover-click', props.story)
}
</script>

<style lang="scss" scoped>
.story-card {
  display: flex;
  padding: $lv-card-padding;
  background: $lv-surface-solid;
  border: 1rpx solid $lv-border;
  border-radius: $lv-radius-md;
  box-shadow: $lv-shadow-sm;

  &:active {
    transform: scale(0.98);
    opacity: 0.9;
    transition: transform 0.1s ease, opacity 0.1s ease;
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
  }

  &__info {
    flex: 1;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    min-width: 0;
  }

  &__title {
    font-size: $lv-font-lg;
    font-weight: 600;
    color: $lv-text-primary;
    @include text-ellipsis;
    margin-bottom: 8rpx;
  }

  &__description {
    font-size: $lv-font-sm;
    color: $lv-text-secondary;
    @include text-ellipsis(2);
    margin-bottom: 12rpx;
  }

  &__meta {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }

  &__chapters {
    font-size: $lv-font-xs;
    color: $lv-primary;
    background: $lv-primary-light;
    padding: 4rpx 12rpx;
    border-radius: $lv-radius-full;
  }

  &__date {
    font-size: $lv-font-xs;
    color: $lv-text-muted;
  }
}
</style>
