<template>
  <view class="lv-navbar">
    <view class="lv-navbar__status-bar" :style="{ height: statusBarHeight + 'px' }" />
    <view class="lv-navbar__content">
      <view class="lv-navbar__left" @tap="handleBack">
        <view v-if="showBack" class="lv-navbar__back">
          <ArrowLeft :size="20" color="#0f172a" />
        </view>
        <slot name="left" />
      </view>
      <view class="lv-navbar__center">
        <text v-if="title" class="lv-navbar__title">{{ title }}</text>
        <slot name="center" />
      </view>
      <view class="lv-navbar__right">
        <slot name="right" />
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { getStatusBarHeight } from '@/utils/platform'
import { ArrowLeft } from '@lucide/vue'

interface NavbarProps {
  title?: string
  showBack?: boolean
  bgColor?: string
}

const props = withDefaults(defineProps<NavbarProps>(), {
  title: '',
  showBack: false,
  bgColor: 'rgba(248, 251, 255, 0.85)'
})

const emit = defineEmits<{
  (e: 'back'): void
}>()

const statusBarHeight = ref(0)

onMounted(() => {
  statusBarHeight.value = getStatusBarHeight()
})

function handleBack() {
  if (props.showBack) {
    emit('back')
    uni.navigateBack()
  }
}
</script>

<style lang="scss" scoped>
.lv-navbar {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  z-index: 100;
  @include lv-glass-navbar;

  &__status-bar {
    width: 100%;
  }

  &__content {
    display: flex;
    align-items: center;
    justify-content: space-between;
    height: 88rpx;
    padding: 0 $lv-page-padding;
  }

  &__left {
    display: flex;
    align-items: center;
    min-width: 100rpx;
  }

  &__back {
    @include touch-target;
    margin-right: 12rpx;
  }

  &__center {
    flex: 1;
    display: flex;
    align-items: center;
    justify-content: center;
  }

  &__title {
    font-size: $lv-font-lg;
    font-weight: 600;
    color: $lv-text-primary;
    @include text-ellipsis;
  }

  &__right {
    display: flex;
    align-items: center;
    min-width: 100rpx;
    justify-content: flex-end;
  }
}
</style>
