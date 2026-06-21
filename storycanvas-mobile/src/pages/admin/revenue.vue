<template>
  <view class="admin-revenue">
    <view class="admin-revenue__header">
      <text class="admin-revenue__title">收入看板</text>
      <lv-button size="sm" secondary :loading="busy" @tap="loadAll">刷新</lv-button>
    </view>

    <lv-loading v-if="!summary" />

    <template v-else>
      <!-- 指标卡片 -->
      <view class="admin-revenue__grid">
        <view class="admin-revenue__card">
          <text class="admin-revenue__card-label">总收入</text>
          <text class="admin-revenue__card-value">¥{{ formatMoney(summary.total_revenue) }}</text>
          <text class="admin-revenue__card-sublabel">{{ summary.paid_orders }} 笔已支付</text>
        </view>
        <view class="admin-revenue__card">
          <text class="admin-revenue__card-label">本月收入</text>
          <text class="admin-revenue__card-value">¥{{ formatMoney(summary.monthly_revenue) }}</text>
          <text class="admin-revenue__card-sublabel">{{ summary.monthly_paid_orders }} 笔订单</text>
        </view>
        <view class="admin-revenue__card">
          <text class="admin-revenue__card-label">本月订单</text>
          <text class="admin-revenue__card-value">{{ summary.monthly_orders }}</text>
          <text class="admin-revenue__card-sublabel">{{ summary.monthly_paid_orders }} 已支付</text>
        </view>
        <view class="admin-revenue__card">
          <text class="admin-revenue__card-label">支付转化率</text>
          <text class="admin-revenue__card-value">{{ summary.conversion_rate }}%</text>
          <text class="admin-revenue__card-sublabel">活跃订阅 {{ summary.active_subscriptions }}</text>
        </view>
      </view>

      <!-- 订单状态分布 -->
      <view class="admin-revenue__section">
        <text class="admin-revenue__section-title">订单状态分布</text>
        <view class="admin-revenue__dist-bar">
          <view
            class="admin-revenue__dist-segment"
            :style="{ width: statusPct('paid') + '%', backgroundColor: '#10b981' }"
          />
          <view
            class="admin-revenue__dist-segment"
            :style="{ width: statusPct('cancelled') + '%', backgroundColor: '#ef4444' }"
          />
          <view
            class="admin-revenue__dist-segment"
            :style="{ width: statusPct('expired') + '%', backgroundColor: '#f59e0b' }"
          />
        </view>
        <view class="admin-revenue__dist-legend">
          <view class="admin-revenue__dist-item">
            <view class="admin-revenue__dist-dot" style="background: #10b981" />
            <text class="admin-revenue__dist-label">已支付 {{ summary.paid_orders }}</text>
          </view>
          <view class="admin-revenue__dist-item">
            <view class="admin-revenue__dist-dot" style="background: #ef4444" />
            <text class="admin-revenue__dist-label">已取消 {{ summary.cancelled_orders }}</text>
          </view>
          <view class="admin-revenue__dist-item">
            <view class="admin-revenue__dist-dot" style="background: #f59e0b" />
            <text class="admin-revenue__dist-label">已过期 {{ summary.expired_orders }}</text>
          </view>
        </view>
      </view>

      <!-- 最近订单 -->
      <view class="admin-revenue__section">
        <text class="admin-revenue__section-title">订单管理</text>

        <!-- 状态筛选 -->
        <view class="admin-revenue__filters">
          <view
            v-for="opt in statusOptions"
            :key="opt.value"
            class="admin-revenue__filter-btn"
            :class="{ 'admin-revenue__filter-btn--active': currentStatus === opt.value }"
            @tap="changeStatus(opt.value)"
          >
            <text>{{ opt.label }}</text>
          </view>
        </view>

        <lv-loading v-if="ordersLoading" />

        <view v-else-if="orderItems.length === 0" class="admin-revenue__empty">
          <lv-empty title="暂无订单" />
        </view>

        <view v-else class="admin-revenue__order-list">
          <view
            v-for="order in orderItems"
            :key="order.order_no"
            class="admin-revenue__order"
          >
            <view class="admin-revenue__order-header">
              <text class="admin-revenue__order-no">{{ order.order_no }}</text>
              <lv-tag :type="orderStatusType(order.status)" :text="orderStatusLabel(order.status)" size="sm" />
            </view>
            <view class="admin-revenue__order-info">
              <text class="admin-revenue__order-user">{{ order.user_name || '用户#' + order.user_id }}</text>
              <text class="admin-revenue__order-amount">{{ order.currency }} {{ order.amount }}</text>
            </view>
            <text class="admin-revenue__order-time">{{ order.created_at }}</text>
            <view v-if="order.status === 'pending'" class="admin-revenue__order-actions">
              <lv-button size="sm" :loading="actingOrderNo === order.order_no" @tap="updateStatus(order, 'paid')">标记已支付</lv-button>
              <lv-button size="sm" type="danger" :loading="actingOrderNo === order.order_no" @tap="updateStatus(order, 'cancelled')">取消</lv-button>
            </view>
          </view>
        </view>

        <!-- 分页 -->
        <view v-if="searchResult && searchResult.total_pages > 1" class="admin-revenue__pagination">
          <lv-button size="sm" secondary :disabled="searchResult.page <= 1 || ordersLoading" @tap="prevPage">上一页</lv-button>
          <text class="admin-revenue__pagination-info">{{ searchResult.page }} / {{ searchResult.total_pages }}</text>
          <lv-button size="sm" secondary :disabled="searchResult.page >= searchResult.total_pages || ordersLoading" @tap="nextPage">下一页</lv-button>
        </view>
      </view>
    </template>
  </view>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { adminApi } from '@/api'
