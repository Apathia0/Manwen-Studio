<template>
  <view class="onboarding-page">
    <lv-navbar title="灵感捕手" show-back />

    <onboarding-stepper
      :steps="['故事概念', '题材定位', '核心卖点', '目标体量', '核心设定']"
      :current="currentStep"
    />

    <view class="onboarding-page__chat">
      <scroll-view scroll-y class="onboarding-page__messages" :scroll-into-view="scrollTarget">
        <view
          v-for="(msg, index) in messages"
          :key="index"
          :id="`msg-${index}`"
          :class="['onboarding-page__message', `onboarding-page__message--${msg.role}`]"
        >
          <view class="onboarding-page__bubble">
            <text class="onboarding-page__text">{{ msg.content }}</text>
            <view v-if="index === messages.length - 1 && streaming" class="onboarding-page__cursor" />
          </view>
        </view>
        <view id="scroll-bottom" />
      </scroll-view>
    </view>

    <view class="onboarding-page__input">
      <view class="onboarding-page__input-wrapper">
        <input
          v-model="inputText"
          class="onboarding-page__field"
          :placeholder="streaming ? '等待回复...' : '输入你的想法...'"
          :disabled="streaming"
          @confirm="handleSend"
        />
        <view
          v-if="!streaming"
          :class="['onboarding-page__send', { 'onboarding-page__send--disabled': !inputText.trim() }]"
          @tap="handleSend"
        >
          <Send :size="24" color="#ffffff" />
        </view>
      </view>
      <text v-if="!isCompleted" class="onboarding-page__skip" @tap="handleSkip">跳过引导</text>
    </view>

    <lv-modal v-model:visible="showConfirm" title="创意简报" @confirm="handleConfirm">
      <bible-summary :bible="bible" default-expanded />
    </lv-modal>
  </view>
</template>

<script setup lang="ts">
import { ref, nextTick } from 'vue'
import { Send } from '@lucide/vue'
import { onLoad } from '@dcloudio/uni-app'
import { onboardingApi } from '@/api'
import { useStoriesStore } from '@/stores/stories'
import { useUiStore } from '@/stores/ui'
import LvNavbar from '@/components/lv-navbar/lv-navbar.vue'
import OnboardingStepper from '@/components/onboarding-stepper/onboarding-stepper.vue'
import LvModal from '@/components/lv-modal/lv-modal.vue'
import BibleSummary from '@/components/bible-summary/bible-summary.vue'

interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
}

const storyStore = useStoriesStore()
const uiStore = useUiStore()

const storyId = ref(0)
const currentStep = ref(0)
const messages = ref<ChatMessage[]>([
  { role: 'assistant', content: '你好！我是灵感捕手。请告诉我你想要创作什么样的故事？' }
])
const inputText = ref('')
const streaming = ref(false)
const isCompleted = ref(false)
const showConfirm = ref(false)
const bible = ref<any>({})
const collectedInfo = ref<Record<string, string>>({})
const scrollTarget = ref('')

onLoad((options) => {
  const id = parseInt(options?.storyId || '0')
  if (!id) {
    uiStore.error('未指定故事')
    return
  }
  storyId.value = id
  storyStore.setActiveStory(id)
  console.log('[Onboarding] storyId =', id)
})

async function handleSend() {
  const text = inputText.value.trim()
  if (!text || streaming.value) return

  inputText.value = ''
  messages.value.push({ role: 'user', content: text })
  scrollToBottom()

  streaming.value = true
  try {
    // 构造正确的请求格式：messages 数组
    const requestMessages = messages.value.map(m => ({ role: m.role, content: m.content }))

    const data = await onboardingApi.sendMessage(storyId.value, {
      messages: requestMessages,
      collected_info: collectedInfo.value,
      step: currentStep.value
    })

    messages.value.push({ role: 'assistant', content: data.reply })
    scrollToBottom()

    // 更新收集的信息
    if (data.collected_info) {
      collectedInfo.value = data.collected_info
    }

    // 更新步骤
    if (data.step) {
      currentStep.value = data.step - 1 // 步骤从 1 开始，索引从 0 开始
    }

    // 检查是否完成
    if (data.is_complete) {
      isCompleted.value = true
      if (data.creative_brief) {
        bible.value = data.creative_brief
      }
      showConfirm.value = true
    }
  } catch (e: any) {
    uiStore.error(e.message || '发送失败')
  } finally {
    streaming.value = false
  }
}

