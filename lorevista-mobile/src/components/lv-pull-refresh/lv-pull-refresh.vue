<template>
  <scroll-view
    scroll-y
    class="lv-pull-refresh"
    @scrolltoupper="handleScrollToUpper"
    @scroll="handleScroll"
  >
    <view class="lv-pull-refresh__content">
      <view v-if="refreshing" class="lv-pull-refresh__loading">
        <lv-loading :size="32" />
        <text class="lv-pull-refresh__text">刷新中...</text>
      </view>
      <slot />
    </view>
  </scroll-view>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import LvLoading from '../lv-loading/lv-loading.vue'

interface PullRefreshProps {
  modelValue?: boolean
}

const props = withDefaults(defineProps<PullRefreshProps>(), {
  modelValue: false
})

const emit = defineEmits<{
  (e: 'update:modelValue', value: boolean): void
  (e: 'refresh'): void
}>()

const refreshing = ref(props.modelValue)

function handleScrollToUpper() {
  if (!refreshing.value) {
    refreshing.value = true
    emit('update:modelValue', true)
    emit('refresh')
  }
}

function handleScroll() {
  // 可以在这里处理更多逻辑
}

function stopRefresh() {
  refreshing.value = false
  emit('update:modelValue', false)
}

defineExpose({ stopRefresh })
</script>

<style lang="scss" scoped>
.lv-pull-refresh {
  height: 100%;

  &__content {
    min-height: 100%;
  }

  &__loading {
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 24rpx 0;
    background: $lv-primary-lighter;
  }

  &__text {
    margin-left: 12rpx;
    font-size: $lv-font-sm;
    color: $lv-text-secondary;
  }
}
</style>
