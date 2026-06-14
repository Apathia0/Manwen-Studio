import { useState } from 'react';
import type { AuthUser, PublicPlatformSettings, UsageResponse, MySubscriptionResponse, EntitlementResponse, AdminOrderItem } from '../api';
import {
  getApiKeySettings,
  saveApiKeySettings,
  clearApiKeySettings,
  changePassword as changePasswordApi,
} from '../api';
import {
  formatDateTime,
  formatMoney,
  formatSubscriptionPeriod,
  featureLabel,
  featureDescription,
  formatFeatureValue,
  statusLabel,
  paymentMethodLabel,
  orderSourceLabel,
  LEGACY_FEATURE_KEY_MAP,
} from '../lib/format';
import { toast } from '../lib/toast';
import { PasswordChangeForm } from './PasswordChangeForm';

/** 用户账户与用量页面 */
export function UserAccountUsagePage({
  session,
  platform,
  usage,
  subscription,
  entitlements,
  orders,
  actioningOrderNo,
  onConfirmMockPayment,
  onCancelOrder,
}: {
  session: AuthUser | null;
  platform: PublicPlatformSettings;
  usage: UsageResponse | null;
  subscription: MySubscriptionResponse | null;
  entitlements: EntitlementResponse | null;
  orders: AdminOrderItem[];
  actioningOrderNo: string | null;
  onConfirmMockPayment: (orderNo: string) => void;
  onCancelOrder: (orderNo: string) => void;
}) {
  const [apiSettings, setApiSettings] = useState(() => getApiKeySettings());
  const entitlementEntries = Object.entries(entitlements?.entitlements || {});
  const pendingOrder = orders.find((order) => order.status === 'pending') || null;
  const canOverrideApiKey = Boolean(session?.can_override_api_key);
  const canOverrideApiUrl = Boolean(session?.can_override_api_url);

  return (
    <div>
      <h2 className="text-xl font-semibold">账户与用量</h2>
      <p className="mt-1 text-sm text-slate-600">查看当前套餐状态、本月核心能力剩余额度，以及当前套餐已经为你开放的能力项，方便判断是否需要升级套餐。</p>
      <div className="mt-4 grid gap-4 md:grid-cols-3">
        <div className="rounded-3xl border border-[#d7e3f4] bg-white/95 p-5 shadow-[0_14px_34px_rgba(59,130,246,0.08)]">
          <div className="text-xs font-medium text-slate-500">当前套餐</div>
          <div className="mt-2 text-2xl font-semibold text-slate-900">{subscription?.subscription.plan.name || '-'}</div>
          <div className="mt-2 text-sm text-slate-600">状态：{statusLabel(subscription?.subscription.status)}</div>
          <div className="mt-2 text-sm text-slate-600">
            到期时间：{subscription?.subscription.expires_at ? formatDateTime(subscription.subscription.expires_at) : '长期有效'}
          </div>
          <div className="mt-1 text-sm text-slate-600">
            当前账期：{formatSubscriptionPeriod(subscription?.subscription.current_period_start, subscription?.subscription.current_period_end)}
          </div>
        </div>
        <div className="rounded-3xl border border-[#d7e3f4] bg-white/95 p-5 shadow-[0_14px_34px_rgba(59,130,246,0.08)]">
          <div className="text-xs font-medium text-slate-500">当前月费</div>
          <div className="mt-2 text-2xl font-semibold text-slate-900">{subscription ? `¥${formatMoney(subscription.subscription.plan.monthly_price)}` : '-'}</div>
          <div className="mt-2 text-sm text-slate-600">{subscription?.subscription.plan.currency || '-'}</div>
        </div>
        <div className="rounded-3xl border border-[#d7e3f4] bg-white/95 p-5 shadow-[0_14px_34px_rgba(59,130,246,0.08)]">
          <div className="text-xs font-medium text-slate-500">最近订单</div>
          <div className="mt-2 text-sm font-semibold text-slate-900">{subscription?.latest_order?.order_no || '-'}</div>
          <div className="mt-2 text-sm text-slate-600">{statusLabel(subscription?.latest_order?.status) || '暂无订单'}</div>
          {pendingOrder ? (
            <div className="mt-3 rounded-2xl bg-[#f8fbff] px-3 py-3 text-xs leading-6 text-slate-600">
              <div>待支付金额：{pendingOrder.currency} {formatMoney(pendingOrder.amount)}</div>
              <div>支付方式：{paymentMethodLabel(pendingOrder.payment_method)}</div>
              <div>失效时间：{formatDateTime(pendingOrder.expired_at)}</div>
              {pendingOrder.extra?.alipay_qr_code ? <div className="break-all">支付宝付款码：{pendingOrder.extra.alipay_qr_code}</div> : null}
            </div>
          ) : null}
        </div>
      </div>

      {pendingOrder ? (
        <div className="mt-4 rounded-3xl border border-[#bfdbfe] bg-[#eff6ff] p-5 shadow-[0_14px_34px_rgba(59,130,246,0.08)]">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <div className="text-sm font-semibold text-slate-900">有一笔待支付订单</div>
              <div className="mt-1 text-sm text-slate-600">
                订单号 {pendingOrder.order_no}，金额 {pendingOrder.currency} {formatMoney(pendingOrder.amount)}，方式 {paymentMethodLabel(pendingOrder.payment_method)}。
              </div>
              {pendingOrder.extra?.alipay_payment_url ? (
                <a className="mt-2 inline-block text-sm text-[#1d4ed8] underline" href={pendingOrder.extra.alipay_payment_url} target="_blank" rel="noreferrer">
                  打开支付宝收银二维码
                </a>
              ) : null}
              <div className="mt-1 text-xs text-slate-500">真实支付会通过回调或手动刷新更新订单状态，未完成的订单可在失效前取消。</div>
            </div>
            <div className="flex flex-wrap gap-3">
              {pendingOrder.payment_method === 'mock_qr' ? (
                <button
                  onClick={() => onConfirmMockPayment(pendingOrder.order_no)}
                  disabled={actioningOrderNo === pendingOrder.order_no}
                  className="rounded-2xl bg-[#1d4ed8] px-4 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {actioningOrderNo === pendingOrder.order_no ? '处理中...' : '确认模拟支付'}
                </button>
              ) : null}
              <button
                onClick={() => onCancelOrder(pendingOrder.order_no)}
                disabled={actioningOrderNo === pendingOrder.order_no}
                className="rounded-2xl border border-[#bfdbfe] bg-white px-4 py-2 text-sm font-medium text-slate-700 disabled:cursor-not-allowed disabled:opacity-60"
              >
                取消订单
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {canOverrideApiKey || canOverrideApiUrl ? (
        <div className="mt-4 rounded-3xl border border-[#d7e3f4] bg-white/95 p-5 shadow-[0_14px_34px_rgba(59,130,246,0.08)]">
          <div className="text-sm font-semibold text-slate-900">自定义模型对接</div>
          <div className="mt-1 text-xs text-slate-500">
            这里的配置只对当前浏览器生效。没有权限的字段即使填写，服务端也会继续使用管理员配置。
          </div>
          <div className="mt-2 text-xs text-[#1d4ed8]">
            启用自定义中转地址后，对应请求将不再扣减平台套餐配额。
          </div>
          <div className="mt-4 grid gap-4 xl:grid-cols-2">
            <div className="rounded-2xl border border-[#e5edf8] bg-[#f8fbff] p-4">
              <div className="mb-3 text-sm font-semibold text-slate-900">文本模型</div>
              <div className="mb-3 rounded-2xl border border-[#d7e3f4] bg-white px-3 py-3 text-xs text-slate-600">
                <div>平台地址：{platform.api?.deepseek_base_url || '-'}</div>
                <div className="mt-1">平台模型：{platform.api?.deepseek_model || '-'}</div>
              </div>
              <div className="space-y-3">
                <input
                  value={apiSettings.deepseekBaseUrl}
                  onChange={(e) => setApiSettings((prev) => ({ ...prev, deepseekBaseUrl: e.target.value }))}
                  disabled={!canOverrideApiUrl}
                  placeholder={platform.api?.deepseek_base_url || '自定义 DeepSeek Base URL'}
                  className="w-full rounded-2xl border border-[#d7e3f4] px-3 py-2 text-sm outline-none transition focus:border-[#60a5fa] focus:ring-2 focus:ring-[#bfdbfe] disabled:cursor-not-allowed disabled:bg-slate-100"
                />
                <input
                  value={apiSettings.deepseekModel}
                  onChange={(e) => setApiSettings((prev) => ({ ...prev, deepseekModel: e.target.value }))}
                  disabled={!canOverrideApiUrl}
                  placeholder={platform.api?.deepseek_model || '自定义 DeepSeek 模型名'}
                  className="w-full rounded-2xl border border-[#d7e3f4] px-3 py-2 text-sm outline-none transition focus:border-[#60a5fa] focus:ring-2 focus:ring-[#bfdbfe] disabled:cursor-not-allowed disabled:bg-slate-100"
                />
                <input
                  value={apiSettings.deepseekApiKey}
                  onChange={(e) => setApiSettings((prev) => ({ ...prev, deepseekApiKey: e.target.value }))}
                  disabled={!canOverrideApiKey}
                  type="password"
                  placeholder="自定义 DeepSeek API Key"
                  className="w-full rounded-2xl border border-[#d7e3f4] px-3 py-2 text-sm outline-none transition focus:border-[#60a5fa] focus:ring-2 focus:ring-[#bfdbfe] disabled:cursor-not-allowed disabled:bg-slate-100"
                />
              </div>
            </div>
            <div className="rounded-2xl border border-[#e5edf8] bg-[#f8fbff] p-4">
              <div className="mb-3 text-sm font-semibold text-slate-900">图片模型</div>
              <div className="mb-3 rounded-2xl border border-[#d7e3f4] bg-white px-3 py-3 text-xs text-slate-600">
                <div>平台地址：{platform.api?.image_base_url || '-'}</div>
                <div className="mt-1">平台模型：{platform.api?.image_model || '-'}</div>
              </div>
              <div className="space-y-3">
                <input
                  value={apiSettings.imageBaseUrl}
                  onChange={(e) => setApiSettings((prev) => ({ ...prev, imageBaseUrl: e.target.value }))}
                  disabled={!canOverrideApiUrl}
                  placeholder={platform.api?.image_base_url || '自定义图片服务 Base URL'}
                  className="w-full rounded-2xl border border-[#d7e3f4] px-3 py-2 text-sm outline-none transition focus:border-[#60a5fa] focus:ring-2 focus:ring-[#bfdbfe] disabled:cursor-not-allowed disabled:bg-slate-100"
                />
                <input
                  value={apiSettings.imageModel}
                  onChange={(e) => setApiSettings((prev) => ({ ...prev, imageModel: e.target.value }))}
                  disabled={!canOverrideApiUrl}
                  placeholder={platform.api?.image_model || '自定义图片模型名'}
                  className="w-full rounded-2xl border border-[#d7e3f4] px-3 py-2 text-sm outline-none transition focus:border-[#60a5fa] focus:ring-2 focus:ring-[#bfdbfe] disabled:cursor-not-allowed disabled:bg-slate-100"
                />
                <input
                  value={apiSettings.imageApiKey}
                  onChange={(e) => setApiSettings((prev) => ({ ...prev, imageApiKey: e.target.value }))}
                  disabled={!canOverrideApiKey}
                  type="password"
                  placeholder="自定义图片 API Key"
                  className="w-full rounded-2xl border border-[#d7e3f4] px-3 py-2 text-sm outline-none transition focus:border-[#60a5fa] focus:ring-2 focus:ring-[#bfdbfe] disabled:cursor-not-allowed disabled:bg-slate-100"
                />
              </div>
            </div>
          </div>
          <div className="mt-4 flex flex-wrap gap-3">
            <button
              onClick={() => {
                saveApiKeySettings(apiSettings);
                toast.success('配置已保存');
              }}
              className="rounded-2xl bg-[#1d4ed8] px-4 py-2 text-sm font-medium text-white"
            >
              保存本地对接配置
            </button>
            <button
              onClick={() => {
                clearApiKeySettings();
                setApiSettings(getApiKeySettings());
                toast.info('本地配置已清空');
              }}
              className="rounded-2xl border border-[#d7e3f4] bg-white px-4 py-2 text-sm font-medium text-slate-700"
            >
              清空本地配置
            </button>
          </div>
        </div>
      ) : null}

      <div className="mt-4 rounded-3xl border border-[#d7e3f4] bg-white/95 p-5 shadow-[0_14px_34px_rgba(59,130,246,0.08)]">
        <div className="text-sm font-semibold text-slate-900">密码修改</div>
        <PasswordChangeForm onChangePassword={changePasswordApi} />
      </div>

      <div className="mt-4 overflow-hidden rounded-3xl border border-[#d7e3f4] bg-white/95 shadow-[0_14px_34px_rgba(59,130,246,0.08)]">
        <div className="border-b border-[#e5edf8] px-4 py-3">
          <div className="text-sm font-semibold text-slate-900">本月核心额度</div>
          <div className="mt-1 text-xs text-slate-500">这里展示会直接影响创作效率的主要可消耗能力。</div>
        </div>
        <table className="w-full text-left text-sm">
          <thead className="bg-[#f8fbff] text-slate-500">
            <tr>
              <th className="px-4 py-3 font-medium">能力项</th>
              <th className="px-4 py-3 font-medium">总量</th>
              <th className="px-4 py-3 font-medium">已用</th>
              <th className="px-4 py-3 font-medium">剩余</th>
            </tr>
          </thead>
          <tbody>
            {(() => {
              const items = usage?.items || [];
              const activeKeys = new Set(items.map(i => i.feature_key));
              const deduped = items.filter(
                item => !(item.feature_key in LEGACY_FEATURE_KEY_MAP && LEGACY_FEATURE_KEY_MAP[item.feature_key] && activeKeys.has(LEGACY_FEATURE_KEY_MAP[item.feature_key]))
              );
              return deduped.filter((item) => featureLabel(item.feature_key)).map((item) => {
              const percent = item.limit > 0 ? Math.max(0, Math.min(100, Math.round((item.remaining / item.limit) * 100))) : 0;
              return (
                <tr key={item.feature_key} className="border-t border-[#e5edf8] align-top">
                  <td className="px-4 py-3">
                    <div className="font-medium text-slate-900">{featureLabel(item.feature_key)}</div>
                    <div className="mt-1 text-xs text-slate-500">{featureDescription(item.feature_key)}</div>
                  </td>
                  <td className="px-4 py-3">{item.limit}</td>
                  <td className="px-4 py-3">{item.used}</td>
                  <td className="px-4 py-3">
                    <div className="font-medium text-slate-900">{item.remaining}</div>
                    <div className="mt-2 h-2.5 rounded-full bg-[#e5edf8]">
                      <div className="h-2.5 rounded-full bg-[#3b82f6]" style={{ width: `${percent}%` }} />
                    </div>
                  </td>
                </tr>
              );
            });
            })()}
          </tbody>
        </table>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-[1.4fr_1fr]">
        <div className="rounded-3xl border border-[#d7e3f4] bg-white/95 p-5 shadow-[0_14px_34px_rgba(59,130,246,0.08)]">
          <div className="text-sm font-semibold text-slate-900">当前权益说明</div>
          <div className="mt-1 text-xs text-slate-500">这里展示你的套餐已经开通的能力项和对应额度，不再显示难理解的内部系统键名。</div>
          <div className="mt-4 space-y-3">
            {entitlementEntries.filter(([key]) => featureLabel(key)).map(([key, value]) => (
              <div key={key} className="rounded-2xl bg-[#f8fbff] px-4 py-3">
                <div className="flex items-center justify-between gap-4">
                  <div>
                    <div className="font-medium text-slate-900">{featureLabel(key)}</div>
                    <div className="mt-1 text-xs text-slate-500">{featureDescription(key)}</div>
                  </div>
                  <div className="text-sm font-semibold text-slate-900">{formatFeatureValue(key, value)}</div>
                </div>
              </div>
            ))}
            {entitlementEntries.length === 0 ? <div className="text-sm text-slate-500">暂无权益信息</div> : null}
          </div>
        </div>

        <div className="rounded-3xl border border-[#d7e3f4] bg-white/95 p-5 shadow-[0_14px_34px_rgba(59,130,246,0.08)]">
          <div className="text-sm font-semibold text-slate-900">我的订单</div>
          <div className="mt-1 text-xs text-slate-500">最近 5 条订单或后台调整记录。</div>
          <div className="mt-4 space-y-3">
            {orders.slice(0, 5).map((order) => (
              <div key={order.order_no} className="rounded-2xl border border-[#e5edf8] px-4 py-3 text-sm">
                <div className="flex items-start justify-between gap-3">
                  <div className="font-medium text-slate-900">{order.order_no}</div>
                  <span className="rounded-full bg-[#eff6ff] px-2 py-1 text-xs text-[#1d4ed8]">
                    {orderSourceLabel(order.source)}
                  </span>
                </div>
                <div className="mt-2 grid gap-1 text-slate-600">
                  <div>金额：{order.currency} {formatMoney(order.amount)}</div>
                  <div>状态：{statusLabel(order.status)}</div>
                  <div>方式：{paymentMethodLabel(order.payment_method)}</div>
                  <div>套餐：{order.plan_name || `#${order.plan_id}`}</div>
                  <div>时间：{formatDateTime(order.paid_at || order.created_at)}</div>
                  {order.operator?.name ? <div>操作人：{order.operator.name}</div> : null}
                  {order.note ? <div>说明：{order.note}</div> : null}
                  {order.extra?.feature_name || order.extra?.feature_key ? (
                    <div>
                      补发内容：{order.extra?.feature_name || featureLabel(String(order.extra?.feature_key || ''))}
                      {order.extra?.amount ? ` +${order.extra.amount}` : ''}
                    </div>
                  ) : null}
                </div>
                {order.status === 'pending' ? (
                  <div className="mt-3 flex flex-wrap gap-2">
                    {order.payment_method === 'mock_qr' ? (
                      <button
                        onClick={() => onConfirmMockPayment(order.order_no)}
                        disabled={actioningOrderNo === order.order_no}
                        className="rounded-xl bg-[#1d4ed8] px-3 py-1.5 text-xs font-medium text-white disabled:cursor-not-allowed disabled:opacity-60"
                      >
                        {actioningOrderNo === order.order_no ? '处理中...' : '确认支付'}
                      </button>
                    ) : null}
                    <button
                      onClick={() => onCancelOrder(order.order_no)}
                      disabled={actioningOrderNo === order.order_no}
                      className="rounded-xl border border-[#d7e3f4] px-3 py-1.5 text-xs font-medium text-slate-700 disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      取消
                    </button>
                  </div>
                ) : null}
              </div>
            ))}
            {orders.length === 0 ? <div className="text-sm text-slate-500">暂无订单记录</div> : null}
          </div>
        </div>
      </div>
    </div>
  );
}
