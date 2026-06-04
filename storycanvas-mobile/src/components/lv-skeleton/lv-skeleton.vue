<template>
  <view :class="skeletonClasses">
    <view v-if="avatar" class="lv-skeleton__avatar" />
    <view class="lv-skeleton__content">
      <view v-for="i in rows" :key="i" class="lv-skeleton__row" :style="{ width: getRowWidth(i) }" />
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed } from 'vue'

interface SkeletonProps {
  avatar?: boolean
  rows?: number
  animate?: boolean
  rowWidth?: string | number
}

const props = withDefaults(defineProps<SkeletonProps>(), {
  avatar: false,
  rows: 3,
  animate: true,
  rowWidth: '100%'
})

const skeletonClasses = computed(() => [
  'lv-skeleton',
  {
    'lv-skeleton--animate': props.animate
  }
])

function getRowWidth(index: number): string {
  if (index === props.rows) {
    return '70%'
  }
  return typeof props.rowWidth === 'number' ? `${props.rowWidth}%` : props.rowWidth
}
</script>

<style lang="scss" scoped>
.lv-skeleton {
  display: flex;
  padding: $lv-card-padding;

  &--animate {
    .lv-skeleton__avatar,
    .lv-skeleton__row {
      animation: skeleton-pulse 1.5s ease-in-out infinite;
    }
  }

  &__avatar {
    width: 96rpx;
    height: 96rpx;
    border-radius: $lv-radius-md;
    background: $lv-border-light;
    margin-right: 24rpx;
    flex-shrink: 0;
  }

  &__content {
    flex: 1;
  }

  &__row {
    height: 28rpx;
    background: $lv-border-light;
    border-radius: $lv-radius-sm;
    margin-bottom: 16rpx;

    &:last-child {
      margin-bottom: 0;
    }
  }
}

@keyframes skeleton-pulse {
  0% {
    opacity: 1;
  }
  50% {
    opacity: 0.5;
  }
  100% {
    opacity: 1;
  }
}
</style>
