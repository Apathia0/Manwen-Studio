<template>
  <view class="import-guidance">
    <lv-navbar title="导入后补充上下文" show-back />

    <!-- 步骤指示器 -->
    <view class="import-guidance__steps">
      <view
        v-for="(label, idx) in STEPS"
        :key="label"
        class="import-guidance__step"
        :class="{
          'import-guidance__step--active': step === idx + 1,
          'import-guidance__step--done': idx + 1 < step || (idx + 1 === step && isComplete)
        }"
      >
        <view class="import-guidance__step-dot">
          <text v-if="idx + 1 < step || (idx + 1 === step && isComplete)">✓</text>
          <text v-else>{{ idx + 1 }}</text>
        </view>
        <text class="import-guidance__step-label">{{ label }}</text>
      </view>
    </view>

    <!-- 提示 -->
    <view class="import-guidance__hint">
      这一步不会重做建书，只是为你导入的现有作品补充后续创作约束。
    </view>

    <!-- 聊天区域 -->
    <scroll-view scroll-y class="import-guidance__messages" :scroll-into-view="scrollTarget">
      <view
        v-for="(msg, i) in messages"
        :key="i"
        :class="['import-guidance__msg', `import-guidance__msg--${msg.role}`]"
        :id="`msg-${i}`"
      >
        <view class="import-guidance__bubble">{{ msg.content }}</view>
      </view>
      <view v-if="loading" class="import-guidance__msg import-guidance__msg--assistant">
        <view class="import-guidance__bubble import-guidance__bubble--loading">
          <text class="import-guidance__loading-text">正在整理你的导入作品上下文...</text>
        </view>
      </view>
      <view id="scroll-bottom" />
    </scroll-view>

    <!-- 当前摘要（移动端用可展开面板） -->
    <view v-if="canShowSummary" class="import-guidance__summary">
      <view class="import-guidance__summary-header" @tap="showSummary = !showSummary">
        <text class="import-guidance__summary-title">当前摘要</text>
        <text class="import-guidance__summary-toggle">{{ showSummary ? '收起' : '展开' }}</text>
      </view>
      <view v-if="showSummary" class="import-guidance__summary-body">
        <view v-if="collectedInfo.must_keep" class="import-guidance__summary-card">
          <text class="import-guidance__summary-card-label">必须保留</text>
          <text class="import-guidance__summary-card-value">{{ collectedInfo.must_keep }}</text>
        </view>
        <view v-if="collectedInfo.author_goal" class="import-guidance__summary-card">
          <text class="import-guidance__summary-card-label">后续目标</text>
          <text class="import-guidance__summary-card-value">{{ collectedInfo.author_goal }}</text>
        </view>
        <view v-if="collectedInfo.adjustment_scope" class="import-guidance__summary-card">
          <text class="import-guidance__summary-card-label">可调整范围</text>
          <text class="import-guidance__summary-card-value">{{ collectedInfo.adjustment_scope }}</text>
        </view>
        <view v-if="collectedInfo.longline_plan" class="import-guidance__summary-card">
          <text class="import-guidance__summary-card-label">长线计划</text>
          <text class="import-guidance__summary-card-value">{{ collectedInfo.longline_plan }}</text>
        </view>
        <view v-if="collectedInfo.tone_guardrails" class="import-guidance__summary-card">
          <text class="import-guidance__summary-card-label">风格边界</text>
          <text class="import-guidance__summary-card-value">{{ collectedInfo.tone_guardrails }}</text>
        </view>
      </view>
    </view>

    <!-- 底部输入区 -->
    <view class="import-guidance__foot">
      <view class="import-guidance__input-row">
        <input
          v-model="inputText"
          class="import-guidance__input"
          :placeholder="loading ? '等待回复...' : '输入你的补充说明...'"
          :disabled="loading"
          @confirm="handleSend"
        />
        <view
          :class="['import-guidance__send', { 'import-guidance__send--disabled': loading || !inputText.trim() }]"
          @tap="handleSend"
        >
          <Send :size="22" color="#ffffff" />
        </view>
      </view>
      <view v-if="error" class="import-guidance__error">{{ error }}</view>
      <view class="import-guidance__actions">
        <text class="import-guidance__skip" @tap="handleSkip">
          {{ skipLoading ? '跳过中...' : '跳过，先进入工作台' }}
        </text>
      </view>
    </view>

    <!-- 确认弹窗 -->
    <lv-modal v-model:visible="showConfirm" title="确认导入上下文" @confirm="handleConfirm">
      <text class="import-guidance__confirm-desc">
        这些信息会写入作品圣经，后续框架生成、续写和对话调整都会默认参考它。
      </text>
      <view class="import-guidance__confirm-grid">
        <view class="import-guidance__confirm-card">
          <text class="import-guidance__confirm-card-label">必须保留</text>
          <text class="import-guidance__confirm-card-value">{{ collectedInfo.must_keep || '待补充' }}</text>
        </view>
        <view class="import-guidance__confirm-card">
          <text class="import-guidance__confirm-card-label">后续目标</text>
          <text class="import-guidance__confirm-card-value">{{ collectedInfo.author_goal || '待补充' }}</text>
        </view>
        <view class="import-guidance__confirm-card">
          <text class="import-guidance__confirm-card-label">可调整范围</text>
          <text class="import-guidance__confirm-card-value">{{ collectedInfo.adjustment_scope || '待补充' }}</text>
        </view>
        <view class="import-guidance__confirm-card">
          <text class="import-guidance__confirm-card-label">长线计划</text>
          <text class="import-guidance__confirm-card-value">{{ collectedInfo.longline_plan || '待补充' }}</text>
        </view>
      </view>
    </lv-modal>
  </view>
