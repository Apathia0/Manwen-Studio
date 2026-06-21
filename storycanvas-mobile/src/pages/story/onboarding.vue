<template>
  <view class="onboarding-page">
    <lv-navbar :title="phaseTitle" show-back />

    <!-- 阶段：chatting 时的提取进度 -->
    <template v-if="phase === 'chatting'">
      <view class="onboarding-page__depth-bar-wrap">
        <view class="onboarding-page__depth-bar">
          <view class="onboarding-page__depth-fill" :style="{ width: `${understandingDepth}%` }" />
        </view>
        <text class="onboarding-page__depth-text">
          提取进度 {{ understandingDepth }}% · {{ filledCount }}/5
        </text>
      </view>

      <!-- 理解字段面板（可折叠） -->
      <view v-if="hasUnderstanding" class="onboarding-page__panel">
        <view class="onboarding-page__panel-header" @tap="showPanel = !showPanel">
          <text class="onboarding-page__panel-title">当前理解</text>
          <text class="onboarding-page__panel-toggle">{{ showPanel ? '收起' : '展开' }}</text>
        </view>
        <view v-if="showPanel" class="onboarding-page__panel-body">
          <view v-if="understanding.concept" class="onboarding-page__panel-card">
            <text class="onboarding-page__panel-label">核心概念</text>
            <text class="onboarding-page__panel-value">{{ understanding.concept }}</text>
          </view>
          <view v-if="understanding.setting" class="onboarding-page__panel-card">
            <text class="onboarding-page__panel-label">世界观与规则</text>
            <text class="onboarding-page__panel-value">{{ understanding.setting }}</text>
          </view>
          <view v-if="understanding.tone" class="onboarding-page__panel-card">
            <text class="onboarding-page__panel-label">风格标签</text>
            <text class="onboarding-page__panel-value">{{ understanding.tone }}</text>
          </view>
          <view v-if="understanding.goals" class="onboarding-page__panel-card">
            <text class="onboarding-page__panel-label">创作目标</text>
            <text class="onboarding-page__panel-value">{{ understanding.goals }}</text>
          </view>
          <view v-if="understanding.synthesis" class="onboarding-page__panel-card">
            <text class="onboarding-page__panel-label">主角设定</text>
            <text class="onboarding-page__panel-value">{{ understanding.synthesis }}</text>
          </view>
        </view>
      </view>
    </template>

    <!-- 聊天消息区（所有阶段共享） -->
    <view class="onboarding-page__chat">
      <scroll-view scroll-y class="onboarding-page__messages" :scroll-into-view="scrollTarget">
        <!-- 提示 -->
        <view class="onboarding-page__hint">
          AI 正逐步提取你的故事设定：核心概念→世界观→风格标签→创作目标→主角设定。回答越具体，框架生成越精准。
        </view>

        <view
          v-for="(msg, index) in messages"
          :key="index"
          :id="`msg-${index}`"
        >
          <!-- 创意简报内联卡片 -->
          <view v-if="msg.creative_brief" class="onboarding-page__brief-wrap">
            <bible-summary :bible="msg.creative_brief" default-expanded />
            <view class="onboarding-page__brief-actions" v-if="phase === 'chatting'">
              <view class="onboarding-page__brief-btn onboarding-page__brief-btn--secondary" @tap="handleContinueEdit">
                继续对话修改
              </view>
              <view class="onboarding-page__brief-btn onboarding-page__brief-btn--primary" @tap="handleConfirm">
                确认生成
              </view>
            </view>
          </view>

          <!-- 普通消息 -->
          <view v-else :class="['onboarding-page__message', `onboarding-page__message--${msg.role}`]">
            <view class="onboarding-page__bubble">
              <text class="onboarding-page__text">{{ msg.content }}</text>
              <view v-if="index === messages.length - 1 && loading" class="onboarding-page__cursor" />
            </view>
          </view>
        </view>

        <!-- AI 思考中 -->
        <view v-if="loading && phase === 'chatting'" class="onboarding-page__message onboarding-page__message--assistant">
          <view class="onboarding-page__bubble onboarding-page__bubble--loading">
            <text class="onboarding-page__loading-dots">正在思考...</text>
          </view>
        </view>

        <view id="scroll-bottom" />
      </scroll-view>
    </view>

    <!-- 底部区域 -->
    <view class="onboarding-page__foot">
      <!-- chatting: 输入框 -->
      <template v-if="phase === 'chatting'">
        <view class="onboarding-page__input-row">
          <input
            v-model="inputText"
            class="onboarding-page__input"
            :placeholder="loading ? '等待回复...' : '输入你的想法...'"
            :disabled="loading"
            @confirm="handleSend"
          />
          <view
            :class="['onboarding-page__send', { 'onboarding-page__send--disabled': loading || !inputText.trim() }]"
            @tap="handleSend"
          >
            <Send :size="22" color="#ffffff" />
          </view>
        </view>
        <view v-if="error" class="onboarding-page__error">{{ error }}</view>
        <text class="onboarding-page__skip" @tap="handleSkip">跳过引导，直接开始</text>
      </template>

      <!-- confirming: 框架生成中 -->
      <template v-if="phase === 'confirming'">
        <view class="onboarding-page__status">
          <view class="onboarding-page__status-spinner" />
          <view class="onboarding-page__status-texts">
            <text class="onboarding-page__status-title">正在构建故事框架...</text>
            <text class="onboarding-page__status-desc">生成大纲 · 角色设定 · 标签 · 章节规划</text>
          </view>
        </view>
      </template>

      <!-- ready: 完成 -->
      <template v-if="phase === 'ready'">
        <view class="onboarding-page__status onboarding-page__status--success">
          <view class="onboarding-page__status-check">✓</view>
          <view class="onboarding-page__status-texts">
            <text class="onboarding-page__status-title">故事框架已就绪！</text>
            <text class="onboarding-page__status-desc">大纲、角色、标签已自动生成，进入工作台即可查看</text>
          </view>
        </view>
        <view class="onboarding-page__ready-actions">
          <text class="onboarding-page__skip" @tap="handleSkip">跳过引导，直接开始</text>
          <view class="onboarding-page__ready-btn" @tap="handleGoWorkspace">进入工作台</view>
        </view>
      </template>

      <!-- error: 错误 -->
      <template v-if="phase === 'error'">
        <view class="onboarding-page__status onboarding-page__status--error">
          <text class="onboarding-page__error-text">{{ confirmError }}</text>
        </view>
        <view class="onboarding-page__error-actions">
          <view class="onboarding-page__ready-btn" @tap="handleConfirm">重试</view>
          <text class="onboarding-page__skip" @tap="phase = 'chatting'; error = ''; confirmError = ''">返回对话</text>
        </view>
      </template>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, computed, nextTick } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { Send } from '@lucide/vue'
