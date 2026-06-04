import { useEffect, useState } from 'react';
import {
  getAdminRevenueSummary,
  getAdminRevenueMonthly,
  getAdminOrders,
  searchAdminOrders,
  updateAdminOrderStatus,
  type AdminRevenueSummary,
  type AdminRevenueMonthlyItem,
  type AdminOrderItem,
  type AdminOrderSearchParams,
  type AdminOrderSearchResult,
} from '../../api';
import { formatMoney } from './AdminPages';
import { toast } from '../../lib/toast';

function cn(...parts: Array<string | false | null | undefined>) {
  return parts.filter(Boolean).join(' ');
}

function formatDateTime(value: string | null | undefined) {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString('zh-CN');
}

function orderStatusLabel(status: string) {
  if (status === 'pending') return '待支付';
  if (status === 'paid') return '已支付';
  if (status === 'cancelled') return '已取消';
  if (status === 'expired') return '已过期';
  return status;
}

function orderStatusColor(status: string): string {
  switch (status) {
    case 'paid': return 'bg-emerald-100 text-emerald-700';
    case 'pending': return 'bg-amber-100 text-amber-700';
    case 'cancelled': return 'bg-red-100 text-red-700';
    case 'expired': return 'bg-orange-100 text-orange-700';
    default: return 'bg-slate-100 text-slate-600';
  }
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

function BarChart({ data }: { data: { label: string; value: number }[] }) {
  const [hovered, setHovered] = useState<number | null>(null);
  const n = data.length;
  const gap = n > 8 ? 3 : 6;
  const barPct = n > 1 ? Math.min(80, (100 - gap * (n - 1)) / n) : 100;
  const max = Math.max(...data.map((d) => d.value), 1);

  return (
    <div className="flex items-end justify-center" style={{ height: 160, gap: `${gap}px` }}>
      {data.map((item, i) => {
        const h = max > 0 ? (item.value / max) * 140 : 0;
        return (
          <div
            key={item.label}
            className="relative flex flex-col items-center gap-1"
            style={{ width: `${barPct}%`, minWidth: 6, maxWidth: n > 8 ? 40 : 64 }}
            onMouseEnter={() => setHovered(i)}
            onMouseLeave={() => setHovered(null)}
          >
            {hovered === i ? (
              <div className="absolute bottom-full z-10 mb-1.5 whitespace-nowrap rounded-lg bg-slate-800 px-2.5 py-1.5 text-center text-xs text-white shadow-lg">
                <div className="font-semibold text-blue-300">¥{formatMoney(item.value)}</div>
                <div className="text-white/70">{item.label}</div>
              </div>
            ) : null}
            <div
              className="w-full rounded-t-md transition-all duration-300"
              style={{
                height: Math.max(h, 2),
                backgroundColor: hovered === i ? '#2563eb' : '#3b82f6',
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

  const [searchResult, setSearchResult] = useState<AdminOrderSearchResult | null>(null);
  const [searchFilters, setSearchFilters] = useState<AdminOrderSearchParams>({ page: 1, page_size: 20, status: '' });
  const [datePreset, setDatePreset] = useState('all');
  const [actingOrderNo, setActingOrderNo] = useState<string | null>(null);
  const [loadingOrders, setLoadingOrders] = useState(false);
  const [monthRange, setMonthRange] = useState(12);

  function getDateRange(preset: string): { start?: string; end?: string } {
    const now = new Date();
    switch (preset) {
      case '7d': {
        const d = new Date(now); d.setDate(d.getDate() - 7);
        return { start: d.toISOString().slice(0, 10), end: now.toISOString().slice(0, 10) };
      }
      case '30d': {
        const d = new Date(now); d.setDate(d.getDate() - 30);
        return { start: d.toISOString().slice(0, 10), end: now.toISOString().slice(0, 10) };
      }
      case '90d': {
        const d = new Date(now); d.setDate(d.getDate() - 90);
        return { start: d.toISOString().slice(0, 10), end: now.toISOString().slice(0, 10) };
      }
      case '1y': {
        const d = new Date(now); d.setFullYear(d.getFullYear() - 1);
        return { start: d.toISOString().slice(0, 10), end: now.toISOString().slice(0, 10) };
      }
      default: return {};
    }
  }

  function applyFilters(overrides: Partial<AdminOrderSearchParams & { _datePreset?: string }>) {
    const newStatus = overrides.status !== undefined ? overrides.status : searchFilters.status;
    if (overrides._datePreset !== undefined) setDatePreset(overrides._datePreset);
    const newPage = (overrides.status !== undefined || overrides._datePreset !== undefined) ? 1 : (overrides.page ?? searchFilters.page);
    setSearchFilters(prev => ({ ...prev, status: newStatus, page: newPage }));
  }

  async function loadSearchOrders(filters: AdminOrderSearchParams, dp: string) {
    setLoadingOrders(true);
    try {
      const params: AdminOrderSearchParams = { ...filters };
      const dr = getDateRange(dp);
      if (dr.start) params.start_date = dr.start;
      if (dr.end) params.end_date = dr.end;
      const result = await searchAdminOrders(params);
      setSearchResult(result);
    } catch (error: any) {
      onError(error?.message || '加载订单失败');
    } finally {
      setLoadingOrders(false);
    }
  }

  async function handleOrderStatus(orderNo: string, status: 'paid' | 'cancelled' | 'expired') {
    setActingOrderNo(orderNo);
    try {
      await updateAdminOrderStatus(orderNo, status);
      toast.success('订单状态已更新');
      await loadSearchOrders(searchFilters, datePreset);
    } catch (error: any) {
      onError(error?.message || '订单状态更新失败');
    } finally {
      setActingOrderNo(null);
    }
  }

  async function loadAll(range?: number) {
    const months = range ?? monthRange;
    const [s, m, o] = await Promise.all([
      getAdminRevenueSummary(),
      getAdminRevenueMonthly(months),
      getAdminOrders(),
    ]);
    setSummary(s);
    setMonthly(m);
    setRecentOrders(o.filter((ord) => ord.status === 'paid').slice(0, 20));

    await loadSearchOrders({ page: 1, page_size: 20, status: '' }, 'all');
  }

  function handleMonthRangeChange(range: number) {
    setMonthRange(range);
    void run(() => loadAll(range));
  }

  useEffect(() => {
    void run(loadAll);
  }, []);

  useEffect(() => {
    if (summary) {
      void loadSearchOrders(searchFilters, datePreset);
    }
  }, [searchFilters.page, searchFilters.status, searchFilters.page_size, datePreset]);

  if (!summary) {
    return (
      <SectionCard title="收入看板">
        <div className="py-8 text-center text-sm text-slate-500">加载中…</div>
      </SectionCard>
    );
  }

  function fillMissingMonths(data: AdminRevenueMonthlyItem[], count: number) {
    const map = new Map(data.map((m) => [m.period, m.revenue]));
    const result: { label: string; value: number }[] = [];
    const now = new Date();
    for (let i = count - 1; i >= 0; i--) {
      const d = new Date(now.getFullYear(), now.getMonth() - i, 1);
      const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
      result.push({ label: key.slice(5), value: map.get(key) ?? 0 });
    }
    return result;
  }

  const barData = fillMissingMonths(monthly, monthRange);

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
        <div className="mb-4 flex items-center gap-2">
          {[6, 12].map((n) => (
            <button
              key={n}
              onClick={() => handleMonthRangeChange(n)}
              className={`rounded-2xl px-3 py-1.5 text-sm font-medium transition ${
                monthRange === n
                  ? 'bg-[#3b82f6] text-white'
                  : 'border border-[#d7e3f4] bg-white text-slate-600 hover:bg-[#eff6ff]'
              }`}
            >
              近{n}个月
            </button>
          ))}
        </div>
        <BarChart data={barData} />
      </SectionCard>

      <div className="grid gap-5 md:grid-cols-2">
        <SectionCard title="套餐收入分布">
          {byPlan.length > 0 ? <DistributionBar items={byPlan} /> : <div className="py-4 text-center text-sm text-slate-500">暂无数据</div>}
        </SectionCard>
        <SectionCard title="订单状态分布">
          <DistributionBar items={statusDist} />
        </SectionCard>
      </div>

      <SectionCard title="订单管理">
        {/* 筛选栏 */}
        <div className="mb-4 flex flex-wrap items-center gap-3">
          <select
            value={searchFilters.status || ''}
            onChange={(e) => applyFilters({ status: e.target.value })}
            className="rounded-2xl border border-[#d7e3f4] bg-white px-3 py-2 text-sm outline-none focus:border-[#60a5fa]"
          >
            <option value="">全部状态</option>
            <option value="pending">待支付</option>
            <option value="paid">已支付</option>
            <option value="cancelled">已取消</option>
            <option value="expired">已过期</option>
          </select>

          {[
            { value: 'all', label: '全部时间' },
            { value: '7d', label: '近7天' },
            { value: '30d', label: '近30天' },
            { value: '90d', label: '近90天' },
            { value: '1y', label: '近1年' },
          ].map((opt) => (
            <button
              key={opt.value}
              onClick={() => applyFilters({ _datePreset: opt.value })}
              className={`rounded-2xl px-3 py-2 text-sm font-medium transition ${
                datePreset === opt.value
                  ? 'bg-[#3b82f6] text-white'
                  : 'border border-[#d7e3f4] bg-white text-slate-600 hover:bg-[#eff6ff]'
              }`}
            >
              {opt.label}
            </button>
          ))}

          <button
            disabled={loadingOrders}
            onClick={() => void loadSearchOrders(searchFilters, datePreset)}
            className="ml-auto rounded-2xl border border-[#d7e3f4] bg-white px-4 py-2 text-sm font-medium text-slate-700 transition hover:bg-[#eff6ff] disabled:cursor-not-allowed disabled:opacity-50"
          >
            {loadingOrders ? '加载中…' : '刷新'}
          </button>
        </div>

        {/* 订单表格 */}
        <div className="overflow-hidden rounded-2xl border border-[#e5edf8]">
          <table className="w-full text-left text-sm">
            <thead className="bg-[#f8fbff] text-slate-500">
              <tr>
                <th className="px-3 py-3 font-medium">订单号</th>
                <th className="px-3 py-3 font-medium">用户</th>
                <th className="px-3 py-3 font-medium">金额</th>
                <th className="px-3 py-3 font-medium">状态</th>
                <th className="px-3 py-3 font-medium">来源</th>
                <th className="px-3 py-3 font-medium">创建时间</th>
                <th className="px-3 py-3 font-medium">操作</th>
              </tr>
            </thead>
            <tbody>
              {(searchResult?.items ?? []).map((order) => (
                <tr key={order.order_no} className="border-t border-[#e5edf8]">
                  <td className="px-3 py-3 font-medium text-slate-900">{order.order_no}</td>
                  <td className="px-3 py-3">
                    <div>#{order.user_id}</div>
                    <div className="text-xs text-slate-500">{order.user_name || '-'}</div>
                  </td>
                  <td className="px-3 py-3">{order.currency} {formatMoney(order.amount)}</td>
                  <td className="px-3 py-3">
                    <span className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-medium ${orderStatusColor(order.status)}`}>
                      {orderStatusLabel(order.status)}
                    </span>
                  </td>
                  <td className="px-3 py-3">{order.source || '-'}</td>
                  <td className="px-3 py-3">
                    <div>{formatDateTime(order.created_at)}</div>
                    <div className="text-xs text-slate-500">失效：{formatDateTime(order.expired_at)}</div>
                  </td>
                  <td className="px-3 py-3">
                    <div className="flex flex-wrap gap-2">
                      <button
                        disabled={actingOrderNo === order.order_no || order.status === 'paid'}
                        onClick={() => void handleOrderStatus(order.order_no, 'paid')}
                        className="rounded-xl border border-[#d7e3f4] bg-white px-3 py-1.5 text-xs font-medium text-slate-700 transition hover:bg-[#eff6ff] disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        标记已支付
                      </button>
                      <button
                        disabled={actingOrderNo === order.order_no || order.status === 'cancelled'}
                        onClick={() => void handleOrderStatus(order.order_no, 'cancelled')}
                        className="rounded-xl border border-[#d7e3f4] bg-white px-3 py-1.5 text-xs font-medium text-slate-700 transition hover:bg-[#eff6ff] disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        取消
                      </button>
                      <button
                        disabled={actingOrderNo === order.order_no || order.status === 'expired'}
                        onClick={() => void handleOrderStatus(order.order_no, 'expired')}
                        className="rounded-xl border border-[#d7e3f4] bg-white px-3 py-1.5 text-xs font-medium text-slate-700 transition hover:bg-[#eff6ff] disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        过期
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
              {(!searchResult || searchResult.items.length === 0) ? (
                <tr>
                  <td colSpan={7} className="px-3 py-8 text-center text-sm text-slate-500">
                    暂无匹配订单
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>

        {/* 分页 */}
        {searchResult && searchResult.total_pages > 1 ? (
          <div className="mt-4 flex items-center justify-between text-sm text-slate-600">
            <span>共 {searchResult.total} 条</span>
            <div className="flex items-center gap-2">
              <button
                disabled={searchResult.page <= 1 || loadingOrders}
                onClick={() => setSearchFilters(prev => ({ ...prev, page: prev.page! - 1 }))}
                className="rounded-2xl border border-[#d7e3f4] bg-white px-3 py-1.5 text-sm transition hover:bg-[#eff6ff] disabled:cursor-not-allowed disabled:opacity-50"
              >
                上一页
              </button>
              <span className="px-2">第 {searchResult.page} / {searchResult.total_pages} 页</span>
              <button
                disabled={searchResult.page >= searchResult.total_pages || loadingOrders}
                onClick={() => setSearchFilters(prev => ({ ...prev, page: prev.page! + 1 }))}
                className="rounded-2xl border border-[#d7e3f4] bg-white px-3 py-1.5 text-sm transition hover:bg-[#eff6ff] disabled:cursor-not-allowed disabled:opacity-50"
              >
                下一页
              </button>
            </div>
          </div>
        ) : null}
      </SectionCard>
    </div>
  );
}
