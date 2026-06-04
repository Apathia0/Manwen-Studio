<template>
  <view class="lv-swiper-tabs">
    <view class="lv-swiper-tabs__nav">
      <view
        v-for="(tab, index) in tabs"
        :key="index"
        :class="['lv-swiper-tabs__item', { 'lv-swiper-tabs__item--active': current === index }]"
        @tap="handleTap(index)"
      >
        <text class="lv-swiper-tabs__item-text">{{ tab }}</text>
        <view v-if="current === index" class="lv-swiper-tabs__item-line" />
      </view>
    </view>
    <swiper
      class="lv-swiper-tabs__content"
      :current="current"
      @change="handleChange"
    >
      <swiper-item v-for="(tab, index) in tabs" :key="index">
        <scroll-view scroll-y class="lv-swiper-tabs__scroll">
          <slot :name="`tab-${index}`" />
        </scroll-view>
      </swiper-item>
    </swiper>
  </view>
</template>

<script setup lang="ts">
import { ref } from 'vue'

interface SwiperTabsProps {
  tabs: string[]
  current?: number
}

const props = withDefaults(defineProps<SwiperTabsProps>(), {
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

function handleChange(event: any) {
  const index = event.detail.current
  emit('update:current', index)
  emit('change', index)
}
</script>

<style lang="scss" scoped>
.lv-swiper-tabs {
  display: flex;
  flex-direction: column;
  height: 100%;

  &__nav {
    display: flex;
    border-bottom: 1rpx solid $lv-border-light;
    background: $lv-surface-solid;
  }

  &__item {
    flex: 1;
    position: relative;
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 24rpx 0;
    cursor: pointer;

    &--active {
      .lv-swiper-tabs__item-text {
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
  }

  &__scroll {
    height: 100%;
  }
}
</style>
