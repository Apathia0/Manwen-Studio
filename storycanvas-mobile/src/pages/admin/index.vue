<template>
  <view class="admin-hub">
    <lv-navbar title="管理中心" />

    <view class="admin-hub__content">
      <view class="admin-hub__user-info">
        <Shield :size="24" color="#2563eb" />
        <view class="admin-hub__user-text">
          <text class="admin-hub__user-name">管理员模式</text>
          <text class="admin-hub__user-desc">管理平台套餐、用户和配置</text>
        </view>
      </view>

      <view class="admin-hub__menu">
        <view class="admin-hub__menu-item" @tap="goTo('/pages/admin/plans')">
          <view class="admin-hub__menu-icon">
            <CreditCard :size="18" color="#2563eb" />
          </view>
          <text class="admin-hub__menu-text">套餐管理</text>
          <ChevronRight :size="14" color="#94a3b8" />
        </view>
        <view class="admin-hub__menu-item" @tap="goTo('/pages/admin/users')">
          <view class="admin-hub__menu-icon">
            <Users :size="18" color="#2563eb" />
          </view>
          <text class="admin-hub__menu-text">用户管理</text>
          <ChevronRight :size="14" color="#94a3b8" />
        </view>
        <view class="admin-hub__menu-item" @tap="goTo('/pages/admin/platform')">
          <view class="admin-hub__menu-icon">
            <Settings2 :size="18" color="#2563eb" />
          </view>
          <text class="admin-hub__menu-text">平台配置</text>
          <ChevronRight :size="14" color="#94a3b8" />
        </view>
        <view class="admin-hub__menu-item" @tap="goTo('/pages/admin/orders')">
          <view class="admin-hub__menu-icon">
            <ScrollText :size="18" color="#2563eb" />
          </view>
          <text class="admin-hub__menu-text">订单中心</text>
          <ChevronRight :size="14" color="#94a3b8" />
        </view>
        <view class="admin-hub__menu-item" @tap="goTo('/pages/admin/audit-logs')">
          <view class="admin-hub__menu-icon">
            <FileSearch :size="18" color="#2563eb" />
          </view>
          <text class="admin-hub__menu-text">操作审计</text>
          <ChevronRight :size="14" color="#94a3b8" />
        </view>
        <view class="admin-hub__menu-item" @tap="goTo('/pages/admin/announcement')">
          <view class="admin-hub__menu-icon">
            <Megaphone :size="18" color="#2563eb" />
          </view>
          <text class="admin-hub__menu-text">公告管理</text>
          <ChevronRight :size="14" color="#94a3b8" />
        </view>
        <view class="admin-hub__menu-item" @tap="goTo('/pages/admin/template-review')">
          <view class="admin-hub__menu-icon">
            <Library :size="18" color="#2563eb" />
          </view>
          <text class="admin-hub__menu-text">模板审核</text>
          <ChevronRight :size="14" color="#94a3b8" />
        </view>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import LvNavbar from '@/components/lv-navbar/lv-navbar.vue'
import { Shield, CreditCard, Users, Settings2, ScrollText, FileSearch, Megaphone, Library, ChevronRight } from '@lucide/vue'

function goTo(url: string) {
  uni.navigateTo({ url })
}
</script>

<style lang="scss" scoped>
.admin-hub {
  min-height: 100vh;
  background: linear-gradient(180deg, $lv-bg-start 0%, $lv-bg-end 100%);

  &__content {
    padding: calc(var(--status-bar-height) + 88rpx) $lv-page-padding $lv-page-padding;
  }

  &__user-info {
    display: flex;
    align-items: center;
    gap: 20rpx;
    background: $lv-surface-solid;
    border-radius: $lv-radius-lg;
    padding: 32rpx;
    margin-bottom: $lv-section-gap;
    box-shadow: $lv-shadow-sm;
  }

  &__user-text {
    flex: 1;
  }

  &__user-name {
    display: block;
    font-size: $lv-font-lg;
    font-weight: 600;
    color: $lv-text-primary;
    margin-bottom: 6rpx;
  }

  &__user-desc {
    display: block;
    font-size: $lv-font-xs;
    color: $lv-text-muted;
  }

  &__menu {
    background: $lv-surface-solid;
    border-radius: $lv-radius-lg;
    overflow: hidden;
    box-shadow: $lv-shadow-sm;
  }

  &__menu-item {
    display: flex;
    align-items: center;
    padding: 28rpx 32rpx;
    border-bottom: 1rpx solid $lv-border-light;

    &:last-child {
      border-bottom: none;
    }

    &:active {
      background: $lv-primary-lighter;
    }
  }

  &__menu-icon {
    width: 36rpx;
    height: 36rpx;
    @include flex-center;
    margin-right: 20rpx;
    flex-shrink: 0;
  }

  &__menu-text {
    flex: 1;
    font-size: $lv-font-base;
    color: $lv-text-primary;
  }
}
</style>
