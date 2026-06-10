# 管理员收入看板实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 LoreVista 管理后台新增「收入看板」独立页面，以概览卡片+月度趋势图+分布图+订单表的方式可视化收入数据。

**Architecture:** 
- 后端新增 2 个聚合查询 API 端点，直接对 `BillingOrder` 表做 SQLAlchemy ORM 聚合（`GROUP BY` + `func.sum` + `func.count`）
- 前端新增独立组件 `RevenueDashboard.tsx`，纯 CSS 图表（零依赖），通过 `App.tsx` 导航集成
- 遵循现有单文件路由风格，不引入新依赖

**Tech Stack:** Python FastAPI + SQLAlchemy 2.0 / React 19 + TypeScript + Tailwind v4 + Lucide icons

---

### Task 1: 后端收入汇总 API

**Files:**
- Modify: `backend/main.py`
  - Line 49: 添加 `case, and_` 到现有 `from sqlalchemy import` 导入
  - After line 4574: 添加 `/api/admin/revenue/summary` 和 `/api/admin/revenue/monthly` 路由

- [ ] **Step 1: 修改 SQLAlchemy 导入**

将 `backend/main.py:49`:
```python
from sqlalchemy import func
```
改为：
```python
from sqlalchemy import case, func, and_
```

- [ ] **Step 2: 添加收入汇总路由**

在 `backend/main.py` 的 `admin_update_order_status` 路由之后（line 4574 之后，`@app.post("/api/stories")` 之前），添加：

```python
@app.get("/api/admin/revenue/summary")
def admin_revenue_summary(request: Request, db: Session = Depends(get_db)):
    _require_admin(request, db)
    now = _utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # 全局聚合
    total = db.query(
        func.count(BillingOrder.id).label("total_orders"),
        func.coalesce(func.sum(case((BillingOrder.status == "paid", BillingOrder.amount), else_=0)), 0).label("total_revenue"),
        func.count(case((BillingOrder.status == "paid", 1))).label("paid_orders"),
        func.count(case((BillingOrder.status == "cancelled", 1))).label("cancelled_orders"),
        func.count(case((BillingOrder.status == "expired", 1))).label("expired_orders"),
    ).first()

    # 本月聚合
    monthly = db.query(
        func.count(BillingOrder.id).label("monthly_orders"),
        func.count(case((BillingOrder.status == "paid", 1))).label("monthly_paid_orders"),
        func.coalesce(func.sum(case(
            (and_(BillingOrder.status == "paid", BillingOrder.paid_at >= month_start), BillingOrder.amount),
            else_=0
        )), 0).label("monthly_revenue"),
        func.count(func.distinct(case(
            (and_(BillingOrder.status == "paid", BillingOrder.paid_at >= month_start), BillingOrder.user_id),
        ))).label("monthly_new_users"),
    ).filter(
        BillingOrder.created_at >= month_start
    ).first()

    # 活跃订阅数
    active_subs = db.query(func.count(UserSubscription.id)).filter(
        UserSubscription.status == "active"
    ).scalar() or 0

    monthly_orders = monthly.monthly_orders or 0
    monthly_paid = monthly.monthly_paid_orders or 0
    conversion_rate = round(monthly_paid / monthly_orders * 100, 1) if monthly_orders > 0 else 0.0

    return {
        "total_revenue": float(total.total_revenue or 0),
        "total_orders": total.total_orders or 0,
        "paid_orders": total.paid_orders or 0,
        "cancelled_orders": total.cancelled_orders or 0,
        "expired_orders": total.expired_orders or 0,
        "monthly_revenue": float(monthly.monthly_revenue or 0),
        "monthly_orders": monthly_orders,
        "monthly_paid_orders": monthly_paid,
        "conversion_rate": conversion_rate,
        "active_subscriptions": active_subs,
        "monthly_new_users": monthly.monthly_new_users or 0,
    }
```

- [ ] **Step 3: 添加月度趋势路由**

在收入汇总路由之后，添加：

