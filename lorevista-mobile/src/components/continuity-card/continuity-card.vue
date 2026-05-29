<template>
  <view class="continuity-card">
    <view class="continuity-card__header" @tap="toggleExpanded">
      <text class="continuity-card__title">连贯性摘要</text>
      <ChevronUp v-if="expanded" :size="14" color="#94a3b8" />
      <ChevronDown v-else :size="14" color="#94a3b8" />
    </view>
    <view v-if="expanded" class="continuity-card__content">
      <text class="continuity-card__text">{{ summary }}</text>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { ChevronUp, ChevronDown } from '@lucide/vue'

interface ContinuityCardProps {
  summary: string
  defaultExpanded?: boolean
}

const props = withDefaults(defineProps<ContinuityCardProps>(), {
  defaultExpanded: false
})

const expanded = ref(props.defaultExpanded)

function toggleExpanded() {
  expanded.value = !expanded.value
}
</script>

<style lang="scss" scoped>
.continuity-card {
  background: $lv-primary-lighter;
  border: 1rpx solid $lv-border;
  border-radius: $lv-radius-md;
  overflow: hidden;
  margin-bottom: 24rpx;

  &__header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 20rpx $lv-card-padding;
    cursor: pointer;

    &:active {
      background: $lv-primary-light;
    }
  }

  &__title {
    font-size: $lv-font-sm;
    font-weight: 600;
    color: $lv-primary;
  }

  &__content {
    padding: 0 $lv-card-padding $lv-card-padding;
  }

  &__text {
    font-size: $lv-font-sm;
    color: $lv-text-secondary;
    line-height: 1.6;
  }
}
</style>
