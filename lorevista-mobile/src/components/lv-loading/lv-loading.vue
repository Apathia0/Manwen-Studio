<template>
  <view :class="loadingClasses">
    <view class="lv-loading__spinner" :style="spinnerStyle" />
    <text v-if="text" class="lv-loading__text">{{ text }}</text>
  </view>
</template>

<script setup lang="ts">
import { computed } from 'vue'

interface LoadingProps {
  size?: number
  color?: string
  text?: string
  vertical?: boolean
}

const props = withDefaults(defineProps<LoadingProps>(), {
  size: 40,
  color: '#2563eb',
  vertical: false
})

const loadingClasses = computed(() => [
  'lv-loading',
  {
    'lv-loading--vertical': props.vertical
  }
])

const spinnerStyle = computed(() => ({
  width: props.size + 'rpx',
  height: props.size + 'rpx',
  borderColor: `${props.color} ${props.color} transparent transparent`
}))
</script>

<style lang="scss" scoped>
.lv-loading {
  display: inline-flex;
  align-items: center;
  justify-content: center;

  &--vertical {
    flex-direction: column;
  }

  &__spinner {
    border: 4rpx solid transparent;
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
  }

  &__text {
    margin-left: 16rpx;
    font-size: $lv-font-sm;
    color: $lv-text-secondary;
  }

  &--vertical &__text {
    margin-left: 0;
    margin-top: 12rpx;
  }
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
