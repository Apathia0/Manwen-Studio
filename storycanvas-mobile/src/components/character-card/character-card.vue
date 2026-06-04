<template>
  <view class="character-card">
    <view class="character-card__header">
      <view class="character-card__avatar">
        <User :size="18" color="#2563eb" />
      </view>
      <view class="character-card__info">
        <text class="character-card__name">{{ character.name }}</text>
        <text class="character-card__role">{{ character.role }}</text>
      </view>
    </view>
    <view v-if="expanded" class="character-card__content">
      <view v-if="character.description" class="character-card__section">
        <text class="character-card__label">描述</text>
        <text class="character-card__value">{{ character.description }}</text>
      </view>
      <view v-if="character.personality" class="character-card__section">
        <text class="character-card__label">性格</text>
        <text class="character-card__value">{{ character.personality }}</text>
      </view>
      <view v-if="character.motivation" class="character-card__section">
        <text class="character-card__label">动机</text>
        <text class="character-card__value">{{ character.motivation }}</text>
      </view>
      <view v-if="character.fear" class="character-card__section">
        <text class="character-card__label">恐惧</text>
        <text class="character-card__value">{{ character.fear }}</text>
      </view>
      <view v-if="character.big_five" class="character-card__section">
        <text class="character-card__label">大五人格</text>
        <view class="character-card__bf-list">
          <text v-for="(val, key) in character.big_five" :key="key" class="character-card__bf-item">
            {{ key }}: {{ val }}
          </text>
        </view>
      </view>
      <view v-if="character.arc" class="character-card__section">
        <text class="character-card__label">角色弧光</text>
        <text class="character-card__value">{{ formatArc(character.arc) }}</text>
      </view>
      <view v-if="character.relationships?.length" class="character-card__section">
        <text class="character-card__label">关系</text>
        <view v-for="(rel, i) in character.relationships" :key="i" class="character-card__rel-item">
          <text class="character-card__rel-name">{{ rel.target || rel.character }}</text>
          <text class="character-card__rel-type">—— {{ rel.type || rel.relationship }}</text>
        </view>
      </view>
    </view>
    <view class="character-card__footer" @tap="toggleExpanded">
      <text class="character-card__toggle">
        {{ expanded ? '收起详情' : '展开详情' }}
      </text>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import type { Character } from '@/api/types'
import { User } from '@lucide/vue'

interface CharacterCardProps {
  character: Character
}

defineProps<CharacterCardProps>()

const expanded = ref(false)

function toggleExpanded() {
  expanded.value = !expanded.value
}

function formatArc(arc: Record<string, any>): string {
  if (typeof arc === 'string') return arc
  if (arc.description) return arc.description
  if (arc.type) return `${arc.type}: ${arc.description || ''}`
  return JSON.stringify(arc)
}
</script>

<style lang="scss" scoped>
.character-card {
  background: $lv-surface-solid;
  border: 1rpx solid $lv-border;
  border-radius: $lv-radius-md;
  overflow: hidden;

  &__header {
    display: flex;
    align-items: center;
    padding: $lv-card-padding;
  }

  &__avatar {
    width: 80rpx;
    height: 80rpx;
    border-radius: 50%;
    background: $lv-primary-lighter;
    @include flex-center;
    color: $lv-primary;
    font-size: 36rpx;
    margin-right: 24rpx;
    flex-shrink: 0;
  }

  &__info {
    flex: 1;
  }

  &__name {
    display: block;
    font-size: $lv-font-lg;
    font-weight: 600;
    color: $lv-text-primary;
    margin-bottom: 4rpx;
  }

  &__role {
    display: block;
    font-size: $lv-font-sm;
    color: $lv-text-secondary;
  }

  &__content {
    padding: 0 $lv-card-padding $lv-card-padding;
    border-top: 1rpx solid $lv-border-light;
  }

  &__section {
    padding: 16rpx 0;
    border-bottom: 1rpx solid $lv-border-light;
    &:last-child { border-bottom: none; }
  }

  &__label {
    display: block;
    font-size: $lv-font-xs;
    color: $lv-text-muted;
    margin-bottom: 8rpx;
  }

  &__value {
    display: block;
    font-size: $lv-font-sm;
    color: $lv-text-primary;
    line-height: 1.6;
    white-space: pre-wrap;
  }

  &__bf-list {
    display: flex;
    flex-wrap: wrap;
    gap: 8rpx;
  }

  &__bf-item {
    font-size: 20rpx;
    color: $lv-text-primary;
    background: $lv-primary-lighter;
    padding: 4rpx 12rpx;
    border-radius: 8rpx;
  }

  &__rel-item {
    display: flex;
    align-items: center;
    gap: 8rpx;
    padding: 8rpx 0;
    border-bottom: 1rpx solid $lv-border-light;
    &:last-child { border-bottom: none; }
  }

  &__rel-name {
    font-size: $lv-font-sm;
    color: $lv-text-primary;
    font-weight: 500;
  }

  &__rel-type {
    font-size: $lv-font-sm;
    color: $lv-text-muted;
  }

  &__footer {
    display: flex;
    justify-content: center;
    padding: 16rpx;
    border-top: 1rpx solid $lv-border-light;
    cursor: pointer;
    &:active { background: $lv-primary-lighter; }
  }

  &__toggle {
    font-size: $lv-font-sm;
    color: $lv-primary;
  }
}
</style>
