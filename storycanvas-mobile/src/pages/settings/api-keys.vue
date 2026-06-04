<template>
  <view class="api-keys-page">
    <lv-navbar title="API 密钥" show-back />
    <view class="api-keys-page__content">
      <view class="api-keys-page__hint">
        <text class="api-keys-page__hint-title">安全提示</text>
        <text>请勿将密钥分享给他人。密钥拥有完整操作权限。</text>
      </view>

      <view v-for="key in keys" :key="key.id" class="api-keys-page__item">
        <view class="api-keys-page__item-header">
          <text>{{ key.name }}</text>
          <text class="api-keys-page__masked">{{ maskKey(key.key) }}</text>
        </view>
        <view class="api-keys-page__item-actions">
          <text @tap="copyKey(key.key)">复制</text>
          <text @tap="deleteKey(key.id)">删除</text>
        </view>
      </view>

      <lv-button block @tap="createNewKey">创建新密钥</lv-button>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { get, del, post } from '@/utils/request'
import LvNavbar from '@/components/lv-navbar/lv-navbar.vue'
import LvButton from '@/components/lv-button/lv-button.vue'

interface ApiKey { id: number; name: string; key: string }
const keys = ref<ApiKey[]>([])

onMounted(async () => {
  try { keys.value = await get<ApiKey[]>('/api/settings/api-keys') } catch (e) { console.error(e) }
})

function maskKey(key: string) { return key.slice(0, 8) + '...' + key.slice(-4) }
function copyKey(key: string) { uni.setClipboardData({ data: key }); uni.showToast({ title: '已复制', icon: 'success' }) }
async function deleteKey(id: number) { try { await del(`/api/settings/api-keys/${id}`); keys.value = keys.value.filter(k => k.id !== id) } catch (e) { console.error(e) } }
async function createNewKey() {
  try {
    const newKey = await post('/api/settings/api-keys', { name: `Key-${Date.now()}` }) as any
    keys.value.push(newKey)
  } catch (e) { console.error(e) }
}
</script>

<style lang="scss" scoped>
.api-keys-page { min-height: 100vh; background: $lv-bg-start;
  &__content { padding: calc(var(--status-bar-height) + 88rpx + $lv-page-padding) $lv-page-padding; }
  &__hint { background: #fef9c3; border-radius: 16rpx; padding: 20rpx; margin-bottom: 24rpx; font-size: 22rpx; color: #854d0e; }
  &__hint-title { display: block; font-weight: 600; margin-bottom: 8rpx; }
  &__item { background: #fff; border-radius: 24rpx; padding: 24rpx; margin-bottom: 16rpx; }
  &__item-header { margin-bottom: 12rpx; font-size: 26rpx; } &__masked { display: block; font-family: monospace; font-size: 22rpx; color: $lv-text-muted; margin-top: 4rpx; }
  &__item-actions { display: flex; gap: 24rpx; font-size: 24rpx; color: $lv-primary; }
}
</style>
