<template>
  <view class="checkout-qr">
    <view class="checkout-qr__header">
      <text class="checkout-qr__title">扫码支付</text>
    </view>
    <view class="checkout-qr__image">
      <image :src="qrCodeUrl || text" class="checkout-qr__img" mode="aspectFit" />
    </view>
    <view class="checkout-qr__info">
      <text v-if="amount" class="checkout-qr__amount">¥{{ amount }}</text>
      <text class="checkout-qr__desc">请使用支付宝扫描二维码完成支付</text>
    </view>
    <view class="checkout-qr__actions">
      <button class="checkout-qr__btn" @tap="handleSync">
        我已完成支付
      </button>
    </view>
  </view>
</template>

<script setup lang="ts">
interface CheckoutQrProps {
  qrCodeUrl?: string
  amount?: number
  text?: string
}

const props = withDefaults(defineProps<CheckoutQrProps>(), {
  qrCodeUrl: '',
  amount: 0,
  text: ''
})

const emit = defineEmits<{
  (e: 'sync'): void
}>()

function handleSync() {
  emit('sync')
}
</script>

<style lang="scss" scoped>
.checkout-qr {
  background: $lv-surface-solid;
  border-radius: $lv-radius-lg;
  padding: $lv-card-padding;
  box-shadow: $lv-shadow-md;

  &__header {
    text-align: center;
    margin-bottom: 32rpx;
  }

  &__title {
    font-size: $lv-font-lg;
    font-weight: 600;
    color: $lv-text-primary;
  }

  &__image {
    display: flex;
    justify-content: center;
    margin-bottom: 32rpx;
  }

  &__img {
    width: 400rpx;
    height: 400rpx;
  }

  &__info {
    text-align: center;
    margin-bottom: 32rpx;
  }

  &__amount {
    display: block;
    font-size: 64rpx;
    font-weight: 700;
    color: $lv-text-primary;
    margin-bottom: 12rpx;
  }

  &__desc {
    font-size: $lv-font-sm;
    color: $lv-text-secondary;
  }

  &__actions {
    display: flex;
    justify-content: center;
  }

  &__btn {
    width: 100%;
    height: 88rpx;
    background: linear-gradient(135deg, $lv-primary 0%, $lv-primary-dark 100%);
    color: $lv-text-on-primary;
    border: none;
    border-radius: $lv-radius-full;
    font-size: $lv-font-base;
    font-weight: 600;

    &:active {
      opacity: 0.9;
    }
  }
}
</style>
