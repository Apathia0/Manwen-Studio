<template>
  <view :class="textareaWrapperClasses">
    <view v-if="label" class="lv-textarea__label">
      <text class="lv-textarea__label-text">{{ label }}</text>
    </view>
    <view class="lv-textarea__field-wrapper">
      <textarea
        :value="modelValue"
        :placeholder="placeholder"
        :disabled="disabled || readonly"
        :maxlength="maxlength"
        :auto-height="autoHeight"
        class="lv-textarea__field"
        @input="handleInput"
        @focus="handleFocus"
        @blur="handleBlur"
      />
      <view v-if="showCount" class="lv-textarea__count">
        <text class="lv-textarea__count-text">{{ currentCount }}/{{ maxlength }}</text>
      </view>
    </view>
    <view v-if="error" class="lv-textarea__error">
      <text class="lv-textarea__error-text">{{ error }}</text>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'

interface TextareaProps {
  modelValue: string
  label?: string
  placeholder?: string
  disabled?: boolean
  readonly?: boolean
  error?: string
  maxlength?: number
  showCount?: boolean
  autoHeight?: boolean
}

const props = withDefaults(defineProps<TextareaProps>(), {
  placeholder: '',
  disabled: false,
  readonly: false,
  maxlength: 500,
  showCount: false,
  autoHeight: true
})

const emit = defineEmits<{
  (e: 'update:modelValue', value: string): void
  (e: 'focus', event: Event): void
  (e: 'blur', event: Event): void
}>()

const focused = ref(false)

const textareaWrapperClasses = computed(() => [
  'lv-textarea',
  {
    'lv-textarea--focused': focused.value,
    'lv-textarea--disabled': props.disabled,
    'lv-textarea--readonly': props.readonly,
    'lv-textarea--error': props.error
  }
])

const currentCount = computed(() => props.modelValue.length)

function handleInput(event: any) {
  emit('update:modelValue', event.detail.value)
}

function handleFocus(event: Event) {
  focused.value = true
  emit('focus', event)
}

function handleBlur(event: Event) {
  focused.value = false
  emit('blur', event)
}
</script>

<style lang="scss" scoped>
.lv-textarea {
  margin-bottom: $lv-item-gap;

  &__label {
    margin-bottom: 12rpx;
  }

  &__label-text {
    font-size: $lv-font-sm;
    color: $lv-text-secondary;
    font-weight: 500;
  }

  &__field-wrapper {
    position: relative;
    background: #ffffff;
    border: 1rpx solid $lv-border;
    border-radius: $lv-radius-sm;
    transition: border-color 0.2s ease, box-shadow 0.2s ease;
  }

  &__field {
    width: 100%;
    min-height: 200rpx;
    padding: 24rpx;
    font-size: $lv-font-base;
    color: $lv-text-primary;
    background: transparent;
  }

  &__count {
    position: absolute;
    bottom: 16rpx;
    right: 16rpx;
  }

  &__count-text {
    font-size: $lv-font-xs;
    color: $lv-text-muted;
  }

  &__error {
    margin-top: 8rpx;
  }

  &__error-text {
    font-size: $lv-font-xs;
    color: $lv-error;
  }

  &--focused &__field-wrapper {
    border-color: $lv-border-focus;
    box-shadow: 0 0 0 4rpx rgba(37, 99, 235, 0.1);
  }

  &--disabled &__field-wrapper {
    background: $lv-primary-lighter;
    opacity: 0.7;
  }

  &--readonly &__field-wrapper {
    background: $lv-primary-lighter;
  }

  &--error &__field-wrapper {
    border-color: $lv-error;
    box-shadow: 0 0 0 4rpx rgba(190, 18, 60, 0.1);
  }
}
</style>
