<template>
  <view class="framework-chat">
    <lv-navbar title="调整框架" show-back />

    <scroll-view scroll-y class="framework-chat__messages" :scroll-into-view="scrollTarget">
      <view
        v-for="(msg, i) in messages"
        :key="i"
        :id="`msg-${i}`"
        :class="['framework-chat__message', `framework-chat__message--${msg.role}`]"
      >
        <view class="framework-chat__bubble">
          <text class="framework-chat__text">{{ msg.content }}</text>
          <view v-if="i === messages.length - 1 && streaming" class="framework-chat__cursor" />
        </view>
      </view>
      <view id="scroll-bottom" />
    </scroll-view>

    <view v-if="frameworkUpdated" class="framework-chat__banner" @tap="goFramework">
      <lv-icon name="CheckCircle" :size="16" color="#15803d" style="margin-right: 8rpx;" />
      <text class="framework-chat__banner-text">框架已更新，点击查看</text>
    </view>

    <chat-input
      v-model="inputText"
      placeholder="描述你想要的调整..."
      :streaming="streaming"
      @send="handleSend"
      @stop="stopStreaming"
    />
  </view>
</template>

<script setup lang="ts">
import { ref, nextTick, onUnmounted } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { useSSE } from '@/composables/useSSE'
import { useFrameworkStore } from '@/stores/framework'
import { useUiStore } from '@/stores/ui'
import { getToken } from '@/utils/storage'
import { frameworkApi } from '@/api'
import LvNavbar from '@/components/lv-navbar/lv-navbar.vue'
import LvIcon from '@/components/lv-icon/lv-icon.vue'
import ChatInput from '@/components/chat-input/chat-input.vue'

interface ChatMsg {
  role: 'user' | 'assistant'
  content: string
}

const frameworkStore = useFrameworkStore()
const uiStore = useUiStore()

const messages = ref<ChatMsg[]>([
  { role: 'assistant', content: '我是框架助手，你可以告诉我想要调整的框架内容。例如：\n- 增加一个反派角色\n- 第二幕增加一个转折章节\n- 调整故事结局为开放式' }
])
const inputText = ref('')
const streaming = ref(false)
const frameworkUpdated = ref(false)
const scrollTarget = ref('')

const storyId = ref(0)

onLoad((options) => {
  storyId.value = parseInt(options?.storyId || '0')
})

onUnmounted(() => {
  sseHandle?.stop()
})

let sseHandle: ReturnType<typeof useSSE> | null = null

function handleSend(text: string) {
  if (!text.trim() || streaming.value) return

  messages.value.push({ role: 'user', content: text })
  inputText.value = ''
  scrollToBottom()

  streaming.value = true
  let assistantContent = ''

  const token = getToken()
  const headers: Record<string, string> = {}
  if (token) headers['Authorization'] = `Bearer ${token}`

  const sse = useSSE()
  sseHandle = sse

  sse.start({
    url: frameworkApi.adjustUrl(storyId.value),
    headers,
    body: { messages: [{ role: 'user', content: text }] },
    onEvent: (event) => {
      if (event.type === 'token') {
        assistantContent += event.data.content
        // 更新最后一条消息
        const lastMsg = messages.value[messages.value.length - 1]
        if (lastMsg && lastMsg.role === 'assistant' && lastMsg !== messages.value[0]) {
          lastMsg.content = assistantContent
        } else {
          messages.value.push({ role: 'assistant', content: assistantContent })
        }
        scrollToBottom()
      } else if (event.type === 'done') {
        if (event.data.content && assistantContent !== event.data.content) {
          const lastMsg = messages.value[messages.value.length - 1]
          if (lastMsg) lastMsg.content = event.data.content
        }
        streaming.value = false
        frameworkUpdated.value = true
        // 刷新框架数据
        frameworkStore.loadFramework(storyId.value)
      } else if (event.type === 'error') {
        streaming.value = false
        uiStore.error(event.data.error || '请求失败')
      }
    },
    onError: () => {
      streaming.value = false
      uiStore.error('网络错误')
    },
    onComplete: () => {
      streaming.value = false
    }
  })
}

function stopStreaming() {
  sseHandle?.stop()
  streaming.value = false
}

function goFramework() {
  uni.navigateBack()
}

function scrollToBottom() {
  nextTick(() => {
    scrollTarget.value = 'scroll-bottom'
  })
}
</script>

<style lang="scss" scoped>
.framework-chat {
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: linear-gradient(180deg, $lv-bg-start 0%, $lv-bg-end 100%);

  &__messages {
    flex: 1;
    padding: $lv-page-padding;
    overflow: hidden;
  }

  &__message {
    margin-bottom: 24rpx;
    display: flex;

    &--user {
      justify-content: flex-end;

      .framework-chat__bubble {
        background: $lv-primary;
        color: $lv-text-on-primary;
        border-radius: 24rpx 24rpx 8rpx 24rpx;
      }
    }

    &--assistant {
      justify-content: flex-start;

      .framework-chat__bubble {
        background: #f8fbff;
        color: $lv-text-primary;
        border: 1rpx solid $lv-border-light;
        border-radius: 24rpx 24rpx 24rpx 8rpx;
      }
    }
  }

  &__bubble {
    max-width: 85%;
    padding: 24rpx;
  }

  &__text {
    font-size: $lv-font-base;
    line-height: 1.6;
    white-space: pre-wrap;
  }

  &__cursor {
    display: inline-block;
    width: 4rpx;
    height: 28rpx;
    background: $lv-primary;
    animation: pulse 1s infinite;
    margin-left: 4rpx;
    vertical-align: middle;
  }

  &__banner {
    display: flex;
    align-items: center;
    justify-content: center;
    background: $lv-success-bg;
    border: 1rpx solid rgba(21, 128, 61, 0.2);
    border-radius: $lv-radius-md;
    padding: 24rpx;
    margin: 0 $lv-page-padding 16rpx;
    &:active { opacity: 0.8; }
  }

  &__banner-text {
    font-size: $lv-font-sm;
    color: $lv-success;
    font-weight: 600;
  }
}

@keyframes pulse {
  0% { opacity: 1; }
  50% { opacity: 0.3; }
  100% { opacity: 1; }
}
</style>
