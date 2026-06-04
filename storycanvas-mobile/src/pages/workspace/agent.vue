<template>
  <view class="agent-page">
    <lv-navbar title="AI 助手" show-back />

    <view class="agent-page__header">
      <lv-button size="sm" @tap="newConversation">新对话</lv-button>
      <lv-button size="sm" secondary @tap="goHistory">历史</lv-button>
    </view>

    <view class="agent-page__quick">
      <view class="agent-page__quick-grid">
        <view v-for="action in quickActions" :key="action" class="agent-page__quick-btn" @tap="sendQuick(action)">
          <text>{{ action }}</text>
        </view>
      </view>
    </view>

    <scroll-view scroll-y class="agent-page__messages">
      <chat-message v-for="msg in messages" :key="msg.id" :role="msg.role" :content="msg.content" :tool-calls="msg.toolCalls" />
      <chat-message
        v-if="streamingContent"
        role="assistant"
        :content="streamingContent"
        :streaming="true"
      />
      <lv-loading v-if="streaming && !streamingContent" />
    </scroll-view>

    <chat-input v-model="inputText" :streaming="streaming" @send="handleSend" @stop="stopStreaming" />

    <changes-banner
      v-if="pendingChanges.length > 0"
      :count="pendingChanges.length"
      @confirm="confirmChanges"
      @rollback="rollbackChanges"
    />
  </view>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { storeToRefs } from 'pinia'
import { useAgentStore } from '@/stores/agent'
import { useUiStore } from '@/stores/ui'
import LvNavbar from '@/components/lv-navbar/lv-navbar.vue'
import LvButton from '@/components/lv-button/lv-button.vue'
import LvLoading from '@/components/lv-loading/lv-loading.vue'
import ChatMessage from '@/components/chat-message/chat-message.vue'
import ChatInput from '@/components/chat-input/chat-input.vue'
import ChangesBanner from '@/components/changes-banner/changes-banner.vue'

const agentStore = useAgentStore()
const uiStore = useUiStore()
const { messages, streaming, streamingContent, pendingChanges } = storeToRefs(agentStore)

const inputText = ref('')
const quickActions = ['阅读当前章节', '修改当前章节', '优化故事框架', '质量评估', '优化分镜脚本', '角色设定建议']

let storyId = 0

onLoad(async (options) => {
  storyId = parseInt(options?.storyId || '0')
  if (!storyId) return

  const convId = options?.convId ? parseInt(options.convId) : 0

  // 加载会话列表
  try {
    await agentStore.loadConversations(storyId)
  } catch (e) {
    console.error('加载会话列表失败', e)
  }

  if (convId) {
    // 从历史页面进入，加载指定会话
    try {
      await agentStore.loadConversation(storyId, convId)
      return
    } catch (e) {
      console.error('加载历史会话失败', e)
    }
  } else if (agentStore.conversations.length > 0) {
    // 首次进入，自动打开最近一个会话
    const latest = agentStore.conversations[0]
    try {
      await agentStore.loadConversation(storyId, latest.id)
      return
    } catch (e) {
      console.error('加载最近会话失败', e)
    }
  }

  // 没有任何历史会话，显示欢迎页
  pendingChanges.value = []
  messages.value = [{ id: 'welcome', role: 'assistant', content: '我是你的AI写作助手，有什么可以帮到你的？' }]
})

async function newConversation() {
  if (storyId) {
    await agentStore.createConversation(storyId)
  }
  pendingChanges.value = []
  messages.value = [{ id: 'welcome', role: 'assistant', content: '我是你的AI写作助手，有什么可以帮到你的？' }]
}

function sendQuick(action: string) {
  handleSend(action)
}

async function handleSend(text: string) {
  if (!text.trim() || agentStore.streaming) return
  inputText.value = ''
  await agentStore.sendMessage(storyId, text)
}

function stopStreaming() {
  agentStore.stopStreaming()
}

async function confirmChanges() {
  try {
    await agentStore.confirmChanges(storyId)
    uiStore.success('变更已确认')
  } catch (e: any) {
    uiStore.error(e.message || '确认失败')
  }
}

async function rollbackChanges() {
  try {
    await agentStore.rollbackChanges(storyId)
    uiStore.success('变更已撤回')
  } catch (e: any) {
    uiStore.error(e.message || '撤回失败')
  }
}

function goHistory() {
  uni.navigateTo({ url: `/pages/workspace/agent-history?storyId=${storyId}` })
}
</script>

<style lang="scss" scoped>
.agent-page {
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: linear-gradient(180deg, $lv-bg-start 0%, $lv-bg-end 100%);

  &__header {
    display: flex;
    gap: 16rpx;
    padding: 16rpx $lv-page-padding;
    padding-top: calc(var(--status-bar-height) + 88rpx + 16rpx);
  }

  &__quick {
    padding: 0 $lv-page-padding 16rpx;
  }

  &__quick-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 12rpx;
  }

  &__quick-btn {
    padding: 16rpx;
    background: $lv-surface-solid;
    border-radius: $lv-radius-sm;
    text-align: center;
    font-size: $lv-font-sm;
    border: 1rpx solid $lv-border;
    &:active { background: $lv-primary-lighter; }
  }

  &__messages {
    flex: 1;
    margin-bottom: 140rpx;
    padding: $lv-page-padding;
    overflow: hidden;
  }
}
</style>
