# 收入看板合并订单管理 — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task.

**目标:** 将独立订单中心合并到收入看板底部，实现筛选、分页、状态操作一体化

**架构:**
- 后端新增分页查询接口 GET /api/admin/orders/search，支持 status/date_range/page/page_size
- RevenueDashboard 底部扩展为完整订单管理区（筛选栏 + 分页表格 + 状态操作按钮）
- 删除独立 AdminOrdersPage 组件及相关路由

**Tech Stack:** FastAPI / SQLAlchemy 2.0 / React 19 / TypeScript / Tailwind v4

---

### Task 1: 后端分页订单搜索 API

**Files:**
- Modify: `backend/main.py` — 新增路由 + 查询函数
- Test: 无（沿用已有测试模式，手动验证）

- [ ] **Step 1: 在 main.py 的 admin 路由区域新增 `/api/admin/orders/search`**

在 `admin_orders` 路由（line 4538）之后、`admin_update_order_status`（line 4547）之前，插入新路由：

```python
@app.get("/api/admin/orders/search")
def admin_orders_search(
    request: Request,
    page: int = 1,
    page_size: int = 20,
    status: str = "",
    start_date: str = "",
    end_date: str = "",
    db: Session = Depends(get_db),
):
    _require_admin(request, db)
    page = max(1, page)
    page_size = max(1, min(100, page_size))

    query = db.query(BillingOrder)
    if status and status.strip():
        query = query.filter(BillingOrder.status == status.strip())
    if start_date:
        try:
            sd = datetime.strptime(start_date, "%Y-%m-%d")
            query = query.filter(BillingOrder.created_at >= sd)
        except ValueError:
            pass
    if end_date:
        try:
            ed = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
            query = query.filter(BillingOrder.created_at < ed)
        except ValueError:
            pass

    total = query.count()
    total_pages = max(1, (total + page_size - 1) // page_size)
    orders = query.order_by(BillingOrder.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()

    for order in orders:
        _sync_order_status(order, db)

    return {
        "items": [_serialize_order_with_db(order, db) for order in orders],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }
```

确保文件顶部已有 `from datetime import datetime, timedelta`（检查 main.py 的 import 区）。

- [ ] **Step 2: 验证语法正确**

Run: `python -c "import main"` — 应无 import 错误

- [ ] **Step 3: Commit**

```bash
git add backend/main.py
git commit -m "feat: add paginated admin orders search API with status/date filtering"
```

---

### Task 2: 前端分页订单类型和 API 函数

**Files:**
- Modify: `frontend/src/api.ts` — 新增类型 + 接口函数

- [ ] **Step 1: 在 AdminOrderItem 接口之后新增分页类型**

在 `frontend/src/api.ts` 中 `AdminRevenueMonthlyItem` 之前（line 634 之前），插入：

```typescript
export interface AdminOrderSearchParams {
  page?: number;
  page_size?: number;
  status?: string;
  start_date?: string;
  end_date?: string;
}

export interface AdminOrderSearchResult {
  items: AdminOrderItem[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}
```

- [ ] **Step 2: 新增 searchAdminOrders API 函数**

在 `getAdminOrders`（line 1035-1038）之后，插入：

```typescript
export async function searchAdminOrders(
  params: AdminOrderSearchParams
): Promise<AdminOrderSearchResult> {
  const search = new URLSearchParams();
  if (params.page) search.set('page', String(params.page));
  if (params.page_size) search.set('page_size', String(params.page_size));
  if (params.status) search.set('status', params.status);
  if (params.start_date) search.set('start_date', params.start_date);
  if (params.end_date) search.set('end_date', params.end_date);
  const qs = search.toString();
  const res = await fetch(`${BASE}/api/admin/orders/search${qs ? '?' + qs : ''}`, {
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}
```

- [ ] **Step 3: 验证 TypeScript**

