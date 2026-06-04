<template>
  <view :class="['tool-call-status', `tool-call-status--${status}`]">
    <view class="tool-call-status__icon">
      <Loader v-if="status === 'running'" :size="16" class="animate-spin" />
      <CheckCircle v-else-if="status === 'success'" :size="16" />
      <XCircle v-else-if="status === 'error'" :size="16" />
      <Circle v-else :size="16" />
    </view>
    <view class="tool-call-status__info">
      <text class="tool-call-status__name">{{ name }}</text>
      <text v-if="summary" class="tool-call-status__summary">{{ summary }}</text>
    </view>
  </view>
</template>

<script setup lang="ts">
import { Loader, CheckCircle, XCircle, Circle } from '@lucide/vue'

interface ToolCallStatusProps {
  name: string
  status: 'running' | 'success' | 'error'
  summary?: string
}

withDefaults(defineProps<ToolCallStatusProps>(), {
  summary: ''
})
</script>

<style lang="scss" scoped>
.tool-call-status {
  display: flex;
  align-items: center;
  padding: 16rpx;
  background: $lv-surface-solid;
  border: 1rpx solid $lv-border-light;
  border-radius: $lv-radius-sm;
  margin-bottom: 8rpx;

  &--running {
    border-color: $lv-primary;
    color: $lv-primary;
  }

  &--success {
    border-color: $lv-success;
    color: $lv-success;
  }

  &--error {
    border-color: $lv-error;
    color: $lv-error;
  }

  &__icon {
    margin-right: 12rpx;
    @include flex-center;
  }

  &__info {
    flex: 1;
  }

  &__name {
    font-size: $lv-font-sm;
    font-weight: 600;
    display: block;
  }

  &__summary {
    font-size: $lv-font-xs;
    color: $lv-text-secondary;
    margin-top: 4rpx;
    display: block;
  }
}

.animate-spin {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
