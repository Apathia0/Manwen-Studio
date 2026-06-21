<template>
  <view v-if="count > 0" class="changes-banner">
    <view class="changes-banner__info">
      <text class="changes-banner__count">{{ count }} 项修改待确认</text>
    </view>
    <view class="changes-banner__actions">
      <button class="changes-banner__btn changes-banner__btn--view" @tap="handleView">
        查看对比
      </button>
      <button class="changes-banner__btn changes-banner__btn--confirm" :disabled="confirming || rollbacking" @tap="handleConfirm">
        {{ confirming ? '确认中...' : '确认' }}
      </button>
      <button class="changes-banner__btn changes-banner__btn--rollback" :disabled="confirming || rollbacking" @tap="handleRollback">
        {{ rollbacking ? '撤回中...' : '撤回' }}
      </button>
    </view>
  </view>
</template>

<script setup lang="ts">
interface ChangesBannerProps {
  count: number
  confirming?: boolean
  rollbacking?: boolean
}

withDefaults(defineProps<ChangesBannerProps>(), {
  confirming: false,
  rollbacking: false
})

const emit = defineEmits<{
  (e: 'view'): void
  (e: 'confirm'): void
  (e: 'rollback'): void
}>()

function handleView() {
  emit('view')
}

function handleConfirm() {
  emit('confirm')
}

function handleRollback() {
  emit('rollback')
}
</script>

<style lang="scss" scoped>
.changes-banner {
  padding: 24rpx;
  background: $lv-warning-bg;
  border: 1rpx solid rgba(217, 119, 6, 0.2);
  border-radius: $lv-radius-md;
  margin-bottom: 24rpx;

  &__info {
    margin-bottom: 16rpx;
  }

  &__count {
    font-size: $lv-font-base;
    font-weight: 600;
    color: $lv-warning;
  }

  &__actions {
    display: flex;
    gap: 12rpx;
  }

  &__btn {
    flex: 1;
    height: 64rpx;
    border: none;
    border-radius: $lv-radius-sm;
    font-size: $lv-font-sm;
    font-weight: 500;

    &--view {
      background: transparent;
      color: $lv-warning;
      border: 1rpx solid $lv-warning;
    }

    &--confirm {
      background: $lv-success;
      color: $lv-text-on-primary;

      &:disabled {
        opacity: 0.5;
      }
    }

    &--rollback {
      background: transparent;
      color: $lv-error;
      border: 1rpx solid $lv-error;

      &:disabled {
        opacity: 0.5;
      }
    }
  }
}
</style>
