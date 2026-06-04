<template>
  <view class="chapter-selector">
    <view class="chapter-selector__prev" @tap="handlePrev">
      <ChevronLeft :size="18" />
    </view>
    <view class="chapter-selector__info">
      <text class="chapter-selector__label">第 {{ chapterNumber }} 章</text>
      <text class="chapter-selector__title">{{ chapterTitle }}</text>
    </view>
    <view class="chapter-selector__next" @tap="handleNext">
      <ChevronRight :size="18" />
    </view>
  </view>
</template>

<script setup lang="ts">
import { ChevronLeft, ChevronRight } from '@lucide/vue'

interface ChapterSelectorProps {
  chapterNumber: number
  chapterTitle: string
  hasPrev?: boolean
  hasNext?: boolean
}

const props = withDefaults(defineProps<ChapterSelectorProps>(), {
  hasPrev: true,
  hasNext: true
})

const emit = defineEmits<{
  (e: 'prev'): void
  (e: 'next'): void
}>()

function handlePrev() {
  if (props.hasPrev) {
    emit('prev')
  }
}

function handleNext() {
  if (props.hasNext) {
    emit('next')
  }
}
</script>

<style lang="scss" scoped>
.chapter-selector {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 24rpx $lv-page-padding;
  background: $lv-surface-solid;
  border-top: 1rpx solid $lv-border-light;

  &__prev,
  &__next {
    width: 64rpx;
    height: 64rpx;
    border-radius: 50%;
    @include flex-center;
    background: $lv-primary-lighter;
    color: $lv-primary;

    &:active:not(:disabled) {
      background: $lv-primary-light;
    }

    &:disabled {
      opacity: 0.3;
      color: $lv-text-muted;
    }
  }

  &__info {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    margin: 0 16rpx;
  }

  &__label {
    font-size: $lv-font-xs;
    color: $lv-text-muted;
  }

  &__title {
    font-size: $lv-font-base;
    font-weight: 600;
    color: $lv-text-primary;
    @include text-ellipsis;
  }
}
</style>
