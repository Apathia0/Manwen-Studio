<template>
  <scroll-view class="admin-system-update" scroll-y>
    <!-- 头部 -->
    <view class="admin-system-update__header">
      <text class="admin-system-update__title">系统更新</text>
      <lv-button size="sm" secondary :loading="statusLoading" @tap="loadStatus">刷新状态</lv-button>
    </view>

    <!-- 当前状态 -->
    <view class="admin-system-update__card">
      <view class="admin-system-update__card-row">
        <text class="admin-system-update__label">当前状态</text>
        <view
          class="admin-system-update__status-badge"
          :class="`admin-system-update__status-badge--${status.status}`"
        >
          {{ statusLabel(status.status) }}
        </view>
      </view>
      <view class="admin-system-update__card-row">
        <text class="admin-system-update__label">当前版本</text>
        <text class="admin-system-update__value">{{ status.current_version || '未知' }}</text>
      </view>
      <view v-if="status.target_version" class="admin-system-update__card-row">
        <text class="admin-system-update__label">目标版本</text>
        <text class="admin-system-update__value">{{ status.target_version }}</text>
      </view>
      <view v-if="status.message" class="admin-system-update__card-row">
        <text class="admin-system-update__label">消息</text>
        <text class="admin-system-update__value">{{ status.message }}</text>
      </view>
    </view>

    <!-- 检测更新 -->
    <view class="admin-system-update__section">
      <view class="admin-system-update__section-header">
        <text class="admin-system-update__section-title">版本检测</text>
        <lv-button size="sm" :loading="checkLoading" @tap="handleCheckUpdate">检测更新</lv-button>
      </view>
      <view v-if="updateCheck" class="admin-system-update__card">
        <view class="admin-system-update__card-row">
          <text class="admin-system-update__label">当前版本</text>
          <text class="admin-system-update__value">{{ updateCheck.current_version }}</text>
        </view>
        <view class="admin-system-update__card-row">
          <text class="admin-system-update__label">最新版本</text>
          <text class="admin-system-update__value">{{ updateCheck.latest_version || '未知' }}</text>
        </view>
        <view class="admin-system-update__card-row">
          <text class="admin-system-update__label">可更新</text>
          <text
            class="admin-system-update__value"
            :class="updateCheck.update_available ? 'admin-system-update__text--warn' : 'admin-system-update__text--ok'"
          >
            {{ updateCheck.update_available ? '是' : '否' }}
          </text>
        </view>
        <view v-if="updateCheck.release_notes" class="admin-system-update__card-row">
          <text class="admin-system-update__label">更新说明</text>
          <text class="admin-system-update__value admin-system-update__value--notes">{{ updateCheck.release_notes }}</text>
        </view>
      </view>
    </view>

    <!-- 手动更新 -->
    <view class="admin-system-update__section">
      <text class="admin-system-update__section-title">执行更新</text>
      <view class="admin-system-update__card">
        <lv-input
          v-model="targetVersion"
          label="目标版本（留空使用默认版本）"
          placeholder="如 v1.2.3"
        />
        <lv-button
          block
          :loading="startLoading"
          :disabled="status.running"
          class="admin-system-update__start-btn"
          @tap="handleStart"
        >
          {{ status.running ? '更新执行中...' : '开始更新' }}
        </lv-button>
      </view>
    </view>

    <!-- 更新日志 -->
    <view class="admin-system-update__section">
      <text class="admin-system-update__section-title">执行日志</text>
      <view class="admin-system-update__log-container">
        <text class="admin-system-update__log-text">{{ logText }}</text>
      </view>
    </view>
  </scroll-view>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { adminApi } from '@/api'
import type { AdminSystemUpdateStatus, AdminSystemUpdateCheck } from '@/api/admin'
import LvButton from '@/components/lv-button/lv-button.vue'
import LvInput from '@/components/lv-input/lv-input.vue'

const status = ref<AdminSystemUpdateStatus>({
  status: 'idle',
  message: '',
  running: false,
  log_tail: [],
})
const updateCheck = ref<AdminSystemUpdateCheck | null>(null)
const targetVersion = ref('')
const statusLoading = ref(false)
const checkLoading = ref(false)
const startLoading = ref(false)

let pollTimer: ReturnType<typeof setInterval> | null = null

const logText = computed(() => {
  const lines = status.value.log_tail || []
  return lines.length > 0 ? lines.join('\n') : '暂无日志'
})

function statusLabel(s: string): string {
  const m: Record<string, string> = {
    idle: '空闲',
    queued: '排队中',
    running: '执行中',
    succeeded: '已完成',
    failed: '失败',
    unknown: '未知',
  }
  return m[s] || s
}

