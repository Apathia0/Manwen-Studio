<template>
  <view class="agent-history">
    <lv-navbar title="历史会话" show-back />
    <view class="agent-history__content">
      <view v-for="conv in conversations" :key="conv.id" class="agent-history__item" @tap="openConversation(conv.id)">
        <view class="agent-history__info">
          <text class="agent-history__title">{{ conv.title }}</text>
          <text class="agent-history__date">{{ conv.updated_at }}</text>
        </view>
        <view class="agent-history__delete" @tap.stop="deleteConversation(conv.id)">
          <Trash2 :size="16" color="#ef4444" />
        </view>
      </view>
      <lv-empty v-if="conversations.length === 0" title="暂无历史会话" description="开始新的对话" />
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { get } from '@/utils/request'
import { agentApi } from '@/api'
import { useAgentStore } from '@/stores/agent'
import { Trash2 } from '@lucide/vue'
import LvNavbar from '@/components/lv-navbar/lv-navbar.vue'
import LvEmpty from '@/components/lv-empty/lv-empty.vue'

interface Conv { id: number; title: string; updated_at: string; chapter_id?: number | null }
const conversations = ref<Conv[]>([])
const agentStore = useAgentStore()

let storyId = ''

onMounted(async () => {
  const pages = getCurrentPages(); const page = pages[pages.length - 1] as any
  storyId = page.options?.storyId || ''
  if (!storyId) return
  try {
    conversations.value = await get<Conv[]>(`/api/stories/${storyId}/agent/conversations`)
  } catch (e) { console.error(e) }
})

function openConversation(id: number) {
  const conversation = conversations.value.find(item => item.id === id)
  const chapterId = conversation?.chapter_id || ''
  uni.navigateTo({ url: `/pages/workspace/agent?convId=${id}&storyId=${storyId}&chapterId=${chapterId}` })
}

function deleteConversation(id: number) {
  uni.showModal({
    title: '删除会话',
    content: '确定删除该会话吗？删除后不可恢复。',
    success: async (res) => {
      if (!res.confirm) return
      try {
        await agentStore.deleteConversation(Number(storyId), id)
        conversations.value = conversations.value.filter(c => c.id !== id)
        uni.showToast({ title: '已删除', icon: 'success' })
      } catch (e: any) {
        uni.showToast({ title: e.message || '删除失败', icon: 'none' })
      }
    }
  })
}
</script>

<style lang="scss" scoped>
.agent-history {
  min-height: 100vh; background: $lv-bg-start;
  &__content { padding: calc(var(--status-bar-height) + 88rpx + $lv-page-padding) $lv-page-padding; }
  &__item {
    padding: 28rpx; background: #fff; border-radius: 24rpx; margin-bottom: 16rpx;
    display: flex; justify-content: space-between; align-items: center;
    &:active { background: $lv-primary-lighter; }
  }
  &__info { flex: 1; min-width: 0; margin-right: 16rpx; }
  &__title { font-size: 28rpx; color: $lv-text-primary; font-weight: 500; display: block; margin-bottom: 8rpx; }
  &__date { font-size: 22rpx; color: $lv-text-muted; }
  &__delete {
    width: 56rpx; height: 56rpx;
    display: flex; align-items: center; justify-content: center;
    flex-shrink: 0;
    &:active { opacity: 0.5; }
  }
}
</style>