async function handleSkip() {
  try {
    await onboardingApi.skipOnboarding(storyId.value)
    uiStore.success('已跳过引导')
    setTimeout(() => {
      uni.navigateBack()
    }, 1500)
  } catch (e: any) {
    uiStore.error(e.message || '操作失败')
  }
}

async function handleConfirm() {
  try {
    await onboardingApi.confirmOnboarding(storyId.value, {
      collected_info: collectedInfo.value,
      messages: messages.value.map(m => ({ role: m.role, content: m.content }))
    })
    uiStore.success('引导完成！')
    showConfirm.value = false
    setTimeout(() => {
      uni.navigateTo({ url: `/pages/workspace/chapter-view?storyId=${storyId.value}` })
    }, 1500)
  } catch (e: any) {
    uiStore.error(e.message || '确认失败')
  }
}

function scrollToBottom() {
  nextTick(() => {
    scrollTarget.value = 'scroll-bottom'
  })
}
</script>

<style lang="scss" scoped>
.onboarding-page {
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: linear-gradient(180deg, $lv-bg-start 0%, $lv-bg-end 100%);

  &__chat {
    flex: 1;
    overflow: hidden;
  }

  &__messages {
    height: 100%;
    padding: $lv-page-padding;
  }

  &__message {
    margin-bottom: 24rpx;
    display: flex;

    &--user {
      justify-content: flex-end;

      .onboarding-page__bubble {
        background: $lv-primary;
        color: $lv-text-on-primary;
        border-radius: 24rpx 24rpx 8rpx 24rpx;
      }
    }

    &--assistant {
      justify-content: flex-start;

      .onboarding-page__bubble {
        background: #f8fbff;
        color: $lv-text-primary;
        border: 1rpx solid $lv-border-light;
        border-radius: 24rpx 24rpx 24rpx 8rpx;
      }
    }
  }

  &__bubble {
    max-width: 80%;
    padding: 24rpx;
  }

  &__text {
    font-size: $lv-font-base;
    line-height: 1.6;
  }

  &__cursor {
    display: inline-block;
    width: 4rpx;
    height: 28rpx;
    background: $lv-primary;
    animation: pulse 1s infinite;
  }

  &__input {
    padding: 16rpx $lv-page-padding;
    background: $lv-surface-solid;
    border-top: 1rpx solid $lv-border-light;
    @include safe-area-bottom(16rpx);
  }

  &__input-wrapper {
    display: flex;
    align-items: center;
    background: $lv-primary-lighter;
    border-radius: $lv-radius-lg;
    padding: 12rpx 16rpx;
  }

  &__field {
    flex: 1;
    height: 48rpx;
    font-size: $lv-font-base;
    color: $lv-text-primary;
    background: transparent;
  }

  &__send {
    width: 64rpx;
    height: 64rpx;
    border-radius: 50%;
    @include flex-center;
    background: $lv-primary;
    color: $lv-text-on-primary;
    margin-left: 12rpx;

    &--disabled {
      background: $lv-border-light;
      color: $lv-text-muted;
    }
  }

  &__skip {
    display: block;
    text-align: center;
    font-size: $lv-font-sm;
    color: $lv-text-muted;
    margin-top: 16rpx;

    &:active {
      color: $lv-primary;
    }
  }
}

@keyframes pulse {
  0% { opacity: 1; }
  50% { opacity: 0.3; }
  100% { opacity: 1; }
}
</style>
