import { useEffect, useState } from 'react';
import {
  getAdminRevenueSummary,
  getAdminRevenueMonthly,
  getAdminOrders,
  type AdminRevenueSummary,
  type AdminRevenueMonthlyItem,
  type AdminOrderItem,
} from '../../api';
import { formatMoney } from './AdminPages';

function cn(...parts: Array<string | false | null | undefined>) {
  return parts.filter(Boolean).join(' ');
}

function formatDateTime(value: string | null | undefined) {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString('zh-CN');
}

function SectionCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-3xl border border-[#d7e3f4] bg-white/90 p-5 shadow-[0_14px_34px_rgba(59,130,246,0.08)]">
      <div className="mb-4">
        <h2 className="text-lg font-semibold text-slate-900">{title}</h2>
      </div>
      {children}
    </section>
  );
}

type AsyncAction = () => Promise<void>;

function useBusyAction(onError: (message: string) => void) {
  const [busy, setBusy] = useState(false);
  async function run(action: AsyncAction) {
    if (busy) return;
    setBusy(true);
    try {
      await action();
    } catch (error: any) {
      onError(error?.message || '操作失败');
    } finally {
      setBusy(false);
    }
  }
  return { busy, run };
}

function MetricCard({
  label,
  value,
  sublabel,
  trend,
  trendUp,
}: {
  label: string;
  value: string;
  sublabel?: string;
  trend?: string;
  trendUp?: boolean;
}) {
  return (
    <div className="rounded-2xl border border-[#e5edf8] bg-white p-4 transition hover:shadow-[0_8px_24px_rgba(59,130,246,0.08)]">
      <div className="text-xs font-medium uppercase tracking-[0.08em] text-slate-500">{label}</div>
      <div className="mt-2 text-2xl font-bold text-slate-900">{value}</div>
      {sublabel ? <div className="mt-1 text-xs text-slate-500">{sublabel}</div> : null}
      {trend ? (
        <div className={cn('mt-1 text-xs font-medium', trendUp ? 'text-emerald-600' : 'text-red-500')}>
          {trendUp ? '↑' : '↓'} {trend}
        </div>
      ) : null}
    </div>
  );
}

function BarChart({ data }: { data: { label: string; value: number; color?: string }[] }) {
  const max = Math.max(...data.map((d) => d.value), 1);
  return (
    <div className="flex items-end gap-2" style={{ height: 160 }}>
      {data.map((item) => {
        const h = max > 0 ? (item.value / max) * 140 : 0;
        return (
          <div key={item.label} className="flex flex-1 flex-col items-center gap-1">
            <div
              className="w-full rounded-t-md transition-all duration-500"
              style={{
                height: Math.max(h, 2),
                backgroundColor: item.color || '#3b82f6',
              }}
            />
            <span className="text-[10px] text-slate-500">{item.label}</span>
          </div>
        );
      })}
    </div>
  );
}

