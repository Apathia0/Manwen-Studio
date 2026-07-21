import type { AuthUser, PublicPlatformSettings, AdminOrderItem } from '../api';
import {
  changePassword as changePasswordApi,
} from '../api';
import {
  formatDateTime,
  formatMoney,
  statusLabel,
  paymentMethodLabel,
  orderSourceLabel,
} from '../lib/format';
import { PasswordChangeForm } from './PasswordChangeForm';
import { PointsAiAccountPanel } from './PointsAiAccountPanel';

export function UserAccountUsagePage({
  session,
  platform,
  orders,
  actioningOrderNo,
  onConfirmMockPayment,
  onCancelOrder,
  onRefreshOrders,
}: {
  session: AuthUser | null;
  platform: PublicPlatformSettings;
  orders: AdminOrderItem[];
  actioningOrderNo: string | null;
  onConfirmMockPayment: (orderNo: string) => void;
  onCancelOrder: (orderNo: string) => void;
  onRefreshOrders: () => void;
}) {
  const pendingOrder = orders.find((order) => order.status === 'pending') || null;
  const canOverrideApiKey = Boolean(session?.can_override_api_key);
  const canOverrideApiUrl = Boolean(session?.can_override_api_url);

  return (
    <div>
      <h2 className="text-xl font-semibold">账户与积分</h2>
      <p className="mt-1 text-sm text-slate-600">
        使用平台模型消耗积分；可在下方配置自己的 API Key 并切换为「我的 Key」模式（本站不扣积分）。
      </p>
      <PointsAiAccountPanel
        canOverrideApiKey={canOverrideApiKey}
        canOverrideApiUrl={canOverrideApiUrl}
        platformApi={platform.api}
      />

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

      <div className="mt-4 rounded-3xl border border-[#d7e3f4] bg-white/95 p-5 shadow-[0_14px_34px_rgba(59,130,246,0.08)]">
        <div className="text-sm font-semibold text-slate-900">密码修改</div>
        <PasswordChangeForm onChangePassword={changePasswordApi} />
      </div>

      <div className="mt-4 rounded-3xl border border-[#d7e3f4] bg-white/95 p-5 shadow-[0_14px_34px_rgba(59,130,246,0.08)]">
        <div className="flex items-center justify-between">
          <div className="text-sm font-semibold text-slate-900">我的订单</div>
          <button onClick={onRefreshOrders} className="text-xs text-[#1d4ed8] hover:underline">刷新</button>
        </div>
        <div className="mt-1 text-xs text-slate-500">最近订单记录。</div>
        <div className="mt-4 space-y-3">
          {orders.slice(0, 10).map((order) => (
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
                <div>时间：{formatDateTime(order.paid_at || order.created_at)}</div>
                {order.operator?.name ? <div>操作人：{order.operator.name}</div> : null}
                {order.note ? <div>说明：{order.note}</div> : null}
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
  );
}
