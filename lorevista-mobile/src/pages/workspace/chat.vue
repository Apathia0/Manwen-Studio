<template>
  <view class="chat-page">
    <lv-navbar title="AI 对话" show-back />

    <scroll-view scroll-y class="chat-page__messages">
      <view class="chat-page__list">
        <chat-message
          v-for="(msg, i) in chatMessages"
          :key="i"
          :role="msg.role"
          :content="msg.content"
        />
        <chat-message
          v-if="streamingContent"
          role="assistant"
          :content="streamingContent"
          :streaming="streaming"
        />
      </view>
    </scroll-view>

    <chat-input
      v-model="inputText"
      :streaming="streaming"
      @send="handleSend"
      @stop="stopStreaming"
    />
  </view>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { useChat } from '@/composables/useChat'
import LvNavbar from '@/components/lv-navbar/lv-navbar.vue'
import ChatMessage from '@/components/chat-message/chat-message.vue'
import ChatInput from '@/components/chat-input/chat-input.vue'

const inputText = ref('')
const chapterId = ref(0)

const { messages: chatMessages, streaming, streamingContent, sendMessage, stopStreaming } = useChat(() => chapterId.value)

onLoad((options) => {
  chapterId.value = parseInt(options?.chapterId || '0')
})

function handleSend(text: string) {
  sendMessage(text)
}
</script>

<style lang="scss" scoped>
.chat-page {
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: linear-gradient(180deg, $lv-bg-start 0%, $lv-bg-end 100%);

  &__messages {
    flex: 1;
    margin-bottom: 140rpx;
  }

  &__list {
    padding: $lv-page-padding;
    padding-bottom: 32rpx;
  }
}
</style>
