import { useEffect, useRef, useState } from 'react';
import QRCode from 'qrcode';
import { X } from 'lucide-react';
import { syncMyOrder, type BillingCheckout } from '../api';
import { formatMoney, formatDateTime, paymentMethodLabel } from '../lib/format';

/** 支付结账弹窗 */
export function PaymentCheckoutDialog({
  checkout,
  onClose,
  onSuccess,
}: {
  checkout: (BillingCheckout & { orderNo: string }) | null;
  onClose: () => void;
  onSuccess: (message: string) => void;
}) {
  const [qrDataUrl, setQrDataUrl] = useState<string>('');
  const [checkingPayment, setCheckingPayment] = useState(false);
  const onSuccessRef = useRef(onSuccess);
  onSuccessRef.current = onSuccess;
  const pollingRef = useRef(false);
  const paidHandledRef = useRef(false);

  useEffect(() => {
    let cancelled = false;
    async function renderQr() {
      if (!checkout?.qr_code_text) {
        setQrDataUrl('');
        return;
      }
      try {
        const url = await QRCode.toDataURL(checkout.qr_code_text, {
          width: 280,
          margin: 1,
          color: {
            dark: '#0f172a',
            light: '#ffffff',
          },
        });
        if (!cancelled) setQrDataUrl(url);
      } catch {
        if (!cancelled) setQrDataUrl('');
      }
    }
    void renderQr();
    return () => {
      cancelled = true;
    };
  }, [checkout]);

  useEffect(() => {
    if (!checkout?.orderNo) return;
    paidHandledRef.current = false;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;

    async function pollOrderStatus() {
      if (cancelled || pollingRef.current || paidHandledRef.current) return;
      pollingRef.current = true;
      try {
        const result = await syncMyOrder(checkout.orderNo);
        if (cancelled) return;
        if (result.status === 'paid') {
          paidHandledRef.current = true;
          onSuccessRef.current('支付成功，订单已自动确认。');
          return;
        }
      } catch {
        // 轮询失败静默，下个周期继续
      } finally {
        pollingRef.current = false;
      }
      if (!cancelled) {
        timer = setTimeout(pollOrderStatus, 3000);
      }
    }

    timer = setTimeout(pollOrderStatus, 3000);
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [checkout?.orderNo]);

  async function confirmPaymentPaid() {
    if (!checkout?.orderNo || checkingPayment || paidHandledRef.current) return;
    setCheckingPayment(true);
    try {
      const result = await syncMyOrder(checkout.orderNo);
      if (result.status === 'paid') {
        paidHandledRef.current = true;
        onSuccess(`支付成功，${result.subscription.plan.name} 已生效。`);
      }
    } finally {
      setCheckingPayment(false);
    }
  }

  if (!checkout) return null;

  const isQuotaPurchase = checkout.source === 'quota_purchase';
  const itemLabel = isQuotaPurchase ? '购买内容' : '套餐';
  const cycleLabel = isQuotaPurchase ? '单次购买' : (checkout.billing_cycle === 'yearly' ? '年付' : '月付');

  const canCheckManually =
    checkout.method === 'alipay_qr' ||
    checkout.method === 'mapay_qr' ||
    checkout.method.startsWith('epay_') ||
    checkout.method.startsWith('mapay_');
  const scanHint = checkout.provider === 'alipay'
    ? '打开支付宝扫一扫完成付款'
    : checkout.provider === 'epay'
      ? `在已打开的页面中完成支付（${paymentMethodLabel(checkout.method)}）`
      : checkout.provider === 'mapay'
        ? `使用${paymentMethodLabel(checkout.method)}完成付款`
        : '请使用对应支付 App 扫码完成付款';

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-[rgba(15,23,42,0.48)] px-4">
      <div className="w-full max-w-4xl rounded-[28px] border border-[#d7e3f4] bg-white p-6 shadow-[0_24px_60px_rgba(15,23,42,0.2)]">
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="text-lg font-semibold text-slate-900">支付订单</div>
            <div className="mt-1 text-sm text-slate-500">
              订单号 {checkout.orderNo}，请使用{paymentMethodLabel(checkout.method)}完成支付。
            </div>
          </div>
          <button
            onClick={onClose}
            className="rounded-full border border-[#d7e3f4] bg-white p-2 text-slate-500 transition hover:bg-[#f8fbff] hover:text-slate-900"
          >
            <X size={16} />
          </button>
        </div>

        <div className="mt-6 grid gap-6 lg:grid-cols-[320px_minmax(0,1fr)]">
          <div className="rounded-3xl border border-[#d7e3f4] bg-[#f8fbff] p-5">
            <div className="rounded-3xl bg-white p-4 shadow-[0_10px_24px_rgba(59,130,246,0.08)]">
              {qrDataUrl ? (
                <img src={qrDataUrl} alt="支付二维码" className="mx-auto h-[280px] w-[280px] rounded-2xl" />
              ) : checkout.payment_url ? (
                <div className="flex h-[280px] items-center justify-center rounded-2xl bg-[#f8fbff] px-6 text-center text-sm leading-6 text-slate-500">
                  该通道返回支付链接，请在右侧打开后完成付款。
                </div>
              ) : (
                <div className="flex h-[280px] items-center justify-center rounded-2xl bg-[#f8fbff] text-sm text-slate-500">
                  正在生成二维码...
                </div>
              )}
            </div>
            <div className="mt-4 text-center text-sm text-slate-600">
              {scanHint}
            </div>
          </div>

          <div className="space-y-4">
            <div className="rounded-3xl border border-[#d7e3f4] bg-white p-5">
              <div className="text-sm font-semibold text-slate-900">订单信息</div>
              <div className="mt-4 grid gap-3 sm:grid-cols-2">
                <div className="rounded-2xl bg-[#f8fbff] px-4 py-3">
                  <div className="text-xs text-slate-500">{itemLabel}</div>
                  <div className="mt-1 text-sm font-medium text-slate-900">{checkout.plan_name}</div>
                </div>
                <div className="rounded-2xl bg-[#f8fbff] px-4 py-3">
                  <div className="text-xs text-slate-500">金额</div>
                  <div className="mt-1 text-sm font-medium text-slate-900">{checkout.currency} {formatMoney(checkout.amount)}</div>
                </div>
                <div className="rounded-2xl bg-[#f8fbff] px-4 py-3">
                  <div className="text-xs text-slate-500">{isQuotaPurchase ? '购买类型' : '计费周期'}</div>
                  <div className="mt-1 text-sm font-medium text-slate-900">{cycleLabel}</div>
                </div>
                <div className="rounded-2xl bg-[#f8fbff] px-4 py-3">
                  <div className="text-xs text-slate-500">失效时间</div>
                  <div className="mt-1 text-sm font-medium text-slate-900">{formatDateTime(checkout.expires_at)}</div>
                </div>
              </div>
            </div>

            <div className="rounded-3xl border border-[#d7e3f4] bg-white p-5">
              <div className="text-sm font-semibold text-slate-900">支付说明</div>
              <div className="mt-3 whitespace-pre-wrap text-sm leading-7 text-slate-600">
                {checkout.instructions || '请在二维码失效前完成支付，支付成功后系统会通过官方回调自动更新订单状态。'}
              </div>
              {checkout.payment_url ? (
                <a
                  href={checkout.payment_url}
                  target="_blank"
                  rel="noreferrer"
                  className="mt-4 inline-flex rounded-2xl bg-[#1d4ed8] px-4 py-2 text-sm font-medium text-white transition hover:bg-[#1e40af]"
                >
                  在新窗口打开支付链接
                </a>
              ) : null}
              {canCheckManually ? (
                <button
                  onClick={() => void confirmPaymentPaid()}
                  disabled={checkingPayment}
                  className="mt-4 ml-3 inline-flex rounded-2xl border border-[#bfdbfe] bg-white px-4 py-2 text-sm font-medium text-[#1d4ed8] transition hover:bg-[#eff6ff] disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {checkingPayment ? '正在确认支付...' : '我已完成支付'}
                </button>
              ) : null}
              <div className="mt-4 flex items-center gap-2 text-xs text-slate-400">
                <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-400" />
                系统正在自动检测支付状态，无需手动操作
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
