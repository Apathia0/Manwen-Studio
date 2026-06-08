<template>
  <view class="checkout-page">
    <lv-navbar title="支付" show-back />

    <view class="checkout-page__content">
      <!-- 订单信息 -->
      <view class="checkout-page__info">
        <view class="checkout-page__row">
          <text class="checkout-page__label">订单号</text>
          <text class="checkout-page__value">{{ orderNo }}</text>
        </view>
        <view class="checkout-page__row" v-if="planName">
          <text class="checkout-page__label">套餐</text>
          <text class="checkout-page__value">{{ planName }}</text>
        </view>
        <view class="checkout-page__row" v-if="amount">
          <text class="checkout-page__label">金额</text>
          <text class="checkout-page__value">¥{{ amount }}</text>
        </view>
      </view>

      <!-- 支付说明 -->
      <view v-if="instructions" class="checkout-page__instructions">
        <text class="checkout-page__instructions-text">{{ instructions }}</text>
      </view>

      <!-- 二维码支付 -->
      <view v-if="qrCodeText" class="checkout-page__qr">
        <text class="checkout-page__qr-title">请扫码支付</text>
        <checkout-qr :text="qrCodeText" />
        <text class="checkout-page__qr-hint">{{ qrHint }}</text>
      </view>

      <!-- 支付状态 -->
      <view v-if="payStatus" :class="['checkout-page__status', `checkout-page__status--${payStatus}`]">
        <view v-if="payStatus === 'success'" class="checkout-page__status-icon">
          <lv-icon name="CheckCircle" :size="40" color="#15803d" />
        </view>
        <view v-else-if="payStatus === 'pending'" class="checkout-page__status-icon">
          <lv-icon name="Loader" :size="40" color="#d97706" />
        </view>
        <view v-else class="checkout-page__status-icon">
          <lv-icon name="XCircle" :size="40" color="#be123c" />
        </view>
        <text class="checkout-page__status-text">{{ statusText }}</text>
      </view>

      <!-- 操作按钮 -->
      <view class="checkout-page__actions">
        <!-- 模拟支付确认 -->
        <lv-button v-if="canMockConfirm && payStatus === 'pending'" block @tap="handleMockConfirm" :loading="actionLoading">
          确认支付
        </lv-button>

        <!-- 外部扫码/跳转支付：我已完成支付 -->
        <lv-button v-if="canManualCheck && payStatus === 'pending'" block secondary @tap="handleCheckStatus" :loading="actionLoading">
          我已完成支付
        </lv-button>

        <!-- 刷新状态 -->
        <lv-button v-if="payStatus === 'pending' && !canMockConfirm && !canManualCheck" block @tap="handleCheckStatus">
          刷新状态
        </lv-button>

        <!-- 支付成功 -->
        <lv-button v-if="payStatus === 'success'" block @tap="goBack">
          完成
        </lv-button>

        <!-- 支付失败 / 取消 -->
        <lv-button v-if="payStatus === 'failed'" block secondary @tap="handleCancel" :loading="actionLoading">
          取消订单
        </lv-button>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { usePayment } from '@/composables/usePayment'
import { billingApi } from '@/api'
import { useUiStore } from '@/stores/ui'
import LvNavbar from '@/components/lv-navbar/lv-navbar.vue'
import LvButton from '@/components/lv-button/lv-button.vue'
import LvIcon from '@/components/lv-icon/lv-icon.vue'
import CheckoutQr from '@/components/checkout-qr/checkout-qr.vue'

const { mockConfirm, syncOrder } = usePayment()
const uiStore = useUiStore()

const orderNo = ref('')
const method = ref('')
const qrCodeText = ref('')
const planName = ref('')
const amount = ref(0)
const instructions = ref('')
const canMockConfirm = ref(false)

const payStatus = ref<'pending' | 'success' | 'failed' | null>(null)
const actionLoading = ref(false)

let pollTimer: ReturnType<typeof setInterval> | null = null

const statusText = computed(() => {
  switch (payStatus.value) {
    case 'success': return '支付成功！'
    case 'pending': return '等待支付...'
    case 'failed': return '支付失败'
    default: return ''
  }
})

const canManualCheck = computed(() => (
  method.value === 'alipay_qr' ||
  method.value === 'mapay_qr' ||
  method.value.startsWith('epay_') ||
  method.value.startsWith('mapay_')
))

const qrHint = computed(() => {
  if (method.value === 'alipay_qr' || method.value === 'mapay_alipay') return '打开支付宝扫一扫完成付款'
  if (method.value === 'mapay_wxpay') return '打开微信扫一扫完成付款'
  if (method.value === 'mapay_qqpay') return '打开 QQ 钱包扫一扫完成付款'
  if (method.value.startsWith('mapay_')) return '请使用码支付对应通道完成付款'
  if (method.value.startsWith('epay_')) return '请使用对应支付 App 扫码完成付款'
  return '请扫码完成付款'
})

