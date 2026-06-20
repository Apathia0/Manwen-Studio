<template>
  <view class="profile-page">
    <lv-navbar title="个人中心" />

    <view class="profile-page__content">
      <!-- 用户信息卡 -->
      <view class="profile-page__user-card">
        <view class="profile-page__avatar">
          <User :size="28" color="#2563eb" />
        </view>
        <view class="profile-page__user-info">
          <text class="profile-page__name">{{ authStore.user?.name || '未登录' }}</text>
          <text class="profile-page__email">{{ authStore.user?.email || '' }}</text>
          <view v-if="billingStore.subscription" class="profile-page__subscription">
            <lv-tag :type="billingStore.subscription.status === 'active' ? 'success' : 'default'" :text="billingStore.subscription.plan.name" />
            <text class="profile-page__expiry">{{ billingStore.subscription.expires_at ? '可用至 ' + formatDate(billingStore.subscription.expires_at) : '未订阅' }}</text>
          </view>
        </view>
      </view>

      <!-- 用量统计 -->
      <view class="profile-page__section">
        <text class="profile-page__section-title">本月用量</text>
        <lv-card>
          <usage-meter
            v-for="item in billingStore.usage"
            :key="item.feature_key"
            :label="featureLabel(item.feature_key)"
            :used="item.used"
            :limit="item.limit"
            color="#2563eb"
          />
          <lv-empty v-if="billingStore.usage.length === 0" title="暂无用量数据" />
        </lv-card>
      </view>

      <!-- 菜单列表 -->
      <view class="profile-page__menu">
        <view class="profile-page__menu-item" @tap="goUpgrade">
          <view class="profile-page__menu-icon">
            <CreditCard :size="18" color="#2563eb" />
          </view>
          <text class="profile-page__menu-text">升级套餐</text>
          <view class="profile-page__menu-arrow">
            <ChevronRight :size="14" color="#94a3b8" />
          </view>
        </view>
        <view class="profile-page__menu-item" @tap="goOrders">
          <view class="profile-page__menu-icon">
            <FileText :size="18" color="#2563eb" />
          </view>
          <text class="profile-page__menu-text">订单记录</text>
          <view class="profile-page__menu-arrow">
            <ChevronRight :size="14" color="#94a3b8" />
          </view>
        </view>
        <view class="profile-page__menu-item" @tap="goApiKeys">
          <view class="profile-page__menu-icon">
            <Key :size="18" color="#2563eb" />
          </view>
          <text class="profile-page__menu-text">API 配置</text>
          <view class="profile-page__menu-arrow">
            <ChevronRight :size="14" color="#94a3b8" />
          </view>
        </view>
        <view class="profile-page__menu-item" @tap="goTemplates">
          <view class="profile-page__menu-icon">
            <Library :size="18" color="#2563eb" />
          </view>
          <text class="profile-page__menu-text">提示词模板</text>
          <view class="profile-page__menu-arrow">
            <ChevronRight :size="14" color="#94a3b8" />
          </view>
        </view>
        <view class="profile-page__menu-item" @tap="goModelConfig">
          <view class="profile-page__menu-icon">
            <Settings :size="18" color="#2563eb" />
          </view>
          <text class="profile-page__menu-text">自定义模型</text>
          <view class="profile-page__menu-arrow">
            <ChevronRight :size="14" color="#94a3b8" />
          </view>
        </view>
        <view class="profile-page__menu-item" @tap="goPassword">
          <view class="profile-page__menu-icon">
            <Lock :size="18" color="#2563eb" />
          </view>
          <text class="profile-page__menu-text">修改密码</text>
          <view class="profile-page__menu-arrow">
            <ChevronRight :size="14" color="#94a3b8" />
          </view>
        </view>
        <view class="profile-page__menu-item" @tap="goAbout">
          <view class="profile-page__menu-icon">
            <Info :size="18" color="#2563eb" />
          </view>
          <text class="profile-page__menu-text">关于应用</text>
          <view class="profile-page__menu-arrow">
            <ChevronRight :size="14" color="#94a3b8" />
          </view>
        </view>
      </view>

      <!-- 管理员入口 -->
      <view v-if="authStore.user?.role === 'admin'" class="profile-page__menu">
        <view class="profile-page__menu-item" @tap="goAdmin">
          <view class="profile-page__menu-icon">
            <Shield :size="18" color="#2563eb" />
          </view>
          <text class="profile-page__menu-text">管理中心</text>
          <view class="profile-page__menu-arrow">
            <ChevronRight :size="14" color="#94a3b8" />
          </view>
        </view>
      </view>

      <view class="profile-page__logout">
        <lv-button type="danger" block @tap="handleLogout">退出登录</lv-button>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { useBillingStore } from '@/stores/billing'
