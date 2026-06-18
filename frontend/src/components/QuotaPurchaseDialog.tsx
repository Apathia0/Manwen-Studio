import { useState, useEffect } from 'react';
import type { QuotaPriceItem, UsageItem, BillingCheckout } from '../api';
import { getQuotaPrices, purchaseQuota } from '../api';
import { featureLabel, featureDescription, formatMoney } from '../lib/format';
import { toast } from '../lib/toast';
import { PaymentCheckoutDialog } from './PaymentCheckoutDialog';

interface QuotaPurchaseDialogProps {
  featureKey: string;
  usage?: UsageItem | null;
  onClose: () => void;
  onSuccess: () => void;
}

export function QuotaPurchaseDialog({ featureKey, usage, onClose, onSuccess }: QuotaPurchaseDialogProps) {
  const [priceItem, setPriceItem] = useState<QuotaPriceItem | null>(null);
  const [amount, setAmount] = useState(10);
  const [loading, setLoading] = useState(false);
  const [checkout, setCheckout] = useState<(BillingCheckout & { orderNo: string }) | null>(null);

  useEffect(() => {
    getQuotaPrices().then((prices) => {
      const item = prices.find((p) => p.feature_key === featureKey);
      if (item) setPriceItem(item);
    });
  }, [featureKey]);

  const totalPrice = priceItem ? amount * priceItem.price_per_unit : 0;

  const handlePurchase = async () => {
    if (!priceItem) return;
    setLoading(true);
    try {
      const result = await purchaseQuota(featureKey, amount);
      if (result.status === 'pending' && result.checkout) {
        setCheckout({ ...result.checkout, orderNo: result.order.order_no });
      } else {
        toast.success('配额购买成功！');
        onSuccess();
        onClose();
      }
    } catch (err: any) {
      toast.error(err?.message || '购买失败');
    } finally {
      setLoading(false);
    }
  };

  if (checkout) {
    return (
      <PaymentCheckoutDialog
        checkout={checkout}
        onClose={() => { setCheckout(null); onClose(); }}
        onSuccess={() => { onSuccess(); onClose(); }}
      />
    );
  }

  const label = featureLabel(featureKey);
  const desc = featureDescription(featureKey);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30" onClick={onClose}>
      <div
        className="mx-4 w-full max-w-md rounded-3xl border border-[#d7e3f4] bg-white p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <h3 className="text-lg font-semibold text-slate-900">购买 {label}</h3>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-600 text-xl leading-none">&times;</button>
        </div>
        {desc ? <p className="mt-1 text-sm text-slate-500">{desc}</p> : null}

        {usage ? (
          <div className="mt-3 rounded-2xl bg-[#f8fbff] px-4 py-3 text-sm text-slate-600">
            <div className="flex justify-between">
              <span>本月已用</span>
              <span className="font-medium text-slate-900">{usage.used} / {usage.limit}</span>
            </div>
            <div className="mt-1 flex justify-between">
              <span>当前剩余</span>
              <span className="font-medium text-slate-900">{usage.remaining}</span>
            </div>
          </div>
        ) : null}

        <div className="mt-4">
          <label className="text-sm font-medium text-slate-700">购买数量</label>
          <div className="mt-1 flex items-center gap-3">
            <button
              onClick={() => setAmount(Math.max(1, amount - 10))}
              className="flex h-10 w-10 items-center justify-center rounded-xl border border-[#d7e3f4] text-lg font-medium text-slate-600 hover:bg-slate-50"
            >-</button>
            <input
              type="number"
              min={1}
              value={amount}
              onChange={(e) => setAmount(Math.max(1, parseInt(e.target.value) || 1))}
              className="flex-1 rounded-xl border border-[#d7e3f4] px-3 py-2 text-center text-lg font-semibold outline-none focus:border-[#60a5fa]"
            />
            <button
              onClick={() => setAmount(amount + 10)}
              className="flex h-10 w-10 items-center justify-center rounded-xl border border-[#d7e3f4] text-lg font-medium text-slate-600 hover:bg-slate-50"
            >+</button>
          </div>
          {priceItem ? (
            <div className="mt-2 text-right text-sm text-slate-500">
              {priceItem.price_per_unit} 元/{priceItem.unit}
            </div>
          ) : null}
        </div>

        <div className="mt-4 flex items-center justify-between rounded-2xl bg-[#eff6ff] px-4 py-3">
          <span className="text-sm font-medium text-slate-700">合计</span>
          <span className="text-xl font-bold text-[#1d4ed8]">¥{formatMoney(totalPrice)}</span>
        </div>

        <button
          onClick={handlePurchase}
          disabled={loading || !priceItem}
          className="mt-4 w-full rounded-2xl bg-[#1d4ed8] py-2.5 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-60"
        >
          {loading ? '处理中...' : `确认购买 ${amount} ${priceItem?.unit || '次'}`}
        </button>
      </div>
    </div>
  );
}
