<template>
  <view class="continuity-card">
    <view class="continuity-card__header" @tap="toggleExpanded">
      <text class="continuity-card__title">连贯性摘要</text>
      <view class="continuity-card__actions">
        <text v-if="editable" class="continuity-card__edit" @tap.stop="$emit('edit')">编辑</text>
        <ChevronUp v-if="expanded" :size="14" color="#94a3b8" />
        <ChevronDown v-else :size="14" color="#94a3b8" />
      </view>
    </view>
    <view v-if="expanded" class="continuity-card__content">
      <view v-if="chapterSummary" class="continuity-card__section">
        <text class="continuity-card__label">当前章摘要</text>
        <text class="continuity-card__text">{{ chapterSummary }}</text>
      </view>
      <view v-if="handoff.ending_location" class="continuity-card__section">
        <text class="continuity-card__label">当前场景</text>
        <text class="continuity-card__text">{{ handoff.ending_location }}</text>
      </view>
      <view v-if="handoff.active_conflict" class="continuity-card__section">
        <text class="continuity-card__label">即时冲突</text>
        <text class="continuity-card__text">{{ handoff.active_conflict }}</text>
      </view>
      <view v-if="activeCharacters.length" class="continuity-card__section">
        <text class="continuity-card__label">在场角色</text>
        <view class="continuity-card__chips">
          <text v-for="item in activeCharacters" :key="item" class="continuity-card__chip">{{ item }}</text>
        </view>
      </view>
      <view v-if="characterStates.length" class="continuity-card__section">
        <text class="continuity-card__label">角色状态</text>
        <text v-for="item in characterStates" :key="item" class="continuity-card__line">{{ item }}</text>
      </view>
      <view v-if="openLoops.length" class="continuity-card__section">
        <text class="continuity-card__label">下一章应继续推进</text>
        <text v-for="item in openLoops" :key="item" class="continuity-card__line">· {{ item }}</text>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { ChevronUp, ChevronDown } from '@lucide/vue'

interface ContinuityCardProps {
  summary: Record<string, any> | string
  defaultExpanded?: boolean
  editable?: boolean
}

const props = withDefaults(defineProps<ContinuityCardProps>(), {
  defaultExpanded: false,
  editable: false
})
defineEmits<{ edit: [] }>()

const expanded = ref(props.defaultExpanded)
const parsed = computed<Record<string, any>>(() => {
  if (typeof props.summary === 'object' && props.summary) return props.summary
  if (!props.summary) return {}
  try {
    const value = JSON.parse(props.summary)
    return value && typeof value === 'object' ? value : { summary: props.summary }
  } catch {
    return { summary: props.summary }
  }
})
const chapterSummary = computed(() => {
  const value = parsed.value.chapter_summary
  return typeof value === 'string' ? value : value?.summary || parsed.value.summary || ''
})
const handoff = computed(() => parsed.value.chapter_handoff || {})
const activeCharacters = computed(() => toList(handoff.value.active_characters))
const openLoops = computed(() => toList(handoff.value.immediate_open_loops || handoff.value.open_loops))
const characterStates = computed(() => {
  const value = handoff.value.character_states
  if (Array.isArray(value)) return value.map(formatValue).filter(Boolean)
  if (value && typeof value === 'object') {
    return Object.entries(value).map(([name, state]) => `${name}：${formatValue(state)}`)
  }
  return toList(value)
})

function formatValue(value: any): string {
  if (typeof value === 'string') return value
  if (Array.isArray(value)) return value.map(formatValue).filter(Boolean).join('、')
  if (value && typeof value === 'object') {
    return Object.entries(value).map(([key, item]) => `${key}：${formatValue(item)}`).join('；')
  }
  return value == null ? '' : String(value)
}

function toList(value: any): string[] {
  if (Array.isArray(value)) return value.map(formatValue).filter(Boolean)
  if (value && typeof value === 'object') return Object.entries(value).map(([key, item]) => `${key}：${formatValue(item)}`)
  return value ? [String(value)] : []
}

function toggleExpanded() {
  expanded.value = !expanded.value
}
</script>

<style lang="scss" scoped>
.continuity-card {
  background: $lv-primary-lighter;
  border: 1rpx solid $lv-border;
  border-radius: $lv-radius-md;
  overflow: hidden;
  margin-bottom: 24rpx;

  &__header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 20rpx $lv-card-padding;
    cursor: pointer;

    &:active {
      background: $lv-primary-light;
    }
  }

  &__title {
    font-size: $lv-font-sm;
    font-weight: 600;
    color: $lv-primary;
  }

  &__content {
    padding: 0 $lv-card-padding $lv-card-padding;
  }

  &__text {
    font-size: $lv-font-sm;
    color: $lv-text-secondary;
    line-height: 1.6;
  }

  &__actions {
    display: flex;
    align-items: center;
    gap: 16rpx;
  }

  &__edit {
    color: $lv-primary;
    font-size: $lv-font-xs;
  }

  &__section {
    padding: 14rpx 0;
    border-top: 1rpx solid rgba(148, 163, 184, 0.18);
  }

  &__label {
    display: block;
    margin-bottom: 8rpx;
    font-size: $lv-font-xs;
    font-weight: 600;
    color: $lv-text-muted;
  }

  &__line {
    display: block;
    font-size: $lv-font-sm;
    color: $lv-text-secondary;
    line-height: 1.6;
  }

  &__chips {
    display: flex;
    flex-wrap: wrap;
    gap: 10rpx;
  }

  &__chip {
    padding: 6rpx 14rpx;
    border-radius: $lv-radius-full;
    background: $lv-primary-light;
    color: $lv-primary;
    font-size: $lv-font-xs;
  }
}
</style>
