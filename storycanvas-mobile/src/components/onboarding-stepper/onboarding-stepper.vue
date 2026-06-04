<template>
  <view class="onboarding-stepper">
    <scroll-view scroll-x class="onboarding-stepper__scroll">
      <view class="onboarding-stepper__inner">
        <view
          v-for="(step, index) in steps"
          :key="index"
          :class="[
            'onboarding-stepper__step',
            {
              'onboarding-stepper__step--active': current === index,
              'onboarding-stepper__step--completed': current > index
            }
          ]"
        >
          <view class="onboarding-stepper__dot">
            <Check v-if="current > index" :size="12" />
            <text v-else>{{ index + 1 }}</text>
          </view>
          <text class="onboarding-stepper__label">{{ step }}</text>
        </view>
      </view>
    </scroll-view>
  </view>
</template>

<script setup lang="ts">
import { Check } from '@lucide/vue'

interface StepperProps {
  steps: string[]
  current?: number
}

withDefaults(defineProps<StepperProps>(), {
  current: 0
})
</script>

<style lang="scss" scoped>
.onboarding-stepper {
  padding: 24rpx 0;
  background: $lv-surface-solid;
  border-bottom: 1rpx solid $lv-border-light;

  &__scroll {
    white-space: nowrap;
  }

  &__inner {
    display: inline-flex;
    padding: 0 $lv-page-padding;
  }

  &__step {
    display: flex;
    flex-direction: column;
    align-items: center;
    margin-right: 48rpx;
    position: relative;

    &:last-child {
      margin-right: 0;
    }

    &--active {
      .onboarding-stepper__dot {
        background: $lv-primary;
        color: $lv-text-on-primary;
        transform: scale(1.1);
      }

      .onboarding-stepper__label {
        color: $lv-primary;
        font-weight: 600;
      }
    }

    &--completed {
      .onboarding-stepper__dot {
        background: $lv-success;
        color: $lv-text-on-primary;
      }
    }
  }

  &__dot {
    width: 48rpx;
    height: 48rpx;
    border-radius: 50%;
    background: $lv-border-light;
    color: $lv-text-muted;
    @include flex-center;
    font-size: $lv-font-sm;
    font-weight: 600;
    margin-bottom: 8rpx;
    transition: all 0.2s ease;
  }

  &__label {
    font-size: $lv-font-xs;
    color: $lv-text-muted;
    white-space: nowrap;
  }
}
</style>
