import { get, post } from '@/utils/request'
import type { PublicPlan, SubscriptionSummary, UsageItem, OrderItem } from './types'

interface Entitlements {
  plan: { id: number; code: string; name: string }
  entitlements: Record<string, any>
}

interface UsageResponse {
  period_key: string
  plan_code: string
  items: UsageItem[]
}

interface SubscriptionResponse {
  user: { id: number; name: string; email: string; role: string }
  subscription: SubscriptionSummary | null
  latest_order: OrderItem | null
}

interface CheckoutInfo {
  mode: string
  method: string
  provider: string
  instructions: string
  amount: number
  currency: string
  plan_name: string
  billing_cycle: string
  expires_at: string
  qr_code_text: string
  payment_url: string
  can_mock_confirm: boolean
}

interface CheckoutResult {
  ok: boolean
  message: string
  status: string
  subscription: SubscriptionSummary
  order: OrderItem
  checkout: CheckoutInfo
}

/** 获取公开套餐列表 */
export function getPublicPlans(): Promise<PublicPlan[]> {
  return get<PublicPlan[]>('/api/plans/public')
}

/** 获取用户权益 */
export async function getEntitlements(): Promise<Entitlements> {
  return get<Entitlements>('/api/me/entitlements')
}

/** 获取当前订阅 */
export async function getSubscription(): Promise<SubscriptionSummary | null> {
  const res = await get<SubscriptionResponse>('/api/me/subscription')
  return res.subscription
}

/** 获取用量统计 */
export async function getUsage(): Promise<UsageItem[]> {
  const res = await get<UsageResponse>('/api/me/usage')
  return res.items || []
}

/** 获取订单列表 */
export function getOrders(): Promise<OrderItem[]> {
  return get<OrderItem[]>('/api/me/orders')
}

/** 订阅套餐 */
export function subscribe(planId: number, billingCycle: string, paymentMethod?: string): Promise<CheckoutResult> {
  const body: Record<string, any> = { plan_id: planId, billing_cycle: billingCycle }
  if (paymentMethod) body.payment_method = paymentMethod
  return post<CheckoutResult>('/api/billing/subscribe', body)
}

/** 同步订单状态 */
export function syncOrder(orderNo: string): Promise<{
  ok: boolean; status: string; order: OrderItem; subscription: SubscriptionSummary; checkout: CheckoutInfo | null
}> {
  return post(`/api/me/orders/${orderNo}/sync`)
}

/** 模拟支付确认 */
export function mockConfirm(orderNo: string): Promise<{
  ok: boolean; status: string; order: OrderItem; subscription: SubscriptionSummary
}> {
  return post(`/api/me/orders/${orderNo}/mock-confirm`)
}

/** 取消订单 */
export function cancelOrder(orderNo: string): Promise<any> {
  return post(`/api/me/orders/${orderNo}/cancel`)
}
