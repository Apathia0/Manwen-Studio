<template>
  <view class="admin-audit">
    <view class="admin-audit__content">
      <view class="admin-audit__header">
        <lv-input v-model="searchQuery" placeholder="搜索操作人、动作、目标..." clearable />
        <lv-button size="sm" secondary @tap="loadLogs">刷新</lv-button>
      </view>

      <lv-loading v-if="loading" />

      <view v-else-if="filteredLogs.length === 0" class="admin-audit__empty">
        <lv-empty title="暂无审计日志" />
      </view>

      <view v-else class="admin-audit__list">
        <view v-for="log in filteredLogs" :key="log.id" class="admin-audit__item">
          <view class="admin-audit__item-header">
            <lv-tag type="primary" :text="log.action" size="sm" />
            <text class="admin-audit__item-time">{{ log.created_at }}</text>
          </view>
          <view class="admin-audit__item-info">
            <text class="admin-audit__item-actor">{{ log.actor_name || '系统' }}</text>
            <text class="admin-audit__item-target">{{ log.target_type }} {{ log.target_id || '' }}</text>
          </view>
          <text v-if="log.summary" class="admin-audit__item-summary">{{ log.summary }}</text>
          <view v-if="log.detail && Object.keys(log.detail).length > 0" class="admin-audit__item-detail">
            <text class="admin-audit__item-detail-text">{{ JSON.stringify(log.detail, null, 2) }}</text>
          </view>
        </view>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { adminApi } from '@/api'
import type { AdminAuditLogItem } from '@/api/admin'
import LvInput from '@/components/lv-input/lv-input.vue'
import LvButton from '@/components/lv-button/lv-button.vue'
import LvTag from '@/components/lv-tag/lv-tag.vue'
import LvLoading from '@/components/lv-loading/lv-loading.vue'
import LvEmpty from '@/components/lv-empty/lv-empty.vue'

const loading = ref(false)
const logs = ref<AdminAuditLogItem[]>([])
const searchQuery = ref('')

const filteredLogs = computed(() => {
  const q = searchQuery.value.toLowerCase()
  if (!q) return logs.value
  return logs.value.filter(l =>
    l.actor_name?.toLowerCase().includes(q) ||
    l.action.toLowerCase().includes(q) ||
    l.target_type?.toLowerCase().includes(q) ||
    l.summary?.toLowerCase().includes(q)
  )
})

onMounted(() => loadLogs())

async function loadLogs() {
  loading.value = true
  try {
    logs.value = await adminApi.getAdminAuditLogs({ limit: 200 })
  } catch (e: any) {
    uni.showToast({ title: e.message || '加载失败', icon: 'none' })
  } finally {
    loading.value = false
  }
}
</script>

<style lang="scss" scoped>
.admin-audit {
  min-height: 100vh;
  background: linear-gradient(180deg, $lv-bg-start 0%, $lv-bg-end 100%);

  &__content {
    padding: $lv-page-padding;
  }

  &__header {
    display: flex;
    gap: 16rpx;
    margin-bottom: 20rpx;
  }

  &__list {
    display: flex;
    flex-direction: column;
    gap: 16rpx;
  }

  &__item {
    background: $lv-surface-solid;
    border-radius: $lv-radius-lg;
    padding: 24rpx;
    box-shadow: $lv-shadow-sm;
  }

  &__item-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 12rpx;
  }

  &__item-time {
    font-size: $lv-font-xs;
    color: $lv-text-muted;
  }

  &__item-info {
    display: flex;
    gap: 16rpx;
    margin-bottom: 8rpx;
  }

  &__item-actor {
    font-size: $lv-font-sm;
    font-weight: 500;
    color: $lv-text-primary;
  }

  &__item-target {
    font-size: $lv-font-sm;
    color: $lv-text-secondary;
  }

  &__item-summary {
    display: block;
    font-size: $lv-font-sm;
    color: $lv-text-secondary;
    margin-bottom: 8rpx;
  }

  &__item-detail {
    background: $lv-primary-lighter;
    border-radius: $lv-radius-sm;
    padding: 16rpx;
    max-height: 300rpx;
    overflow: auto;
  }

  &__item-detail-text {
    font-size: $lv-font-xs;
    font-family: monospace;
    color: $lv-text-secondary;
    white-space: pre-wrap;
    word-break: break-all;
  }

  &__empty {
    padding: 60rpx 0;
  }
}
</style>
