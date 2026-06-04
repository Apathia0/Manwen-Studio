<template>
  <view class="cover-edit">
    <lv-navbar title="封面编辑" show-back />

    <scroll-view scroll-y class="cover-edit__scroll">
      <!-- 预览 -->
      <view class="cover-edit__preview">
        <image v-if="coverUrl" :src="coverUrl" class="cover-edit__image" mode="aspectFit" />
        <view v-else class="cover-edit__placeholder">
          <lv-icon name="ImagePlus" :size="48" color="#94a3b8" />
          <text class="cover-edit__placeholder-text">点击下方按钮生成或上传封面</text>
        </view>
        <view v-if="loading !== 'idle'" class="cover-edit__loading-overlay">
          <lv-loading />
        </view>
      </view>

      <!-- 错误提示 -->
      <view v-if="error" class="cover-edit__error">
        <text class="cover-edit__error-text">{{ error }}</text>
      </view>

      <!-- 操作按钮 -->
      <view class="cover-edit__actions">
        <lv-button
          block
          class="cover-edit__btn"
          :loading="loading === 'generating'"
          @tap="handleGenerate"
        >
          <lv-icon name="Sparkles" :size="14" color="#fff" style="margin-right: 8rpx;" />
          AI 生成封面
        </lv-button>

        <lv-button
          block
          secondary
          class="cover-edit__btn"
          :loading="loading === 'uploading'"
          @tap="handleUpload"
        >
          本地上传
        </lv-button>
      </view>

      <!-- 调整 -->
      <view class="cover-edit__adjust">
        <text class="cover-edit__label">调整描述</text>
        <textarea
          v-model="prompt"
          class="cover-edit__textarea"
          placeholder="描述想要的封面风格，如：暗黑奇幻风格，主角持剑站在山顶..."
          :disabled="loading !== 'idle'"
        />
        <lv-button
          block
          secondary
          :loading="loading === 'adjusting'"
          :disabled="!prompt.trim()"
          @tap="handleAdjust"
        >
          调整封面
        </lv-button>
      </view>
    </scroll-view>
  </view>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { storiesApi } from '@/api'
import { coverImageUrl } from '@/utils/url'
import { useImagePicker } from '@/composables/useImagePicker'
import LvNavbar from '@/components/lv-navbar/lv-navbar.vue'
import LvButton from '@/components/lv-button/lv-button.vue'
import LvIcon from '@/components/lv-icon/lv-icon.vue'
import LvLoading from '@/components/lv-loading/lv-loading.vue'

const { chooseAndConvert } = useImagePicker()

let storyId = 0
const coverUrl = ref('')
const prompt = ref('')
const error = ref('')
const loading = ref<'idle' | 'generating' | 'uploading' | 'adjusting'>('idle')

onLoad((options) => {
  storyId = parseInt(options?.storyId || options?.id || '0')
  if (!storyId) {
    error.value = '参数错误'
    return
  }
  loadCover()
})

async function loadCover() {
  try {
    const story = await storiesApi.getStory(storyId)
    if (story.cover_image) {
      coverUrl.value = coverImageUrl(story.cover_image) || ''
    }
  } catch {
    // 故事不存在就跳过
  }
}

async function handleGenerate() {
  loading.value = 'generating'
  error.value = ''
  try {
    const res = await storiesApi.generateCover(storyId)
    coverUrl.value = coverImageUrl(res.cover_image) || ''
  } catch (e: any) {
    error.value = e.message || '生成失败'
  } finally {
    loading.value = 'idle'
  }
}

async function handleUpload() {
  loading.value = 'uploading'
  error.value = ''
  try {
    const base64List = await chooseAndConvert()
    if (!base64List || base64List.length < 1) {
      // 用户取消选择，立即重置 loading
      loading.value = 'idle'
      return
    }
    const res = await storiesApi.uploadCover(storyId, base64List[0])
    coverUrl.value = coverImageUrl(res.cover_image) || ''
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
    const res = await storiesApi.adjustCover(storyId, prompt.value)
    coverUrl.value = coverImageUrl(res.cover_image) || ''
  } catch (e: any) {
    error.value = e.message || '调整失败'
  } finally {
    loading.value = 'idle'
  }
}
</script>

<style lang="scss" scoped>
.cover-edit {
  min-height: 100vh;
  background: linear-gradient(180deg, $lv-bg-start 0%, $lv-bg-end 100%);

  &__scroll {
    padding: calc(var(--status-bar-height) + 88rpx + $lv-page-padding) $lv-page-padding 80rpx;
  }

  &__preview {
    position: relative;
    width: 100%;
    aspect-ratio: 3/4;
    max-height: 600rpx;
    background: $lv-primary-lighter;
    border-radius: $lv-radius-lg;
    overflow: hidden;
    margin-bottom: $lv-section-gap;
    display: flex;
    align-items: center;
    justify-content: center;
  }

  &__image {
    width: 100%;
    height: 100%;
  }

  &__placeholder {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 16rpx;
    color: $lv-text-muted;
  }

  &__placeholder-text {
    font-size: $lv-font-sm;
  }

  &__loading-overlay {
    position: absolute;
    inset: 0;
    background: rgba(255, 255, 255, 0.6);
    display: flex;
    align-items: center;
    justify-content: center;
  }

  &__error {
    background: #fef2f2;
    border-radius: $lv-radius-sm;
    padding: 16rpx;
    margin-bottom: $lv-section-gap;
  }

  &__error-text {
    font-size: $lv-font-sm;
    color: $lv-error;
  }

  &__actions {
    display: flex;
    flex-direction: column;
    gap: 16rpx;
    margin-bottom: $lv-section-gap;
  }

  &__adjust {
    display: flex;
    flex-direction: column;
    gap: 12rpx;
  }

  &__label {
    display: block;
    font-size: $lv-font-sm;
    color: $lv-text-secondary;
    font-weight: 500;
  }

  &__textarea {
    width: 100%;
    min-height: 120rpx;
    padding: 20rpx;
    border: 1rpx solid $lv-border;
    border-radius: $lv-radius-sm;
    font-size: $lv-font-sm;
    color: $lv-text-primary;
    background: #fff;
    line-height: 1.5;
    resize: none;
    box-sizing: border-box;

    &::placeholder {
      color: $lv-text-muted;
    }

    &:disabled {
      background: $lv-primary-lighter;
    }
  }
}
</style>