</template>

<script setup lang="ts">
import { ref, computed, nextTick } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { Send } from '@lucide/vue'
import { onboardingApi } from '@/api'
import { useUiStore } from '@/stores/ui'
import LvNavbar from '@/components/lv-navbar/lv-navbar.vue'
import LvModal from '@/components/lv-modal/lv-modal.vue'

const STEPS = ['导入类型', '保留项', '后续目标', '可调整范围']

const INITIAL_PROMPT = '已读取你导入的作品内容。接下来我会用 3 到 4 个问题，快速补齐后续续写和框架调整最关键的上下文。先告诉我：你导入的是旧正文、旧大纲，还是两者混合？'

interface Msg {
  role: 'user' | 'assistant'
  content: string
}

const uiStore = useUiStore()

const storyId = ref(0)
const messages = ref<Msg[]>([{ role: 'assistant', content: INITIAL_PROMPT }])
const inputText = ref('')
const loading = ref(false)
const collectedInfo = ref<Record<string, string>>({})
const step = ref(1)
const isComplete = ref(false)
const showConfirm = ref(false)
const confirmLoading = ref(false)
const skipLoading = ref(false)
const error = ref('')
const showSummary = ref(false)
const scrollTarget = ref('')

onLoad((options) => {
  const id = parseInt(options?.storyId || '0')
  if (!id) {
    uiStore.error('未指定故事')
    return
  }
  storyId.value = id
})

async function handleSend() {
  const text = inputText.value.trim()
  if (!text || loading.value) return

  inputText.value = ''
  error.value = ''

  messages.value.push({ role: 'user', content: text })
  scrollToBottom()
  loading.value = true

  try {
    const apiMessages = messages.value.map(m => ({ role: m.role, content: m.content }))
    // 使用正确的导入引导 API
    const result = await onboardingApi.sendImportMessage(storyId.value, {
      messages: apiMessages,
      collected_info: collectedInfo.value,
      step: step.value
    })

    messages.value.push({ role: 'assistant', content: result.reply })
    scrollToBottom()

    if (result.collected_info) {
      collectedInfo.value = result.collected_info
    }
    if (result.step) {
      step.value = result.step
    }
    if (result.is_complete) {
      isComplete.value = true
      showConfirm.value = true
    }
  } catch (e: any) {
    error.value = e.message || '发送失败，请重试'
  } finally {
    loading.value = false
  }
}

async function handleSkip() {
  skipLoading.value = true
  error.value = ''
  try {
    await onboardingApi.skipImport(storyId.value)
    uiStore.success('已跳过引导')
    setTimeout(() => {
      uni.redirectTo({ url: `/pages/workspace/chapter-view?storyId=${storyId.value}` })
    }, 1500)
  } catch (e: any) {
    error.value = e.message || '跳过失败'
  } finally {
    skipLoading.value = false
  }
}

async function handleConfirm() {
  confirmLoading.value = true
  error.value = ''
  try {
    await onboardingApi.confirmImport(storyId.value, {
      collected_info: collectedInfo.value,
      messages: messages.value.map(m => ({ role: m.role, content: m.content }))
    })
    uiStore.success('引导完成！')
    showConfirm.value = false
    setTimeout(() => {
      uni.redirectTo({ url: `/pages/workspace/chapter-view?storyId=${storyId.value}` })
    }, 1500)
  } catch (e: any) {
    error.value = e.message || '确认失败'
  } finally {
    confirmLoading.value = false
  }
}

function scrollToBottom() {
  nextTick(() => {
    scrollTarget.value = 'scroll-bottom'
  })
}

const canShowSummary = computed(() => Object.keys(collectedInfo.value).length > 0)
</script>

