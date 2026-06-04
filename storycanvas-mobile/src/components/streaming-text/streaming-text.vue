<template>
  <view class="streaming-text">
    <text class="streaming-text__content">{{ content }}</text>
    <view v-if="streaming" class="streaming-text__cursor" />
  </view>
</template>

<script setup lang="ts">
interface StreamingTextProps {
  content: string
  streaming?: boolean
}

withDefaults(defineProps<StreamingTextProps>(), {
  streaming: false
})
</script>

<style lang="scss" scoped>
.streaming-text {
  display: inline-flex;
  align-items: flex-start;

  &__content {
    font-size: $lv-font-base;
    color: $lv-text-primary;
    line-height: 1.6;
    word-break: break-all;
  }

  &__cursor {
    display: inline-block;
    width: 4rpx;
    height: 28rpx;
    background: $lv-primary;
    margin-left: 4rpx;
    animation: pulse 1s infinite;
  }
}

@keyframes pulse {
  0% {
    opacity: 1;
  }
  50% {
    opacity: 0.3;
  }
  100% {
    opacity: 1;
  }
}
</style>
