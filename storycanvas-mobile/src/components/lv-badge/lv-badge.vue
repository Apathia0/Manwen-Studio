<template>
  <view class="lv-badge-wrapper">
    <slot />
    <view v-if="showBadge" :class="badgeClasses">
      <text class="lv-badge__text">{{ displayText }}</text>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed } from 'vue'

interface BadgeProps {
  value?: number | string
  type?: 'primary' | 'success' | 'warning' | 'error'
  show?: boolean
}

const props = withDefaults(defineProps<BadgeProps>(), {
  value: '',
  type: 'error',
  show: true
})

const showBadge = computed(() => {
  if (!props.show) return false
  if (typeof props.value === 'number') {
    return props.value > 0
  }
  return !!props.value
})

const displayText = computed(() => {
  if (typeof props.value === 'number') {
    return props.value > 99 ? '99+' : String(props.value)
  }
  return String(props.value)
})

const badgeClasses = computed(() => [
  'lv-badge',
  `lv-badge--${props.type}`
])
</script>

<style lang="scss" scoped>
.lv-badge-wrapper {
  position: relative;
  display: inline-block;
}

.lv-badge {
  position: absolute;
  top: -8rpx;
  right: -8rpx;
  min-width: 32rpx;
  height: 32rpx;
  padding: 0 10rpx;
  border-radius: 32rpx;
  @include flex-center;

  &--primary {
    background: $lv-primary;
    color: $lv-text-on-primary;
  }

  &--success {
    background: $lv-success;
    color: $lv-text-on-primary;
  }

  &--warning {
    background: $lv-warning;
    color: $lv-text-on-primary;
  }

  &--error {
    background: $lv-error;
    color: $lv-text-on-primary;
  }

  &__text {
    font-size: 20rpx;
    font-weight: 600;
    line-height: 1;
  }
}
</style>
