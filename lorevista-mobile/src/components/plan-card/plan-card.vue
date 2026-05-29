<template>
  <view :class="['plan-card', { 'plan-card--active': isActive }]">
    <view v-if="isActive" class="plan-card__badge">
      <text class="plan-card__badge-text">当前套餐</text>
    </view>
    <view class="plan-card__header">
      <view class="plan-card__icon">
        <lv-icon v-if="icon" :name="icon" :size="32" color="#2563eb" />
      </view>
      <text class="plan-card__name">{{ plan.name }}</text>
      <view class="plan-card__price">
        <text class="plan-card__currency">¥</text>
        <text class="plan-card__amount">{{ displayPrice }}</text>
        <text class="plan-card__period">/{{ cycle === 'monthly' ? '月' : '年' }}</text>
      </view>
    </view>

    <view v-if="plan.description" class="plan-card__desc">{{ plan.description }}</view>

    <view class="plan-card__highlights">
      <view v-for="item in highlightFeatures" :key="item.key" class="plan-card__highlight">
        <text class="plan-card__highlight-label">{{ item.label }}</text>
        <text class="plan-card__highlight-value">{{ item.value }}</text>
      </view>
    </view>

    <view class="plan-card__extra">
      支持{{ plan.features?.['manga.allow_color_mode'] ? '彩漫+黑白' : '黑白' }}漫画模式
      ，单章节最多生成 {{ plan.features?.['manga.max_image_count_per_chapter'] ?? 0 }} 张图片。
    </view>

    <view class="plan-card__action">
      <button
        v-if="!isActive"
        class="plan-card__btn"
        @tap="handleSubscribe"
      >
        立即订阅
      </button>
      <text v-else class="plan-card__current">当前套餐</text>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { PublicPlan } from '@/api/types'
import { FEATURE_LABELS } from '@/utils/constants'
import LvIcon from '@/components/lv-icon/lv-icon.vue'

const props = withDefaults(defineProps<PlanCardProps>(), {
  isActive: false,
  icon: ''
})

const emit = defineEmits<{
  (e: 'subscribe', plan: PublicPlan): void
}>()

interface PlanCardProps {
  plan: PublicPlan
  cycle: 'monthly' | 'yearly'
  isActive?: boolean
  icon?: string
}

const HIGHLIGHT_KEYS = [
  'framework.generate.monthly_limit',
  'scene.generate.monthly_limit',
  'manga.image.monthly_limit',
] as const

const highlightFeatures = computed(() => {
  if (!props.plan.features) return []
  return HIGHLIGHT_KEYS.map(key => {
    const meta = FEATURE_LABELS[key]
    const value = props.plan.features?.[key] ?? 0
    return {
      key,
      label: meta?.label || key,
      value: meta?.kind === 'boolean' ? (value ? '支持' : '不支持') : `${value} ${meta?.unit || ''}`.trim()
    }
  })
})

const displayPrice = computed(() => {
  return props.cycle === 'monthly'
    ? props.plan.monthly_price
    : (props.plan.yearly_price ?? props.plan.monthly_price * 12)
})

function handleSubscribe() {
  emit('subscribe', props.plan)
}
</script>

<style lang="scss" scoped>
.plan-card {
  position: relative;
  background: $lv-surface-solid;
  border: 1rpx solid $lv-border;
  border-radius: $lv-radius-lg;
  padding: $lv-card-padding;
  box-shadow: $lv-shadow-sm;

  &--active {
    border-color: $lv-primary;
    box-shadow: 0 0 0 4rpx rgba(37, 99, 235, 0.1);
  }

  &__badge {
    position: absolute;
    top: 0;
    right: 0;
    background: $lv-primary;
    color: $lv-text-on-primary;
    padding: 8rpx 24rpx;
    border-radius: 0 $lv-radius-lg 0 $lv-radius-sm;
  }

  &__badge-text {
    font-size: $lv-font-xs;
    font-weight: 600;
  }

  &__header {
    text-align: center;
    margin-bottom: 32rpx;
  }

  &__icon {
    margin-bottom: 16rpx;
    display: flex;
    justify-content: center;
  }

  &__name {
    font-size: $lv-font-xl;
    font-weight: 600;
    color: $lv-text-primary;
    margin-bottom: 16rpx;
    display: block;
  }

  &__price {
    display: flex;
    align-items: baseline;
    justify-content: center;
  }

  &__currency {
    font-size: $lv-font-lg;
    color: $lv-text-secondary;
  }

  &__amount {
    font-size: 64rpx;
    font-weight: 700;
    color: $lv-text-primary;
  }

  &__period {
    font-size: $lv-font-sm;
    color: $lv-text-muted;
    margin-left: 4rpx;
  }

  &__desc {
    text-align: center;
    font-size: $lv-font-sm;
    color: $lv-text-secondary;
    margin-bottom: 24rpx;
    line-height: 1.5;
  }

  &__highlights {
    background: $lv-primary-lighter;
    border-radius: $lv-radius-md;
    padding: 24rpx;
    margin-bottom: 16rpx;
  }

  &__highlight {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 12rpx;
    font-size: $lv-font-sm;

    &:last-child {
      margin-bottom: 0;
    }
  }

  &__highlight-label {
    color: $lv-text-secondary;
  }

  &__highlight-value {
    color: $lv-text-primary;
    font-weight: 600;
  }

  &__extra {
    text-align: center;
    font-size: $lv-font-xs;
    color: $lv-text-muted;
    padding: 16rpx;
    margin-bottom: 24rpx;
    border: 1rpx dashed $lv-border;
    border-radius: $lv-radius-sm;
    line-height: 1.5;
  }

  &__action {
    text-align: center;
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

  &__current {
    font-size: $lv-font-base;
    color: $lv-text-muted;
    font-weight: 500;
  }
}
</style>
