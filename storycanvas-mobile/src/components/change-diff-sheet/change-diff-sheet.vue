<template>
  <view v-if="visible" class="change-diff-sheet">
    <view class="change-diff-sheet__header">
      <view class="change-diff-sheet__close" @tap="emit('close')">
        <lv-icon name="ArrowLeft" :size="20" color="#334155" />
      </view>
      <view class="change-diff-sheet__title-wrap">
        <text class="change-diff-sheet__title">修改对比</text>
        <text class="change-diff-sheet__subtitle">{{ changes.length }} 项修改待确认</text>
      </view>
    </view>

    <scroll-view v-if="changes.length > 1" scroll-x class="change-diff-sheet__tabs" show-scrollbar="false">
      <view class="change-diff-sheet__tabs-inner">
        <view
          v-for="(change, index) in changes"
          :key="changeKey(change, index)"
          :class="['change-diff-sheet__tab', { 'change-diff-sheet__tab--active': activeIndex === index }]"
          @tap="activeIndex = index"
        >
          <text>{{ change.display_name || `修改 ${index + 1}` }}</text>
        </view>
      </view>
    </scroll-view>

    <scroll-view v-if="activeChange" scroll-y class="change-diff-sheet__body">
      <view class="change-diff-sheet__summary">
        <text class="change-diff-sheet__name">{{ activeChange.display_name || '创作内容' }}</text>
        <text class="change-diff-sheet__field">{{ fieldLabel(activeChange.field) }}</text>
      </view>

      <view class="change-diff-sheet__modes">
        <view
          v-for="item in modes"
          :key="item.value"
          :class="['change-diff-sheet__mode', { 'change-diff-sheet__mode--active': mode === item.value }]"
          @tap="mode = item.value"
        >
          <text>{{ item.label }}</text>
        </view>
      </view>

      <view v-if="mode === 'diff'" class="change-diff-sheet__diff">
        <view
          v-for="(line, index) in diffLines"
          :key="index"
          :class="['change-diff-sheet__line', `change-diff-sheet__line--${line.type}`]"
        >
          <text class="change-diff-sheet__marker">{{ line.type === 'add' ? '+' : line.type === 'remove' ? '−' : ' ' }}</text>
          <text class="change-diff-sheet__line-text">{{ line.text || ' ' }}</text>
        </view>
        <view v-if="diffLines.length === 0" class="change-diff-sheet__empty">无差异</view>
      </view>

      <view v-else :class="['change-diff-sheet__text-panel', `change-diff-sheet__text-panel--${mode}`]">
        <text>{{ mode === 'old' ? oldText : newText }}</text>
      </view>
    </scroll-view>

    <view v-else class="change-diff-sheet__empty-state">
      <text>没有待确认的修改</text>
    </view>

    <view v-if="changes.length > 0" class="change-diff-sheet__footer">
      <button
        class="change-diff-sheet__button change-diff-sheet__button--rollback"
        :disabled="confirming || rollbacking"
        @tap="emit('rollback')"
      >
        {{ rollbacking ? '撤回中…' : '撤回全部' }}
      </button>
      <button
        class="change-diff-sheet__button change-diff-sheet__button--confirm"
        :disabled="confirming || rollbacking"
        @tap="emit('confirm')"
      >
        {{ confirming ? '确认中…' : '确认保存' }}
      </button>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import LvIcon from '@/components/lv-icon/lv-icon.vue'
import type { PendingChange } from '@/api/types'

type ViewMode = 'diff' | 'old' | 'new'
type DiffType = 'add' | 'remove' | 'same'

interface DiffLine {
  type: DiffType
  text: string
}

const props = withDefaults(defineProps<{
  visible: boolean
  changes: PendingChange[]
  confirming?: boolean
  rollbacking?: boolean
}>(), {
  confirming: false,
  rollbacking: false
})

const emit = defineEmits<{
  (event: 'close'): void
  (event: 'confirm'): void
  (event: 'rollback'): void
}>()

const activeIndex = ref(0)
const mode = ref<ViewMode>('diff')
const modes: Array<{ value: ViewMode; label: string }> = [
  { value: 'diff', label: '差异' },
  { value: 'old', label: '修改前' },
  { value: 'new', label: '修改后' }
]

