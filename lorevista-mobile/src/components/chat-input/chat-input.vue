<template>
  <view class="chat-input">
    <view class="chat-input__wrapper">
      <textarea
        v-model="inputValue"
        :placeholder="placeholder"
        :disabled="disabled"
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
          <component :is="SendIcon" :size="28" color="#fff" :stroke-width="2.5" />
        </view>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { Send as SendIcon, Square as SquareIcon } from '@lucide/vue'

interface ChatInputProps {
  modelValue?: string
  placeholder?: string
  disabled?: boolean
  streaming?: boolean
}

const props = withDefaults(defineProps<ChatInputProps>(), {
  modelValue: '',
  placeholder: '输入指令...',
  disabled: false,
  streaming: false
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
}
</style>
