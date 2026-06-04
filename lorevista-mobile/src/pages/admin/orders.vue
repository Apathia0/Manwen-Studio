<template>
  <view class="admin-orders">
    <view class="admin-orders__content">
      <view class="admin-orders__header">
        <lv-button size="sm" secondary @tap="loadOrders">刷新订单</lv-button>
      </view>

      <lv-loading v-if="loading" />

      <view v-else-if="orders.length === 0" class="admin-orders__empty">
        <lv-empty title="暂无订单" />
      </view>

      <view v-else class="admin-orders__list">
        <view v-for="order in orders" :key="order.order_no" class="admin-orders__item">
          <view class="admin-orders__item-header">
            <text class="admin-orders__item-no">{{ order.order_no }}</text>
            <lv-tag :type="statusType(order.status)" :text="statusLabel(order.status)" size="sm" />
          </view>
          <view class="admin-orders__item-info">
            <text class="admin-orders__item-user">{{ order.user_name || `用户 #${order.user_id}` }}</text>
            <text class="admin-orders__item-plan">{{ order.plan_name || '-' }}</text>
            <text class="admin-orders__item-amount">{{ order.currency }} {{ order.amount }}</text>
          </view>
          <text class="admin-orders__item-time">{{ order.created_at }}</text>
          <view v-if="order.status === 'pending'" class="admin-orders__item-actions">
            <lv-button size="sm" @tap="handleStatus(order, 'paid')">标记已支付</lv-button>
            <lv-button size="sm" type="danger" @tap="handleStatus(order, 'cancelled')">取消</lv-button>
          </view>
        </view>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { adminApi } from '@/api'
import type { AdminOrderItem } from '@/api/admin'
import LvButton from '@/components/lv-button/lv-button.vue'
import LvTag from '@/components/lv-tag/lv-tag.vue'
import LvLoading from '@/components/lv-loading/lv-loading.vue'
import LvEmpty from '@/components/lv-empty/lv-empty.vue'

const loading = ref(false)
const orders = ref<AdminOrderItem[]>([])

const statusLabels: Record<string, string> = {
  pending: '待支付',
  paid: '已支付',
  cancelled: '已取消',
  expired: '已过期',
}

function statusLabel(status: string): string {
  return statusLabels[status] || status
}

function statusType(status: string): string {
  if (status === 'paid') return 'success'
  if (status === 'pending') return 'warning'
  if (status === 'cancelled' || status === 'expired') return 'default'
  return 'default'
}

onMounted(() => loadOrders())

async function loadOrders() {
  loading.value = true
  try {
    orders.value = await adminApi.getAdminOrders()
  } catch (e: any) {
    uni.showToast({ title: e.message || '加载失败', icon: 'none' })
  } finally {
    loading.value = false
  }
}

async function handleStatus(order: AdminOrderItem, status: 'paid' | 'cancelled' | 'expired') {
  try {
    await adminApi.updateAdminOrderStatus(order.order_no, status)
    uni.showToast({ title: '已更新', icon: 'success' })
    await loadOrders()
  } catch (e: any) {
    uni.showToast({ title: e.message || '操作失败', icon: 'none' })
  }
}
</script>

<style lang="scss" scoped>
.admin-orders {
  min-height: 100vh;
  background: linear-gradient(180deg, $lv-bg-start 0%, $lv-bg-end 100%);

  &__content {
    padding: $lv-page-padding;
  }

  &__header {
    display: flex;
    justify-content: flex-end;
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

  &__item-no {
    font-size: $lv-font-xs;
    font-family: monospace;
    color: $lv-text-secondary;
  }

  &__item-info {
    display: flex;
    gap: 16rpx;
    margin-bottom: 8rpx;
    flex-wrap: wrap;
  }

  &__item-user {
    font-size: $lv-font-sm;
    font-weight: 500;
    color: $lv-text-primary;
  }

  &__item-plan {
    font-size: $lv-font-sm;
    color: $lv-text-secondary;
  }

  &__item-amount {
    font-size: $lv-font-sm;
    font-weight: 600;
    color: $lv-primary;
  }

  &__item-time {
    font-size: $lv-font-xs;
    color: $lv-text-muted;
    margin-bottom: 12rpx;
  }

  &__item-actions {
    display: flex;
    gap: 12rpx;
    border-top: 1rpx solid $lv-border-light;
    padding-top: 16rpx;
  }

  &__empty {
    padding: 60rpx 0;
  }
}
</style>
