import { defineStore } from 'pinia'
import { ref } from 'vue'
import { billingApi } from '@/api'
import type { PublicPlan, SubscriptionSummary, UsageItem, OrderItem } from '@/api/types'

export const useBillingStore = defineStore('billing', () => {
  const plans = ref<PublicPlan[]>([])
  const subscription = ref<SubscriptionSummary | null>(null)
  const entitlements = ref<Record<string, any> | null>(null)
  const usage = ref<UsageItem[]>([])
  const orders = ref<OrderItem[]>([])
  const loading = ref(false)

  async function fetchPlans() {
    loading.value = true
    try {
      plans.value = await billingApi.getPublicPlans()
    } finally {
      loading.value = false
    }
  }

  async function fetchEntitlements() {
    try {
      entitlements.value = await billingApi.getEntitlements() as any
    } catch {
      entitlements.value = null
    }
  }

  async function fetchSubscription() {
    try {
      subscription.value = await billingApi.getSubscription()
    } catch {
      subscription.value = null
    }
  }

  async function fetchUsage() {
    try {
      usage.value = await billingApi.getUsage()
    } catch {
      usage.value = []
    }
  }

  async function fetchOrders() {
    try {
      orders.value = await billingApi.getOrders()
    } catch {
      orders.value = []
    }
  }

  async function subscribe(planId: number, billingCycle: string, paymentMethod?: string) {
    const result = await billingApi.subscribe(planId, billingCycle, paymentMethod)
    if (result.subscription) subscription.value = result.subscription
    return result
  }

  async function syncOrder(orderNo: string) {
    return await billingApi.syncOrder(orderNo)
  }

  async function cancelOrder(orderNo: string) {
    return await billingApi.cancelOrder(orderNo)
  }

  return {
    plans,
    subscription,
    entitlements,
    usage,
    orders,
    loading,
    fetchPlans,
    fetchEntitlements,
    fetchSubscription,
    fetchUsage,
    fetchOrders,
    subscribe,
    syncOrder,
    cancelOrder
  }
})
