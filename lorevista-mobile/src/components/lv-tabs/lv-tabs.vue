<template>
  <view class="lv-tabs">
    <scroll-view scroll-x class="lv-tabs__nav">
      <view class="lv-tabs__nav-inner">
        <view
          v-for="(tab, index) in tabs"
          :key="index"
          :class="['lv-tabs__item', { 'lv-tabs__item--active': current === index }]"
          @tap="handleTap(index)"
        >
          <text class="lv-tabs__item-text">{{ tab }}</text>
          <view v-if="current === index" class="lv-tabs__item-line" />
        </view>
      </view>
    </scroll-view>
    <view class="lv-tabs__content">
      <slot />
    </view>
  </view>
</template>

<script setup lang="ts">
interface TabsProps {
  tabs: string[]
  current?: number
}

const props = withDefaults(defineProps<TabsProps>(), {
  current: 0
})

const emit = defineEmits<{
  (e: 'update:current', index: number): void
  (e: 'change', index: number): void
}>()

function handleTap(index: number) {
  emit('update:current', index)
  emit('change', index)
}
</script>

<style lang="scss" scoped>
.lv-tabs {
  display: flex;
  flex-direction: column;
  height: 100%;

  &__nav {
    white-space: nowrap;
    border-bottom: 1rpx solid $lv-border-light;
  }

  &__nav-inner {
    display: inline-flex;
    padding: 0 $lv-page-padding;
  }

  &__item {
    position: relative;
    display: inline-flex;
    flex-direction: column;
    align-items: center;
    padding: 24rpx 32rpx;
    cursor: pointer;

    &--active {
      .lv-tabs__item-text {
        color: $lv-primary;
        font-weight: 600;
      }
    }
  }

  &__item-text {
    font-size: $lv-font-base;
    color: $lv-text-secondary;
    transition: color 0.2s ease;
  }

  &__item-line {
    position: absolute;
    bottom: 0;
    left: 50%;
    transform: translateX(-50%);
    width: 48rpx;
    height: 6rpx;
    background: $lv-primary;
    border-radius: $lv-radius-full;
  }

  &__content {
    flex: 1;
    overflow: hidden;
  }
}
</style>
