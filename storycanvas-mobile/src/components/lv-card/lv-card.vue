<template>
  <view :class="cardClasses" @tap="handleTap">
    <slot />
  </view>
</template>

<script setup lang="ts">
import { computed } from 'vue'

interface CardProps {
  padding?: 'none' | 'sm' | 'md' | 'lg'
  shadow?: 'sm' | 'md' | 'lg'
  radius?: 'md' | 'lg'
  hoverable?: boolean
}

const props = withDefaults(defineProps<CardProps>(), {
  padding: 'md',
  shadow: 'sm',
  radius: 'md',
  hoverable: false
})

const emit = defineEmits<{
  (e: 'tap', event: Event): void
}>()

const cardClasses = computed(() => [
  'lv-card',
  `lv-card--padding-${props.padding}`,
  `lv-card--shadow-${props.shadow}`,
  `lv-card--radius-${props.radius}`,
  {
    'lv-card--hoverable': props.hoverable
  }
])

function handleTap(event: Event) {
  emit('tap', event)
}
</script>

<style lang="scss" scoped>
.lv-card {
  @include lv-glass-card;
  background: $lv-surface-solid;
  border: 1rpx solid $lv-border;

  &--padding-none {
    padding: 0;
  }

  &--padding-sm {
    padding: 20rpx;
  }

  &--padding-md {
    padding: $lv-card-padding;
  }

  &--padding-lg {
    padding: 36rpx;
  }

  &--shadow-sm {
    box-shadow: $lv-shadow-sm;
  }

  &--shadow-md {
    box-shadow: $lv-shadow-md;
  }

  &--shadow-lg {
    box-shadow: $lv-shadow-lg;
  }

  &--radius-md {
    border-radius: $lv-radius-md;
  }

  &--radius-lg {
    border-radius: $lv-radius-lg;
  }

  &--hoverable {
    &:active {
      transform: scale(0.98);
      opacity: 0.9;
      transition: transform 0.1s ease, opacity 0.1s ease;
    }
  }
}
</style>