```python
@app.get("/api/admin/revenue/monthly")
def admin_revenue_monthly(months: int = 12, request: Request = None, db: Session = Depends(get_db)):
    _require_admin(request, db)
    now = _utcnow()
    start_date = now - datetime.timedelta(days=months * 31)

    rows = db.query(
        func.date_trunc("month", BillingOrder.created_at).label("month"),
        func.coalesce(func.sum(case((BillingOrder.status == "paid", BillingOrder.amount), else_=0)), 0).label("revenue"),
        func.count(BillingOrder.id).label("orders"),
        func.count(case((BillingOrder.status == "paid", 1))).label("paid"),
        func.count(case((BillingOrder.status == "cancelled", 1))).label("cancelled"),
        func.count(case((BillingOrder.status == "expired", 1))).label("expired"),
    ).filter(
        BillingOrder.created_at >= start_date
    ).group_by("month").order_by("month").all()

    return [
        {
            "period": row.month.strftime("%Y-%m"),
            "revenue": float(row.revenue),
            "orders": row.orders,
            "paid": row.paid,
            "cancelled": row.cancelled,
            "expired": row.expired,
        }
        for row in rows
    ]
```

- [ ] **Step 4: 验证后端语法**

Run: `python -c "import ast; ast.parse(open('backend/main.py').read()); print('Syntax OK')"`
Expected: `Syntax OK`

- [ ] **Step 5: Commit**

```bash
git add backend/main.py
git commit -m "feat: add admin revenue summary and monthly trend APIs"
```

---

### Task 2: 前端 API 类型与函数

**Files:**
- Modify: `frontend/src/api.ts`
  - After `AdminOrderItem` interface (line 618): 添加 `AdminRevenueSummary` 和 `AdminRevenueMonthlyItem` 类型
  - After `updateAdminOrderStatus` function (line 1030): 添加 `getAdminRevenueSummary` 和 `getAdminRevenueMonthly` 函数

- [ ] **Step 1: 添加类型定义**

在 `api.ts` 的 `AdminOrderItem` 接口之后（line 618 之后）、`AdminAuditLogItem` 之前（line 620 之前），插入：

```typescript
export interface AdminRevenueSummary {
  total_revenue: number;
  total_orders: number;
  paid_orders: number;
  cancelled_orders: number;
  expired_orders: number;
  monthly_revenue: number;
  monthly_orders: number;
  monthly_paid_orders: number;
  conversion_rate: number;
  active_subscriptions: number;
  monthly_new_users: number;
}

export interface AdminRevenueMonthlyItem {
  period: string;
  revenue: number;
  orders: number;
  paid: number;
  cancelled: number;
  expired: number;
}
```

- [ ] **Step 2: 添加 API 函数**

在 `api.ts` 的 `updateAdminOrderStatus` 函数之后（line 1030 之后）、`getAdminAuditLogs` 之前（line 1032 之前），插入：

```typescript
export async function getAdminRevenueSummary(): Promise<AdminRevenueSummary> {
  const res = await fetch(`${BASE}/api/admin/revenue/summary`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getAdminRevenueMonthly(months = 12): Promise<AdminRevenueMonthlyItem[]> {
  const res = await fetch(`${BASE}/api/admin/revenue/monthly?months=${months}`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api.ts
git commit -m "feat: add revenue API types and functions"
```

---

### Task 3: 前端收入看板组件

**Files:**
- Create: `frontend/src/components/admin/RevenueDashboard.tsx`
- Modify: `frontend/src/components/admin/AdminPages.tsx` — 在文件末尾，`AdminSystemPromptsPage` 导出之后，添加 `AdminRevenueDashboardPage` 导出

- [ ] **Step 1: 创建 RevenueDashboard.tsx**

创建新文件 `frontend/src/components/admin/RevenueDashboard.tsx`：

```typescript
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

function orderStatusLabel(status: string) {
  if (status === 'pending') return '待支付';
  if (status === 'paid') return '已支付';
  if (status === 'cancelled') return '已取消';
  if (status === 'expired') return '已过期';
  return status;
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
  // From recent paid orders, aggregate by plan_name
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
      {/* 标题 + 刷新 */}
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

      {/* 概览卡片 */}
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

      {/* 月度趋势 */}
      <SectionCard title="月度收入趋势">
        {monthly.length > 0 ? (
          <BarChart data={barData} />
        ) : (
          <div className="py-6 text-center text-sm text-slate-500">暂无月度数据</div>
        )}
      </SectionCard>

      {/* 分布图 */}
      <div className="grid gap-5 md:grid-cols-2">
        <SectionCard title="套餐收入分布">
          {byPlan.length > 0 ? <DistributionBar items={byPlan} /> : <div className="py-4 text-center text-sm text-slate-500">暂无数据</div>}
        </SectionCard>
        <SectionCard title="订单状态分布">
          <DistributionBar items={statusDist} />
        </SectionCard>
      </div>

      {/* 最近已支付订单 */}
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
```

