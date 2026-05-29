<template>
  <view class="bible-summary">
    <view class="bible-summary__header" @tap="toggleExpanded">
      <text class="bible-summary__title">创意简报</text>
      <ChevronUp v-if="expanded" :size="14" color="#94a3b8" />
      <ChevronDown v-else :size="14" color="#94a3b8" />
    </view>
    <view v-if="expanded" class="bible-summary__content">
      <view v-if="bible.genre" class="bible-summary__item">
        <text class="bible-summary__label">题材</text>
        <text class="bible-summary__value">{{ bible.genre }}</text>
      </view>
      <view v-if="bible.style" class="bible-summary__item">
        <text class="bible-summary__label">风格</text>
        <text class="bible-summary__value">{{ bible.style }}</text>
      </view>
      <view v-if="bible.audience" class="bible-summary__item">
        <text class="bible-summary__label">受众</text>
        <text class="bible-summary__value">{{ bible.audience }}</text>
      </view>
      <view v-if="bible.sellingPoint" class="bible-summary__item">
        <text class="bible-summary__label">核心卖点</text>
        <text class="bible-summary__value">{{ bible.sellingPoint }}</text>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { ChevronUp, ChevronDown } from '@lucide/vue'

interface StoryBible {
  genre?: string
  style?: string
  audience?: string
  sellingPoint?: string
}

interface BibleSummaryProps {
  bible: StoryBible
  defaultExpanded?: boolean
}

const props = withDefaults(defineProps<BibleSummaryProps>(), {
  defaultExpanded: false
})

const expanded = ref(props.defaultExpanded)

function toggleExpanded() {
  expanded.value = !expanded.value
}
</script>

<style lang="scss" scoped>
.bible-summary {
  background: $lv-surface-solid;
  border: 1rpx solid $lv-border;
  border-radius: $lv-radius-md;
  overflow: hidden;

  &__header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: $lv-card-padding;
    cursor: pointer;

    &:active {
      background: $lv-primary-lighter;
    }
  }

  &__title {
    font-size: $lv-font-base;
    font-weight: 600;
    color: $lv-text-primary;
  }

  &__content {
    padding: 0 $lv-card-padding $lv-card-padding;
  }

  &__item {
    display: flex;
    justify-content: space-between;
    padding: 12rpx 0;
    border-bottom: 1rpx solid $lv-border-light;

    &:last-child {
      border-bottom: none;
    }
  }

  &__label {
    font-size: $lv-font-sm;
    color: $lv-text-muted;
    flex-shrink: 0;
  }

  &__value {
    font-size: $lv-font-sm;
    color: $lv-text-primary;
    text-align: right;
    flex: 1;
    margin-left: 16rpx;
  }
}
</style>
