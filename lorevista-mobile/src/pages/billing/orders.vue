<template>
  <view class="orders-page">
    <lv-navbar title="订单记录" show-back />

    <view class="orders-page__content">
      <lv-loading v-if="loading" />

      <template v-else>
        <view
          v-for="order in billingStore.orders"
          :key="order.order_no"
          class="orders-page__item"
          @tap="goDetail(order)"
        >
          <view class="orders-page__item-header">
            <text class="orders-page__plan">{{ order.plan_name }}</text>
            <text :class="['orders-page__status', `orders-page__status--${order.status}`]">
              {{ statusMap[order.status] || order.status }}
            </text>
          </view>
          <view class="orders-page__item-body">
            <view class="orders-page__row">
              <text class="orders-page__label">金额</text>
              <text class="orders-page__value">¥{{ order.amount.toFixed(2) }}</text>
            </view>
            <view class="orders-page__row">
              <text class="orders-page__label">时间</text>
              <text class="orders-page__value">{{ formatDate(order.created_at, 'full') }}</text>
            </view>
            <view class="orders-page__row">
              <text class="orders-page__label">订单号</text>
              <text class="orders-page__value orders-page__order-no">{{ order.order_no }}</text>
            </view>
          </view>
        </view>

        <lv-empty v-if="billingStore.orders.length === 0" title="暂无订单" description="订阅套餐后会在这里显示订单记录" />
      </template>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useBillingStore } from '@/stores/billing'
import { formatDate } from '@/utils/format'
import type { OrderItem } from '@/api/types'
import LvNavbar from '@/components/lv-navbar/lv-navbar.vue'
import LvLoading from '@/components/lv-loading/lv-loading.vue'
import LvEmpty from '@/components/lv-empty/lv-empty.vue'

const billingStore = useBillingStore()
const loading = ref(true)

const statusMap: Record<string, string> = {
  pending: '待支付',
  paid: '已支付',
  confirmed: '已确认',
  cancelled: '已取消',
  refunded: '已退款',
  expired: '已过期'
}

onMounted(async () => {
  try {
    await billingStore.fetchOrders()
  } catch (e) {
    console.error('加载订单失败:', e)
  } finally {
    loading.value = false
  }
})

function goDetail(order: OrderItem) {
  uni.navigateTo({ url: `/pages/billing/order-detail?orderNo=${order.order_no}` })
}
</script>

<style lang="scss" scoped>
.orders-page {
  min-height: 100vh;
  background: linear-gradient(180deg, $lv-bg-start 0%, $lv-bg-end 100%);

  &__content {
    padding: calc(var(--status-bar-height) + 88rpx + $lv-page-padding) $lv-page-padding;
  }

  &__item {
    background: $lv-surface-solid;
    border-radius: $lv-radius-lg;
    padding: 28rpx;
    margin-bottom: 16rpx;
    box-shadow: $lv-shadow-sm;

    &:active {
      background: $lv-primary-lighter;
    }
  }

  &__item-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 16rpx;
    padding-bottom: 16rpx;
    border-bottom: 1rpx solid $lv-border-light;
  }

  &__plan {
    font-size: $lv-font-base;
    font-weight: 600;
    color: $lv-text-primary;
  }

  &__status {
    font-size: $lv-font-sm;
    font-weight: 500;
  }

  &__status--pending { color: $lv-warning; }
  &__status--paid,
  &__status--confirmed { color: $lv-success; }
  &__status--cancelled,
  &__status--expired { color: $lv-text-muted; }
  &__status--refunded { color: $lv-error; }

  &__row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 6rpx 0;
  }

  &__label {
    font-size: $lv-font-sm;
    color: $lv-text-secondary;
  }

  &__value {
    font-size: $lv-font-sm;
    color: $lv-text-primary;
  }

  &__order-no {
    font-family: monospace;
    font-size: $lv-font-xs;
  }
}
</style>