function DistributionBar({ items }: { items: { label: string; value: number; color: string }[] }) {
  const total = items.reduce((s, i) => s + i.value, 0) || 1;
  return (
    <div className="space-y-2">
      <div className="flex h-5 overflow-hidden rounded-full bg-[#e5edf8]">
        {items.map((item) => (
          <div
            key={item.label}
            style={{
              width: `${(item.value / total) * 100}%`,
              backgroundColor: item.color,
              minWidth: item.value > 0 ? 4 : 0,
            }}
          />
        ))}
      </div>
      <div className="space-y-1">
        {items.map((item) => (
          <div key={item.label} className="flex items-center justify-between text-xs">
            <div className="flex items-center gap-2">
              <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ backgroundColor: item.color }} />
              <span className="text-slate-600">{item.label}</span>
            </div>
            <span className="font-medium text-slate-800">
              {Math.round((item.value / total) * 100)}%（{item.value}）
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

export function AdminRevenueDashboardPage({ onError }: { onError: (message: string) => void }) {
  const [summary, setSummary] = useState<AdminRevenueSummary | null>(null);
  const [monthly, setMonthly] = useState<AdminRevenueMonthlyItem[]>([]);
  const [recentOrders, setRecentOrders] = useState<AdminOrderItem[]>([]);
  const { busy, run } = useBusyAction(onError);

  async function loadAll() {
    const [s, m, o] = await Promise.all([
      getAdminRevenueSummary(),
      getAdminRevenueMonthly(12),
      getAdminOrders(),
    ]);
    setSummary(s);
    setMonthly(m);
    setRecentOrders(o.filter((ord) => ord.status === 'paid').slice(0, 20));
  }

  useEffect(() => {
    void run(loadAll);
  }, []);

  if (!summary) {
    return (
      <SectionCard title="收入看板">
        <div className="py-8 text-center text-sm text-slate-500">加载中…</div>
      </SectionCard>
    );
  }

  const barData = monthly.map((m) => ({
    label: m.period.slice(5),
    value: m.revenue,
    color: m.revenue > 0 ? '#3b82f6' : '#e5edf8',
  }));

  const byPlan: { label: string; value: number; color: string }[] = [];
  const planMap = new Map<string, number>();
  for (const order of recentOrders) {
    const name = order.plan_name || '未知';
    planMap.set(name, (planMap.get(name) || 0) + order.amount);
  }
  const colors = ['#3b82f6', '#8b5cf6', '#10b981', '#f59e0b', '#ef4444'];
  let ci = 0;
  for (const [name, amount] of planMap) {
    byPlan.push({ label: name, value: amount, color: colors[ci % colors.length] });
    ci++;
  }

  const statusDist = [
    { label: '已支付', value: summary.paid_orders, color: '#10b981' },
    { label: '已取消', value: summary.cancelled_orders, color: '#ef4444' },
    { label: '已过期', value: summary.expired_orders, color: '#f59e0b' },
  ];

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold text-slate-900">收入看板</h1>
        <button
          disabled={busy}
          onClick={() => void run(loadAll)}
          className="rounded-2xl border border-[#d7e3f4] bg-white px-4 py-2 text-sm font-medium text-slate-700 transition hover:bg-[#eff6ff] disabled:cursor-not-allowed disabled:opacity-50"
        >
          {busy ? '刷新中…' : '刷新数据'}
        </button>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <MetricCard
          label="总收入"
          value={`¥${formatMoney(summary.total_revenue)}`}
          sublabel={`共 ${summary.paid_orders} 笔已支付订单`}
        />
        <MetricCard
          label="本月收入"
          value={`¥${formatMoney(summary.monthly_revenue)}`}
          sublabel={`${summary.monthly_paid_orders} 笔订单`}
        />
        <MetricCard
          label="本月订单"
          value={`${summary.monthly_orders}`}
          sublabel={`${summary.monthly_paid_orders} 已支付 · ${summary.monthly_orders - summary.monthly_paid_orders} 未支付`}
        />
        <MetricCard
          label="支付转化率"
          value={`${summary.conversion_rate}%`}
          sublabel={`活跃订阅 ${summary.active_subscriptions} · 新付费 ${summary.monthly_new_users}`}
          trend={summary.conversion_rate >= 50 ? '良好' : '偏低'}
          trendUp={summary.conversion_rate >= 50}
        />
      </div>

      <SectionCard title="月度收入趋势">
        {monthly.length > 0 ? (
          <BarChart data={barData} />
        ) : (
          <div className="py-6 text-center text-sm text-slate-500">暂无月度数据</div>
        )}
      </SectionCard>

      <div className="grid gap-5 md:grid-cols-2">
        <SectionCard title="套餐收入分布">
          {byPlan.length > 0 ? <DistributionBar items={byPlan} /> : <div className="py-4 text-center text-sm text-slate-500">暂无数据</div>}
        </SectionCard>
        <SectionCard title="订单状态分布">
          <DistributionBar items={statusDist} />
        </SectionCard>
      </div>

      <SectionCard title="最近收入订单">
        {recentOrders.length > 0 ? (
          <div className="overflow-hidden rounded-2xl border border-[#e5edf8]">
            <table className="w-full text-left text-sm">
              <thead className="bg-[#f8fbff] text-slate-500">
                <tr>
                  <th className="px-3 py-3 font-medium">订单号</th>
                  <th className="px-3 py-3 font-medium">用户</th>
                  <th className="px-3 py-3 font-medium">金额</th>
                  <th className="px-3 py-3 font-medium">周期</th>
                  <th className="px-3 py-3 font-medium">支付方式</th>
                  <th className="px-3 py-3 font-medium">支付时间</th>
                </tr>
              </thead>
              <tbody>
                {recentOrders.map((order) => (
                  <tr key={order.order_no} className="border-t border-[#e5edf8]">
                    <td className="px-3 py-3 font-medium text-slate-900">{order.order_no}</td>
                    <td className="px-3 py-3">
                      <div>#{order.user_id}</div>
                      <div className="text-xs text-slate-500">{order.user_name || '-'}</div>
                    </td>
                    <td className="px-3 py-3">{order.currency} {formatMoney(order.amount)}</td>
                    <td className="px-3 py-3">{order.billing_cycle === 'yearly' ? '年付' : '月付'}</td>
                    <td className="px-3 py-3">{order.payment_method || '-'}</td>
                    <td className="px-3 py-3">{formatDateTime(order.paid_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="py-6 text-center text-sm text-slate-500">暂无已支付订单</div>
        )}
      </SectionCard>
    </div>
  );
}
