<template>
  <view class="vrp">
    <!-- 宽高比选择 -->
    <view class="vrp__group">
      <text class="vrp__group-label">宽高比</text>
      <view class="vrp__group-options">
        <view
          v-for="opt in ASPECT_RATIO_OPTIONS"
          :key="opt.value"
          :class="['vrp__option', { 'vrp__option--active': localValue.aspect_ratio === opt.value }]"
          @tap="handleSelect('aspect_ratio', opt.value)"
        >
          <text class="vrp__option-text">{{ opt.label }}</text>
        </view>
      </view>
    </view>

    <!-- 时长选择 -->
    <view class="vrp__group">
      <text class="vrp__group-label">时长</text>
      <view class="vrp__group-options">
        <view
          v-for="opt in DURATION_OPTIONS"
          :key="opt.value"
          :class="['vrp__option', { 'vrp__option--active': localValue.duration === opt.value }]"
          @tap="handleSelect('duration', opt.value)"
        >
          <text class="vrp__option-text">{{ opt.label }}</text>
        </view>
      </view>
    </view>

    <!-- 尺寸选择 -->
    <view class="vrp__group">
      <text class="vrp__group-label">尺寸</text>
      <view class="vrp__group-options">
        <view
          v-for="opt in SIZE_OPTIONS"
          :key="opt.value"
          :class="['vrp__option', { 'vrp__option--active': localValue.size === opt.value }]"
          @tap="handleSelect('size', opt.value)"
        >
          <text class="vrp__option-text">{{ opt.label }}</text>
        </view>
      </view>
    </view>

    <!-- 方向选择 -->
    <view class="vrp__group">
      <text class="vrp__group-label">方向</text>
      <view class="vrp__group-options">
        <view
          v-for="opt in ORIENTATION_OPTIONS"
          :key="opt.value"
          :class="['vrp__option', { 'vrp__option--active': localValue.orientation === opt.value }]"
          @tap="handleSelect('orientation', opt.value)"
        >
          <text class="vrp__option-text">{{ opt.label }}</text>
        </view>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'

/** 渲染参数类型 */
export interface RenderParams {
  aspect_ratio?: string
  duration?: number
  size?: string
  orientation?: string
  input_mode?: string
}

const ASPECT_RATIO_OPTIONS = [
  { label: '16:9', value: '16:9' },
  { label: '9:16', value: '9:16' },
  { label: '1:1', value: '1:1' },
  { label: '4:3', value: '4:3' },
  { label: '3:2', value: '3:2' },
  { label: '2:3', value: '2:3' },
]

const DURATION_OPTIONS = [
  { label: '5s', value: 5 },
  { label: '10s', value: 10 },
  { label: '15s', value: 15 },
]

const SIZE_OPTIONS = [
  { label: '小', value: 'small' },
  { label: '中', value: 'medium' },
  { label: '大', value: 'large' },
]

const ORIENTATION_OPTIONS = [
  { label: '横屏', value: 'landscape' },
  { label: '竖屏', value: 'portrait' },
]

const props = withDefaults(defineProps<{
  modelValue?: RenderParams
}>(), {
  modelValue: () => ({})
})

const emit = defineEmits<{
  (e: 'update:modelValue', val: RenderParams): void
}>()

const localValue = ref<RenderParams>({ ...props.modelValue })

watch(() => props.modelValue, (val) => {
  localValue.value = { ...val }
}, { deep: true })

function handleSelect<K extends keyof RenderParams>(key: K, value: RenderParams[K]) {
  localValue.value = { ...localValue.value, [key]: value }
  emit('update:modelValue', { ...localValue.value })
}
</script>

<style lang="scss" scoped>
.vrp {
  display: flex;
  flex-direction: column;
  gap: $lv-section-gap;
  padding: $lv-page-padding;
  background: $lv-surface-solid;
  border-radius: $lv-radius-md;
  box-shadow: $lv-shadow-sm;

  &__group {
    display: flex;
    flex-direction: column;
    gap: 12rpx;
  }

  &__group-label {
    font-size: $lv-font-sm;
    font-weight: 500;
    color: $lv-text-secondary;
  }

  &__group-options {
    display: flex;
    flex-wrap: wrap;
    gap: 12rpx;
  }

  &__option {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 8rpx 24rpx;
    border-radius: $lv-radius-full;
    background: $lv-primary-lighter;
    transition: all 0.2s ease;
    min-height: $lv-touch-min;
    min-width: 72rpx;

    &:active {
      transform: scale(0.96);
      opacity: 0.85;
    }

    &--active {
      background: $lv-primary;
      box-shadow: $lv-shadow-sm;

      .vrp__option-text {
        color: $lv-text-on-primary;
      }
    }
  }

  &__option-text {
    font-size: $lv-font-sm;
    font-weight: 500;
    color: $lv-text-secondary;
    transition: color 0.2s ease;
    white-space: nowrap;
  }
}
</style>
