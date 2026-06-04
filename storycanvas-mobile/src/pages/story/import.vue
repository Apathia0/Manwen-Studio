<template>
  <view class="import-page">
    <lv-navbar title="导入小说" show-back />
    <view class="import-page__content">
      <lv-button block @tap="chooseFile">选择文件</lv-button>
      <view v-if="selectedFile" class="import-page__file">
        <FileText :size="24" color="#475569" />
        <text class="import-page__file-name">{{ selectedFile }}</text>
      </view>
      <view class="import-page__hint">
        <text class="import-page__hint-text">支持 txt, md, docx 格式</text>
        <text class="import-page__hint-text">文件大小不超过 10MB</text>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { FileText } from '@lucide/vue'
import LvNavbar from '@/components/lv-navbar/lv-navbar.vue'
import LvButton from '@/components/lv-button/lv-button.vue'

const selectedFile = ref('')

function chooseFile() {
  // #ifdef MP-WEIXIN
  ;(uni as any).chooseMessageFile({
    count: 1, type: 'file', extension: ['txt', 'md', 'docx'],
    success: (res: any) => {
      selectedFile.value = res.tempFiles[0].name
      uni.navigateTo({ url: '/pages/story/import-guidance' })
    }
  })
  // #endif
  // #ifndef MP-WEIXIN
  uni.showToast({ title: '文件选择功能', icon: 'none' })
  // #endif
}
</script>

<style lang="scss" scoped>
.import-page {
  min-height: 100vh; background: $lv-bg-start;
  &__content { padding: calc(var(--status-bar-height) + 88rpx + $lv-page-padding) $lv-page-padding; }
  &__file { display: flex; align-items: center; background: #fff; border-radius: 24rpx; padding: 28rpx; margin-top: 24rpx; gap: 16rpx; }
  &__file-name { font-size: 28rpx; color: $lv-text-primary; }
  &__hint { margin-top: 32rpx; text-align: center; }
  &__hint-text { display: block; font-size: 22rpx; color: $lv-text-muted; }
}
</style>
