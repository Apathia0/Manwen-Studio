<template>
  <view class="ref-image-card" @tap="handleTap" @longpress="handleLongPress">
    <image
      :src="imageUrl"
      class="ref-image-card__image"
      mode="aspectFill"
      lazy-load
    />
    <view class="ref-image-card__actions">
      <view class="ref-image-card__btn" @tap.stop="handleRedraw">
        <RefreshCw :size="14" />
      </view>
      <view class="ref-image-card__btn ref-image-card__btn--danger" @tap.stop="handleDelete">
        <Trash2 :size="14" />
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { refImageUrl } from '@/utils/url'
import { RefreshCw, Trash2 } from '@lucide/vue'

interface RefImageCardProps {
  imagePath: string
}

const props = defineProps<RefImageCardProps>()

const emit = defineEmits<{
  (e: 'tap'): void
  (e: 'longpress'): void
  (e: 'redraw'): void
  (e: 'delete'): void
}>()

const imageUrl = computed(() => {
  return refImageUrl(props.imagePath)
})

function handleTap() {
  emit('tap')
}

function handleLongPress() {
  emit('longpress')
}

function handleRedraw() {
  emit('redraw')
}

function handleDelete() {
  emit('delete')
}
</script>

<style lang="scss" scoped>
.ref-image-card {
  position: relative;
  border-radius: $lv-radius-md;
  overflow: hidden;
  aspect-ratio: 1;

  &:active {
    transform: scale(0.98);
    opacity: 0.9;
    transition: transform 0.1s ease, opacity 0.1s ease;
  }

  &__image {
    width: 100%;
    height: 100%;
  }

  &__actions {
    position: absolute;
    bottom: 0;
    left: 0;
    right: 0;
    display: flex;
    justify-content: flex-end;
    padding: 12rpx;
    background: linear-gradient(transparent, rgba(0, 0, 0, 0.6));
    opacity: 0;
    transition: opacity 0.2s ease;
  }

  &:hover &__actions,
  &:active &__actions {
    opacity: 1;
  }

  &__btn {
    width: 56rpx;
    height: 56rpx;
    border-radius: 50%;
    background: rgba(255, 255, 255, 0.9);
    @include flex-center;
    margin-left: 12rpx;
    color: $lv-text-primary;

    &--danger {
      background: $lv-error;
      color: $lv-text-on-primary;
    }

    &:active {
      opacity: 0.8;
    }
  }
}
</style>