onMounted(() => {
  loadStatus()
})

onUnmounted(() => {
  stopPolling()
})

function startPolling() {
  stopPolling()
  pollTimer = setInterval(loadStatus, 3000)
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

async function loadStatus() {
  statusLoading.value = true
  try {
    const data = await adminApi.getAdminSystemUpdateStatus()
    status.value = data
    if (data.running) {
      startPolling()
    } else {
      stopPolling()
    }
  } catch (e: any) {
    uni.showToast({ title: e.message || '获取状态失败', icon: 'none' })
  } finally {
    statusLoading.value = false
  }
}

async function handleCheckUpdate() {
  checkLoading.value = true
  try {
    const data = await adminApi.checkAdminSystemUpdate()
    updateCheck.value = data
    uni.showToast({
      title: data.update_available ? `检测到新版本 ${data.latest_version}` : '当前已是最新版本',
      icon: 'none',
    })
  } catch (e: any) {
    uni.showToast({ title: e.message || '检测失败', icon: 'none' })
  } finally {
    checkLoading.value = false
  }
}

async function handleStart() {
  const versionText = targetVersion.value ? `目标版本：${targetVersion.value}` : '使用默认版本'
  uni.showModal({
    title: '确认执行系统更新',
    content: versionText,
    success: async (res) => {
      if (res.confirm) {
        startLoading.value = true
        try {
          const next = await adminApi.startAdminSystemUpdate(targetVersion.value || undefined)
          status.value = next
          uni.showToast({ title: '系统更新已启动', icon: 'success' })
          if (next.running) {
            startPolling()
          }
        } catch (e: any) {
          uni.showToast({ title: e.message || '启动更新失败', icon: 'none' })
        } finally {
          startLoading.value = false
        }
      }
    },
  })
}
</script>

<style lang="scss" scoped>
.admin-system-update {
  min-height: 100vh;
  background: linear-gradient(180deg, $lv-bg-start 0%, $lv-bg-end 100%);

  &__header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: $lv-page-padding;
    padding-bottom: 0;
  }

  &__title {
    font-size: $lv-font-lg;
    font-weight: 600;
    color: $lv-text-primary;
  }

  &__card {
    margin: $lv-page-padding;
    margin-top: 0;
    background: $lv-surface-solid;
    border-radius: $lv-radius-lg;
    padding: 24rpx;
    box-shadow: $lv-shadow-sm;
  }

  &__card-row {
    display: flex;
    align-items: flex-start;
    margin-bottom: 16rpx;

    &:last-child {
      margin-bottom: 0;
    }
  }

  &__label {
    flex-shrink: 0;
    width: 140rpx;
    font-size: $lv-font-sm;
    color: $lv-text-muted;
  }

  &__value {
    flex: 1;
    font-size: $lv-font-sm;
    color: $lv-text-primary;
    word-break: break-all;

    &--notes {
      color: $lv-text-secondary;
      line-height: 1.5;
    }
  }

  &__text--warn {
    color: #f59e0b;
  }

  &__text--ok {
    color: #22c55e;
  }

  &__status-badge {
    display: inline-block;
    padding: 4rpx 16rpx;
    border-radius: 100rpx;
    font-size: $lv-font-xs;
    font-weight: 500;

    &--idle {
      background: $lv-primary-lighter;
      color: $lv-primary;
    }

    &--queued {
      background: #fef3c7;
      color: #d97706;
    }

    &--running {
      background: #dbeafe;
      color: #2563eb;
    }

    &--succeeded {
      background: #dcfce7;
      color: #16a34a;
    }

    &--failed {
      background: #fee2e2;
      color: #dc2626;
    }

    &--unknown {
      background: #f1f5f9;
      color: #94a3b8;
    }
  }

  &__section {
    margin-bottom: 24rpx;
    padding: 0 $lv-page-padding;
  }

  &__section-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 16rpx;
  }

  &__section-title {
    display: block;
    font-size: $lv-font-md;
    font-weight: 600;
    color: $lv-text-primary;
    margin-bottom: 16rpx;
  }

  &__section-header &__section-title {
    margin-bottom: 0;
  }

  &__start-btn {
    margin-top: 20rpx;
  }

  &__log-container {
    background: #1e293b;
    border-radius: $lv-radius-lg;
    padding: 20rpx;
    max-height: 500rpx;
    overflow: auto;
  }

  &__log-text {
    display: block;
    font-family: 'Courier New', monospace;
    font-size: 20rpx;
    color: #e2e8f0;
    line-height: 1.6;
    white-space: pre-wrap;
    word-break: break-all;
  }
}
</style>
