<template>
  <view class="manga-gallery">
    <!-- 顶部栏 -->
    <view class="manga-gallery__topbar">
      <text class="manga-gallery__count">{{ currentIndex + 1 }} / {{ images.length }}</text>
      <view class="manga-gallery__close" @tap="close">
        <X :size="24" color="#ffffff" />
      </view>
    </view>

    <!-- 图片滑动区域 -->
    <swiper
      class="manga-gallery__swiper"
      :current="currentIndex"
      @change="handleChange"
    >
      <swiper-item v-for="(img, i) in images" :key="img.id || i">
        <view class="manga-gallery__image-wrap">
          <image
            :src="getImageUrl(img)"
            class="manga-gallery__image"
            mode="aspectFit"
            :show-menu-by-longpress="true"
            @load="onImageLoad"
            @error="onImageError"
          />
          <lv-loading v-if="imageLoading" class="manga-gallery__loading" />
        </view>
      </swiper-item>
    </swiper>

    <!-- 空状态 -->
    <view v-if="images.length === 0 && !loading" class="manga-gallery__empty">
      <text class="manga-gallery__empty-text">暂无漫画图片</text>
    </view>

    <!-- 底部工具栏 -->
    <view v-if="images.length > 0" class="manga-gallery__toolbar" @tap.stop>
      <view class="manga-gallery__btn" @tap="handleRegenerate">
        <RefreshCw :size="22" color="#ffffff" />
        <text class="manga-gallery__btn-text">重新生成</text>
      </view>
      <view class="manga-gallery__btn" @tap="handleRedraw">
        <Paintbrush :size="22" color="#ffffff" />
        <text class="manga-gallery__btn-text">重绘</text>
      </view>
      <view class="manga-gallery__btn" @tap="handleSave">
        <Download :size="22" color="#ffffff" />
        <text class="manga-gallery__btn-text">保存到相册</text>
      </view>
    </view>
    <!-- 重绘弹窗 -->
    <image-redraw-modal
      :visible="showRedrawModal"
      :image-url="currentImageUrl"
      :image-number="currentImageNumber"
      :chapter-id="chapterId"
      ref-type="manga"
      @close="showRedrawModal = false"
      @success="handleRedrawSuccess"
    />
  </view>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { X, RefreshCw, Download, Paintbrush } from '@lucide/vue'
import { onLoad } from '@dcloudio/uni-app'
import { mangaApi } from '@/api'
import { mangaImageUrl } from '@/utils/url'
import { useUiStore } from '@/stores/ui'
import type { MangaImage } from '@/api/types'
import LvLoading from '@/components/lv-loading/lv-loading.vue'
import ImageRedrawModal from '@/components/image-redraw-modal/image-redraw-modal.vue'

const uiStore = useUiStore()

const images = ref<MangaImage[]>([])
const currentIndex = ref(0)
const loading = ref(true)
const imageLoading = ref(true)
let chapterId = 0

/** 重绘弹窗状态 */
const showRedrawModal = ref(false)

/** 当前图片 URL */
const currentImageUrl = computed(() => {
  const img = images.value[currentIndex.value]
  return img ? getImageUrl(img) : ''
})

/** 当前图片编号 */
const currentImageNumber = computed(() => {
  const img = images.value[currentIndex.value]
  return img ? img.image_number : 0
})

onLoad(async (options) => {
  chapterId = parseInt(options?.chapterId || '0')
  const startImageNumber = parseInt(options?.imageNumber || '1')

  if (!chapterId) {
    uiStore.error('未指定章节')
    loading.value = false
    return
  }

  try {
    const scenes = await mangaApi.getScenes(chapterId)
    // getScenes 返回的是分镜文本，不是图片
    // 需要从章节详情获取图片列表
    const { chaptersApi } = await import('@/api')
    const chapter = await chaptersApi.getChapter(chapterId)
    images.value = (chapter as any).images || []

    // 定位到指定图片
    const targetIndex = images.value.findIndex(img => img.image_number === startImageNumber)
    if (targetIndex !== -1) {
      currentIndex.value = targetIndex
    }
  } catch (e) {
    console.error('加载漫画图片失败:', e)
    uiStore.error('加载失败')
  } finally {
    loading.value = false
  }
})

function getImageUrl(img: MangaImage): string {
  return mangaImageUrl(img.image_path)
}