<style lang="scss" scoped>
.import-guidance {
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: linear-gradient(180deg, $lv-bg-start 0%, $lv-bg-end 100%);

  &__steps {
    display: flex;
    align-items: center;
    padding: 16rpx $lv-page-padding;
    background: $lv-surface-solid;
    border-bottom: 1rpx solid $lv-border-light;
  }

  &__step {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 8rpx;
    position: relative;

    &::after {
      content: '';
      position: absolute;
      top: 16rpx;
      right: -50%;
      width: 100%;
      height: 2rpx;
      background: $lv-border-light;
      z-index: 0;
    }

    &:last-child::after {
      display: none;
    }

    &--done {
      .import-guidance__step-dot {
        background: $lv-primary;
        color: #fff;
        border-color: $lv-primary;
      }
      .import-guidance__step-label {
        color: $lv-primary;
      }
    }

    &--active {
      .import-guidance__step-dot {
        background: $lv-primary;
        color: #fff;
        border-color: $lv-primary;
        box-shadow: 0 0 0 4rpx rgba($lv-primary, 0.3);
      }
      .import-guidance__step-label {
        color: $lv-primary;
        font-weight: 600;
      }
    }
  }

  &__step-dot {
    width: 32rpx;
    height: 32rpx;
    border-radius: 50%;
    background: #f1f5f9;
    border: 2rpx solid $lv-border-light;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 18rpx;
    color: $lv-text-muted;
    z-index: 1;
  }

  &__step-label {
    font-size: $lv-font-xs;
    color: $lv-text-muted;
  }

  &__hint {
    margin: 16rpx $lv-page-padding 0;
    padding: 16rpx 20rpx;
    background: #eff6ff;
    border: 1rpx solid #bfdbfe;
    border-radius: $lv-radius-lg;
    font-size: $lv-font-xs;
    line-height: 1.6;
    color: #1d4ed8;
  }

  &__messages {
    flex: 1;
    padding: $lv-page-padding;
  }

  &__msg {
    margin-bottom: 24rpx;
    display: flex;

    &--user {
      justify-content: flex-end;

      .import-guidance__bubble {
        background: $lv-primary;
        color: $lv-text-on-primary;
        border-radius: 24rpx 24rpx 8rpx 24rpx;
      }
    }

    &--assistant {
      justify-content: flex-start;

      .import-guidance__bubble {
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

  &__loading-text {
    font-size: $lv-font-sm;
    color: $lv-text-muted;
  }

  &__summary {
    margin: 0 $lv-page-padding 16rpx;
    background: $lv-surface-solid;
    border-radius: $lv-radius-lg;
    border: 1rpx solid $lv-border-light;
    overflow: hidden;
  }

  &__summary-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 16rpx 20rpx;
  }

  &__summary-title {
    font-size: $lv-font-sm;
    font-weight: 600;
    color: $lv-text-primary;
  }

  &__summary-toggle {
    font-size: $lv-font-xs;
    color: $lv-primary;
  }

  &__summary-body {
    padding: 0 20rpx 16rpx;
    display: flex;
    flex-direction: column;
    gap: 12rpx;
  }

  &__summary-card {
    background: #eff6ff;
    border: 1rpx solid #d7e3f4;
    border-radius: $lv-radius-md;
    padding: 16rpx;
  }

  &__summary-card-label {
    display: block;
    font-size: $lv-font-xs;
    font-weight: 600;
    color: $lv-primary;
    margin-bottom: 4rpx;
  }

  &__summary-card-value {
    display: block;
    font-size: $lv-font-xs;
    color: $lv-text-secondary;
    line-height: 1.5;
  }

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

  &__actions {
    margin-top: 12rpx;
    display: flex;
    justify-content: center;
  }

  &__skip {
    font-size: $lv-font-sm;
    color: $lv-text-muted;

    &:active {
      color: $lv-primary;
    }
  }

  &__confirm-desc {
    display: block;
    font-size: $lv-font-sm;
    color: $lv-text-secondary;
    margin-bottom: 24rpx;
    line-height: 1.5;
  }

  &__confirm-grid {
    display: flex;
    flex-direction: column;
    gap: 16rpx;
  }

  &__confirm-card {
    background: #f8fbff;
    border: 1rpx solid #d7e3f4;
    border-radius: $lv-radius-md;
    padding: 20rpx;
  }

  &__confirm-card-label {
    display: block;
    font-size: $lv-font-xs;
    font-weight: 600;
    color: $lv-primary;
    margin-bottom: 8rpx;
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }

  &__confirm-card-value {
    display: block;
    font-size: $lv-font-sm;
    color: $lv-text-primary;
    line-height: 1.6;
  }
}
</style>
