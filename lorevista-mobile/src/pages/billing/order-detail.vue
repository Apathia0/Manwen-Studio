<template>
  <view class="order-detail">
    <lv-navbar title="订单详情" show-back />
    <view class="order-detail__content">
      <view class="order-detail__header">
        <text class="order-detail__label">{{ statusLabel }}</text>
        <component :is="statusIconComp" :size="32" :color="statusColor" />
      </view>
      <view class="order-detail__body">
        <view class="order-detail__row"><text>订单编号</text><text>{{ order.order_no }}</text></view>
        <view class="order-detail__row"><text>套餐</text><text>{{ order.plan_name }}</text></view>
        <view class="order-detail__row"><text>金额</text><text>¥{{ (order.amount ?? 0).toFixed(2) }}</text></view>
        <view class="order-detail__row"><text>创建时间</text><text>{{ order.created_at }}</text></view>
        <view class="order-detail__row" v-if="order.paid_at"><text>支付时间</text><text>{{ order.paid_at }}</text></view>
      </view>
      <lv-button v-if="order.status === 'pending'" block @tap="handlePay">去支付</lv-button>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { CheckCircle, XCircle, Clock } from '@lucide/vue'
import { get } from '@/utils/request'
import type { OrderItem } from '@/api/types'
import { useUiStore } from '@/stores/ui'
import LvNavbar from '@/components/lv-navbar/lv-navbar.vue'
import LvButton from '@/components/lv-button/lv-button.vue'

const uiStore = useUiStore()

const statusMap: Record<string, string> = {
  pending: '待支付', paid: '支付成功', confirmed: '已确认',
  cancelled: '已取消', refunded: '已退款', expired: '已过期'
}

const statusLabel = computed(() => statusMap[order.status || 'pending'] || order.status)

const statusIconComp = computed(() => {
  const map: Record<string, any> = { pending: Clock, paid: CheckCircle, confirmed: CheckCircle, cancelled: XCircle }
  return map[order.status || 'pending'] || Clock
})

const statusColor = computed(() => {
  const map: Record<string, string> = { paid: '#22c55e', confirmed: '#22c55e', cancelled: '#ef4444' }
  return map[order.status || ''] || '#f59e0b'
})

const order = reactive<Partial<OrderItem>>({})

onMounted(async () => {
  const pages = getCurrentPages()
  const page = pages[pages.length - 1] as any
  const orderNo = page.options?.orderNo || ''
  if (!orderNo) return
  try {
    const orders = await get<OrderItem[]>('/api/me/orders')
    const found = orders.find((o: OrderItem) => o.order_no === orderNo)
    if (found) Object.assign(order, found)
  } catch (e) {
    console.error('加载订单失败:', e)
  }
})

function handlePay() {
  if (!order.order_no) return
  // 对于 pending 状态的订单，跳转到统一 checkout 页处理
  const qr = (order as any).checkout?.qr_code_text || ''
  const method = (order as any).checkout?.method || ''
  uni.navigateTo({
    url: `/pages/billing/checkout?orderNo=${order.order_no}&method=${method}${qr ? '&qr=' + encodeURIComponent(qr) : ''}`
  })
}
</script>

<style lang="scss" scoped>
.order-detail { min-height: 100vh; background: $lv-bg-start;
  &__content { padding: calc(var(--status-bar-height) + 88rpx + $lv-page-padding) $lv-page-padding; }
  &__header { text-align: center; padding: 48rpx 0; }
  &__label { font-size: 36rpx; font-weight: 600; color: $lv-text-primary; }
  &__body { background: #fff; border-radius: 24rpx; padding: 24rpx; }
  &__row { display: flex; justify-content: space-between; padding: 16rpx 0; font-size: 26rpx; color: $lv-text-secondary; border-bottom: 1rpx solid $lv-border-light; &:last-child { border: none; } }
}
</style>
