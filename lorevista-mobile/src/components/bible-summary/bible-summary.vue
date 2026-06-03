<template>
  <view class="bible-summary">
    <view class="bible-summary__header" @tap="toggleExpanded">
      <view class="bible-summary__header-left">
        <lv-icon name="BookOpen" :size="16" color="#2563eb" />
        <text class="bible-summary__title">创意简报</text>
      </view>
      <view class="bible-summary__header-right">
        <lv-icon :name="expanded ? 'ChevronUp' : 'ChevronDown'" :size="14" color="#94a3b8" />
      </view>
    </view>
    <view v-if="expanded" class="bible-summary__content">
      <!-- 核心信息 -->
      <view v-if="bible.one_line_premise" class="bible-summary__item">
        <text class="bible-summary__label">一句话梗概</text>
        <text class="bible-summary__value">{{ bible.one_line_premise }}</text>
      </view>
      <view v-if="bible.genre" class="bible-summary__item">
        <text class="bible-summary__label">题材方向</text>
        <text class="bible-summary__value">{{ bible.genre }}</text>
      </view>
      <view v-if="bible.selling_point" class="bible-summary__item">
        <text class="bible-summary__label">核心卖点</text>
        <text class="bible-summary__value">{{ bible.selling_point }}</text>
      </view>
      <view v-if="bible.main_conflict" class="bible-summary__item">
        <text class="bible-summary__label">主线矛盾</text>
        <text class="bible-summary__value">{{ bible.main_conflict }}</text>
      </view>
      <view v-if="bible.long_hook" class="bible-summary__item">
        <text class="bible-summary__label">长线悬念</text>
        <text class="bible-summary__value">{{ bible.long_hook }}</text>
      </view>
      <view v-if="bible.target_word_count" class="bible-summary__item">
        <text class="bible-summary__label">目标篇幅</text>
        <text class="bible-summary__value">{{ bible.target_word_count }}</text>
      </view>
      <view v-if="bible.pacing_strategy" class="bible-summary__item">
        <text class="bible-summary__label">节奏策略</text>
        <text class="bible-summary__value">{{ bible.pacing_strategy }}</text>
      </view>
      <view v-if="bible.protagonist_core" class="bible-summary__item">
        <text class="bible-summary__label">主角核心</text>
        <text class="bible-summary__value">{{ bible.protagonist_core }}</text>
      </view>
      <!-- 兼容旧字段 -->
      <view v-if="bible.style && !bible.genre" class="bible-summary__item">
        <text class="bible-summary__label">风格</text>
        <text class="bible-summary__value">{{ bible.style }}</text>
      </view>
      <view v-if="bible.audience" class="bible-summary__item">
        <text class="bible-summary__label">受众</text>
        <text class="bible-summary__value">{{ bible.audience }}</text>
      </view>
      <view v-if="bible.sellingPoint && !bible.selling_point" class="bible-summary__item">
        <text class="bible-summary__label">核心卖点</text>
        <text class="bible-summary__value">{{ bible.sellingPoint }}</text>
      </view>

      <!-- 编辑按钮 -->
      <view v-if="editable" class="bible-summary__edit" @tap="$emit('edit')">
        <lv-icon name="Pencil" :size="12" color="#2563eb" />
        <text class="bible-summary__edit-text">编辑</text>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import LvIcon from '@/components/lv-icon/lv-icon.vue'

interface StoryBible {
  one_line_premise?: string
  genre?: string
  style?: string
  audience?: string
  selling_point?: string
  sellingPoint?: string
  main_conflict?: string
  long_hook?: string
  target_word_count?: string
  pacing_strategy?: string
  protagonist_core?: string
  [key: string]: any
}

interface BibleSummaryProps {
  bible: StoryBible
  defaultExpanded?: boolean
  editable?: boolean
}

const props = withDefaults(defineProps<BibleSummaryProps>(), {
  defaultExpanded: false,
  editable: false,
})

defineEmits<{
  edit: []
}>()

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
  margin-bottom: 24rpx;

  &__header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 24rpx 32rpx;
    cursor: pointer;

    &:active {
      background: $lv-primary-lighter;
    }
  }

  &__header-left {
    display: flex;
    align-items: center;
    gap: 12rpx;
  }

  &__header-right {
    display: flex;
    align-items: center;
  }

  &__title {
    font-size: $lv-font-base;
    font-weight: 600;
    color: $lv-text-primary;
  }

  &__content {
    padding: 0 32rpx 24rpx;
  }

  &__item {
    display: flex;
    flex-direction: column;
    padding: 16rpx 0;
    border-bottom: 1rpx solid $lv-border-light;

    &:last-child {
      border-bottom: none;
    }
  }

  &__label {
    font-size: $lv-font-xs;
    color: $lv-text-muted;
    margin-bottom: 8rpx;
  }

  &__value {
    font-size: $lv-font-sm;
    color: $lv-text-primary;
    line-height: 1.5;
  }

  &__edit {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8rpx;
    padding: 16rpx;
    margin-top: 12rpx;
    border-top: 1rpx solid $lv-border-light;

    &:active {
      background: $lv-primary-lighter;
    }
  }

  &__edit-text {
    font-size: $lv-font-xs;
    color: $lv-primary;
  }
}
</style>
