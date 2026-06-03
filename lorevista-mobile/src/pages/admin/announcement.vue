<template>
  <view class="admin-announcement">
    <view class="admin-announcement__content">
      <lv-loading v-if="loading" />

      <template v-else>
        <view class="admin-announcement__section">
          <view class="admin-announcement__checkbox" @tap="announcement.enabled = !announcement.enabled">
            <lv-icon :name="announcement.enabled ? 'CheckSquare' : 'Square'" :size="18" :color="announcement.enabled ? '#2563eb' : '#94a3b8'" />
            <text class="admin-announcement__checkbox-text">启用公告弹窗</text>
          </view>

          <lv-input v-model="announcement.title" placeholder="公告标题" />
          <lv-textarea v-model="announcement.content" placeholder="公告内容（支持 HTML）" :maxlength="-1" />

          <text class="admin-announcement__preview-title">预览</text>
          <view class="admin-announcement__preview">
            <rich-text :nodes="announcement.content || '<p>暂无内容</p>'" />
          </view>
        </view>

        <view class="admin-announcement__footer">
          <lv-button :loading="saving" @tap="handleSave" block>保存公告</lv-button>
        </view>
      </template>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { adminApi } from '@/api'
import type { PlatformAnnouncement } from '@/api/admin'
import LvInput from '@/components/lv-input/lv-input.vue'
import LvTextarea from '@/components/lv-textarea/lv-textarea.vue'
import LvButton from '@/components/lv-button/lv-button.vue'
import LvLoading from '@/components/lv-loading/lv-loading.vue'
import LvIcon from '@/components/lv-icon/lv-icon.vue'

const loading = ref(false)
const saving = ref(false)
const announcement = ref<PlatformAnnouncement>({ enabled: false, title: '', content: '' })

onMounted(async () => {
  loading.value = true
  try {
    announcement.value = await adminApi.getAdminAnnouncement()
  } catch (e: any) {
    uni.showToast({ title: e.message || '加载失败', icon: 'none' })
  } finally {
    loading.value = false
  }
})

async function handleSave() {
  saving.value = true
  try {
    await adminApi.updateAdminAnnouncement(announcement.value)
    uni.showToast({ title: '保存成功', icon: 'success' })
  } catch (e: any) {
    uni.showToast({ title: e.message || '保存失败', icon: 'none' })
  } finally {
    saving.value = false
  }
}
</script>

<style lang="scss" scoped>
.admin-announcement {
  min-height: 100vh;
  background: linear-gradient(180deg, $lv-bg-start 0%, $lv-bg-end 100%);

  &__content {
    padding: calc(var(--status-bar-height) + 88rpx) $lv-page-padding $lv-page-padding;
  }

  &__section {
    background: $lv-surface-solid;
    border-radius: $lv-radius-lg;
    padding: 32rpx;
    box-shadow: $lv-shadow-sm;
  }

  &__checkbox {
    display: flex;
    align-items: center;
    gap: 12rpx;
    margin-bottom: 24rpx;
  }

  &__checkbox-text {
    font-size: $lv-font-base;
    font-weight: 500;
    color: $lv-text-primary;
  }

  &__preview-title {
    display: block;
    font-size: $lv-font-sm;
    font-weight: 600;
    color: $lv-text-secondary;
    margin-top: 24rpx;
    margin-bottom: 12rpx;
  }

  &__preview {
    background: $lv-primary-lighter;
    border-radius: $lv-radius-md;
    padding: 24rpx;
    max-height: 400rpx;
    overflow: auto;
  }

  &__footer {
    margin-top: 32rpx;
  }
}
</style>