Run: `npx tsc --noEmit` — 应无错误

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api.ts
git commit -m "feat: add AdminOrderSearchParams/Result types and searchAdminOrders API"
```

---

### Task 3: RevenueDashboard 底部订单管理区

**Files:**
- Modify: `frontend/src/components/admin/RevenueDashboard.tsx` — 底部新增筛选+分页+操作

- [ ] **Step 1: 在 RevenueDashboard.tsx 中增强 import**

在文件顶部 import 区域，添加新导入：

```typescript
import { useEffect, useState, useCallback } from 'react';
// 已有 import 保留，追加以下:
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
import { formatMoney, orderStatusLabel } from './AdminPages';
import { toast } from '../../lib/toast';
```

- [ ] **Step 2: 新增 orderStatusColor 工具函数**

在 `formatDateTime` 函数之后添加：

```typescript
function orderStatusColor(status: string): string {
  switch (status) {
    case 'paid': return 'bg-emerald-100 text-emerald-700';
    case 'pending': return 'bg-amber-100 text-amber-700';
    case 'cancelled': return 'bg-red-100 text-red-700';
    case 'expired': return 'bg-orange-100 text-orange-700';
    default: return 'bg-slate-100 text-slate-600';
  }
}
```

- [ ] **Step 3: 替换底部「最近收入订单」Section 为完整订单管理区**

定位文件中 `SectionCard title="最近收入订单"` 部分（line 244-278），替换为完整的订单管理区域代码。关键逻辑：

```tsx
// 新增状态管理
const [searchResult, setSearchResult] = useState<AdminOrderSearchResult | null>(null);
const [searchFilters, setSearchFilters] = useState<AdminOrderSearchParams>({
  page: 1,
  page_size: 20,
  status: '',
});
const [datePreset, setDatePreset] = useState<string>('all');
const [actingOrderNo, setActingOrderNo] = useState<string | null>(null);
const [loadingOrders, setLoadingOrders] = useState(false);

// 计算日期范围
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

