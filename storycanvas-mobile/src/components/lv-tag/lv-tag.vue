<template>
  <view :class="tagClasses">
    <text class="lv-tag__text">{{ text }}</text>
  </view>
</template>

<script setup lang="ts">
import { computed } from 'vue'

interface TagProps {
  text: string
  type?: 'primary' | 'success' | 'warning' | 'error' | 'default'
  size?: 'sm' | 'md'
  plain?: boolean
}

const props = withDefaults(defineProps<TagProps>(), {
  type: 'primary',
  size: 'sm',
  plain: false
})

const tagClasses = computed(() => [
  'lv-tag',
  `lv-tag--${props.type}`,
  `lv-tag--${props.size}`,
  {
    'lv-tag--plain': props.plain
  }
])
</script>

<style lang="scss" scoped>
.lv-tag {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: $lv-radius-full;

  &--primary {
    background: $lv-primary-light;
    color: $lv-primary;
    border: 1rpx solid rgba(37, 99, 235, 0.2);
  }

  &--success {
    background: $lv-success-bg;
    color: $lv-success;
    border: 1rpx solid rgba(21, 128, 61, 0.2);
  }

  &--warning {
    background: $lv-warning-bg;
    color: $lv-warning;
    border: 1rpx solid rgba(217, 119, 6, 0.2);
  }

  &--error {
    background: $lv-error-bg;
    color: $lv-error;
    border: 1rpx solid rgba(190, 18, 60, 0.2);
  }

  &--default {
    background: $lv-primary-lighter;
    color: $lv-text-secondary;
    border: 1rpx solid $lv-border;
  }

  &--sm {
    padding: 4rpx 16rpx;
    font-size: $lv-font-xs;
  }

  &--md {
    padding: 8rpx 24rpx;
    font-size: $lv-font-sm;
  }

  &--plain {
    background: transparent;
    border: 1rpx solid currentColor;
  }

  &__text {
    font-weight: 500;
  }
}
</style>
