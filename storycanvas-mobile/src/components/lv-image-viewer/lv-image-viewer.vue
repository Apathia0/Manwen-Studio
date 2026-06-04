<template>
  <view v-if="visible" class="lv-image-viewer" @tap="handleClose">
    <!-- 顶部栏 -->
    <view class="lv-image-viewer__topbar" @tap.stop>
      <text class="lv-image-viewer__counter">{{ currentIndex + 1 }} / {{ images.length }}</text>
      <view class="lv-image-viewer__close" @tap="handleClose">
        <X :size="24" color="#ffffff" />
      </view>
    </view>

    <!-- 图片区域 -->
    <swiper
      class="lv-image-viewer__swiper"
      :current="currentIndex"
      @change="handleChange"
      @tap.stop
    >
      <swiper-item v-for="(img, i) in images" :key="i">
        <view class="lv-image-viewer__image-wrap">
          <image
            :src="getImageUrl(img)"
            class="lv-image-viewer__image"
            mode="aspectFit"
            :show-menu-by-longpress="true"
          />
        </view>
      </swiper-item>
    </swiper>

    <!-- 底部操作栏 -->
    <view class="lv-image-viewer__bottombar" @tap.stop>
      <view v-if="showSave" class="lv-image-viewer__action" @tap="handleSave">
        <Download :size="22" color="#ffffff" />
        <text class="lv-image-viewer__action-text">保存</text>
      </view>
      <view v-if="showRegenerate" class="lv-image-viewer__action" @tap="handleRegenerate">
        <RefreshCw :size="22" color="#ffffff" />
        <text class="lv-image-viewer__action-text">重绘</text>
      </view>
      <view v-if="images.length > 1" class="lv-image-viewer__dots">
        <view
          v-for="(_, i) in images"
          :key="i"
          :class="['lv-image-viewer__dot', { 'lv-image-viewer__dot--active': i === currentIndex }]"
        />
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { X, Download, RefreshCw } from '@lucide/vue'
import { mangaImageUrl } from '@/utils/url'

interface ImageItem {
  image_path?: string
  image_number?: number
  url?: string
}

const props = withDefaults(defineProps<{
  visible: boolean
  images: ImageItem[] | string[]
  initialIndex?: number
  showSave?: boolean
  showRegenerate?: boolean
}>(), {
  initialIndex: 0,
  showSave: true,
  showRegenerate: false
})

const emit = defineEmits<{
  (e: 'update:visible', value: boolean): void
  (e: 'close'): void
  (e: 'save', index: number): void
  (e: 'regenerate', index: number): void
  (e: 'change', index: number): void
}>()

const currentIndex = ref(props.initialIndex)

watch(() => props.visible, (val) => {
  if (val) {
    currentIndex.value = props.initialIndex
  }
})

watch(() => props.initialIndex, (val) => {
  if (props.visible) {
    currentIndex.value = val
  }
})

function getImageUrl(img: ImageItem | string): string {
  if (typeof img === 'string') {
    return img.startsWith('http') ? img : mangaImageUrl(img)
  }
  if (img.url) return img.url
  if (img.image_path) return mangaImageUrl(img.image_path)
  return ''
}

function handleChange(e: any) {
  currentIndex.value = e.detail.current
  emit('change', currentIndex.value)
}

function handleClose() {
  emit('update:visible', false)
  emit('close')
}

function handleSave() {
  const url = getImageUrl(props.images[currentIndex.value])
  if (!url) return

  uni.downloadFile({
    url,
    success: (res) => {
      if (res.statusCode === 200) {
        uni.saveImageToPhotosAlbum({
          filePath: res.tempFilePath,
          success: () => {
            uni.showToast({ title: '已保存到相册', icon: 'success' })
            emit('save', currentIndex.value)
          },
          fail: (err) => {
            if (err.errMsg.includes('deny') || err.errMsg.includes('auth')) {
              uni.showModal({
                title: '提示',
                content: '需要授权保存图片到相册',
                confirmText: '去设置',
                success: (res) => {
                  if (res.confirm) {
                    uni.openSetting()
                  }
                }
              })
            } else {
              uni.showToast({ title: '保存失败', icon: 'none' })
            }
          }
        })
      }
    },
    fail: () => {
      uni.showToast({ title: '下载失败', icon: 'none' })
    }
  })
}

function handleRegenerate() {
  emit('regenerate', currentIndex.value)
}
</script>

<style lang="scss" scoped>
.lv-image-viewer {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  z-index: 9999;
  background: rgba(0, 0, 0, 0.95);
  display: flex;
  flex-direction: column;

  &__topbar {
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: calc(var(--status-bar-height) + 16rpx) $lv-page-padding 16rpx;
    z-index: 10;
  }

  &__counter {
    font-size: $lv-font-base;
    color: rgba(255, 255, 255, 0.8);
  }

  &__close {
    position: absolute;
    right: $lv-page-padding;
    top: calc(var(--status-bar-height) + 16rpx);
    width: 64rpx;
    height: 64rpx;
    @include flex-center;
    color: rgba(255, 255, 255, 0.8);
    font-size: 40rpx;
  }

  &__swiper {
    flex: 1;
    width: 100%;
  }

  &__image-wrap {
    width: 100%;
    height: 100%;
    @include flex-center;
  }

  &__image {
    width: 100%;
    height: 100%;
  }

  &__bottombar {
    position: absolute;
    bottom: 0;
    left: 0;
    right: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 48rpx;
    padding: 24rpx $lv-page-padding;
    padding-bottom: calc(env(safe-area-inset-bottom) + 24rpx);
    z-index: 10;
  }

  &__action {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 8rpx;
    color: rgba(255, 255, 255, 0.8);

    &:active {
      opacity: 0.7;
    }
  }

  &__action-text {
    font-size: $lv-font-xs;
    color: rgba(255, 255, 255, 0.6);
  }

  &__dots {
    display: flex;
    gap: 12rpx;
  }

  &__dot {
    width: 12rpx;
    height: 12rpx;
    border-radius: 50%;
    background: rgba(255, 255, 255, 0.3);
    transition: all 0.2s ease;

    &--active {
      background: #ffffff;
      width: 24rpx;
      border-radius: 6rpx;
    }
  }
}
</style>