- [ ] **Step 2: 在 AdminPages.tsx 中导出新组件**

在 `AdminPages.tsx` 末尾（`AdminSystemPromptsPage` 之后），添加：

```typescript
export { AdminRevenueDashboardPage } from './RevenueDashboard';
```

- [ ] **Step 3: Verify TypeScript compilation**

Run: `npx tsc --noEmit`
Expected: No type errors

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/admin/RevenueDashboard.tsx frontend/src/components/admin/AdminPages.tsx
git commit -m "feat: add revenue dashboard component"
```

---

### Task 4: 导航集成（App.tsx）

**Files:**
- Modify: `frontend/src/App.tsx`
  - import 区域: 添加 `AdminRevenueDashboardPage` 导入
  - `RouteKey`: 添加 `'revenue'`
  - `ADMIN_NAV`: 添加收入看板导航项（放在 `orders` 之前）
  - 条件渲染区域: 添加 `route === 'revenue'` 渲染

- [ ] **Step 1: 添加导入**

在 `App.tsx` 的 Admin 组件导入中（line 25-33），添加 `AdminRevenueDashboardPage`：

```typescript
import {
  AdminAnnouncementPage,
  AdminAuditLogsPage,
  AdminOrdersPage,
  AdminPlanManagementPage,
  AdminPlatformSettingsPage,
  AdminRevenueDashboardPage,
  AdminSystemPromptsPage,
  AdminUserManagementPage,
} from './components/admin/AdminPages';
```

- [ ] **Step 2: 添加 RouteKey**

在 `RouteKey` 联合类型中（line 82-101），添加 `'revenue'`：

```typescript
type RouteKey =
  | 'landing'
  | 'login'
  | 'register'
  | 'pricing'
  | 'stories'
  | 'onboarding'
  | 'import-guidance'
  | 'workspace'
  | 'account'
  | 'templates'
  | 'template-review'
  | 'forgot-password'
  | 'plan-config'
  | 'quota-rules'
  | 'entitlements'
  | 'orders'
  | 'revenue'
  | 'audit-logs'
  | 'announcement'
  | 'system-prompts';
```

- [ ] **Step 3: 添加导航菜单项**

在 `ADMIN_NAV` 数组（line 121-130）中，在 `orders` 之前添加 revenue 项，并更新后续索引标签覆盖：

```typescript
const ADMIN_NAV: NavItem[] = [
  { key: 'plan-config', label: '套餐配置', icon: Settings2 },
  { key: 'quota-rules', label: '配额规则', icon: Gauge },
  { key: 'entitlements', label: '用户权益', icon: ShieldCheck },
  { key: 'revenue', label: '收入看板', icon: BarChart3 },
  { key: 'orders', label: '订单订阅', icon: ScrollText },
  { key: 'audit-logs', label: '操作审计', icon: MessageSquareQuote },
  { key: 'announcement', label: '公告管理', icon: MessageSquareQuote },
  { key: 'template-review', label: '模板审核', icon: Library },
  { key: 'system-prompts', label: '系统提示词', icon: MessageSquareQuote },
];

ADMIN_NAV[0].label = '套餐管理';
ADMIN_NAV[1].label = '平台配置';
ADMIN_NAV[2].label = '用户管理';
ADMIN_NAV[3].label = '收入看板';
ADMIN_NAV[4].label = '订单中心';
ADMIN_NAV[5].label = '操作审计';
ADMIN_NAV[6].label = '公告管理';
ADMIN_NAV[7].label = '模板审核';
ADMIN_NAV[8].label = '系统提示词';
```

同时确保 `App.tsx` 顶部导入 `BarChart3` from `lucide-react`（检查 lucide-react 导入中是否已包含，如果不包含则添加）。

- [ ] **Step 4: 添加条件渲染**

在 `App.tsx` 的条件渲染区域（line 777 的 `orders` 路由之前），添加：

```tsx
{route === 'revenue' && session.role === 'admin' && <AdminRevenueDashboardPage onError={(message) => toast.error(message)} />}
```

- [ ] **Step 5: Verify TypeScript compilation**

Run: `npx tsc --noEmit`
Expected: No type errors

- [ ] **Step 6: Commit**

```bash
git add frontend/src/App.tsx
git commit -m "feat: add revenue dashboard navigation and routing"
```
