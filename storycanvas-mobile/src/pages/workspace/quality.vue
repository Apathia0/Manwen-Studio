<template>
  <view class="quality-page">
    <lv-navbar title="质量评估" show-back />
    <view class="quality-page__content">
      <lv-button block :loading="assessing" :disabled="assessing" @tap="runAssessment">开始评估</lv-button>
      <view v-if="result" class="quality-page__result">
        <view class="quality-page__score">
          <text class="quality-page__score-num">{{ formatScore(result.overall) }}</text>
          <text class="quality-page__score-label">综合评分</text>
        </view>
        <view v-for="item in scoreItems" :key="item.key" class="quality-page__item">
          <text class="quality-page__item-name">{{ item.name }}</text>
          <lv-progress :percentage="toPercentage(item.score)" :color="scoreColor(item.score)" show-info />
        </view>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { chaptersApi } from '@/api'
import type { QualityScore } from '@/api/chapters'
import LvNavbar from '@/components/lv-navbar/lv-navbar.vue'
import LvButton from '@/components/lv-button/lv-button.vue'
import LvProgress from '@/components/lv-progress/lv-progress.vue'

const result = ref<QualityScore | null>(null)
const assessing = ref(false)
const scoreItems = computed(() => [
  { key: 'content', name: '内容完整度', score: result.value?.content },
  { key: 'writing', name: '文笔表现', score: result.value?.writing },
  { key: 'plot', name: '情节推进', score: result.value?.plot },
  { key: 'character', name: '角色塑造', score: result.value?.character }
])

function formatScore(score?: number) {
  return typeof score === 'number' ? score.toFixed(1) : '--'
}

function toPercentage(score?: number) {
  if (typeof score !== 'number') return 0
  return score <= 10 ? Math.round(score * 10) : Math.round(score)
}

function scoreColor(score?: number) {
  const percentage = toPercentage(score)
  return percentage >= 70 ? '#15803d' : percentage >= 40 ? '#d97706' : '#be123c'
}

async function runAssessment() {
  if (assessing.value) return
  const pages = getCurrentPages(); const page = pages[pages.length - 1] as any
  const chapterId = page.options?.chapterId || 0
  assessing.value = true
  try {
    result.value = await chaptersApi.qualityAssess(Number(chapterId))
  } catch (e: any) {
    uni.showToast({ title: e.message || '评估失败', icon: 'none' })
  } finally {
    assessing.value = false
  }
}
</script>

<style lang="scss" scoped>
.quality-page {
  min-height: 100vh; background: $lv-bg-start;
  &__content { padding: calc(var(--status-bar-height) + 88rpx + $lv-page-padding) $lv-page-padding; }
  &__result { margin-top: 24rpx; background: #fff; border-radius: 24rpx; padding: 32rpx; }
  &__score { text-align: center; margin-bottom: 32rpx; }
  &__score-num { display: block; font-size: 96rpx; font-weight: 700; color: $lv-primary; }
  &__score-label { font-size: 24rpx; color: $lv-text-muted; }
  &__item { margin-bottom: 20rpx; }
  &__item-name { display: block; font-size: 26rpx; color: $lv-text-secondary; margin-bottom: 8rpx; }
}
</style>
