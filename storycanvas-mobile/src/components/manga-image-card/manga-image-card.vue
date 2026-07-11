<template>
  <view class="manga-image-card" :style="{ aspectRatio: cssAspectRatio }" @tap="handleTap">
    <image
      :src="imageUrl"
      class="manga-image-card__image"
      mode="aspectFit"
      lazy-load
    />
    <view v-if="showNumber" class="manga-image-card__number">
      <text class="manga-image-card__number-text">{{ imageNumber }}</text>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { mangaImageUrl } from '@/utils/url'

interface MangaImageCardProps {
  imagePath: string
  imageNumber?: number
  showNumber?: boolean
  cacheBust?: number
  aspectRatio?: string
}

const props = withDefaults(defineProps<MangaImageCardProps>(), {
  imageNumber: 0,
  showNumber: true,
  cacheBust: 0,
  aspectRatio: '3:4'
})

const emit = defineEmits<{
  (e: 'tap'): void
}>()

const imageUrl = computed(() => {
  return mangaImageUrl(props.imagePath, props.cacheBust)
})
const cssAspectRatio = computed(() => props.aspectRatio.replace(':', ' / '))

function handleTap() {
  emit('tap')
}
</script>

<style lang="scss" scoped>
.manga-image-card {
  position: relative;
  border-radius: $lv-radius-md;
  overflow: hidden;
  background: $lv-primary-lighter;

  &:active {
    transform: scale(0.98);
    opacity: 0.9;
    transition: transform 0.1s ease, opacity 0.1s ease;
  }

  &__image {
    width: 100%;
    height: 100%;
  }

  &__number {
    position: absolute;
    top: 12rpx;
    left: 12rpx;
    width: 48rpx;
    height: 48rpx;
    border-radius: 50%;
    background: rgba(0, 0, 0, 0.6);
    @include flex-center;
  }

  &__number-text {
    font-size: $lv-font-xs;
    color: $lv-text-on-primary;
    font-weight: 600;
  }
}
</style>
