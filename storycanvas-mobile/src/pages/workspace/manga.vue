<template>
  <view class="manga-page">
    <lv-navbar title="漫画生成" show-back />

    <view class="manga-page__content">
      <view class="manga-page__settings">
        <text class="manga-page__label">色彩:</text>
        <picker :value="colorModeIndex" :range="['彩色', '黑白']" @change="handleColorModeChange">
          <text class="manga-page__picker">{{ ['彩色', '黑白'][colorModeIndex] }}</text>
        </picker>
        <text class="manga-page__label">张数:</text>
        <picker :value="imageCountIndex" :range="imageCountOptions.map(o => o.label)" @change="handleImageCountChange">
          <text class="manga-page__picker">{{ imageCountOptions[imageCountIndex].label }}</text>
        </picker>
      </view>

      <lv-button block :loading="mangaStore.isGenerating" @tap="handleGenerate">
        <template v-if="mangaStore.isGenerating">生成中...</template>
        <template v-else>
          <lv-icon name="ImagePlus" :size="16" style="margin-right: 8rpx;" />生成漫画
        </template>
      </lv-button>

      <view v-if="mangaStore.isGenerating" class="manga-page__progress">
        <lv-progress :percentage="mangaStore.progressPercent" show-info />
        <text class="manga-page__status">{{ mangaStore.progress.statusMsg }}</text>
      </view>

      <view v-if="mangaStore.scenes.length > 0" class="manga-page__scenes">
        <text class="manga-page__section-title">分镜脚本 ({{ mangaStore.scenes.length }})</text>
        <view v-for="(scene, i) in mangaStore.scenes" :key="i" class="manga-page__scene-item">
          <text class="manga-page__scene-num">{{ i + 1 }}.</text>
          <text class="manga-page__scene-text">{{ scene }}</text>
        </view>
      </view>

      <view class="manga-page__grid">
        <manga-image-card
          v-for="img in mangaStore.images"
          :key="img.id"
          :image-path="img.image_path"
          :image-number="img.image_number"
          @tap="goGallery(img.image_number)"
        />
      </view>

      <lv-empty v-if="!mangaStore.isGenerating && mangaStore.images.length === 0" title="暂无漫画" description="点击生成按钮开始创作" />

      <view class="manga-page__tools">
        <lv-button secondary block @tap="goCharacters">角色外观</lv-button>
        <lv-button secondary block @tap="goRefImages">参考图</lv-button>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { useMangaStore } from '@/stores/manga'
import { useUiStore } from '@/stores/ui'
import LvNavbar from '@/components/lv-navbar/lv-navbar.vue'
import LvButton from '@/components/lv-button/lv-button.vue'
import LvIcon from '@/components/lv-icon/lv-icon.vue'
import LvProgress from '@/components/lv-progress/lv-progress.vue'
import LvEmpty from '@/components/lv-empty/lv-empty.vue'
import MangaImageCard from '@/components/manga-image-card/manga-image-card.vue'

const mangaStore = useMangaStore()
const uiStore = useUiStore()

const colorModeIndex = ref(0)
const imageCountIndex = ref(1)

const imageCountOptions = [
  { label: '4张', value: 4 },
  { label: '6张', value: 6 },
  { label: '8张', value: 8 },
  { label: '10张', value: 10 },
  { label: '12张', value: 12 },
  { label: '15张', value: 15 },
  { label: '20张', value: 20 }
]

let chapterId = 0

onLoad(async (options) => {
  chapterId = parseInt(options?.chapterId || '0')

  if (!chapterId) {
    uiStore.error('未指定章节')
    return
  }

  try {
    await Promise.all([
      mangaStore.loadScenes(chapterId),
      mangaStore.loadColorMode(chapterId),
      mangaStore.loadImageCount(chapterId)
    ])

    colorModeIndex.value = mangaStore.colorMode === 'bw' ? 1 : 0
    const countIdx = imageCountOptions.findIndex(o => o.value === mangaStore.imageCount)
    if (countIdx !== -1) imageCountIndex.value = countIdx
  } catch (e) {
    console.error('加载漫画数据失败:', e)
  }
})

function handleColorModeChange(e: any) {
  colorModeIndex.value = e.detail.value
  const mode = colorModeIndex.value === 0 ? 'color' : 'bw'
  mangaStore.saveColorMode(chapterId, mode as 'color' | 'bw')
}

function handleImageCountChange(e: any) {
  imageCountIndex.value = e.detail.value
  const count = imageCountOptions[imageCountIndex.value].value
  mangaStore.saveImageCount(chapterId, count)
}

async function handleGenerate() {
  if (!chapterId) return
  await mangaStore.startMangaGeneration(chapterId)
}

function goGallery(imageNumber: number) {
  uni.navigateTo({ url: `/pages/workspace/manga-gallery?chapterId=${chapterId}&imageNumber=${imageNumber}` })
}

function goCharacters() {
  uni.navigateTo({ url: `/pages/workspace/character-profiles?storyId=${chapterId}` })
}

function goRefImages() {
  uni.navigateTo({ url: `/pages/workspace/ref-images?chapterId=${chapterId}` })
}
</script>

<style lang="scss" scoped>
.manga-page {
  min-height: 100vh;
  background: linear-gradient(180deg, $lv-bg-start 0%, $lv-bg-end 100%);

  &__content {
    padding: calc(var(--status-bar-height) + 88rpx) $lv-page-padding $lv-page-padding;
  }

  &__settings {
    display: flex;
    align-items: center;
    gap: 12rpx;
    margin-bottom: 16rpx;
  }

  &__label {
    font-size: $lv-font-sm;
    color: $lv-text-secondary;
  }

  &__picker {
    font-size: $lv-font-sm;
    color: $lv-primary;
    background: $lv-primary-light;
    padding: 8rpx 20rpx;
    border-radius: $lv-radius-full;
  }

  &__progress {
    margin: 16rpx 0;
    padding: 24rpx;
    background: $lv-surface-solid;
    border-radius: $lv-radius-md;
    box-shadow: $lv-shadow-sm;
  }

  &__status {
    display: block;
    font-size: $lv-font-sm;
    color: $lv-text-secondary;
    margin-top: 12rpx;
  }

  &__scenes {
    margin: 24rpx 0;
    background: $lv-surface-solid;
    border-radius: $lv-radius-md;
    padding: 24rpx;
    box-shadow: $lv-shadow-sm;
  }

  &__section-title {
    display: block;
    font-size: $lv-font-base;
    font-weight: 600;
    color: $lv-text-primary;
    margin-bottom: 16rpx;
  }

  &__scene-item {
    display: flex;
    gap: 12rpx;
    padding: 12rpx 0;
    border-bottom: 1rpx solid $lv-border-light;

    &:last-child {
      border-bottom: none;
    }
  }

  &__scene-num {
    font-size: $lv-font-sm;
    color: $lv-primary;
    font-weight: 600;
    flex-shrink: 0;
  }

  &__scene-text {
    font-size: $lv-font-sm;
    color: $lv-text-primary;
    line-height: 1.6;
  }

  &__grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 16rpx;
    margin: 16rpx 0;
  }

  &__tools {
    display: flex;
    gap: 16rpx;
    margin-top: 16rpx;
  }
}
</style>