import { onboardingApi } from '@/api'
import { useStoriesStore } from '@/stores/stories'
import { useUiStore } from '@/stores/ui'
import LvNavbar from '@/components/lv-navbar/lv-navbar.vue'
import BibleSummary from '@/components/bible-summary/bible-summary.vue'

interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  creative_brief?: Record<string, any>
}

interface Understanding {
  concept?: string
  setting?: string
  tone?: string
  goals?: string
  synthesis?: string
}

type OnboardingPhase = 'chatting' | 'confirming' | 'ready' | 'error'

const storyStore = useStoriesStore()
const uiStore = useUiStore()

const storyId = ref(0)
const phase = ref<OnboardingPhase>('chatting')
const messages = ref<ChatMessage[]>([
  { role: 'assistant', content: '你好，我是设定提取助手。请先描述你的故事概念：它属于什么类型（如都市、玄幻、科幻）？主角是谁、什么身份？开篇从什么事件切入？' }
])
const inputText = ref('')
const loading = ref(false)
const error = ref('')
const confirmError = ref('')

// 理解字段
const understanding = ref<Understanding>({})
const understandingDepth = ref(0)
const showPanel = ref(false)

// 创意简报
const bible = ref<any>({})

const scrollTarget = ref('')

const hasUnderstanding = computed(() => Object.values(understanding.value).some(v => !!v))
const filledCount = computed(() => Object.values(understanding.value).filter(v => !!v).length)

