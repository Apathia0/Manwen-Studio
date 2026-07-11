<template>
  <view class="bible-summary">
    <view class="bible-summary__header" @tap="toggleExpanded">
      <view class="bible-summary__header-left">
        <lv-icon name="BookOpen" :size="16" color="#2563eb" />
        <text class="bible-summary__title">作品圣经摘要</text>
      </view>
      <view class="bible-summary__header-right">
        <lv-icon :name="expanded ? 'ChevronUp' : 'ChevronDown'" :size="14" color="#94a3b8" />
      </view>
    </view>
    <view v-if="expanded" class="bible-summary__content">
      <view v-for="item in visibleItems" :key="item.label" class="bible-summary__item">
        <text class="bible-summary__label">{{ item.label }}</text>
        <text class="bible-summary__value">{{ item.value }}</text>
      </view>
      <text v-if="visibleItems.length === 0" class="bible-summary__empty">摘要字段暂未生成，可打开完整圣经查看或补充。</text>

      <!-- 编辑按钮 -->
      <view v-if="editable" class="bible-summary__edit" @tap="$emit('edit')">
        <lv-icon name="Pencil" :size="12" color="#2563eb" />
        <text class="bible-summary__edit-text">编辑</text>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
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
const summary = computed(() => props.bible?.creative_brief || props.bible || {})
const visibleItems = computed(() => {
  const source = summary.value
  const items = [
    ['一句话梗概', source.one_line_premise],
    ['项目定位', source.project_positioning || source.positioning],
    ['题材方向', source.genre || source.style],
    ['目标受众', source.audience],
    ['整体基调', source.tone],
    ['核心卖点', source.core_hook || source.selling_point || source.sellingPoint || source.hook],
    ['主角核心', source.protagonist_core],
    ['主线矛盾', source.main_conflict],
    ['长线悬念', source.longline_mystery || source.long_hook || source.longline],
    ['目标篇幅', source.serial_length_target || source.target_word_count],
    ['节奏策略', source.pacing_strategy],
  ]
  return items.filter((item): item is [string, string] => Boolean(item[1]))
    .map(([label, value]) => ({ label, value: String(value) }))
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

  &__empty {
    display: block;
    padding: 20rpx 0;
    color: $lv-text-muted;
    font-size: $lv-font-sm;
    line-height: 1.6;
  }
}
</style>
