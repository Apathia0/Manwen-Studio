<template>
  <view class="agent-page">
    <view class="agent-page__navbar">
      <view class="agent-page__nav-btn" @tap="goBack">
        <lv-icon name="ArrowLeft" :size="20" color="#0f172a" />
      </view>
      <view class="agent-page__nav-copy">
        <text class="agent-page__title">{{ pageTitle }}</text>
        <text class="agent-page__context">AI 创作助手</text>
      </view>
      <view class="agent-page__nav-btn" @tap="showMoreMenu">
        <lv-icon name="Ellipsis" :size="21" color="#0f172a" />
      </view>
    </view>

    <scroll-view scroll-y class="agent-page__messages" :scroll-into-view="scrollTarget">
      <view class="agent-page__context-card" @tap="showContextDetails">
        <view class="agent-page__status-dot" />
        <view class="agent-page__context-copy">
          <text class="agent-page__context-title">作品上下文已就绪</text>
          <text class="agent-page__context-detail">{{ contextDetail }}</text>
        </view>
        <lv-icon name="ChevronRight" :size="17" color="#94a3b8" />
      </view>

      <view class="agent-page__thread">
        <chat-message
          v-for="msg in messages"
          :key="msg.id"
          :role="msg.role"
          :content="msg.content"
          :tool-calls="msg.toolCalls"
          compact
        />
        <chat-message
          v-if="streamingContent || streamingToolCalls.length > 0"
          role="assistant"
          :content="streamingContent"
          :tool-calls="streamingToolCalls"
          :streaming="true"
          compact
        />
        <lv-loading v-if="streaming && !streamingContent && streamingToolCalls.length === 0" />
        <view id="agent-scroll-bottom" />
      </view>
    </scroll-view>

    <changes-banner
      v-if="pendingChanges.length > 0"
      :count="pendingChanges.length"
      :confirming="confirmingChanges"
      :rollbacking="rollbackingChanges"
      compact
      @view="showPendingChanges"
      @confirm="confirmChanges"
      @rollback="rollbackChanges"
    />

    <change-diff-sheet
      :visible="showChangeDiff"
      :changes="pendingChanges"
      :confirming="confirmingChanges"
      :rollbacking="rollbackingChanges"
      @close="showChangeDiff = false"
      @confirm="confirmChanges"
      @rollback="rollbackChanges"
    />

    <view class="agent-page__composer">
      <scroll-view scroll-x class="agent-page__quick" show-scrollbar="false">
        <view class="agent-page__quick-inner">
          <view v-for="action in quickActions" :key="action.label" class="agent-page__quick-btn" @tap="selectQuick(action)">
            <text>{{ action.label }}</text>
          </view>
        </view>
      </scroll-view>
      <chat-input
        v-model="inputText"
        placeholder="输入创作要求..."
        :streaming="streaming"
        embedded
        @send="handleSend"
        @stop="stopStreaming"
      />
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { onLoad, onShow } from '@dcloudio/uni-app'
import { storeToRefs } from 'pinia'
import { useAgentStore } from '@/stores/agent'
import { useUiStore } from '@/stores/ui'
import LvIcon from '@/components/lv-icon/lv-icon.vue'
import LvLoading from '@/components/lv-loading/lv-loading.vue'
import ChatMessage from '@/components/chat-message/chat-message.vue'
import ChatInput from '@/components/chat-input/chat-input.vue'
import ChangesBanner from '@/components/changes-banner/changes-banner.vue'
import ChangeDiffSheet from '@/components/change-diff-sheet/change-diff-sheet.vue'

interface QuickAction {
  label: string
  prompt: string
}

const agentStore = useAgentStore()
const uiStore = useUiStore()
const { messages, streaming, streamingContent, streamingToolCalls, pendingChanges } = storeToRefs(agentStore)

const inputText = ref('')
const initialTask = ref('自由对话')
const scrollTarget = ref('')
const showChangeDiff = ref(false)
const confirmingChanges = ref(false)
const rollbackingChanges = ref(false)
const quickActions: QuickAction[] = [
  { label: '生成章节', prompt: '请结合章节大纲、上文衔接和人物状态，先给出下一章的生成方案，等我确认后再写入正文。' },
  { label: '调整大纲', prompt: '我想调整故事大纲。请先结合现有框架说明可能影响的章节，再和我确认具体修改。' },
  { label: '调整设定', prompt: '我想调整角色、世界观或故事规则。请结合现有作品圣经检查冲突，并在修改前向我确认。' },
  { label: '润色正文', prompt: '请阅读当前章节，先指出节奏、对白和文字表达的问题，再给出润色方案，确认后再修改。' }
]

