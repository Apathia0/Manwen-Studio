<template>
  <view class="model-config">
    <view class="model-config__content">
      <!-- 说明 -->
      <view class="model-config__info">
        <lv-icon name="Info" :size="14" color="#2563eb" />
        <text class="model-config__info-text">自定义配置仅对当前设备生效，启用自定义中转地址后不扣减平台套餐配额。</text>
      </view>

      <!-- 文本模型 -->
      <view class="model-config__section">
        <text class="model-config__section-title">文本模型</text>
        <view class="model-config__platform-info">
          <text class="model-config__platform-label">平台地址：</text>
          <text class="model-config__platform-value">{{ platformApi?.deepseek_base_url || '-' }}</text>
        </view>
        <view class="model-config__platform-info">
          <text class="model-config__platform-label">平台模型：</text>
          <text class="model-config__platform-value">{{ platformApi?.deepseek_model || '-' }}</text>
        </view>
        <view class="model-config__fields">
          <lv-input
            v-model="textBaseUrl"
            placeholder="自定义 DeepSeek Base URL"
            :disabled="!canOverrideUrl"
          />
          <lv-input
            v-model="textModel"
            placeholder="自定义 DeepSeek 模型名"
            :disabled="!canOverrideUrl"
          />
          <lv-input
            v-model="textApiKey"
            placeholder="自定义 DeepSeek API Key"
            type="password"
            :disabled="!canOverrideKey"
          />
        </view>
      </view>

      <!-- 图片模型 -->
      <view class="model-config__section">
        <text class="model-config__section-title">图片模型</text>
        <view class="model-config__platform-info">
          <text class="model-config__platform-label">平台地址：</text>
          <text class="model-config__platform-value">{{ platformApi?.image_base_url || '-' }}</text>
        </view>
        <view class="model-config__platform-info">
          <text class="model-config__platform-label">平台模型：</text>
          <text class="model-config__platform-value">{{ platformApi?.image_model || '-' }}</text>
        </view>
        <view class="model-config__fields">
          <lv-input
            v-model="imageBaseUrl"
            placeholder="自定义图片服务 Base URL"
            :disabled="!canOverrideUrl"
          />
          <lv-input
            v-model="imageModel"
            placeholder="自定义图片模型名"
            :disabled="!canOverrideUrl"
          />
          <lv-input
            v-model="imageApiKey"
            placeholder="自定义图片 API Key"
            type="password"
            :disabled="!canOverrideKey"
          />
        </view>
      </view>

      <!-- 操作按钮 -->
      <view class="model-config__actions">
        <lv-button @tap="handleSave" block>保存本地配置</lv-button>
        <lv-button secondary @tap="handleClear" block>清空本地配置</lv-button>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { usePlatformStore } from '@/stores/platform'
import { useAuthStore } from '@/stores/auth'
import { getStorage, setStorage, removeStorage } from '@/utils/storage'
import { STORAGE_KEYS } from '@/utils/constants'
import LvInput from '@/components/lv-input/lv-input.vue'
import LvButton from '@/components/lv-button/lv-button.vue'
import LvIcon from '@/components/lv-icon/lv-icon.vue'

const platformStore = usePlatformStore()
const authStore = useAuthStore()

const platformApi = computed(() => platformStore.settings?.api || null)

// 用户权限检查
const canOverrideKey = computed(() => {
  return authStore.user?.can_override_api_key ?? false
})
const canOverrideUrl = computed(() => {
  return authStore.user?.can_override_api_url ?? false
})

// 本地配置
const textBaseUrl = ref('')
const textModel = ref('')
const textApiKey = ref('')
const imageBaseUrl = ref('')
const imageModel = ref('')
const imageApiKey = ref('')

