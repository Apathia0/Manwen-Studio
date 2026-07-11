<template>
  <view :class="['chat-input', { 'chat-input--embedded': embedded }]">
    <view class="chat-input__wrapper">
      <textarea
        v-model="inputValue"
        :placeholder="placeholder"
        :disabled="disabled"
        :cursor-spacing="cursorSpacing"
        :adjust-position="true"
        class="chat-input__field"
        @input="handleInput"
        @focus="handleFocus"
        @blur="handleBlur"
      />
      <view class="chat-input__actions">
        <view
          v-if="streaming"
          class="chat-input__btn chat-input__btn--stop"
          @tap="handleStop"
        >
          <component :is="SquareIcon" :size="28" color="#fff" :stroke-width="2.5" />
        </view>
        <view
          v-else
          :class="['chat-input__btn', { 'chat-input__btn--disabled': !canSend }]"
          @tap="handleSend"
        >
          <text v-if="embedded" class="chat-input__send-label">发送</text>
          <component v-else :is="SendIcon" :size="28" color="#fff" :stroke-width="2.5" />
        </view>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { Send as SendIcon, Square as SquareIcon } from '@lucide/vue'

interface ChatInputProps {
  modelValue?: string
  placeholder?: string
  disabled?: boolean
  streaming?: boolean
  embedded?: boolean
  cursorSpacing?: number
}

const props = withDefaults(defineProps<ChatInputProps>(), {
  modelValue: '',
  placeholder: '输入创作要求...',
  disabled: false,
  streaming: false,
  embedded: false,
  cursorSpacing: 120
})

const emit = defineEmits<{
  (e: 'update:modelValue', value: string): void
  (e: 'send', content: string): void
  (e: 'stop'): void
  (e: 'focus'): void
  (e: 'blur'): void
}>()

const inputValue = ref(props.modelValue)
const focused = ref(false)

const canSend = computed(() => {
  return inputValue.value.trim().length > 0 && !props.disabled && !props.streaming
})

watch(() => props.modelValue, (value) => {
  if (value !== inputValue.value) inputValue.value = value
})

function handleInput() {
  emit('update:modelValue', inputValue.value)
}

function handleSend() {
  if (canSend.value) {
    emit('send', inputValue.value.trim())
    inputValue.value = ''
    emit('update:modelValue', '')
  }
}

function handleStop() {
  emit('stop')
}

function handleFocus() {
  focused.value = true
  emit('focus')
}

function handleBlur() {
  focused.value = false
  emit('blur')
}
</script>

<style lang="scss" scoped>
.chat-input {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  background: $lv-surface-solid;
  border-top: 1rpx solid $lv-border-light;
  padding: 16rpx $lv-page-padding;
  @include safe-area-bottom(16rpx);

  &__wrapper {
    display: flex;
    align-items: flex-end;
    background: $lv-primary-lighter;
    border: 1rpx solid $lv-border;
    border-radius: $lv-radius-lg;
    padding: 12rpx 16rpx;
  }

  &__field {
    flex: 1;
    min-height: 48rpx;
    max-height: 200rpx;
    padding: 0;
    font-size: $lv-font-base;
    color: $lv-text-primary;
    background: transparent;
  }

  &__actions {
    display: flex;
    align-items: center;
    margin-left: 12rpx;
  }

  &__btn {
    width: 72rpx;
    height: 72rpx;
    border-radius: 50%;
    @include flex-center;

    &--stop {
      background: $lv-error;
      color: $lv-text-on-primary;
    }

    &:not(&--stop):not(&--disabled) {
      background: $lv-primary;
      color: $lv-text-on-primary;
    }

    &--disabled {
      background: $lv-border-light;
      color: $lv-text-muted;
    }

    &:active:not(&--disabled) {
      opacity: 0.8;
    }
  }

  &__send-label {
    font-size: 28rpx;
    font-weight: 600;
    color: #ffffff;
  }

  &--embedded {
    position: static;
    padding: 0 20rpx 16rpx;
    border-top: 0;
    background: transparent;

    .chat-input__wrapper {
      gap: 14rpx;
      padding: 0;
      background: transparent;
      border: 0;
      border-radius: 0;
    }

    .chat-input__field {
      box-sizing: border-box;
      height: 84rpx;
      min-height: 84rpx;
      max-height: 160rpx;
      padding: 20rpx;
      border: 1rpx solid #cbd5e1;
      border-radius: 12rpx;
      background: #ffffff;
      font-size: 27rpx;
      line-height: 42rpx;
    }

    .chat-input__actions {
      margin-left: 0;
    }

    .chat-input__btn {
      width: 124rpx;
      height: 84rpx;
      border-radius: 12rpx;
    }
  }
}
</style>