let storyId = 0
let chapterId = 0
let pageConversationId = 0

const pageTitle = computed(() => {
  const titles: Record<string, string> = {
    自由对话: '和助手讨论创作',
    生成下一章: '生成下一章',
    调整大纲: '调整故事大纲',
    调整设定: '调整角色与设定',
    润色当前章节: '润色当前章节'
  }
  return titles[initialTask.value] || '和助手讨论创作'
})
const contextDetail = computed(() => chapterId
  ? '当前章节、大纲、作品圣经、前文摘要'
  : '故事大纲、作品圣经、章节摘要')

onLoad(async (options) => {
  storyId = parseInt(options?.storyId || '0')
  chapterId = parseInt(options?.chapterId || '0')
  initialTask.value = decodeURIComponent(options?.task || '自由对话')
  if (!storyId) return

  try {
    await agentStore.loadConversations(storyId)
    const convId = options?.convId ? parseInt(options.convId) : 0
    const target = convId
      ? agentStore.conversations.find(item => item.id === convId)
      : agentStore.conversations.find(item => chapterId && item.chapter_id === chapterId)

    if (target) {
      await agentStore.loadConversation(storyId, target.id)
      pageConversationId = target.id
      await agentStore.loadPendingChanges(storyId)
    } else {
      const conversation = await agentStore.createConversation(storyId, undefined, chapterId || undefined)
      pageConversationId = conversation.id
      messages.value = [{ id: 'welcome', role: 'assistant', content: getIntroMessage(initialTask.value) }]
    }
  } catch (e) {
    console.error('加载助手会话失败', e)
    messages.value = [{ id: 'welcome', role: 'assistant', content: getIntroMessage(initialTask.value) }]
  }

  const initialAction = getTaskAction(initialTask.value)
  if (initialAction) inputText.value = initialAction.prompt
})

onShow(async () => {
  if (!storyId || !pageConversationId || agentStore.activeConversationId === pageConversationId) return
  try {
    await agentStore.loadConversation(storyId, pageConversationId)
    await agentStore.loadPendingChanges(storyId)
  } catch (e) {
    pageConversationId = 0
    agentStore.activeConversationId = null
    messages.value = [{ id: 'welcome', role: 'assistant', content: '原会话已不可用，请开始一个新对话。' }]
  }
})

watch([streamingContent, () => messages.value.length], () => {
  nextTick(() => {
    scrollTarget.value = ''
    nextTick(() => { scrollTarget.value = 'agent-scroll-bottom' })
  })
})

function getTaskAction(task: string) {
  const map: Record<string, QuickAction> = {
    生成下一章: quickActions[0],
    调整大纲: quickActions[1],
    调整设定: quickActions[2],
    润色当前章节: quickActions[3]
  }
  return map[task]
}

function getIntroMessage(task: string) {
  const messages: Record<string, string> = {
    生成下一章: '我会先结合章节大纲、上文衔接和人物状态给出生成方案，确认后再写入正文。',
    调整大纲: '可以局部修改章节安排，也可以讨论整体情节走向。修改前会明确展示影响范围。',
    调整设定: '我会结合现有作品圣经检查设定冲突，确认后同步更新相关模块。',
    润色当前章节: '可以指定对白、节奏、文风或局部段落。修改结果会先以对比方式展示。'
  }
  return messages[task] || '我已经读取当前章节、大纲、作品圣经和前文摘要。你可以直接告诉我想法。'
}

function selectQuick(action: QuickAction) {
  inputText.value = action.prompt
}

async function newConversation() {
  if (!storyId) return
  const conversation = await agentStore.createConversation(storyId, undefined, chapterId || undefined)
  pageConversationId = conversation.id
  pendingChanges.value = []
  messages.value = [{ id: 'welcome', role: 'assistant', content: getIntroMessage(initialTask.value) }]
}

async function handleSend(text: string) {
  if (!text.trim() || agentStore.streaming) return
  inputText.value = ''
  await agentStore.sendMessage(storyId, text, chapterId || undefined)
}

function stopStreaming() {
  agentStore.stopStreaming()
}

async function confirmChanges() {
  if (confirmingChanges.value || rollbackingChanges.value) return
  confirmingChanges.value = true
  try {
    await agentStore.confirmChanges(storyId)
    showChangeDiff.value = false
    uni.$emit('agent-content-updated', { storyId, chapterId })
    uiStore.success('变更已确认')
  } catch (e: any) {
    uiStore.error(e.message || '确认失败')
  } finally {
    confirmingChanges.value = false
  }
}