import type { AdminOrderItem, AdminRevenueSummary } from '@/api/admin'
import LvButton from '@/components/lv-button/lv-button.vue'
import LvTag from '@/components/lv-tag/lv-tag.vue'
import LvLoading from '@/components/lv-loading/lv-loading.vue'
import LvEmpty from '@/components/lv-empty/lv-empty.vue'

const busy = ref(false)
const summary = ref<AdminRevenueSummary | null>(null)
const ordersLoading = ref(false)
const actingOrderNo = ref<string | null>(null)
const currentStatus = ref('')
const currentPage = ref(1)
const searchResult = ref<{ items: AdminOrderItem[]; total: number; page: number; page_size: number; total_pages: number } | null>(null)

const orderItems = computed(() => searchResult.value?.items || [])

const statusOptions = [
  { value: '', label: '全部' },
  { value: 'pending', label: '待支付' },
  { value: 'paid', label: '已支付' },
  { value: 'cancelled', label: '已取消' },
  { value: 'expired', label: '已过期' },
]

function formatMoney(n: number): string {
  if (n >= 10000) return (n / 10000).toFixed(1) + '万'
  return n.toFixed(2)
}

function orderStatusLabel(status: string): string {
  const map: Record<string, string> = { pending: '待支付', paid: '已支付', cancelled: '已取消', expired: '已过期' }
  return map[status] || status
}

function orderStatusType(status: string): 'success' | 'warning' | 'default' {
  if (status === 'paid') return 'success'
  if (status === 'pending') return 'warning'
  return 'default'
}

const totalOrders = computed(() => {
  if (!summary.value) return 1
  return summary.value.paid_orders + summary.value.cancelled_orders + summary.value.expired_orders
})

function statusPct(status: string): number {
  if (!summary.value) return 0
  const total = totalOrders.value
  if (total === 0) return 0
  const map: Record<string, number> = {
    paid: summary.value.paid_orders,
    cancelled: summary.value.cancelled_orders,
    expired: summary.value.expired_orders,
  }
  return (map[status] || 0) / total * 100
}

function changeStatus(status: string) {
  currentStatus.value = status
  currentPage.value = 1
  loadOrders()
}

function prevPage() {
  if (searchResult.value && searchResult.value.page > 1) {
    currentPage.value--
    loadOrders()
  }
}

function nextPage() {
  if (searchResult.value && searchResult.value.page < searchResult.value.total_pages) {
    currentPage.value++
    loadOrders()
  }
}

async function loadOrders() {
  ordersLoading.value = true
  try {
    const result = await adminApi.searchAdminOrders({
      page: currentPage.value,
      page_size: 20,
      status: currentStatus.value || undefined,
    })
    searchResult.value = result
  } catch (e: any) {
    uni.showToast({ title: e.message || '加载订单失败', icon: 'none' })
  } finally {
    ordersLoading.value = false
  }
}

async function updateStatus(order: AdminOrderItem, status: 'paid' | 'cancelled' | 'expired') {
  actingOrderNo.value = order.order_no
  try {
    await adminApi.updateAdminOrderStatus(order.order_no, status)
    uni.showToast({ title: '已更新', icon: 'success' })
    await loadOrders()
  } catch (e: any) {
    uni.showToast({ title: e.message || '操作失败', icon: 'none' })
  } finally {
    actingOrderNo.value = null
  }
}

