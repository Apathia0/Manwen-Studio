<template>
  <scroll-view scroll-y class="diff-viewer">
    <view v-for="(line, index) in lines" :key="index" :class="getLineClass(line)">
      <text class="diff-viewer__prefix">{{ line.prefix }}</text>
      <text class="diff-viewer__content">{{ line.content }}</text>
    </view>
  </scroll-view>
</template>

<script setup lang="ts">
import { computed } from 'vue'

interface DiffLine {
  type: 'add' | 'remove' | 'context'
  content: string
  prefix: string
}

interface DiffViewerProps {
  diff: string
}

const props = defineProps<DiffViewerProps>()

const lines = computed(() => {
  if (!props.diff) return []
  
  return props.diff.split('\n').map(line => {
    if (line.startsWith('+')) {
      return { type: 'add' as const, content: line.slice(1), prefix: '+' }
    } else if (line.startsWith('-')) {
      return { type: 'remove' as const, content: line.slice(1), prefix: '-' }
    }
    return { type: 'context' as const, content: line, prefix: ' ' }
  })
})

function getLineClass(line: DiffLine): string[] {
  return [
    'diff-viewer__line',
    `diff-viewer__line--${line.type}`
  ]
}
</script>

<style lang="scss" scoped>
.diff-viewer {
  background: #1e1e1e;
  border-radius: $lv-radius-md;
  padding: 16rpx;
  max-height: 600rpx;

  &__line {
    display: flex;
    font-family: monospace;
    font-size: $lv-font-sm;
    line-height: 1.6;
    padding: 2rpx 8rpx;
    border-radius: 4rpx;

    &--add {
      background: rgba(34, 197, 94, 0.2);
      color: #22c55e;
    }

    &--remove {
      background: rgba(239, 68, 68, 0.2);
      color: #ef4444;
    }

    &--context {
      color: #94a3b8;
    }
  }

  &__prefix {
    margin-right: 12rpx;
    user-select: none;
  }

  &__content {
    flex: 1;
    white-space: pre-wrap;
    word-break: break-all;
  }
}
</style>