onMounted(async () => {
  // 加载平台配置
  await platformStore.fetchSettings().catch(() => {})

  // 加载本地存储的配置
  textBaseUrl.value = getStorage(STORAGE_KEYS.DEEPSEEK_BASE_URL) || ''
  textModel.value = getStorage(STORAGE_KEYS.DEEPSEEK_MODEL) || ''
  textApiKey.value = getStorage(STORAGE_KEYS.DEEPSEEK_API_KEY) || ''
  imageBaseUrl.value = getStorage(STORAGE_KEYS.IMAGE_BASE_URL) || ''
  imageModel.value = getStorage(STORAGE_KEYS.IMAGE_MODEL) || ''
  imageApiKey.value = getStorage(STORAGE_KEYS.IMAGE_API_KEY) || ''
})

function handleSave() {
  setStorage(STORAGE_KEYS.DEEPSEEK_BASE_URL, textBaseUrl.value)
  setStorage(STORAGE_KEYS.DEEPSEEK_MODEL, textModel.value)
  setStorage(STORAGE_KEYS.DEEPSEEK_API_KEY, textApiKey.value)
  setStorage(STORAGE_KEYS.IMAGE_BASE_URL, imageBaseUrl.value)
  setStorage(STORAGE_KEYS.IMAGE_MODEL, imageModel.value)
  setStorage(STORAGE_KEYS.IMAGE_API_KEY, imageApiKey.value)
  uni.showToast({ title: '已保存', icon: 'success' })
}

function handleClear() {
  uni.showModal({
    title: '确认清空',
    content: '确定清空所有自定义模型配置？',
    success: (res) => {
      if (res.confirm) {
        textBaseUrl.value = ''
        textModel.value = ''
        textApiKey.value = ''
        imageBaseUrl.value = ''
        imageModel.value = ''
        imageApiKey.value = ''
        removeStorage(STORAGE_KEYS.DEEPSEEK_BASE_URL)
        removeStorage(STORAGE_KEYS.DEEPSEEK_MODEL)
        removeStorage(STORAGE_KEYS.DEEPSEEK_API_KEY)
        removeStorage(STORAGE_KEYS.IMAGE_BASE_URL)
        removeStorage(STORAGE_KEYS.IMAGE_MODEL)
        removeStorage(STORAGE_KEYS.IMAGE_API_KEY)
        uni.showToast({ title: '已清空', icon: 'success' })
      }
    }
  })
}
</script>

<style lang="scss" scoped>
.model-config {
  min-height: 100vh;
  background: linear-gradient(180deg, $lv-bg-start 0%, $lv-bg-end 100%);

  &__content {
    padding: calc(var(--status-bar-height) + 88rpx) $lv-page-padding $lv-page-padding;
  }

  &__info {
    display: flex;
    align-items: flex-start;
    gap: 12rpx;
    background: rgba($lv-primary, 0.06);
    border-radius: $lv-radius-md;
    padding: 24rpx;
    margin-bottom: $lv-section-gap;
  }

  &__info-text {
    flex: 1;
    font-size: $lv-font-xs;
    color: $lv-primary;
    line-height: 1.5;
  }

  &__section {
    background: $lv-surface-solid;
    border-radius: $lv-radius-lg;
    padding: 32rpx;
    margin-bottom: $lv-section-gap;
    box-shadow: $lv-shadow-sm;
  }

  &__section-title {
    display: block;
    font-size: $lv-font-lg;
    font-weight: 600;
    color: $lv-text-primary;
    margin-bottom: 20rpx;
  }

  &__platform-info {
    display: flex;
    align-items: center;
    margin-bottom: 8rpx;
  }

  &__platform-label {
    font-size: $lv-font-xs;
    color: $lv-text-muted;
    margin-right: 8rpx;
  }

  &__platform-value {
    font-size: $lv-font-xs;
    color: $lv-text-secondary;
    word-break: break-all;
  }

  &__fields {
    margin-top: 24rpx;
    display: flex;
    flex-direction: column;
    gap: 20rpx;
  }

  &__actions {
    display: flex;
    flex-direction: column;
    gap: 20rpx;
    margin-top: 40rpx;
  }
}
</style>
