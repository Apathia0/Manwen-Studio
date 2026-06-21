<template>
  <view class="ss-overlay" @tap.self="handleClose">
    <view class="ss-popup">
      <!-- 头部 -->
      <view class="ss-header">
        <text class="ss-header__title">选择风格预设</text>
        <view class="ss-header__close" @tap="handleClose">
          <X :size="20" color="#94a3b8" />
        </view>
      </view>

      <scroll-view scroll-y class="ss-body">
        <!-- 分类标签 -->
        <scroll-view scroll-x class="ss-tabs-scroll" show-scrollbar="false">
          <view class="ss-tabs">
            <view
              v-for="cat in categories"
              :key="cat"
              :class="['ss-tab', { 'ss-tab--active': activeCategory === cat }]"
              @tap="activeCategory = cat"
            >
              <text>{{ categoryLabel(cat) }}</text>
            </view>
          </view>
        </scroll-view>

        <!-- 预设网格 -->
        <view class="ss-grid">
          <view
            v-for="preset in filteredPresets"
            :key="preset.id"
            :class="['ss-grid__item', { 'ss-grid__item--active': localSelectedName === preset.name }]"
            @tap="handleSelectPreset(preset)"
          >
            <image
              v-if="preset.image_url"
              :src="preset.image_url"
              class="ss-grid__image"
              mode="aspectFill"
            />
            <view v-else class="ss-grid__placeholder">
              <lv-icon name="Palette" :size="24" color="#94a3b8" />
            </view>
            <text class="ss-grid__name">{{ preset.name }}</text>
            <view class="ss-grid__tag">
              <text class="ss-grid__tag-text">{{ preset.category }}</text>
            </view>
          </view>
        </view>

        <!-- 自定义风格参考图 -->
        <view class="ss-ref">
          <text class="ss-ref__label">自定义风格参考图</text>
          <template v-if="localRefUrl">
            <view class="ss-ref__preview">
              <image :src="localRefUrl" class="ss-ref__image" mode="aspectFill" />
              <view class="ss-ref__actions">
                <lv-button size="sm" secondary @tap="handleClearRef">清除</lv-button>
                <lv-button size="sm" :loading="uploading" @tap="handleUploadRef">替换</lv-button>
              </view>
            </view>
          </template>
          <template v-else>
            <view class="ss-ref__upload" @tap="handleUploadRef">
              <lv-icon name="Upload" :size="24" color="#94a3b8" />
              <text class="ss-ref__upload-text">{{ uploading ? '上传中...' : '点击上传风格参考图' }}</text>
            </view>
          </template>
        </view>
      </scroll-view>

      <!-- 底部确认 -->
      <view class="ss-footer">
        <lv-button block @tap="handleConfirm">确认选择</lv-button>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { mangaApi } from '@/api'
import { useImagePicker } from '@/composables/useImagePicker'
import LvButton from '@/components/lv-button/lv-button.vue'
import LvIcon from '@/components/lv-icon/lv-icon.vue'
import { X } from '@lucide/vue'
import type { VideoStylePreset } from '@/api/admin'

const props = withDefaults(defineProps<{
  presets: VideoStylePreset[]
  selectedName: string
  styleRefUrl: string | null
  chapterId?: number | null
}>(), {
  styleRefUrl: null,
  chapterId: null
})

const emit = defineEmits<{
  (e: 'update:selectedName', val: string): void
  (e: 'update:styleRefUrl', val: string | null): void
  (e: 'close'): void
}>()

const { chooseImage } = useImagePicker()
const activeCategory = ref<string>('全部')
const localSelectedName = ref(props.selectedName)
const localRefUrl = ref<string | null>(props.styleRefUrl)
const uploading = ref(false)

/** 从预设列表提取分类（名为"全部"的统一显示为中文"全部"） */
const categories = computed<string[]>(() => {
  const cats = new Set<string>()
  for (const p of props.presets) {
    if (p.category) cats.add(p.category)
  }
  return ['全部', ...Array.from(cats)]
})

/** 当前分类对应的分类标签显示名 */
const categoryLabels: Record<string, string> = {
  '全部': '全部',
  'realistic': '写实',
  'anime': '动漫',
  'artistic': '艺术',
  'cinematic': '电影',
}

function categoryLabel(cat: string): string {
  return categoryLabels[cat] || cat
}

/** 按分类过滤后的预设列表 */
const filteredPresets = computed<VideoStylePreset[]>(() => {
  if (activeCategory.value === '全部') return props.presets
  return props.presets.filter(p => p.category === activeCategory.value)
})

