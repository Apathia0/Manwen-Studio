<template>
  <view class="quality-page">
    <lv-navbar title="质量评估" show-back />
    <view class="quality-page__content">
      <lv-button block @tap="runAssessment">开始评估</lv-button>
      <view v-if="result" class="quality-page__result">
        <view class="quality-page__score">
          <text class="quality-page__score-num">{{ result.score }}</text>
          <text class="quality-page__score-label">综合评分</text>
        </view>
        <view v-for="(item,i) in result.items" :key="i" class="quality-page__item">
          <text class="quality-page__item-name">{{ item.name }}</text>
          <lv-progress :percentage="item.score" :color="item.score > 70 ? '#15803d' : item.score > 40 ? '#d97706' : '#be123c'" />
        </view>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { post } from '@/utils/request'
import LvNavbar from '@/components/lv-navbar/lv-navbar.vue'
import LvButton from '@/components/lv-button/lv-button.vue'
import LvProgress from '@/components/lv-progress/lv-progress.vue'

interface QualityItem { name: string; score: number }
interface QualityResult { score: number; items: QualityItem[] }
const result = ref<QualityResult | null>(null)

async function runAssessment() {
  const pages = getCurrentPages(); const page = pages[pages.length - 1] as any
  const chapterId = page.options?.chapterId || 0
  try {
    const res = await post(`/api/chapters/${chapterId}/quality-assess`) as any
    result.value = res
  } catch (e: any) {
    uni.showToast({ title: e.message || '评估失败', icon: 'none' })
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