// 加载订单
async function loadOrders() {
  setLoadingOrders(true);
  try {
    const params: AdminOrderSearchParams = { ...searchFilters };
    const dr = getDateRange(datePreset);
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

// 筛选条件变化
function handleFilterChange(updates: Partial<AdminOrderSearchParams & { datePreset?: string }>) {
  if (updates.datePreset !== undefined) {
    setDatePreset(updates.datePreset);
  }
  if (updates.status !== undefined || updates.datePreset !== undefined) {
    setSearchFilters(prev => ({ ...prev, ...updates, page: 1 }));
  } else {
    setSearchFilters(prev => ({ ...prev, ...updates }));
  }
}

// 状态操作
async function handleOrderStatus(orderNo: string, status: 'paid' | 'cancelled' | 'expired') {
  setActingOrderNo(orderNo);
  try {
    await updateAdminOrderStatus(orderNo, status);
    toast.success('订单状态已更新');
    await loadOrders();
  } catch (error: any) {
    onError(error?.message || '订单状态更新失败');
  } finally {
    setActingOrderNo(null);
  }
}

// 监听筛选条件变化触发加载
useEffect(() => {
  const params: AdminOrderSearchParams = { ...searchFilters };
  const dr = getDateRange(datePreset);
  if (dr.start) params.start_date = dr.start;
  if (dr.end) params.end_date = dr.end;
  setLoadingOrders(true);
  searchAdminOrders(params)
    .then(setSearchResult)
    .catch((e) => onError(e?.message || '加载订单失败'))
    .finally(() => setLoadingOrders(false));
}, [searchFilters.page, searchFilters.status, searchFilters.page_size, datePreset]);
```

然后替换底部 SectionCard 的 JSX 为：

```tsx
<SectionCard title="订单管理">
  {/* 筛选栏 */}
  <div className="mb-4 flex flex-wrap items-center gap-3">
    <select
      value={searchFilters.status || ''}
      onChange={(e) => handleFilterChange({ status: e.target.value })}
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
        onClick={() => handleFilterChange({ datePreset: opt.value })}
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
      onClick={() => void loadOrders()}
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
```

- [ ] **Step 2: 更新 loadAll 函数，首次加载时同时获取订单分页数据**

在 `loadAll` 中追加订单搜索：

```typescript
async function loadAll() {
  const [s, m, o] = await Promise.all([
    getAdminRevenueSummary(),
    getAdminRevenueMonthly(12),
    getAdminOrders(),
  ]);
  setSummary(s);
  setMonthly(m);
  setRecentOrders(o.filter((ord) => ord.status === 'paid').slice(0, 20));

  // 同时加载分页订单
  const initialResult = await searchAdminOrders({ page: 1, page_size: 20 });
  setSearchResult(initialResult);
}
```

- [ ] **Step 3: 验证 TypeScript**

Run: `npx tsc --noEmit` — 应无错误

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/admin/RevenueDashboard.tsx
git commit -m "feat: add order management section to revenue dashboard with filtering, pagination, status operations"
```

---

### Task 4: 路由/导航调整，删除独立订单中心

**Files:**
- Modify: `frontend/src/components/admin/AdminPages.tsx` — 删除 AdminOrdersPage 组件 + 导出 `orderStatusLabel`
- Modify: `frontend/src/App.tsx` — 删除 AdminOrdersPage import/渲染 + 移除 nav 条目

- [ ] **Step 1: 删除 AdminPages.tsx 中的 AdminOrdersPage 组件**

定位 `export function AdminOrdersPage`（line 1439-1544），整段删除。同时需要将该组件中使用的 `orderStatusLabel` 函数改为可导出（在其他组件中使用），以及 `SecondaryButton` 等工具函数。

实际上 `orderStatusLabel` 已在 line 65-71 定义，只需要给它加 `export` 关键字即可（让 RevenueDashboard.tsx 可以 import）。

找到 `function orderStatusLabel` 改为 `export function orderStatusLabel`。

- [ ] **Step 2: 删除 AdminPages.tsx 中不再需要的 import**

删除 `updateAdminOrderStatus` 的 import（如果只有 AdminOrdersPage 用到了它）。检查 AdminPages.tsx 中 `updateAdminOrderStatus` 是否还有其他引用。

- [ ] **Step 3: 修改 App.tsx — 删除 AdminOrdersPage import**

找到 `import { ..., AdminOrdersPage, ... } from` 行（line 29），删除 `AdminOrdersPage`。

- [ ] **Step 4: 修改 App.tsx — 删除 orders 路由渲染**

找到 `{route === 'orders' && session.role === 'admin' && <AdminOrdersPage ... />}`（line 783），删除整行。

- [ ] **Step 5: 修改 App.tsx — 从 ADMIN_NAV 移除 orders 条目**

定位 `{ key: 'orders', label: '订单订阅', icon: ScrollText }`（line 129），删除该行。

同时删除 line 140 的中文标签覆盖：`ADMIN_NAV[4].label = '订单中心';`
另外 revenue 的标签改为「收入与订单」：`ADMIN_NAV[3].label = '收入与订单';`

注意：删除 nav 条目后，后续索引会变化，需要重新调整 `ADMIN_NAV[x].label` 的索引。

实际上仔细看 ADMIN_NAV 的索引映射（lines 136-143）：
```
ADMIN_NAV[0].label = '套餐管理';     // plan-config
ADMIN_NAV[1].label = '平台配置';     // quota-rules
ADMIN_NAV[2].label = '用户管理';     // entitlements
ADMIN_NAV[3].label = '收入看板';     // revenue
ADMIN_NAV[4].label = '订单中心';     // orders ← 删除
ADMIN_NAV[5].label = '操作审计';     // audit-logs
ADMIN_NAV[6].label = '公告管理';     // announcement
ADMIN_NAV[7].label = '模板审核';     // template-review
ADMIN_NAV[8].label = '系统提示词';   // system-prompts
```

删除订单中心后，后续索引需要前移：
```
ADMIN_NAV[0].label = '套餐管理';
ADMIN_NAV[1].label = '平台配置';
ADMIN_NAV[2].label = '用户管理';
ADMIN_NAV[3].label = '收入与订单';   // revenue
ADMIN_NAV[4].label = '操作审计';     // audit-logs (原索引5)
ADMIN_NAV[5].label = '公告管理';     // announcement (原索引6)
ADMIN_NAV[6].label = '模板审核';     // template-review (原索引7)
ADMIN_NAV[7].label = '系统提示词';   // system-prompts (原索引8)
```

- [ ] **Step 6: 验证 TypeScript + Build**

Run: `npx tsc --noEmit`
Run: `npm run build`

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/admin/AdminPages.tsx frontend/src/App.tsx
git commit -m "refactor: remove standalone orders page, merge into revenue dashboard"
```

---

### Task 5: 全面验证

- [ ] **Step 1: 运行后端测试**

Run: `cd backend && python -m pytest tests/ -x -q` — 预期 49 passed

- [ ] **Step 2: 前端 TypeScript + Build 验证**

Run: `cd frontend && npx tsc --noEmit && npm run build`

- [ ] **Step 3: 最终提交（如有未提交更改）**

```bash
git add -A
git commit -m "chore: final verification"
```
