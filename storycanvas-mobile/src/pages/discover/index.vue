<template>
  <view class="discover-page">
    <lv-navbar title="发现" />

    <view class="discover-page__content">
      <!-- 公告横幅 -->
      <view v-if="platformStore.announcement" class="discover-page__banner">
        <lv-icon name="Volume2" :size="28" color="#2563eb" />
        <text class="discover-page__banner-text">{{ platformStore.announcement.title }}</text>
      </view>

      <!-- 计费周期切换 -->
      <view class="discover-page__tabs">
        <view
          :class="['discover-page__tab', { 'discover-page__tab--active': billingCycle === 'monthly' }]"
          @tap="billingCycle = 'monthly'"
        >
          <text class="discover-page__tab-text">按月</text>
        </view>
        <view
          :class="['discover-page__tab', { 'discover-page__tab--active': billingCycle === 'yearly' }]"
          @tap="billingCycle = 'yearly'"
        >
          <text class="discover-page__tab-text">按年 省20%</text>
        </view>
      </view>

      <!-- 加载状态 -->
      <view v-if="billingStore.loading" class="discover-page__loading">
        <lv-loading />
      </view>

      <!-- 套餐列表 -->
      <view v-else class="discover-page__plans">
        <plan-card
          v-for="plan in billingStore.plans"
          :key="plan.id"
          :plan="plan"
          :cycle="billingCycle"
          :is-active="currentPlanId === plan.id"
          :icon="getPlanIcon(plan.name)"
          @subscribe="handleSubscribe"
        />
        <lv-empty v-if="billingStore.plans.length === 0" title="暂无套餐" />
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useBillingStore } from '@/stores/billing'
import { usePlatformStore } from '@/stores/platform'
import { useUiStore } from '@/stores/ui'
import { usePayment } from '@/composables/usePayment'
import type { PublicPlan } from '@/api/types'
import LvNavbar from '@/components/lv-navbar/lv-navbar.vue'
import LvLoading from '@/components/lv-loading/lv-loading.vue'
import LvEmpty from '@/components/lv-empty/lv-empty.vue'
import LvIcon from '@/components/lv-icon/lv-icon.vue'
import PlanCard from '@/components/plan-card/plan-card.vue'

const billingStore = useBillingStore()
const platformStore = usePlatformStore()
const uiStore = useUiStore()
const { subscribe } = usePayment()

const billingCycle = ref<'monthly' | 'yearly'>('monthly')

const currentPlanId = computed(() => billingStore.subscription?.plan?.id || null)

onMounted(async () => {
  await Promise.all([
    billingStore.fetchPlans(),
    billingStore.fetchSubscription(),
    platformStore.fetchAnnouncement(),
  ]).catch(() => {})
})

function getPlanIcon(name: string): string {
  if (name.includes('免费')) return 'Gift'
  if (name.includes('专业') || name.includes('Pro')) return 'Gem'
  return 'Star'
}

async function handleSubscribe(plan: PublicPlan) {
  try {
    const result = await subscribe(plan.id, billingCycle.value)
    if (!result?.order?.order_no) {
      uiStore.error(result?.message || '创建订单失败')
      return
    }

    const { order, checkout } = result

    // 免费套餐自动激活成功
    if (result.status === 'paid') {
      billingStore.fetchSubscription()
      uiStore.success(`订阅成功，${result.subscription?.plan?.name || '套餐'} 已生效`)
      return
    }

    if (checkout.prepay) {
      // #ifdef MP-WEIXIN
      ;(uni as any).requestPayment({
        ...checkout.prepay,
        success: () => {
          uiStore.success('支付成功')
          billingStore.fetchSubscription()
        },
        fail: (err: any) => {
          if (err.errMsg !== 'requestPayment:fail cancel') {
            uiStore.error('支付失败')
          }
        }
      })
      // #endif
      // #ifndef MP-WEIXIN
      uiStore.info('请在微信中完成支付')
      // #endif
    } else if (checkout.qr_code_text) {
      // 扫码支付 — 跳转 checkout 页展示二维码
      uni.navigateTo({
        url: `/pages/billing/checkout?orderNo=${order.order_no}&method=${checkout.method}&qr=${encodeURIComponent(checkout.qr_code_text)}`
      })
    } else {
      // mock_qr 及其他支付方式 — 跳转 checkout 页统一处理
      uni.navigateTo({
        url: `/pages/billing/checkout?orderNo=${order.order_no}&method=${checkout.method}`
      })
    }
  } catch (e: any) {
    uiStore.error(e.message || '订阅失败')
  }
}
</script>

<style lang="scss" scoped>
.discover-page {
  min-height: 100vh;
  background: linear-gradient(180deg, $lv-bg-start 0%, $lv-bg-end 100%);

  &__content {
    padding: calc(var(--status-bar-height) + 88rpx) $lv-page-padding $lv-page-padding;
  }

  &__banner {
    display: flex;
    align-items: center;
    gap: 12rpx;
    background: $lv-primary-light;
    border-radius: $lv-radius-md;
    padding: 24rpx;
    margin-bottom: $lv-section-gap;
  }

  &__banner-text {
    font-size: $lv-font-sm;
    color: $lv-primary;
    flex: 1;
  }

  &__tabs {
    display: flex;
    background: $lv-surface-solid;
    border-radius: $lv-radius-full;
    padding: 8rpx;
    margin-bottom: $lv-section-gap;
    box-shadow: $lv-shadow-sm;
  }

  &__tab {
    flex: 1;
    display: flex;
    align-items: center;
    justify-content: center;
    height: 72rpx;
    border-radius: $lv-radius-full;
    transition: all 0.2s ease;

    &--active {
      background: $lv-primary;
      box-shadow: $lv-shadow-sm;
    }
  }

  &__tab-text {
    font-size: $lv-font-sm;
    color: $lv-text-secondary;

    .discover-page__tab--active & {
      color: $lv-text-on-primary;
      font-weight: 600;
    }
  }

  &__loading {
    display: flex;
    justify-content: center;
    padding: 80rpx 0;
  }

  &__plans {
    display: flex;
    flex-direction: column;
    gap: $lv-section-gap;
  }
}
</style>
