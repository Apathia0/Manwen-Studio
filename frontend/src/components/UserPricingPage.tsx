import { useEffect, useState } from 'react';
import {
  type BillingCheckout,
  type PointsAccount,
  type PointsProduct,
  confirmMyOrderMock,
  getPaymentConfig,
  getPointsAccount,
  getPointsProducts,
  purchasePoints,
} from '../api';
import { toast } from '../lib/toast';

export function UserPricingPage({
  onPrimary,
  onCheckout,
}: {
  plans?: unknown[];
  onPrimary?: () => void;
  subscription?: unknown;
  onSubscribe?: unknown;
  subscribingPlanId?: unknown;
  onCheckout?: (checkout: BillingCheckout & { orderNo: string }) => void;
}) {
  const [account, setAccount] = useState<PointsAccount | null>(null);
  const [products, setProducts] = useState<PointsProduct[]>([]);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [paymentMethods, setPaymentMethods] = useState<Array<{ key: string; label: string }>>([]);
  const [paymentMethod, setPaymentMethod] = useState('');

  const reload = async () => {
    try {
      const [a, p, payment] = await Promise.all([
        getPointsAccount().catch(() => null),
        getPointsProducts().catch(() => ({ products: [] as PointsProduct[] })),
        getPaymentConfig().catch(() => null),
      ]);
      if (a) setAccount(a);
      setProducts(p.products || []);
      if (payment) {
        const methods = payment.methods || [];
        setPaymentMethods(methods);
        setPaymentMethod((current) => {
          if (current && methods.some((method) => method.key === current)) return current;
          if (methods.some((method) => method.key === payment.default_method)) return payment.default_method;
          return methods[0]?.key || payment.default_method || '';
        });
      }
    } catch {
      setProducts([]);
    }
  };

  useEffect(() => {
    void reload();
  }, []);

  const onBuy = async (productId: number) => {
    if (onPrimary) {
      onPrimary();
      return;
    }
    setBusyId(productId);
    try {
      const order = await purchasePoints(productId, paymentMethod || undefined);
      if (order.checkout.can_mock_confirm) {
        await confirmMyOrderMock(order.order_no);
        toast.success(`充值成功，到账 ${order.points} 积分`);
        await reload();
      } else if (onCheckout) {
        onCheckout({ ...order.checkout, orderNo: order.order_no });
      } else {
        toast.success(`订单 ${order.order_no} 已创建，请完成支付`);
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : '购买失败');
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div>
      <h2 className="text-xl font-semibold">积分套餐</h2>
      <p className="mt-1 text-sm text-slate-600">
        使用平台模型消耗积分；文本/图片按模型定价，视频按秒计费。你也可以在账户页配置「我的 Key」走上游额度，不扣本站积分。
      </p>

      {!onPrimary && paymentMethods.length > 0 ? (
        <div className="mt-4 flex items-center gap-3 text-sm text-slate-700">
          <span>支付方式</span>
          <select
            value={paymentMethod}
            onChange={(event) => setPaymentMethod(event.target.value)}
            className="rounded-lg border border-[#d7e3f4] bg-white px-3 py-2"
          >
            {paymentMethods.map((method) => (
              <option key={method.key} value={method.key}>{method.label}</option>
            ))}
          </select>
        </div>
      ) : null}

      <div className="mt-4 grid gap-4 md:grid-cols-3">
        <div className="rounded-3xl border border-[#d7e3f4] bg-white/95 p-5 shadow-[0_14px_34px_rgba(59,130,246,0.08)] md:col-span-1">
          <div className="text-xs font-medium text-slate-500">当前可用积分</div>
          <div className="mt-2 text-3xl font-semibold text-slate-900">
            {account ? account.available_points : onPrimary ? '登录后查看' : '-'}
          </div>
          <div className="mt-2 text-sm text-slate-600">
            预扣中 {account?.reserved_points ?? 0}
          </div>
          <ul className="mt-4 space-y-2 text-sm text-slate-600">
            <li>· 平台账户：按模型积分价扣费</li>
            <li>· 视频：按秒计费，可自选时长</li>
            <li>· 我的 Key：不扣本站积分</li>
          </ul>
        </div>

        <div className="md:col-span-2 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {(products.length > 0
            ? products
            : [
                { id: -1, code: 'demo_10', name: '体验包', description: '适合体验平台模型', price_cny: 10, points: 100, bonus_points: 0, is_visible: true, is_recommended: false, sort_order: 0 },
                { id: -2, code: 'demo_50', name: '创作包', description: '适合持续进行小说和漫画创作', price_cny: 50, points: 550, bonus_points: 50, is_visible: true, is_recommended: true, sort_order: 1 },
                { id: -3, code: 'demo_100', name: '专业包', description: '适合长篇与视频创作', price_cny: 100, points: 1200, bonus_points: 200, is_visible: true, is_recommended: false, sort_order: 2 },
              ]
          ).map((p) => (
            <div
              key={p.id}
              className="rounded-3xl border border-[#d7e3f4] bg-white/95 p-5 shadow-[0_14px_34px_rgba(59,130,246,0.08)]"
            >
              <div className="flex items-center justify-between gap-2">
                <div className="text-base font-semibold text-slate-900">{p.name}</div>
                {p.is_recommended ? <span className="rounded-full bg-blue-50 px-2 py-1 text-xs text-blue-700">推荐</span> : null}
              </div>
              <div className="mt-3 text-3xl font-semibold text-slate-900">
                ¥{p.price_cny}
              </div>
              <div className="mt-2 text-sm text-slate-600">
                {p.points}
                {p.bonus_points > 0 ? ` + 赠 ${p.bonus_points}` : ''} 积分
              </div>
              <div className="mt-3 rounded-2xl bg-[#f8fbff] px-3 py-2 text-xs leading-6 text-slate-500">
                {p.description || '到账后即可用于平台模型调用；视频按秒从积分中扣减。'}
              </div>
              <button
                type="button"
                disabled={busyId === p.id || p.id < 0}
                onClick={() => {
                  if (p.id < 0) {
                    if (onPrimary) onPrimary();
                    else toast.info('请先登录后购买');
                    return;
                  }
                  void onBuy(p.id);
                }}
                className="mt-5 w-full rounded-2xl bg-[#1d4ed8] py-2.5 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-60"
              >
                {onPrimary ? '注册后购买' : busyId === p.id ? '处理中...' : '购买积分套餐'}
              </button>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
