<template>
  <view class="cep-overlay" v-if="modelValue" @tap.self="close">
    <view class="cep-popup">
      <view class="cep-header">
        <text class="cep-header__title">封面编辑</text>
        <view class="cep-header__close" @tap="close">
          <X :size="20" color="#94a3b8" />
        </view>
      </view>

      <scroll-view scroll-y class="cep-body">
        <!-- 预览 -->
        <view class="cep-preview" @tap="handleTapUpload">
          <image v-if="previewUrl" :src="previewUrl" class="cep-preview__img" mode="aspectFit" />
          <view v-else class="cep-preview__placeholder">
            <lv-icon name="ImagePlus" :size="48" color="#94a3b8" />
            <text class="cep-preview__hint">点击上传封面</text>
          </view>
        </view>

        <!-- AI 生成 -->
        <lv-button block class="cep-btn" :loading="loading === 'generating'" @tap="handleGenerate">
          <lv-icon name="Sparkles" :size="14" color="#fff" style="margin-right: 8rpx;" />
          AI 生成封面
        </lv-button>

        <!-- 本地上传 -->
        <lv-button block secondary class="cep-btn" :loading="loading === 'uploading'" @tap="handleTapUpload">
          本地上传
        </lv-button>

        <!-- 调整 -->
        <view class="cep-adjust">
          <text class="cep-adjust__label">调整描述（可选）</text>
          <lv-input v-model="prompt" placeholder="描述想要的封面风格..." />
          <lv-button
            block
            secondary
            class="cep-btn"
            :loading="loading === 'adjusting'"
            :disabled="!prompt.trim()"
            @tap="handleAdjust"
          >
            调整封面
          </lv-button>
        </view>

        <!-- 错误提示 -->
        <view v-if="error" class="cep-error">
          <text class="cep-error__text">{{ error }}</text>
        </view>
      </scroll-view>

      <!-- 底部保存按钮 -->
      <view class="cep-footer">
        <lv-button block :disabled="!previewUrl" @tap="handleSave">
          保存
        </lv-button>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { storiesApi } from '@/api'
import { coverImageUrl } from '@/utils/url'
import { useImagePicker } from '@/composables/useImagePicker'
import LvButton from '@/components/lv-button/lv-button.vue'
import LvInput from '@/components/lv-input/lv-input.vue'
import LvIcon from '@/components/lv-icon/lv-icon.vue'
import { X } from '@lucide/vue'

const props = withDefaults(defineProps<{
  modelValue: boolean
  storyId: number
  coverImage?: string | null
}>(), {
  coverImage: null
})

const emit = defineEmits<{
  (e: 'update:modelValue', val: boolean): void
  (e: 'cover-updated', coverImage: string): void
}>()

const { chooseAndConvert } = useImagePicker()
const previewUrl = ref('')
const prompt = ref('')
const error = ref('')
const loading = ref<'idle' | 'generating' | 'uploading' | 'adjusting'>('idle')

watch(() => props.modelValue, (val) => {
  if (val) {
    error.value = ''
    prompt.value = ''
    previewUrl.value = coverImageUrl(props.coverImage || null) || ''
  }
})

watch(() => props.coverImage, (val) => {
  if (props.modelValue) {
    previewUrl.value = coverImageUrl(val || null) || ''
  }
})

function close() {
  if (loading.value !== 'idle') return
  emit('update:modelValue', false)
}

async function handleGenerate() {
  loading.value = 'generating'
  error.value = ''
  try {
    const res = await storiesApi.generateCover(props.storyId)
    previewUrl.value = coverImageUrl(res.cover_image) || ''
  } catch (e: any) {
    error.value = e.message || '生成失败'
  } finally {
    loading.value = 'idle'
  }
}

async function handleTapUpload() {
  if (loading.value !== 'idle') return
  loading.value = 'uploading'
  error.value = ''
  try {
    const base64List = await chooseAndConvert()
    if (base64List.length > 0) {
      const res = await storiesApi.uploadCover(props.storyId, base64List[0])
      previewUrl.value = coverImageUrl(res.cover_image) || ''
    }
  } catch (e: any) {
    error.value = e.message || '上传失败'
  } finally {
    loading.value = 'idle'
  }
}

async function handleAdjust() {
  if (!prompt.value.trim() || loading.value !== 'idle') return
  loading.value = 'adjusting'
  error.value = ''
  try {
    const res = await storiesApi.adjustCover(props.storyId, prompt.value)
    previewUrl.value = coverImageUrl(res.cover_image) || ''
  } catch (e: any) {
    error.value = e.message || '调整失败'
  } finally {
    loading.value = 'idle'
  }
}

function handleSave() {
  if (!previewUrl.value) return
  emit('cover-updated', previewUrl.value)
  close()
}
</script>

<style lang="scss" scoped>
.cep-overlay {
  position: fixed;
  inset: 0;
  z-index: 1000;
  background: rgba(0, 0, 0, 0.4);
  display: flex;
  align-items: flex-end;
}

.cep-popup {
  width: 100%;
  max-height: 75vh;
  background: $lv-surface-solid;
  border-radius: 32rpx 32rpx 0 0;
  display: flex;
  flex-direction: column;
}

.cep-header {
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

.cep-body {
  flex: 1;
  padding: $lv-page-padding;
}

.cep-preview {
  width: 100%;
  aspect-ratio: 3/4;
  background: $lv-primary-lighter;
  border-radius: $lv-radius-lg;
  overflow: hidden;
  margin-bottom: $lv-section-gap;
  display: flex;
  align-items: center;
  justify-content: center;

  &__img {
    width: 100%;
    height: 100%;
  }

  &__placeholder {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 16rpx;
  }

  &__hint {
    font-size: $lv-font-sm;
    color: $lv-text-muted;
  }
}

.cep-btn {
  margin-bottom: 16rpx;
}

.cep-adjust {
  margin-top: 16rpx;

  &__label {
    display: block;
    font-size: $lv-font-sm;
    color: $lv-text-secondary;
    margin-bottom: 12rpx;
  }
}

.cep-error {
  background: #fef2f2;
  border-radius: $lv-radius-sm;
  padding: 16rpx;
  margin-top: 8rpx;

  &__text {
    font-size: $lv-font-sm;
    color: $lv-error;
  }
}

.cep-footer {
  padding: $lv-page-padding;
  border-top: 1rpx solid $lv-border;
}
</style>