const phaseTitle = computed(() => {
  switch (phase.value) {
    case 'chatting': return 'AI 设定提取'
    case 'confirming': return '正在构建框架...'
    case 'ready': return '故事框架已就绪'
    case 'error': return '生成失败'
    default: return '灵感捕手'
  }
})

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
  if (!text || loading.value || phase.value !== 'chatting') return

  inputText.value = ''
  error.value = ''

  messages.value.push({ role: 'user', content: text })
  scrollToBottom()
  loading.value = true

  try {
    const requestMessages = messages.value.map(m => ({ role: m.role, content: m.content || '' }))

    const data = await onboardingApi.sendMessage(storyId.value, {
      messages: requestMessages,
      collected_info: {},
      step: filledCount.value
    })

    // 更新理解字段
    if (data.understanding) {
      understanding.value = data.understanding
    }
    if (typeof data.understanding_depth === 'number') {
      understandingDepth.value = data.understanding_depth
    }
    if (data.collected_info) {
      // 合并 collected_info
    }

    // 是否附带创意简报
    if (data.has_brief && data.creative_brief) {
      bible.value = data.creative_brief
      messages.value.push({
        role: 'assistant',
        content: data.reply,
        creative_brief: data.creative_brief
      })
    } else {
      messages.value.push({ role: 'assistant', content: data.reply })
    }
    scrollToBottom()
  } catch (e: any) {
    error.value = e.message || '对话失败，请重试'
  } finally {
    loading.value = false
  }
}

async function handleConfirm() {
  loading.value = true
  phase.value = 'confirming'
  confirmError.value = ''

  try {
    await onboardingApi.confirmOnboarding(storyId.value, {
      collected_info: {},
      understanding: understanding.value as Record<string, string>,
      messages: messages.value.map(m => ({ role: m.role, content: m.content || '' })),
      creative_brief: bible.value || undefined
    })
    phase.value = 'ready'
  } catch (e: any) {
    confirmError.value = e.message || '确认失败'
    phase.value = 'error'
  } finally {
    loading.value = false
  }
}

function handleContinueEdit() {
  // 从消息列表中移除创意简报卡片（保留上一条 AI 回复）
  messages.value = messages.value.filter(m => !m.creative_brief)
  bible.value = {}
}

function handleGoWorkspace() {
  uni.redirectTo({ url: `/pages/workspace/chapter-view?storyId=${storyId.value}` })
}

