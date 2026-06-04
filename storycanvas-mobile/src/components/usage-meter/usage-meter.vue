<template>
  <view class="usage-meter">
    <view class="usage-meter__header">
      <text class="usage-meter__label">{{ label }}</text>
      <text class="usage-meter__value">{{ used }}/{{ limit }}</text>
    </view>
    <view class="usage-meter__bar">
      <view
        class="usage-meter__bar-inner"
        :style="barStyle"
      />
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed } from 'vue'

interface UsageMeterProps {
  label: string
  used: number
  limit: number
  color?: string
}

const props = withDefaults(defineProps<UsageMeterProps>(), {
  color: '#2563eb'
})

const percentage = computed(() => {
  if (props.limit === 0) return 0
  return Math.min(100, (props.used / props.limit) * 100)
})

const barStyle = computed(() => ({
  width: `${percentage.value}%`,
  backgroundColor: props.color
}))
</script>

<style lang="scss" scoped>
.usage-meter {
  margin-bottom: 24rpx;

  &__header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 12rpx;
  }

  &__label {
    font-size: $lv-font-sm;
    color: $lv-text-secondary;
  }

  &__value {
    font-size: $lv-font-sm;
    color: $lv-text-muted;
    font-weight: 500;
  }

  &__bar {
    height: 12rpx;
    background: $lv-border-light;
    border-radius: $lv-radius-full;
    overflow: hidden;
  }

  &__bar-inner {
    height: 100%;
    border-radius: $lv-radius-full;
    transition: width 0.3s ease;
  }
}
</style>
