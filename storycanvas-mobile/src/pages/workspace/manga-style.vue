<template>
  <view class="page">
    <lv-navbar title="漫画风格" show-back />
    <scroll-view scroll-y class="page__scroll">
      <view v-if="loading" class="page__empty">正在加载风格预设...</view>
      <template v-else>
        <text class="page__title">选择风格预设</text>
        <view class="page__grid">
          <view
            v-for="preset in presets"
            :key="preset.id"
            :class="['page__preset', { 'page__preset--active': selectedName === preset.name }]"
            @tap="selectPreset(preset.name)"
          >
            <image v-if="preset.image_url" :src="mangaImageUrl(preset.image_url)" class="page__image" mode="aspectFill" />
            <view v-else class="page__placeholder"><lv-icon name="Palette" :size="24" color="#94a3b8" /></view>
            <text class="page__name">{{ preset.name }}</text>
            <text class="page__category">{{ preset.category }}</text>
          </view>
        </view>
        <view class="page__section">
          <text class="page__title">自定义风格参考图</text>
          <image v-if="referenceUrl" :src="mangaImageUrl(referenceUrl)" class="page__reference" mode="aspectFit" />
          <lv-button block secondary :loading="uploading" @tap="uploadReference">{{ referenceUrl ? '替换参考图' : '上传参考图' }}</lv-button>
        </view>
      </template>
    </scroll-view>
  </view>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { adminApi, mangaApi } from '@/api'
import { useMangaStore } from '@/stores/manga'
import { useImagePicker } from '@/composables/useImagePicker'
import { mangaImageUrl } from '@/utils/url'
import LvNavbar from '@/components/lv-navbar/lv-navbar.vue'
import LvButton from '@/components/lv-button/lv-button.vue'
import LvIcon from '@/components/lv-icon/lv-icon.vue'
import type { VideoStylePreset } from '@/api/admin'

const mangaStore = useMangaStore()
const { chooseImage } = useImagePicker()
const chapterId = ref(0)
const loading = ref(true)
const uploading = ref(false)
const presets = ref<VideoStylePreset[]>([])
const selectedName = ref('')
const referenceUrl = ref('')

onLoad(async options => {
  chapterId.value = Number(options?.chapterId || 0)
  try {
    await mangaStore.loadStylePreset(chapterId.value)
    selectedName.value = mangaStore.stylePresetName
    referenceUrl.value = mangaStore.styleReferenceImageUrl
    presets.value = (await adminApi.listStylePresets()).presets || []
  } finally {
    loading.value = false
  }
})

async function selectPreset(name: string) {
  selectedName.value = name
  referenceUrl.value = ''
  mangaStore.saveStyleReferenceImageUrl(chapterId.value, null)
  await mangaStore.saveStylePreset(chapterId.value, name)
  uni.showToast({ title: '风格已选择', icon: 'success' })
}

async function uploadReference() {
  if (uploading.value || !chapterId.value) return
  uploading.value = true
  try {
    const paths = await chooseImage({ count: 1 })
    if (!paths.length) return
    const result = await mangaApi.uploadStyleReferenceImage(chapterId.value, paths[0])
    referenceUrl.value = result.style_reference_image_url || ''
    selectedName.value = ''
    mangaStore.saveStyleReferenceImageUrl(chapterId.value, referenceUrl.value)
    uni.showToast({ title: '参考图已更新', icon: 'success' })
  } finally {
    uploading.value = false
  }
}
</script>

<style lang="scss" scoped>
.page { min-height: 100vh; background: #f4f7fb; }
.page__scroll { height: 100vh; box-sizing: border-box; padding: calc(var(--status-bar-height) + 108rpx) 24rpx 80rpx; }
.page__title { display: block; margin: 12rpx 0 20rpx; color: #0f172a; font-size: 28rpx; font-weight: 700; }
.page__empty { padding: 120rpx 0; color: #94a3b8; text-align: center; }
.page__grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16rpx; }
.page__preset { overflow: hidden; background: #fff; border: 2rpx solid #e2e8f0; border-radius: 8rpx; }
.page__preset--active { border-color: #2563eb; box-shadow: 0 0 0 2rpx rgba(37, 99, 235, 0.12); }
.page__image, .page__placeholder { width: 100%; aspect-ratio: 4 / 3; background: #eef2f7; }
.page__placeholder { display: flex; align-items: center; justify-content: center; }
.page__name { display: block; padding: 12rpx 12rpx 2rpx; color: #0f172a; font-size: 25rpx; font-weight: 600; }
.page__category { display: block; padding: 0 12rpx 12rpx; color: #94a3b8; font-size: 21rpx; }
.page__section { margin-top: 32rpx; padding: 20rpx; background: #fff; border: 1rpx solid #e2e8f0; border-radius: 8rpx; }
.page__reference { width: 100%; height: 360rpx; margin-bottom: 16rpx; background: #f8fafc; }
</style>
