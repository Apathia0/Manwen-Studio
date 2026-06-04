<template>
  <button
    :class="buttonClasses"
    :disabled="disabled || loading"
    @tap="handleTap"
  >
    <view v-if="loading" class="lv-button__loading">
      <view class="lv-button__loading-icon" />
    </view>
    <view class="lv-button__content">
      <slot />
    </view>
  </button>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { defaultButtonProps } from './props'
import type { ButtonProps } from './props'

const props = withDefaults(defineProps<ButtonProps>(), defaultButtonProps)

const emit = defineEmits<{
  (e: 'tap', event: Event): void
}>()

const buttonClasses = computed(() => [
  'lv-button',
  `lv-button--${props.type}`,
  `lv-button--${props.size}`,
  {
    'lv-button--block': props.block,
    'lv-button--loading': props.loading,
    'lv-button--disabled': props.disabled
  }
])

function handleTap(event: Event) {
  if (!props.disabled && !props.loading) {
    emit('tap', event)
  }
}
</script>

<style lang="scss" scoped>
.lv-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: none;
  outline: none;
  font-weight: 500;
  transition: all 0.2s ease;

  &--primary {
    background: linear-gradient(135deg, $lv-primary 0%, $lv-primary-dark 100%);
    color: $lv-text-on-primary;
    box-shadow: $lv-shadow-md;

    &:active:not(:disabled) {
      transform: scale(0.98);
      opacity: 0.9;
    }
  }

  &--secondary {
    background: #ffffff;
    color: $lv-text-primary;
    border: 1rpx solid $lv-border;

    &:active:not(:disabled) {
      background: $lv-primary-lighter;
    }
  }

  &--text {
    background: transparent;
    color: $lv-primary;
    padding: 0;

    &:active:not(:disabled) {
      opacity: 0.7;
    }
  }

  &--danger {
    background: $lv-error;
    color: $lv-text-on-primary;

    &:active:not(:disabled) {
      opacity: 0.9;
    }
  }

  &--sm {
    height: 64rpx;
    padding: 0 24rpx;
    font-size: $lv-font-sm;
    border-radius: $lv-radius-xl;
  }

  &--md {
    height: 88rpx;
    padding: 0 32rpx;
    font-size: $lv-font-base;
    border-radius: $lv-radius-full;
  }

  &--lg {
    height: 96rpx;
    padding: 0 40rpx;
    font-size: $lv-font-md;
    border-radius: $lv-radius-full;
  }

  &--block {
    width: 100%;
  }

  &--loading {
    opacity: 0.7;
  }

  &--disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  &__loading {
    margin-right: 12rpx;
  }

  &__loading-icon {
    width: 32rpx;
    height: 32rpx;
    border: 4rpx solid transparent;
    border-top-color: currentColor;
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
  }

  &__icon {
    margin-right: 12rpx;
  }

  &__content {
    display: flex;
    align-items: center;
    justify-content: center;
  }
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