async function handleSkip() {
  loading.value = true
  error.value = ''
  try {
    await onboardingApi.skipOnboarding(storyId.value)
    uiStore.success('已跳过引导')
    setTimeout(() => {
      uni.redirectTo({ url: `/pages/workspace/chapter-view?storyId=${storyId.value}` })
    }, 1500)
  } catch (e: any) {
    error.value = e.message || '跳过失败'
  } finally {
    loading.value = false
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

  /* ===== 进度条 ===== */
  &__depth-bar-wrap {
    display: flex;
    align-items: center;
    gap: 12rpx;
    padding: 8rpx $lv-page-padding;
    background: $lv-surface-solid;
    border-bottom: 1rpx solid $lv-border-light;
  }

  &__depth-bar {
    flex: 1;
    height: 6rpx;
    background: #e2e8f0;
    border-radius: 3rpx;
    overflow: hidden;
  }

  &__depth-fill {
    height: 100%;
    background: linear-gradient(90deg, #2563eb, #3b82f6);
    border-radius: 3rpx;
    transition: width 0.5s ease;
  }

  &__depth-text {
    font-size: $lv-font-xs;
    color: $lv-text-muted;
    white-space: nowrap;
  }

  /* ===== 理解面板 ===== */
  &__panel {
    margin: 8rpx $lv-page-padding 0;
    background: $lv-surface-solid;
    border-radius: $lv-radius-lg;
    border: 1rpx solid $lv-border-light;
    overflow: hidden;
  }

  &__panel-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 12rpx 16rpx;
  }

  &__panel-title {
    font-size: $lv-font-sm;
    font-weight: 600;
    color: $lv-text-primary;
  }

  &__panel-toggle {
    font-size: $lv-font-xs;
    color: $lv-primary;
  }

  &__panel-body {
    padding: 0 16rpx 12rpx;
    display: flex;
    flex-direction: column;
    gap: 8rpx;
  }

  &__panel-card {
    background: #eff6ff;
    border: 1rpx solid #d7e3f4;
    border-radius: $lv-radius-md;
    padding: 12rpx;
  }

  &__panel-label {
    display: block;
    font-size: $lv-font-xs;
    font-weight: 600;
    color: $lv-primary;
    margin-bottom: 4rpx;
  }

  &__panel-value {
    display: block;
    font-size: $lv-font-xs;
    color: $lv-text-secondary;
    line-height: 1.5;
  }

  /* ===== 聊天区 ===== */
  &__chat {
    flex: 1;
    overflow: hidden;
  }

  &__messages {
    height: 100%;
    padding: $lv-page-padding;
  }

  &__hint {
    margin-bottom: 24rpx;
    padding: 16rpx 20rpx;
    background: #eff6ff;
    border: 1rpx solid #bfdbfe;
    border-radius: $lv-radius-lg;
    font-size: $lv-font-xs;
    line-height: 1.6;
    color: #1d4ed8;
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
    font-size: $lv-font-base;
    line-height: 1.6;
    word-break: break-word;

    &--loading {
      background: #f8fbff;
    }
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
    vertical-align: middle;
  }

  &__loading-dots {
    font-size: $lv-font-sm;
    color: $lv-text-muted;
  }

  /* ===== 创意简报内联卡片 ===== */
  &__brief-wrap {
    margin-bottom: 24rpx;
  }

  &__brief-actions {
    display: flex;
    gap: 16rpx;
    margin-top: 16rpx;
  }

  &__brief-btn {
    flex: 1;
    height: 72rpx;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: 36rpx;
    font-size: $lv-font-sm;
    font-weight: 500;

    &--primary {
      background: $lv-primary;
      color: $lv-text-on-primary;
    }

    &--secondary {
      background: $lv-surface-solid;
      color: $lv-text-secondary;
      border: 1rpx solid $lv-border-light;
    }

    &:active {
      opacity: 0.8;
    }
  }

  /* ===== 底部区 ===== */
  &__foot {
    padding: 16rpx $lv-page-padding;
    background: $lv-surface-solid;
    border-top: 1rpx solid $lv-border-light;
    @include safe-area-bottom(16rpx);
  }

  &__input-row {
    display: flex;
    align-items: center;
    gap: 16rpx;
  }

  &__input {
    flex: 1;
    height: 72rpx;
    background: $lv-primary-lighter;
    border-radius: 36rpx;
    padding: 0 32rpx;
    font-size: $lv-font-base;
    color: $lv-text-primary;
  }

  &__send {
    width: 64rpx;
    height: 64rpx;
    border-radius: 50%;
    @include flex-center;
    background: $lv-primary;
    color: $lv-text-on-primary;
    flex-shrink: 0;

    &--disabled {
      background: $lv-border-light;
      color: $lv-text-muted;
    }
  }

  &__error {
    margin-top: 8rpx;
    font-size: $lv-font-sm;
    color: $lv-error;
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

  /* ===== 状态区 ===== */
  &__status {
    display: flex;
    align-items: center;
    gap: 16rpx;
    padding: 20rpx;
    border-radius: $lv-radius-lg;

    &--success {
      background: #f0fdf4;
      border: 1rpx solid #bbf7d0;
    }

    &--error {
      background: #fef2f2;
      border: 1rpx solid #fecaca;
    }
  }

  &__status-spinner {
    width: 40rpx;
    height: 40rpx;
    border: 4rpx solid #e2e8f0;
    border-top-color: $lv-primary;
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
    flex-shrink: 0;
  }

  &__status-check {
    width: 48rpx;
    height: 48rpx;
    border-radius: 50%;
    background: #22c55e;
    color: #fff;
    font-size: 28rpx;
    font-weight: bold;
    @include flex-center;
    flex-shrink: 0;
  }

  &__status-texts {
    flex: 1;
  }

  &__status-title {
    display: block;
    font-size: $lv-font-base;
    font-weight: 600;
    color: $lv-text-primary;
    margin-bottom: 4rpx;
  }

  &__status-desc {
    display: block;
    font-size: $lv-font-xs;
    color: $lv-text-secondary;
  }

  &__ready-actions {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-top: 12rpx;
  }

  &__ready-btn {
    padding: 16rpx 40rpx;
    background: $lv-primary;
    color: $lv-text-on-primary;
    border-radius: 36rpx;
    font-size: $lv-font-sm;
    font-weight: 500;
    text-align: center;

    &:active {
      opacity: 0.8;
    }
  }

  &__error-text {
    font-size: $lv-font-sm;
    color: #b91c1c;
  }

  &__error-actions {
    display: flex;
    gap: 16rpx;
    margin-top: 12rpx;
    align-items: center;
  }
}

@keyframes pulse {
  0% { opacity: 1; }
  50% { opacity: 0.3; }
  100% { opacity: 1; }
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>
