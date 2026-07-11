<template>
  <view v-if="visible" class="lv-modal" @tap="handleMaskTap">
    <view class="lv-modal__mask" />
    <view class="lv-modal__container" @tap.stop>
      <view v-if="title" class="lv-modal__header">
        <text class="lv-modal__title">{{ title }}</text>
        <button v-if="showClose" class="lv-modal__close" aria-label="关闭" @tap="handleCancel">×</button>
      </view>
      <view class="lv-modal__body">
        <slot />
      </view>
      <view v-if="showFooter" class="lv-modal__footer">
        <button v-if="showCancel" class="lv-modal__btn lv-modal__btn--cancel" @tap="handleCancel">
          {{ cancelText }}
        </button>
        <button class="lv-modal__btn lv-modal__btn--confirm" @tap="handleConfirm">
          {{ confirmText }}
        </button>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
interface ModalProps {
  visible?: boolean
  title?: string
  showFooter?: boolean
  showCancel?: boolean
  showClose?: boolean
  confirmText?: string
  cancelText?: string
  maskClosable?: boolean
}

const props = withDefaults(defineProps<ModalProps>(), {
  visible: false,
  title: '',
  showFooter: true,
  showCancel: true,
  showClose: false,
  confirmText: '确定',
  cancelText: '取消',
  maskClosable: true
})

const emit = defineEmits<{
  (e: 'update:visible', value: boolean): void
  (e: 'confirm'): void
  (e: 'cancel'): void
}>()

function handleMaskTap() {
  if (props.maskClosable) {
    emit('update:visible', false)
  }
}

function handleConfirm() {
  emit('confirm')
  emit('update:visible', false)
}

function handleCancel() {
  emit('cancel')
  emit('update:visible', false)
}
</script>

<style lang="scss" scoped>
.lv-modal {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  z-index: 1000;
  @include flex-center;

  &__mask {
    @include absolute-fill;
    z-index: 0;
    background: rgba(0, 0, 0, 0.5);
  }

  &__container {
    position: relative;
    z-index: 1;
    width: 640rpx;
    max-height: 80vh;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    background: $lv-surface-solid;
    border-radius: $lv-radius-lg;
    box-shadow: $lv-shadow-xl;
    animation: modal-slide-up 0.3s ease;
  }

  &__header {
    position: relative;
    flex-shrink: 0;
    padding: 32rpx 32rpx 0;
    text-align: center;
  }

  &__title {
    font-size: $lv-font-lg;
    font-weight: 600;
    color: $lv-text-primary;
  }

  &__close {
    position: absolute;
    top: 12rpx;
    right: 12rpx;
    width: 64rpx;
    height: 64rpx;
    padding: 0;
    border: 0;
    background: transparent;
    color: $lv-text-secondary;
    font-size: 48rpx;
    line-height: 64rpx;

    &::after {
      border: 0;
    }
  }

  &__body {
    min-height: 0;
    overflow: hidden;
    padding: 32rpx;
  }

  &__footer {
    flex-shrink: 0;
    display: flex;
    border-top: 1rpx solid $lv-border-light;
  }

  &__btn {
    flex: 1;
    height: 96rpx;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: $lv-font-base;
    font-weight: 500;

    &--cancel {
      color: $lv-text-secondary;
      border-right: 1rpx solid $lv-border-light;
    }

    &--confirm {
      color: $lv-primary;
    }

    &:active {
      background: $lv-primary-lighter;
    }
  }
}

@keyframes modal-slide-up {
  from {
    opacity: 0;
    transform: translateY(100rpx);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
</style>
