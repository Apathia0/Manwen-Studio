<template>
  <view v-if="visible" class="lv-action-sheet" @tap="handleMaskTap">
    <view class="lv-action-sheet__mask" />
    <view class="lv-action-sheet__container" @tap.stop>
      <view class="lv-action-sheet__header">
        <text class="lv-action-sheet__title">{{ title }}</text>
      </view>
      <view class="lv-action-sheet__list">
        <view
          v-for="(item, index) in actions"
          :key="index"
          :class="['lv-action-sheet__item', { 'lv-action-sheet__item--danger': item.danger }]"
          @tap="handleItemTap(index)"
        >
          <text class="lv-action-sheet__item-text">{{ item.text }}</text>
        </view>
      </view>
      <view class="lv-action-sheet__cancel" @tap="handleCancel">
        <text class="lv-action-sheet__cancel-text">{{ cancelText }}</text>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
interface ActionSheetItem {
  text: string
  danger?: boolean
}

interface ActionSheetProps {
  visible?: boolean
  title?: string
  actions: ActionSheetItem[]
  cancelText?: string
  maskClosable?: boolean
}

const props = withDefaults(defineProps<ActionSheetProps>(), {
  visible: false,
  title: '',
  cancelText: '取消',
  maskClosable: true
})

const emit = defineEmits<{
  (e: 'update:visible', value: boolean): void
  (e: 'select', index: number): void
  (e: 'cancel'): void
}>()

function handleMaskTap() {
  if (props.maskClosable) {
    emit('update:visible', false)
  }
}

function handleItemTap(index: number) {
  emit('select', index)
  emit('update:visible', false)
}

function handleCancel() {
  emit('cancel')
  emit('update:visible', false)
}
</script>

<style lang="scss" scoped>
.lv-action-sheet {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  z-index: 1000;
  display: flex;
  align-items: flex-end;

  &__mask {
    @include absolute-fill;
    background: rgba(0, 0, 0, 0.5);
  }

  &__container {
    position: relative;
    width: 100%;
    background: $lv-surface-solid;
    border-radius: $lv-radius-lg $lv-radius-lg 0 0;
    animation: sheet-slide-up 0.3s ease;
    @include safe-area-bottom;
  }

  &__header {
    padding: 32rpx;
    text-align: center;
    border-bottom: 1rpx solid $lv-border-light;
  }

  &__title {
    font-size: $lv-font-base;
    color: $lv-text-secondary;
    font-weight: 500;
  }

  &__list {
    padding: 16rpx 0;
  }

  &__item {
    display: flex;
    align-items: center;
    justify-content: center;
    height: $lv-touch-comfortable;
    padding: 0 $lv-page-padding;

    &--danger {
      .lv-action-sheet__item-text {
        color: $lv-error;
      }
    }

    &:active {
      background: $lv-primary-lighter;
    }
  }

  &__item-text {
    font-size: $lv-font-lg;
    color: $lv-text-primary;
  }

  &__cancel {
    display: flex;
    align-items: center;
    justify-content: center;
    height: $lv-touch-comfortable;
    background: $lv-primary-lighter;
    margin-top: 16rpx;

    &:active {
      background: $lv-border-light;
    }
  }

  &__cancel-text {
    font-size: $lv-font-lg;
    color: $lv-text-secondary;
    font-weight: 500;
  }
}

@keyframes sheet-slide-up {
  from {
    transform: translateY(100%);
  }
  to {
    transform: translateY(0);
  }
}
</style>
