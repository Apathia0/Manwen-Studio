<template>
  <view class="lv-fab" @tap="handleTap">
    <view class="lv-fab__icon">
      <component :is="iconComponent" :size="48" color="#fff" :stroke-width="2.5" />
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { Plus, PenLine, Upload } from '@lucide/vue'

const iconMap: Record<string, any> = {
  'icon-plus': Plus,
  'icon-pen': PenLine,
  'icon-upload': Upload
}

interface FabProps {
  icon?: string
}

const props = withDefaults(defineProps<FabProps>(), {
  icon: 'icon-plus'
})

const emit = defineEmits<{
  (e: 'tap', event: Event): void
}>()

const iconComponent = computed(() => {
  return iconMap[props.icon] || Plus
})

function handleTap(event: Event) {
  emit('tap', event)
}
</script>

<style lang="scss" scoped>
.lv-fab {
  position: fixed;
  right: $lv-page-padding;
  bottom: 200rpx;
  width: 112rpx;
  height: 112rpx;
  border-radius: 50%;
  @include gradient-primary;
  box-shadow: $lv-shadow-lg;
  @include flex-center;
  z-index: 50;

  &:active {
    transform: scale(0.95);
    opacity: 0.9;
  }

  &__icon {
    font-size: 48rpx;
    color: $lv-text-on-primary;
  }
}
</style>
