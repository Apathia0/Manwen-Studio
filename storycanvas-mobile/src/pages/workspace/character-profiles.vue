<template>
  <view class="char-profiles">
    <lv-navbar title="角色外观" show-back />
    <view class="char-profiles__content">
      <view v-for="char in characters" :key="char.id" class="char-profiles__card">
        <view class="char-profiles__header">
          <text class="char-profiles__name">{{ char.name }}</text>
          <text class="char-profiles__role">{{ char.role }}</text>
        </view>
        <text class="char-profiles__desc">{{ char.description }}</text>
        <text class="char-profiles__personality">性格: {{ char.personality }}</text>
      </view>
      <lv-empty v-if="characters.length === 0" title="暂无角色" />
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { get } from '@/utils/request'
import type { Character } from '@/api/types'
import LvNavbar from '@/components/lv-navbar/lv-navbar.vue'
import LvEmpty from '@/components/lv-empty/lv-empty.vue'

const characters = ref<Character[]>([])
onMounted(async () => {
  const pages = getCurrentPages(); const page = pages[pages.length - 1] as any
  const storyId = page.options?.storyId || 0
  try {
    const res = await get(`/api/stories/${storyId}/characters`) as any
    characters.value = res.characters || []
  } catch (e) { console.error(e) }
})
</script>

<style lang="scss" scoped>
.char-profiles {
  min-height: 100vh; background: $lv-bg-start;
  &__content { padding: calc(var(--status-bar-height) + 88rpx + $lv-page-padding) $lv-page-padding; }
  &__card { background: #fff; border-radius: 24rpx; padding: 28rpx; margin-bottom: 16rpx; }
  &__header { display: flex; align-items: center; gap: 16rpx; margin-bottom: 12rpx; }
  &__name { font-size: 32rpx; font-weight: 600; color: $lv-text-primary; }
  &__role { font-size: 24rpx; color: $lv-text-muted; }
  &__desc, &__personality { font-size: 26rpx; color: $lv-text-secondary; margin-top: 8rpx; display: block; }
}
</style>