function handleChange(e: any) {
  currentIndex.value = e.detail.current
  imageLoading.value = true
}

function onImageLoad() {
  imageLoading.value = false
}

function onImageError() {
  imageLoading.value = false
  uiStore.error('图片加载失败')
}

function close() {
  uni.navigateBack()
}

async function handleRegenerate() {
  const img = images.value[currentIndex.value]
  if (!img) return

  uni.showModal({
    title: '重新生成',
    content: '确定要重新生成这张图片吗？',
    success: async (res) => {
      if (!res.confirm) return
      try {
        uiStore.info('正在重新生成...')
        const result = await mangaApi.regenerateImage(chapterId, img.image_number, img.prompt || '')
        // 更新图片
        images.value[currentIndex.value] = result
        uiStore.success('重新生成完成')
      } catch (e: any) {
        uiStore.error(e.message || '重新生成失败')
      }
    }
  })
}

function handleSave() {
  const img = images.value[currentIndex.value]
  if (!img) return

  const url = getImageUrl(img)
  uni.downloadFile({
    url,
    success: (res) => {
      if (res.statusCode === 200) {
        uni.saveImageToPhotosAlbum({
          filePath: res.tempFilePath,
          success: () => {
            uiStore.success('已保存到相册')
          },
          fail: (err) => {
            if (err.errMsg.includes('deny') || err.errMsg.includes('auth')) {
              uni.showModal({
                title: '需要授权',
                content: '请在设置中允许保存图片到相册',
                confirmText: '去设置',
                success: (modalRes) => {
                  if (modalRes.confirm) uni.openSetting()
                }
              })
            } else {
              uiStore.error('保存失败')
            }
          }
        })
      }
    },
    fail: () => {
      uiStore.error('下载失败')
    }
  })
}

/** 打开重绘弹窗 */
function handleRedraw() {
  const img = images.value[currentIndex.value]
  if (!img) return
  showRedrawModal.value = true
}

/** 重绘成功后刷新图片列表 */
async function handleRedrawSuccess(result: any) {
  // 用结果更新当前图片
  if (result && result.image_path) {
    images.value[currentIndex.value] = {
      ...images.value[currentIndex.value],
      image_path: result.image_path,
      prompt: result.prompt ?? images.value[currentIndex.value].prompt,
    }
  } else {
    // 如果结果不含图片信息，重新加载章节数据
    try {
      const { chaptersApi } = await import('@/api')
      const chapter = await chaptersApi.getChapter(chapterId)
      images.value = (chapter as any).images || []
    } catch {
      // 静默忽略刷新失败
    }
  }
  uiStore.success('重绘完成')
}
</script>

<style lang="scss" scoped>
.manga-gallery {
  height: 100vh;
  background: #000;
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
    background: linear-gradient(180deg, rgba(0,0,0,0.6) 0%, transparent 100%);
    z-index: 10;
  }

  &__count {
    font-size: $lv-font-base;
    color: rgba(255, 255, 255, 0.9);
  }

  &__close {
    position: absolute;
    right: $lv-page-padding;
    top: calc(var(--status-bar-height) + 16rpx);
    width: 64rpx;
    height: 64rpx;
    @include flex-center;
    color: rgba(255, 255, 255, 0.9);
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
    position: relative;
  }

  &__image {
    width: 100%;
    height: 100%;
  }

  &__loading {
    position: absolute;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
  }

  &__empty {
    flex: 1;
    @include flex-center;
  }

  &__empty-text {
    font-size: $lv-font-base;
    color: rgba(255, 255, 255, 0.5);
  }

  &__toolbar {
    position: absolute;
    bottom: 0;
    left: 0;
    right: 0;
    display: flex;
    justify-content: space-around;
    padding: 32rpx;
    padding-bottom: calc(env(safe-area-inset-bottom) + 32rpx);
    background: linear-gradient(0deg, rgba(0,0,0,0.7) 0%, transparent 100%);
    z-index: 10;
  }

  &__btn {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 8rpx;
    color: rgba(255, 255, 255, 0.9);
    padding: 16rpx 32rpx;

    &:active {
      opacity: 0.7;
    }
  }

  &__btn-text {
    font-size: $lv-font-xs;
    color: rgba(255, 255, 255, 0.7);
  }
}
</style>