function handleSelectPreset(preset: VideoStylePreset) {
  localSelectedName.value = preset.name
  localRefUrl.value = null
  // 选中预设后自动确认并关闭弹窗
  emit('update:selectedName', localSelectedName.value)
  emit('update:styleRefUrl', localRefUrl.value)
  emit('close')
}

function handleClose() {
  emit('close')
}

function handleClearRef() {
  localRefUrl.value = null
  localSelectedName.value = ''
}

async function handleUploadRef() {
  if (uploading.value || !props.chapterId) return
  uploading.value = true
  try {
    const paths = await chooseImage({ count: 1 })
    if (paths.length === 0) return
    const res = await mangaApi.uploadStyleReferenceImage(props.chapterId, paths[0])
    if (res.style_reference_image_url) {
      localRefUrl.value = res.style_reference_image_url
      localSelectedName.value = ''
    }
  } catch (e: any) {
    uni.showToast({ title: e.message || '上传失败', icon: 'none' })
  } finally {
    uploading.value = false
  }
}

function handleConfirm() {
  emit('update:selectedName', localSelectedName.value)
  emit('update:styleRefUrl', localRefUrl.value)
  emit('close')
}
</script>

<style lang="scss" scoped>
.ss-overlay {
  position: fixed;
  inset: 0;
  z-index: 1000;
  background: rgba(0, 0, 0, 0.4);
  display: flex;
  align-items: flex-end;
}

.ss-popup {
  width: 100%;
  max-height: 75vh;
  background: $lv-surface-solid;
  border-radius: 32rpx 32rpx 0 0;
  display: flex;
  flex-direction: column;
}

.ss-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 32rpx $lv-page-padding 24rpx;
  border-bottom: 1rpx solid $lv-border;

  &__title {
    font-size: $lv-font-lg;
    font-weight: 600;
    color: $lv-text-primary;
  }

  &__close {
    padding: 8rpx;
  }
}

.ss-body {
  flex: 1;
  padding: 0 $lv-page-padding $lv-page-padding;
}

// 分类标签
.ss-tabs-scroll {
  white-space: nowrap;
  padding: 24rpx 0;
}

.ss-tabs {
  display: inline-flex;
  gap: 12rpx;
}

.ss-tab {
  display: inline-flex;
  padding: 8rpx 24rpx;
  border-radius: $lv-radius-full;
  background: $lv-primary-lighter;
  font-size: $lv-font-sm;
  color: $lv-text-secondary;

  &--active {
    background: $lv-primary;
    color: $lv-text-on-primary;
  }
}

// 预设网格
.ss-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16rpx;
  padding-bottom: 24rpx;

  &__item {
    display: flex;
    flex-direction: column;
    border-radius: $lv-radius-md;
    overflow: hidden;
    border: 2rpx solid $lv-border-light;
    background: $lv-surface-solid;

    &--active {
      border-color: $lv-primary;
    }
  }

  &__image {
    width: 100%;
    aspect-ratio: 4 / 3;
    display: block;
    background: $lv-primary-lighter;
  }

  &__placeholder {
    width: 100%;
    aspect-ratio: 4 / 3;
    display: flex;
    align-items: center;
    justify-content: center;
    background: $lv-primary-lighter;
  }

  &__name {
    font-size: $lv-font-xs;
    color: $lv-text-primary;
    padding: 8rpx 8rpx 0;
    display: block;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  &__tag {
    padding: 4rpx 8rpx 8rpx;
  }

  &__tag-text {
    font-size: 20rpx;
    color: $lv-text-muted;
  }
}

// 自定义参考图
.ss-ref {
  padding-bottom: 24rpx;

  &__label {
    display: block;
    font-size: $lv-font-sm;
    color: $lv-text-secondary;
    margin-bottom: 12rpx;
  }

  &__preview {
    border-radius: $lv-radius-md;
    overflow: hidden;
    border: 1rpx solid $lv-border-light;
  }

  &__image {
    width: 100%;
    height: 240rpx;
    display: block;
    background: $lv-primary-lighter;
  }

  &__actions {
    display: flex;
    gap: 12rpx;
    padding: 12rpx;
  }

  &__upload {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 8rpx;
    height: 160rpx;
    border-radius: $lv-radius-md;
    border: 2rpx dashed $lv-border;
    background: $lv-primary-lighter;

    &:active {
      background: darken($lv-primary-lighter, 3%);
    }
  }

  &__upload-text {
    font-size: $lv-font-sm;
    color: $lv-text-muted;
  }
}

// 底部确认
.ss-footer {
  padding: $lv-page-padding;
  border-top: 1rpx solid $lv-border;
}
</style>