const fieldLabels: Record<string, string> = {
  novel_content: '正文内容',
  title: '标题',
  description: '描述',
  tags: '标签',
  characters: '角色设定',
  outline: '故事大纲',
  story_bible: '创作圣经',
  scenes_file: '分镜脚本',
  screenplay_text: '剧本文本',
  screenplay_json: '剧本结构',
  storyboard_prompt: '故事板提示词',
  video_prompt: '视频提示词',
  scene_prompt: '场景提示词',
  creative_brief: '创意简报',
  writing_guidance: '写作指导'
}

const activeChange = computed(() => props.changes[activeIndex.value])
const oldText = computed(() => normalizeValue(activeChange.value?.old_value))
const newText = computed(() => normalizeValue(activeChange.value?.new_value))
const diffLines = computed(() => lineDiff(oldText.value, newText.value))

watch(() => props.visible, (visible) => {
  if (visible) {
    activeIndex.value = 0
    mode.value = 'diff'
  }
})

watch(() => props.changes.length, (length) => {
  if (activeIndex.value >= length) activeIndex.value = Math.max(0, length - 1)
})

function normalizeValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '(空)'
  if (typeof value === 'string') return value
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

function lineDiff(oldValue: string, newValue: string): DiffLine[] {
  const maxLines = 800
  const rawOldLines = oldValue.split('\n')
  const rawNewLines = newValue.split('\n')
  const truncated = rawOldLines.length > maxLines || rawNewLines.length > maxLines
  const oldLines = rawOldLines.slice(0, maxLines)
  const newLines = rawNewLines.slice(0, maxLines)

  // 超长内容避免在手机端构建过大的 LCS 矩阵。
  if (oldLines.length * newLines.length > 90000) {
    const result: DiffLine[] = [
      ...oldLines.map(text => ({ type: 'remove' as const, text })),
      ...newLines.map(text => ({ type: 'add' as const, text }))
    ]
    if (truncated) result.push({ type: 'same', text: '内容较长，差异视图仅展示前 800 行，请切换“修改前/修改后”查看全文。' })
    return result
  }

  const table = Array.from({ length: oldLines.length + 1 }, () =>
    new Array<number>(newLines.length + 1).fill(0)
  )
  for (let i = 1; i <= oldLines.length; i++) {
    for (let j = 1; j <= newLines.length; j++) {
      table[i][j] = oldLines[i - 1] === newLines[j - 1]
        ? table[i - 1][j - 1] + 1
        : Math.max(table[i - 1][j], table[i][j - 1])
    }
  }

  const result: DiffLine[] = []
  let i = oldLines.length
  let j = newLines.length
  while (i > 0 || j > 0) {
    if (i > 0 && j > 0 && oldLines[i - 1] === newLines[j - 1]) {
      result.push({ type: 'same', text: oldLines[i - 1] })
      i--
      j--
    } else if (j > 0 && (i === 0 || table[i][j - 1] >= table[i - 1][j])) {
      result.push({ type: 'add', text: newLines[j - 1] })
      j--
    } else {
      result.push({ type: 'remove', text: oldLines[i - 1] })
      i--
    }
  }
  result.reverse()
  if (truncated) result.push({ type: 'same', text: '内容较长，差异视图仅展示前 800 行，请切换“修改前/修改后”查看全文。' })
  return result
}

function fieldLabel(field?: string): string {
  return fieldLabels[field || ''] || field || '内容修改'
}

function changeKey(change: PendingChange, index: number): string {
  return `${change.type}-${change.record_id ?? index}-${change.field ?? index}`
}
</script>