async function rollbackChanges() {
  if (confirmingChanges.value || rollbackingChanges.value) return
  rollbackingChanges.value = true
  try {
    await agentStore.rollbackChanges(storyId)
    showChangeDiff.value = false
    uni.$emit('agent-content-updated', { storyId, chapterId })
    uiStore.success('变更已撤回')
  } catch (e: any) {
    uiStore.error(e.message || '撤回失败')
  } finally {
    rollbackingChanges.value = false
  }
}

async function showPendingChanges() {
  try {
    await agentStore.loadPendingChanges(storyId)
    showChangeDiff.value = true
  } catch (e: any) {
    uiStore.error(e.message || '加载修改对比失败')
  }
}

function goHistory() {
  uni.navigateTo({ url: `/pages/workspace/agent-history?storyId=${storyId}&chapterId=${chapterId}` })
}

function showMoreMenu() {
  uni.showActionSheet({
    itemList: ['新建对话', '历史记录'],
    success: (res) => {
      if (res.tapIndex === 0) newConversation()
      if (res.tapIndex === 1) goHistory()
    }
  })
}

function showContextDetails() {
  uni.showModal({
    title: '作品上下文已就绪',
    content: chapterId
      ? '助手会参考当前章节、故事大纲、作品圣经和前文摘要进行创作讨论。'
      : '助手会参考故事大纲、作品圣经和已有章节摘要进行创作讨论。',
    showCancel: false
  })
}

function goBack() {
  uni.navigateBack()
}
</script>

<style lang="scss" scoped>
.agent-page {
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: #f8fafc;

  &__navbar {
    display: flex;
    align-items: center;
    gap: 12rpx;
    padding: calc(var(--status-bar-height) + 8rpx) 12rpx 8rpx;
    background: #ffffff;
    border-bottom: 1rpx solid #e2e8f0;
  }

  &__nav-btn {
    width: 64rpx;
    height: 64rpx;
    border-radius: 12rpx;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    &:active { background: #f1f5f9; }
  }

  &__nav-copy {
    flex: 1;
    min-width: 0;
    text-align: center;
  }

  &__title {
    display: block;
    font-size: 30rpx;
    line-height: 36rpx;
    font-weight: 700;
    color: #0f172a;
  }

  &__context {
    display: block;
    margin-top: 0;
    font-size: 20rpx;
    color: #64748b;
  }

  &__messages {
    flex: 1;
    box-sizing: border-box;
    width: 100%;
    padding: 24rpx 20rpx 28rpx;
    overflow: hidden;
  }

  &__context-card {
    min-height: 88rpx;
    display: flex;
    align-items: center;
    gap: 16rpx;
    box-sizing: border-box;
    margin-bottom: 28rpx;
    padding: 14rpx 18rpx;
    border: 1rpx solid #dbe4f4;
    border-radius: 12rpx;
    background: #ffffff;
    &:active { background: #f8fafc; }
  }

  &__status-dot {
    width: 14rpx;
    height: 14rpx;
    flex-shrink: 0;
    border-radius: 50%;
    background: #10b981;
    box-shadow: 0 0 0 7rpx #d1fae5;
  }

  &__context-copy {
    flex: 1;
    min-width: 0;
  }

  &__context-title {
    display: block;
    font-size: 24rpx;
    line-height: 32rpx;
    font-weight: 600;
    color: #0f172a;
  }

  &__context-detail {
    display: block;
    margin-top: 2rpx;
    font-size: 20rpx;
    line-height: 28rpx;
    color: #64748b;
  }

  &__thread {
    min-height: calc(100vh - 430rpx - var(--status-bar-height));
    display: flex;
    flex-direction: column;
    justify-content: flex-end;
  }

  &__composer {
    flex-shrink: 0;
    padding-top: 10rpx;
    background: #ffffff;
    border-top: 1rpx solid #e2e8f0;
    padding-bottom: env(safe-area-inset-bottom);
  }

  &__quick {
    width: 100%;
    padding: 0 20rpx 10rpx;
    box-sizing: border-box;
    white-space: nowrap;
  }

  &__quick-inner {
    display: inline-flex;
    gap: 10rpx;
  }

  &__quick-btn {
    height: 54rpx;
    box-sizing: border-box;
    padding: 0 18rpx;
    display: inline-flex;
    align-items: center;
    border: 1rpx solid #cbd5e1;
    border-radius: 8rpx;
    background: #ffffff;
    font-size: 22rpx;
    color: #334155;
    &:active { background: #eff6ff; border-color: #93c5fd; }
  }
}
</style>