async function loadAll() {
  busy.value = true
  try {
    const [s] = await Promise.all([
      adminApi.getAdminRevenueSummary(),
    ])
    summary.value = s
    await loadOrders()
  } catch (e: any) {
    uni.showToast({ title: e.message || '加载失败', icon: 'none' })
  } finally {
    busy.value = false
  }
}

onMounted(() => loadAll())
</script>

<style lang="scss" scoped>
.admin-revenue {
  min-height: 100vh;
  background: linear-gradient(180deg, $lv-bg-start 0%, $lv-bg-end 100%);
  padding: $lv-page-padding;

  &__header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 24rpx;
  }

  &__title {
    font-size: $lv-font-lg;
    font-weight: 600;
    color: $lv-text-primary;
  }

  &__grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 16rpx;
    margin-bottom: 24rpx;
  }

  &__card {
    background: $lv-surface-solid;
    border-radius: $lv-radius-lg;
    padding: 24rpx;
    box-shadow: $lv-shadow-sm;
  }

  &__card-label {
    font-size: $lv-font-xs;
    color: $lv-text-muted;
    text-transform: uppercase;
    letter-spacing: 0.08em;
  }

  &__card-value {
    display: block;
    font-size: $lv-font-xl;
    font-weight: 700;
    color: $lv-text-primary;
    margin: 8rpx 0 4rpx;
  }

  &__card-sublabel {
    font-size: $lv-font-xs;
    color: $lv-text-muted;
  }

  &__section {
    background: $lv-surface-solid;
    border-radius: $lv-radius-lg;
    padding: 24rpx;
    box-shadow: $lv-shadow-sm;
    margin-bottom: 20rpx;
  }

  &__section-title {
    display: block;
    font-size: $lv-font-base;
    font-weight: 600;
    color: $lv-text-primary;
    margin-bottom: 20rpx;
  }

  &__dist-bar {
    display: flex;
    height: 20rpx;
    border-radius: 20rpx;
    overflow: hidden;
    background: $lv-bg-end;
    margin-bottom: 16rpx;
  }

  &__dist-segment {
    height: 100%;
    min-width: 4rpx;
    transition: width 0.3s ease;
  }

  &__dist-legend {
    display: flex;
    flex-wrap: wrap;
    gap: 16rpx;
  }

  &__dist-item {
    display: flex;
    align-items: center;
    gap: 8rpx;
  }

  &__dist-dot {
    width: 16rpx;
    height: 16rpx;
    border-radius: 50%;
    flex-shrink: 0;
  }

  &__dist-label {
    font-size: $lv-font-sm;
    color: $lv-text-secondary;
  }

  &__filters {
    display: flex;
    flex-wrap: wrap;
    gap: 12rpx;
    margin-bottom: 20rpx;
  }

  &__filter-btn {
    padding: 12rpx 24rpx;
    border-radius: 40rpx;
    border: 2rpx solid $lv-border;
    font-size: $lv-font-sm;
    color: $lv-text-secondary;
    background: transparent;
    transition: all 0.2s;

    &--active {
      background: $lv-primary;
      color: #fff;
      border-color: $lv-primary;
    }

    &:active {
      opacity: 0.8;
    }
  }

  &__order-list {
    display: flex;
    flex-direction: column;
    gap: 16rpx;
  }

  &__order {
    background: $lv-bg-end;
    border-radius: $lv-radius-sm;
    padding: 20rpx;
  }

  &__order-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 12rpx;
  }

  &__order-no {
    font-size: $lv-font-xs;
    font-family: monospace;
    color: $lv-text-muted;
  }

  &__order-info {
    display: flex;
    gap: 16rpx;
    margin-bottom: 8rpx;
    flex-wrap: wrap;
  }

  &__order-user {
    font-size: $lv-font-sm;
    font-weight: 500;
    color: $lv-text-primary;
  }

  &__order-amount {
    font-size: $lv-font-sm;
    font-weight: 600;
    color: $lv-primary;
  }

  &__order-time {
    display: block;
    font-size: $lv-font-xs;
    color: $lv-text-muted;
    margin-bottom: 12rpx;
  }

  &__order-actions {
    display: flex;
    gap: 12rpx;
    border-top: 1rpx solid $lv-border-light;
    padding-top: 16rpx;
  }

  &__pagination {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 20rpx;
    margin-top: 24rpx;
  }

  &__pagination-info {
    font-size: $lv-font-sm;
    color: $lv-text-secondary;
  }

  &__empty {
    padding: 40rpx 0;
  }
}
</style>