<style lang="scss" scoped>
.change-diff-sheet {
  position: fixed;
  inset: 0;
  z-index: 1000;
  display: flex;
  flex-direction: column;
  background: #f8fafc;

  &__header {
    display: flex;
    align-items: center;
    gap: 16rpx;
    padding: calc(var(--status-bar-height) + 14rpx) 24rpx 16rpx;
    background: #ffffff;
    border-bottom: 1rpx solid #e2e8f0;
  }

  &__close {
    width: 64rpx;
    height: 64rpx;
    display: flex;
    align-items: center;
    justify-content: center;
  }

  &__title-wrap {
    min-width: 0;
  }

  &__title {
    display: block;
    font-size: 30rpx;
    font-weight: 700;
    color: #0f172a;
  }

  &__subtitle {
    display: block;
    margin-top: 2rpx;
    font-size: 22rpx;
    color: #64748b;
  }

  &__tabs {
    flex-shrink: 0;
    width: 100%;
    padding: 16rpx 24rpx;
    box-sizing: border-box;
    background: #ffffff;
    white-space: nowrap;
    border-bottom: 1rpx solid #e2e8f0;
  }

  &__tabs-inner {
    display: inline-flex;
    gap: 12rpx;
  }

  &__tab {
    max-width: 300rpx;
    padding: 12rpx 20rpx;
    overflow: hidden;
    color: #475569;
    font-size: 24rpx;
    text-overflow: ellipsis;
    background: #f1f5f9;
    border-radius: 8rpx;

    &--active {
      color: #1d4ed8;
      background: #dbeafe;
    }
  }

  &__body {
    flex: 1;
    min-height: 0;
    width: 100%;
    box-sizing: border-box;
    padding: 24rpx;
  }

  &__summary {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16rpx;
    margin-bottom: 20rpx;
  }

  &__name {
    min-width: 0;
    overflow: hidden;
    color: #0f172a;
    font-size: 28rpx;
    font-weight: 700;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  &__field {
    flex-shrink: 0;
    padding: 6rpx 12rpx;
    color: #475569;
    font-size: 21rpx;
    background: #e2e8f0;
    border-radius: 6rpx;
  }

  &__modes {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 6rpx;
    padding: 6rpx;
    margin-bottom: 20rpx;
    background: #e2e8f0;
    border-radius: 8rpx;
  }

  &__mode {
    height: 60rpx;
    display: flex;
    align-items: center;
    justify-content: center;
    color: #64748b;
    font-size: 24rpx;
    border-radius: 6rpx;

    &--active {
      color: #0f172a;
      font-weight: 600;
      background: #ffffff;
    }
  }

  &__diff,
  &__text-panel {
    overflow: hidden;
    background: #ffffff;
    border: 1rpx solid #cbd5e1;
    border-radius: 8rpx;
  }

  &__line {
    display: flex;
    min-height: 42rpx;
    padding: 4rpx 16rpx;
    box-sizing: border-box;
    color: #475569;
    font-family: monospace;
    font-size: 22rpx;
    line-height: 1.55;

    &--add {
      color: #166534;
      background: #dcfce7;
    }

    &--remove {
      color: #991b1b;
      background: #fee2e2;
    }
  }

  &__marker {
    width: 32rpx;
    flex-shrink: 0;
    opacity: 0.7;
  }

  &__line-text {
    flex: 1;
    white-space: pre-wrap;
    word-break: break-all;
  }

  &__text-panel {
    padding: 20rpx;
    color: #475569;
    font-family: monospace;
    font-size: 23rpx;
    line-height: 1.65;
    white-space: pre-wrap;
    word-break: break-all;

    &--new {
      color: #166534;
      background: #f0fdf4;
      border-color: #bbf7d0;
    }
  }

  &__empty,
  &__empty-state {
    padding: 80rpx 24rpx;
    color: #94a3b8;
    font-size: 25rpx;
    text-align: center;
  }

  &__empty-state {
    flex: 1;
  }

  &__footer {
    display: grid;
    grid-template-columns: 1fr 1.35fr;
    gap: 16rpx;
    padding: 20rpx 24rpx calc(env(safe-area-inset-bottom) + 20rpx);
    background: #ffffff;
    border-top: 1rpx solid #e2e8f0;
  }

  &__button {
    height: 84rpx;
    margin: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 27rpx;
    font-weight: 600;
    border-radius: 8rpx;

    &--rollback {
      color: #dc2626;
      background: #fee2e2;
    }

    &--confirm {
      color: #ffffff;
      background: #16a34a;
    }

    &[disabled] {
      opacity: 0.5;
    }
  }
}
</style>
