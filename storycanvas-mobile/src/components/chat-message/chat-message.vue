<template>
  <view :class="messageClasses">
    <view v-if="!compact" class="chat-message__avatar">
      <User v-if="role === 'user'" :size="18" />
      <Bot v-else :size="18" />
    </view>
    <view class="chat-message__content">
      <view class="chat-message__bubble">
        <text class="chat-message__text">{{ content }}</text>
        <view v-if="streaming" class="chat-message__cursor" />
      </view>
      <view v-if="toolCalls && toolCalls.length > 0" class="chat-message__tools">
        <view
          v-for="tool in toolCalls"
          :key="tool.id"
          :class="['chat-message__tool', `chat-message__tool--${tool.status}`]"
        >
          <component :is="toolIconMap[tool.status] || Circle" :size="14" />
          <text class="chat-message__tool-name">{{ getToolStatusLabel(tool.name, tool.status) }}</text>
        </view>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { ToolCallInfo } from '@/api/types'
import { getToolStatusLabel } from '@/utils/agent-tool-display'
import { User, Bot, Loader, CircleCheck, CircleX, Circle } from '@lucide/vue'

interface MessageProps {
  role: 'user' | 'assistant'
  content: string
  streaming?: boolean
  toolCalls?: ToolCallInfo[]
  compact?: boolean
}

const props = withDefaults(defineProps<MessageProps>(), {
  streaming: false,
  toolCalls: () => [],
  compact: false
})

const messageClasses = computed(() => [
  'chat-message',
  `chat-message--${props.role}`,
  { 'chat-message--compact': props.compact }
])

const toolIconMap: Record<string, any> = {
  running: Loader,
  success: CircleCheck,
  error: CircleX,
}
</script>

<style lang="scss" scoped>
.chat-message {
  display: flex;
  margin-bottom: 24rpx;

  &--user {
    flex-direction: row-reverse;

    .chat-message__avatar {
      background: $lv-primary;
      color: $lv-text-on-primary;
    }

    .chat-message__bubble {
      background: $lv-primary;
      color: $lv-text-on-primary;
      border-radius: 24rpx 24rpx 8rpx 24rpx;
      margin-right: 16rpx;
    }
  }

  &--assistant {
    .chat-message__avatar {
      background: $lv-primary-lighter;
      color: $lv-primary;
    }

    .chat-message__bubble {
      background: #f8fbff;
      color: $lv-text-primary;
      border: 1rpx solid $lv-border-light;
      border-radius: 24rpx 24rpx 24rpx 8rpx;
      margin-left: 16rpx;
    }
  }

  &__avatar {
    width: 72rpx;
    height: 72rpx;
    border-radius: 50%;
    @include flex-center;
    flex-shrink: 0;
  }

  &__content {
    max-width: 80%;
  }

  &__bubble {
    padding: 24rpx;
    position: relative;
  }

  &__text {
    font-size: $lv-font-base;
    line-height: 1.6;
    word-break: break-all;
  }

  &__cursor {
    display: inline-block;
    width: 4rpx;
    height: 28rpx;
    background: $lv-primary;
    margin-left: 4rpx;
    animation: pulse 1s infinite;
  }

  &__tools {
    margin-top: 16rpx;
  }

  &__tool {
    display: flex;
    align-items: center;
    padding: 12rpx 16rpx;
    background: $lv-surface-solid;
    border: 1rpx solid $lv-border-light;
    border-radius: $lv-radius-sm;
    margin-bottom: 8rpx;
    font-size: $lv-font-sm;

    &--running {
      border-color: $lv-primary;
      color: $lv-primary;
    }

    &--success {
      border-color: $lv-success;
      color: $lv-success;
    }

    &--error {
      border-color: $lv-error;
      color: $lv-error;
    }
  }

  &__tool-name {
    margin-left: 8rpx;
    font-weight: 500;
  }

  &--compact {
    margin-bottom: 22rpx;

    &.chat-message--user {
      justify-content: flex-start;

      .chat-message__content {
        margin-left: auto;
      }

      .chat-message__bubble {
        margin-right: 0;
        border-radius: 14rpx;
      }
    }

    &.chat-message--assistant {
      .chat-message__bubble {
        margin-left: 0;
        border: 0;
        border-radius: 14rpx;
        background: #eef4ff;
        color: #2b3e61;
      }
    }

    .chat-message__content {
      max-width: 88%;
    }

    .chat-message__bubble {
      padding: 18rpx 22rpx;
    }

    .chat-message__text {
      font-size: 26rpx;
      line-height: 1.55;
      word-break: break-word;
    }
  }
}

@keyframes pulse {
  0% {
    opacity: 1;
  }
  50% {
    opacity: 0.3;
  }
  100% {
    opacity: 1;
  }
}
</style>