onMounted(() => {
  const pages = getCurrentPages()
  const page = pages[pages.length - 1] as any
  orderNo.value = page.options?.orderNo || ''
  method.value = page.options?.method || ''
  qrCodeText.value = page.options?.qr ? decodeURIComponent(page.options.qr) : ''

  if (!orderNo.value) return
  payStatus.value = 'pending'

  // 先同步一次，获取 checkout 详情
  loadCheckoutDetail()
  startPolling()
})

onBeforeUnmount(() => {
  stopPolling()
})

async function loadCheckoutDetail() {
  try {
    const result = await syncOrder(orderNo.value)
    if (result?.checkout) {
      planName.value = result.checkout.plan_name || ''
      amount.value = result.checkout.amount || 0
      instructions.value = result.checkout.instructions || ''
      canMockConfirm.value = result.checkout.can_mock_confirm || false
      method.value = method.value || result.checkout.method || ''
      if (!qrCodeText.value && result.checkout.qr_code_text) {
        qrCodeText.value = result.checkout.qr_code_text
      }
    }
    // 如果订单已不是 pending，更新状态
    if (result?.status === 'paid' || result?.status === 'confirmed') {
      payStatus.value = 'success'
      stopPolling()
    } else if (result?.status === 'cancelled' || result?.status === 'expired') {
      payStatus.value = 'failed'
      stopPolling()
    }
  } catch (e) {
    // 忽略加载错误
  }
}

function startPolling() {
  pollTimer = setInterval(async () => {
    await handleCheckStatus()
  }, 5000)
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

async function handleCheckStatus() {
  if (!orderNo.value) return
  try {
    const result = await syncOrder(orderNo.value)
    if (result?.status === 'paid' || result?.status === 'confirmed') {
      payStatus.value = 'success'
      stopPolling()
      uiStore.success('支付成功！')
    } else if (result?.status === 'cancelled') {
      payStatus.value = 'failed'
      stopPolling()
    }
  } catch (e) {
    // 忽略轮询错误
  }
}

async function handleMockConfirm() {
  if (!orderNo.value) return
  actionLoading.value = true
  try {
    await mockConfirm(orderNo.value)
    payStatus.value = 'success'
    stopPolling()
    uiStore.success('支付成功！')
  } catch (e: any) {
    uiStore.error(e.message || '确认支付失败')
  } finally {
    actionLoading.value = false
  }
}

async function handleCancel() {
  if (!orderNo.value) return
  actionLoading.value = true
  try {
    await billingApi.cancelOrder(orderNo.value)
    payStatus.value = 'failed'
    stopPolling()
    uiStore.success('订单已取消')
  } catch (e: any) {
    uiStore.error(e.message || '取消失败')
  } finally {
    actionLoading.value = false
  }
}

function goBack() {
  uni.navigateBack()
}
</script>

<style lang="scss" scoped>
.checkout-page {
  min-height: 100vh;
  background: linear-gradient(180deg, $lv-bg-start 0%, $lv-bg-end 100%);

  &__content {
    padding: calc(var(--status-bar-height) + 88rpx + $lv-page-padding) $lv-page-padding;
  }

  &__info {
    background: $lv-surface-solid;
    border-radius: $lv-radius-lg;
    padding: 28rpx;
    box-shadow: $lv-shadow-sm;
  }

  &__row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 12rpx 0;
    border-bottom: 1rpx solid $lv-border-light;
    &:last-child { border-bottom: none; }
  }

  &__label {
    font-size: $lv-font-sm;
    color: $lv-text-secondary;
  }

  &__value {
    font-size: $lv-font-sm;
    color: $lv-text-primary;
    font-family: monospace;
  }

  &__instructions {
    margin-top: $lv-section-gap;
    padding: 24rpx;
    background: $lv-primary-light;
    border-radius: $lv-radius-md;
  }

  &__instructions-text {
    font-size: $lv-font-sm;
    color: $lv-primary;
    line-height: 1.6;
    white-space: pre-wrap;
  }

  &__qr {
    margin-top: $lv-section-gap;
    text-align: center;
  }

  &__qr-title {
    display: block;
    font-size: $lv-font-lg;
    font-weight: 600;
    color: $lv-text-primary;
    margin-bottom: 24rpx;
  }

  &__qr-hint {
    display: block;
    font-size: $lv-font-sm;
    color: $lv-text-muted;
    margin-top: 24rpx;
  }

  &__status {
    margin-top: $lv-section-gap;
    text-align: center;
    padding: 32rpx;
    background: $lv-surface-solid;
    border-radius: $lv-radius-lg;
    box-shadow: $lv-shadow-sm;
  }

  &__status-icon {
    display: flex;
    justify-content: center;
    margin-bottom: 16rpx;
  }

  &__status-text {
    display: block;
    font-size: $lv-font-lg;
    font-weight: 600;
  }

  &__status--success &__status-text { color: $lv-success; }
  &__status--pending &__status-text { color: $lv-warning; }
  &__status--failed &__status-text { color: $lv-error; }

  &__actions {
    margin-top: $lv-section-gap;
    display: flex;
    flex-direction: column;
    gap: 16rpx;
  }
}
</style>
