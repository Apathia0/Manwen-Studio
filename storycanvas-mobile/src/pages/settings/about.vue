<template>
  <view class="about-page">
    <lv-navbar title="关于" show-back />
    <view class="about-page__content">
      <view class="about-page__logo">
        <text class="about-page__app-name">LoreVista</text>
        <text class="about-page__version">v1.0.0</text>
      </view>
      <view class="about-page__info">
        <text>LoreVista —— AI 驱动的漫画创作平台</text>
        <text>让你的故事拥有自己的画面</text>
      </view>
      <view class="about-page__links">
        <view class="about-page__link-item"><text>用户协议</text><ChevronRight :size="20" color="#999" /></view>
        <view class="about-page__link-item"><text>隐私政策</text><ChevronRight :size="20" color="#999" /></view>
        <view class="about-page__link-item"><text>版本更新</text><ChevronRight :size="20" color="#999" /></view>
      </view>
      <text class="about-page__copyright">Copyright &copy; 2026 Manwen Studio. All rights reserved.</text>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ChevronRight } from '@lucide/vue'
import LvNavbar from '@/components/lv-navbar/lv-navbar.vue'
</script>

<style lang="scss" scoped>
.about-page { min-height: 100vh; background: $lv-bg-start;
  &__content { padding: calc(var(--status-bar-height) + 88rpx + $lv-page-padding) $lv-page-padding; }
  &__logo { text-align: center; padding: 64rpx 0; }
  &__app-name { display: block; font-size: 64rpx; font-weight: 700; background: linear-gradient(135deg, #00bcd4, #7c3aed); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
  &__version { font-size: 24rpx; color: $lv-text-muted; margin-top: 8rpx; display: block; }
  &__info { text-align: center; font-size: 24rpx; color: $lv-text-secondary; line-height: 2; margin-bottom: 48rpx; }
  &__links { background: #fff; border-radius: 24rpx; overflow: hidden; }
  &__link-item { display: flex; justify-content: space-between; padding: 28rpx 24rpx; font-size: 28rpx; border-bottom: 1rpx solid $lv-border-light; color: $lv-text-primary; &:last-child { border: none; } }
  &__copyright { display: block; text-align: center; font-size: 20rpx; color: $lv-text-muted; margin-top: 64rpx; }
}
</style>