import { FEATURE_LABELS } from '@/utils/constants'
import { formatDate } from '@/utils/format'
import LvNavbar from '@/components/lv-navbar/lv-navbar.vue'
import LvCard from '@/components/lv-card/lv-card.vue'
import LvTag from '@/components/lv-tag/lv-tag.vue'
import LvButton from '@/components/lv-button/lv-button.vue'
import LvEmpty from '@/components/lv-empty/lv-empty.vue'
import UsageMeter from '@/components/usage-meter/usage-meter.vue'
import { User, CreditCard, FileText, Key, Lock, Info, ChevronRight, Library, Settings, Shield } from '@lucide/vue'

const authStore = useAuthStore()
const billingStore = useBillingStore()

function featureLabel(key: string): string {
  return FEATURE_LABELS[key]?.label || key
}

onMounted(async () => {
  await Promise.all([
    billingStore.fetchSubscription(),
    billingStore.fetchUsage()
  ]).catch(() => {})
})

function handleLogout() {
  uni.showModal({
    title: '确认退出',
    content: '确定要退出登录吗？',
    success: (res) => {
      if (res.confirm) {
        authStore.logout()
      }
    }
  })
}

function goUpgrade() {
  uni.switchTab({ url: '/pages/discover/index' })
}

function goOrders() {
  uni.navigateTo({ url: '/pages/billing/orders' })
}

function goApiKeys() {
  uni.navigateTo({ url: '/pages/settings/api-keys' })
}

function goTemplates() {
  uni.switchTab({ url: '/pages/templates/index' })
}

function goModelConfig() {
  uni.navigateTo({ url: '/pages/settings/model-config' })
}

function goPassword() {
  uni.navigateTo({ url: '/pages/settings/password' })
}

function goAbout() {
  uni.navigateTo({ url: '/pages/settings/about' })
}

function goAdmin() {
  uni.navigateTo({ url: '/pages/admin/index' })
}
</script>

<style lang="scss" scoped>
.profile-page {
  min-height: 100vh;
  background: linear-gradient(180deg, $lv-bg-start 0%, $lv-bg-end 100%);

  &__content {
    padding: calc(var(--status-bar-height) + 88rpx) $lv-page-padding $lv-page-padding;
  }

  &__user-card {
    display: flex;
    align-items: center;
    background: $lv-surface-solid;
    border-radius: $lv-radius-lg;
    padding: 40rpx 32rpx;
    margin-bottom: $lv-section-gap;
    box-shadow: $lv-shadow-sm;
  }

  &__avatar {
    width: 120rpx;
    height: 120rpx;
    border-radius: 50%;
    background: $lv-primary-light;
    @include flex-center;
    color: $lv-primary;
    margin-right: 32rpx;
    flex-shrink: 0;
  }

  &__user-info {
    flex: 1;
  }

  &__name {
    display: block;
    font-size: $lv-font-xl;
    font-weight: 600;
    color: $lv-text-primary;
    margin-bottom: 8rpx;
  }

  &__email {
    display: block;
    font-size: $lv-font-sm;
    color: $lv-text-secondary;
    margin-bottom: 12rpx;
  }

  &__subscription {
    display: flex;
    align-items: center;
    gap: 12rpx;
  }

  &__expiry {
    font-size: $lv-font-xs;
    color: $lv-text-muted;
  }

  &__section {
    margin-bottom: $lv-section-gap;
  }

  &__section-title {
    display: block;
    font-size: $lv-font-base;
    font-weight: 600;
    color: $lv-text-primary;
    margin-bottom: 16rpx;
  }

  &__menu {
    background: $lv-surface-solid;
    border-radius: $lv-radius-lg;
    overflow: hidden;
    margin-bottom: $lv-section-gap;
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

  &__menu-arrow {
    width: 28rpx;
    height: 28rpx;
    @include flex-center;
    flex-shrink: 0;
  }

  &__menu-text {
    flex: 1;
    font-size: $lv-font-base;
    color: $lv-text-primary;
  }

  &__logout {
    margin-top: 48rpx;
  }
}
</style>
