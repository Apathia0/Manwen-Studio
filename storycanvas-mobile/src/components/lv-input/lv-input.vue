<template>
  <view :class="inputWrapperClasses">
    <view v-if="label" class="lv-input__label">
      <text class="lv-input__label-text">{{ label }}</text>
    </view>
    <view class="lv-input__field-wrapper">
      <input
        v-if="type !== 'textarea'"
        :type="type"
        :value="modelValue"
        :placeholder="placeholder"
        :disabled="disabled || readonly"
        :maxlength="maxlength"
        class="lv-input__field"
        @input="handleInput"
        @focus="handleFocus"
        @blur="handleBlur"
      />
      <textarea
        v-else
        :value="modelValue"
        :placeholder="placeholder"
        :disabled="disabled || readonly"
        :maxlength="maxlength"
        :auto-height="autoHeight"
        class="lv-input__textarea"
        @input="handleInput"
        @focus="handleFocus"
        @blur="handleBlur"
      />
      <view v-if="showPasswordToggle && type === 'password'" class="lv-input__password-toggle" @tap="togglePasswordVisible">
        <Eye v-if="passwordVisible" :size="18" color="#94a3b8" />
        <EyeOff v-else :size="18" color="#94a3b8" />
      </view>
    </view>
    <view v-if="error" class="lv-input__error">
      <text class="lv-input__error-text">{{ error }}</text>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { Eye, EyeOff } from '@lucide/vue'

interface InputProps {
  modelValue: string
  type?: 'text' | 'password' | 'number' | 'email' | 'textarea'
  label?: string
  placeholder?: string
  disabled?: boolean
  readonly?: boolean
  error?: string
  maxlength?: number
  showPasswordToggle?: boolean
  autoHeight?: boolean
}

const props = withDefaults(defineProps<InputProps>(), {
  type: 'text',
  placeholder: '',
  disabled: false,
  readonly: false,
  showPasswordToggle: false,
  autoHeight: true
})

const emit = defineEmits<{
  (e: 'update:modelValue', value: string): void
  (e: 'focus', event: Event): void
  (e: 'blur', event: Event): void
}>()

const focused = ref(false)
const passwordVisible = ref(false)

const inputWrapperClasses = computed(() => [
  'lv-input',
  {
    'lv-input--focused': focused.value,
    'lv-input--disabled': props.disabled,
    'lv-input--readonly': props.readonly,
    'lv-input--error': props.error
  }
])

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

function togglePasswordVisible() {
  passwordVisible.value = !passwordVisible.value
}
</script>

<style lang="scss" scoped>
.lv-input {
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
    height: $lv-touch-comfortable;
    padding: 0 24rpx;
    font-size: $lv-font-base;
    color: $lv-text-primary;
    background: transparent;
  }

  &__textarea {
    width: 100%;
    min-height: 200rpx;
    padding: 24rpx;
    font-size: $lv-font-base;
    color: $lv-text-primary;
    background: transparent;
  }

  &__password-toggle {
    position: absolute;
    right: 24rpx;
    top: 50%;
    transform: translateY(-50%);
    padding: 12rpx;
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
