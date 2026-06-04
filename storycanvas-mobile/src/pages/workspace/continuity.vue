<template>
  <view class="continuity-page">
    <lv-navbar title="连贯性记忆" show-back />
    <view class="continuity-page__content">
      <lv-card v-if="memories.length > 0">
        <view v-for="(mem,i) in memories" :key="i" class="continuity-page__item">
          <text class="continuity-page__key">{{ mem.key }}</text>
          <text class="continuity-page__value">{{ mem.value }}</text>
        </view>
      </lv-card>
      <lv-empty v-else title="暂无连贯性记忆" />
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { get } from '@/utils/request'
import LvNavbar from '@/components/lv-navbar/lv-navbar.vue'
import LvCard from '@/components/lv-card/lv-card.vue'
import LvEmpty from '@/components/lv-empty/lv-empty.vue'

interface Memory { key: string; value: string }
const memories = ref<Memory[]>([])

onMounted(async () => {
  const pages = getCurrentPages(); const page = pages[pages.length - 1] as any
  const chapterId = page.options?.chapterId || 0
  try {
    const res = await get(`/api/chapters/${chapterId}/continuity-memory`) as any
    memories.value = res.memories || []
  } catch (e) { console.error(e) }
})
</script>

<style lang="scss" scoped>
.continuity-page {
  min-height: 100vh; background: $lv-bg-start;
  &__content { padding: calc(var(--status-bar-height) + 88rpx + $lv-page-padding) $lv-page-padding; }
  &__item { padding: 16rpx 0; border-bottom: 1rpx solid $lv-border-light; }
  &__key { display: block; font-size: 22rpx; color: $lv-text-muted; }
  &__value { display: block; font-size: 28rpx; color: $lv-text-primary; margin-top: 4rpx; }
}
</style>
