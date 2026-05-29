<template>
  <view class="lv-toast-container">
    <view
      v-for="toast in toasts"
      :key="toast.id"
      :class="['lv-toast', `lv-toast--${toast.type}`]"
    >
      <view class="lv-toast__icon">
        <CheckCircle v-if="toast.type === 'success'" :size="20" />
        <XCircle v-else-if="toast.type === 'error'" :size="20" />
        <AlertCircle v-else-if="toast.type === 'warning'" :size="20" />
        <Info v-else :size="20" />
      </view>
      <text class="lv-toast__message">{{ toast.message }}</text>
    </view>
  </view>
</template>

<script setup lang="ts">
import { useUiStore } from '@/stores/ui'
import { CheckCircle, XCircle, AlertCircle, Info } from '@lucide/vue'

const uiStore = useUiStore()

const toasts = uiStore.toasts
</script>

<style lang="scss" scoped>
.lv-toast-container {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  z-index: 9999;
  padding: 100rpx $lv-page-padding 0;
  pointer-events: none;
}

.lv-toast {
  display: flex;
  align-items: center;
  padding: 24rpx 32rpx;
  margin-bottom: 16rpx;
  border-radius: $lv-radius-md;
  box-shadow: $lv-shadow-lg;
  pointer-events: auto;
  animation: toast-slide-in 0.3s ease;

  &--success {
    background: $lv-success-bg;
    border: 1rpx solid rgba(21, 128, 61, 0.2);
    color: $lv-success;
  }

  &--error {
    background: $lv-error-bg;
    border: 1rpx solid rgba(190, 18, 60, 0.2);
    color: $lv-error;
  }

  &--warning {
    background: $lv-warning-bg;
    border: 1rpx solid rgba(217, 119, 6, 0.2);
    color: $lv-warning;
  }

  &--info {
    background: $lv-primary-lighter;
    border: 1rpx solid rgba(37, 99, 235, 0.2);
    color: $lv-primary;
  }

  &__icon {
    margin-right: 16rpx;
    @include flex-center;
    flex-shrink: 0;
  }

  &__message {
    flex: 1;
    font-size: $lv-font-base;
    font-weight: 500;
  }
}

@keyframes toast-slide-in {
  from {
    opacity: 0;
    transform: translateY(-20rpx);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
</style>
