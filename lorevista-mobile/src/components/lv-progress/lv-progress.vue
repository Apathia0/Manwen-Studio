<template>
  <view class="lv-progress">
    <view v-if="showInfo" class="lv-progress__info">
      <text class="lv-progress__info-text">{{ percentage }}%</text>
    </view>
    <view class="lv-progress__bar">
      <view
        class="lv-progress__bar-inner"
        :style="barStyle"
      />
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed } from 'vue'

interface ProgressProps {
  percentage: number
  color?: string
  bgColor?: string
  height?: number
  showInfo?: boolean
}

const props = withDefaults(defineProps<ProgressProps>(), {
  color: '#2563eb',
  bgColor: '#e5edf8',
  height: 12,
  showInfo: false
})

const barStyle = computed(() => ({
  width: `${Math.min(100, Math.max(0, props.percentage))}%`,
  backgroundColor: props.color,
  height: `${props.height}rpx`
}))
</script>

<style lang="scss" scoped>
.lv-progress {
  display: flex;
  align-items: center;
  width: 100%;

  &__info {
    margin-right: 16rpx;
    min-width: 80rpx;
  }

  &__info-text {
    font-size: $lv-font-sm;
    color: $lv-text-secondary;
    font-weight: 500;
  }

  &__bar {
    flex: 1;
    height: 12rpx;
    background: $lv-border-light;
    border-radius: $lv-radius-full;
    overflow: hidden;
  }

  &__bar-inner {
    border-radius: $lv-radius-full;
    transition: width 0.3s ease;
  }
}
</style>
