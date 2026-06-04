<template>
  <view class="ot">
    <view v-for="(act, ai) in outline" :key="String(act.act)" class="ot__act">
      <view class="ot__act-header" @tap="toggleAct(ai)">
        <view class="ot__act-title-row">
          <lv-icon :name="expandedActs[ai] ? 'ChevronDown' : 'ChevronRight'" :size="14" color="#94a3b8" />
          <text class="ot__act-title">第{{ getActChineseNumber(act.act) }}幕: {{ act.title }}</text>
          <text class="ot__act-pct">{{ Math.max(1, Math.round(act.chapters.length / totalChapters * 100)) }}%</text>
        </view>
        <text class="ot__act-count">{{ act.chapters.length }} 章</text>
      </view>

      <view v-if="expandedActs[ai]" class="ot__act-body">
        <view v-for="ch in act.chapters" :key="ch.chapter_number" class="ot__chapter">
          <view class="ot__chapter-row">
            <view class="ot__chapter-info">
              <text class="ot__chapter-num">#{{ String(ch.chapter_number).padStart(2, '0') }}</text>
              <text class="ot__chapter-title">{{ ch.title }}</text>
              <text v-if="ch.is_current" class="ot__chapter-current">当前</text>
            </view>
            <view class="ot__chapter-actions">
              <text
                v-if="!chapterHasContent(ch)"
                class="ot__ch-btn ot__ch-btn--generate"
                @tap.stop="handleGenerate(ch)"
              >
                <lv-icon name="FileText" :size="11" color="#fff" />生成正文
              </text>
              <text
                v-else
                class="ot__ch-btn ot__ch-btn--open"
                @tap.stop="handleSelect(ch)"
              >
                <lv-icon name="BookOpen" :size="11" />打开
              </text>
            </view>
          </view>
          <text v-if="ch.summary" class="ot__ch-summary">{{ ch.summary }}</text>
        </view>

        <view v-if="act.chapters.length === 0" class="ot__empty">
          <text class="ot__empty-text">暂无章节</text>
        </view>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import type { OutlineAct, OutlineChapter, Chapter } from '@/api/types'
import LvIcon from '@/components/lv-icon/lv-icon.vue'

interface Props {
  outline: OutlineAct[]
  chapterMap?: Map<number, Chapter>
  expandedAll?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  chapterMap: () => new Map(),
  expandedAll: true
})

const emit = defineEmits<{
  (e: 'select', chapter: OutlineChapter): void
  (e: 'generate', chapter: OutlineChapter): void
}>()

const totalChapters = computed(() =>
  props.outline.reduce((sum, act) => sum + act.chapters.length, 0)
)

const expandedActs = ref<Record<number, boolean>>(
  Object.fromEntries(props.outline.map((_, i) => [i, props.expandedAll]))
)

function toggleAct(index: number) {
  expandedActs.value[index] = !expandedActs.value[index]
}

watch(() => props.expandedAll, (val) => {
  const newState: Record<number, boolean> = {}
  for (let i = 0; i < props.outline.length; i++) {
    newState[i] = val ?? true
  }
  expandedActs.value = newState
})

function chapterHasContent(ch: OutlineChapter): boolean {
  const actual = props.chapterMap.get(ch.chapter_number)
  return !!(actual?.novel_content?.trim()) || !!(actual?.messages?.length)
}

function handleSelect(ch: OutlineChapter) {
  emit('select', ch)
}

function handleGenerate(ch: OutlineChapter) {
  emit('generate', ch)
}

function getActChineseNumber(act: number | string): string {
  const num = typeof act === 'string' ? parseInt(act, 10) : act
  if (isNaN(num)) return String(act)
  const map: Record<number, string> = { 1: '一', 2: '二', 3: '三', 4: '四', 5: '五' }
  return map[num] || String(num)
}
</script>

<style lang="scss" scoped>
.ot {
  &__act {
    margin-bottom: 20rpx;
    &:last-child { margin-bottom: 0; }
  }

  &__act-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 12rpx 0;
    cursor: pointer;
    &:active { opacity: 0.7; }
  }

  &__act-title-row {
    display: flex;
    align-items: center;
    gap: 8rpx;
    flex: 1;
    min-width: 0;
  }

  &__act-title {
    font-size: $lv-font-sm;
    font-weight: 600;
    color: $lv-text-secondary;
    @include text-ellipsis;
  }

  &__act-pct {
    font-size: 20rpx;
    color: #2563eb;
    background: #eff6ff;
    padding: 2rpx 12rpx;
    border-radius: 12rpx;
  }

  &__act-count {
    font-size: $lv-font-xs;
    color: $lv-text-muted;
    margin-left: 12rpx;
  }

  &__act-body {
    padding-left: 20rpx;
    margin-top: 8rpx;
  }

  &__chapter {
    padding: 12rpx;
    border-radius: $lv-radius-sm;
    margin-bottom: 8rpx;
    background: $lv-primary-lighter;
    &:last-child { margin-bottom: 0; }
  }

  &__chapter-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8rpx;
  }

  &__chapter-info {
    display: flex;
    align-items: center;
    gap: 8rpx;
    flex: 1;
    min-width: 0;
  }

  &__chapter-num {
    font-size: $lv-font-xs;
    color: $lv-text-muted;
    font-family: monospace;
  }

  &__chapter-title {
    font-size: $lv-font-sm;
    color: $lv-text-primary;
    @include text-ellipsis;
  }

  &__chapter-current {
    font-size: 18rpx;
    color: #2563eb;
    background: #dbeafe;
    padding: 2rpx 10rpx;
    border-radius: 10rpx;
  }

  &__chapter-actions {
    flex-shrink: 0;
  }

  &__ch-btn {
    display: inline-flex;
    align-items: center;
    gap: 4rpx;
    padding: 6rpx 16rpx;
    border-radius: 12rpx;
    font-size: 20rpx;
    font-weight: 500;
    &:active { opacity: 0.7; }
    &--generate {
      background: $lv-primary;
      color: #fff;
    }
    &--open {
      background: #eff6ff;
      color: $lv-primary;
    }
  }

  &__ch-summary {
    display: block;
    margin-top: 8rpx;
    font-size: 20rpx;
    color: $lv-text-muted;
    line-height: 1.5;
  }

  &__empty {
    padding: 16rpx 0;
    text-align: center;
  }
  &__empty-text { font-size: $lv-font-sm; color: $lv-text-muted; font-style: italic; }
}
</style>
