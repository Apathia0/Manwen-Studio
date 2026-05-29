<template>
  <view class="lv-empty">
    <view class="lv-empty__image">
      <Inbox :size="40" />
    </view>
    <text class="lv-empty__title">{{ title }}</text>
    <text v-if="description" class="lv-empty__description">{{ description }}</text>
    <view v-if="$slots.action" class="lv-empty__action">
      <slot name="action" />
    </view>
  </view>
</template>

<script setup lang="ts">
import { Inbox } from '@lucide/vue'

interface EmptyProps {
  title?: string
  description?: string
}

withDefaults(defineProps<EmptyProps>(), {
  title: '暂无数据',
  description: ''
})
</script>

<style lang="scss" scoped>
.lv-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 80rpx $lv-page-padding;

  &__image {
    width: 200rpx;
    height: 200rpx;
    display: flex;
    align-items: center;
    justify-content: center;
    margin-bottom: 32rpx;
    background: $lv-primary-lighter;
    border-radius: 50%;
    color: $lv-text-muted;
  }

  &__title {
    font-size: $lv-font-lg;
    font-weight: 600;
    color: $lv-text-primary;
    margin-bottom: 12rpx;
  }

  &__description {
    font-size: $lv-font-base;
    color: $lv-text-secondary;
    text-align: center;
    max-width: 480rpx;
    margin-bottom: 32rpx;
  }

  &__action {
    margin-top: 16rpx;
  }
}
</style>
