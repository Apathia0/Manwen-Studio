<template>
  <view class="framework-section">
    <view class="framework-section__header" @tap="toggleExpanded">
      <view class="framework-section__title-wrapper">
        <component :is="iconComponent" :size="16" color="#64748b" class="framework-section__icon" />
        <text class="framework-section__title">{{ title }}</text>
      </view>
      <view class="framework-section__right">
        <text v-if="count !== undefined" class="framework-section__count">{{ count }}</text>
        <ChevronUp v-if="expanded" :size="14" color="#94a3b8" />
        <ChevronDown v-else :size="14" color="#94a3b8" />
      </view>
    </view>
    <view v-if="expanded" class="framework-section__content">
      <slot />
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { ChevronDown, ChevronUp, Film, ChevronRight, BookOpen, FileText, MessageSquare, Users, Tag, ListTree } from '@lucide/vue'

const iconMap: Record<string, any> = {
  'icon-film': Film,
  'icon-chevron-right': ChevronRight,
  'icon-book-open': BookOpen,
  'icon-file-text': FileText,
  'icon-message-square': MessageSquare,
  'icon-users': Users,
  'icon-tag': Tag,
  'icon-list-tree': ListTree
}

interface FrameworkSectionProps {
  title: string
  icon?: string
  count?: number
  defaultExpanded?: boolean
}

const props = withDefaults(defineProps<FrameworkSectionProps>(), {
  icon: 'icon-chevron-right',
  defaultExpanded: false
})

const expanded = ref(props.defaultExpanded)

const iconComponent = computed(() => {
  return iconMap[props.icon] || ChevronRight
})

function toggleExpanded() {
  expanded.value = !expanded.value
}
</script>

<style lang="scss" scoped>
.framework-section {
  background: $lv-surface-solid;
  border: 1rpx solid $lv-border;
  border-radius: $lv-radius-md;
  overflow: hidden;
  margin-bottom: 16rpx;

  &__header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 24rpx;
    cursor: pointer;

    &:active {
      background: $lv-primary-lighter;
    }
  }

  &__title-wrapper {
    display: flex;
    align-items: center;
  }

  &__icon {
    margin-right: 0;
  }

  &__title {
    font-size: $lv-font-base;
    font-weight: 600;
    color: $lv-text-primary;
    margin-left: 12rpx;
  }

  &__right {
    display: flex;
    align-items: center;
  }

  &__count {
    font-size: $lv-font-sm;
    color: $lv-text-muted;
    margin-right: 12rpx;
  }

  &__content {
    padding: 0 24rpx 24rpx;
    border-top: 1rpx solid $lv-border-light;
  }
}
</style>
