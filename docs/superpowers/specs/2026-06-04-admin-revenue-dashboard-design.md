# 管理员收入看板设计方案

## 概述

在 LoreVista 管理后台中新增「收入看板」独立页面，以可视化方式展示订单收入概况、月度趋势、套餐分布等核心指标，替代当前纯表格的订单管理模式。

## 需求

- 管理员在后台能清晰看到收入情况
- 全状态订单分析（已支付/待支付/已取消/已过期）
- 按月统计为主
- 布局：顶部概览卡片 → 中间图表 → 底部订单表

## 方案选择

采用方案 B（独立看板页），不往现有 1718 行的 `AdminPages.tsx` 中继续堆叠。

## 后端 API

### `GET /api/admin/revenue/summary`

聚合汇总，返回当前整体统计。

```json
{
  "total_revenue": 128000.00,
  "total_orders": 324,
  "paid_orders": 256,
  "cancelled_orders": 32,
  "expired_orders": 36,
  "monthly_revenue": 12500.00,
  "monthly_orders": 28,
  "monthly_paid_orders": 22,
  "conversion_rate": 78.6,
  "active_subscriptions": 45,
  "monthly_new_users": 12
}
```

### `GET /api/admin/revenue/monthly?months=12`

月度趋势数据。

```json
[
  { "period": "2025-06", "revenue": 8200.00, "orders": 18, "paid": 15, "cancelled": 2, "expired": 1 },
  { "period": "2025-07", "revenue": 9500.00, "orders": 22, "paid": 19, "cancelled": 1, "expired": 2 }
]
```

### SQL 聚合策略

- 汇总：在 `BillingOrder` 表上用 `func.count` + `case when` 做单次聚合查询
- 月度趋势：`date_trunc('month', created_at)` + `GROUP BY` + 时间范围过滤
- 活跃订阅：查 `UserSubscription` 表 `status = 'active'` 的计数
- 新增付费用户：按 `paid_at` 维度对用户 ID 做 `COUNT(DISTINCT)`

## 前端组件

### 文件位置

新增 `frontend/src/components/admin/RevenueDashboard.tsx`。

### 页面布局

```
┌──────────────────────────────────────────────────────┐
│  收入看板                                [刷新按钮]    │
├──────────┬──────────┬──────────┬──────────────────────┤
│  总收入    │  本月收入  │  本月订单  │  支付转化率          │
├──────────┴──────────┴──────────┴──────────────────────┤
│  月度收入趋势（纯 CSS 柱状图）                          │
├──────────────────────────┬───────────────────────────┤
│  套餐收入分布（水平比例条）  │  订单状态分布（水平比例条）   │
├──────────────────────────┴───────────────────────────┤
│  最近已支付订单列表（最近 20 笔）                       │
└──────────────────────────────────────────────────────┘
```

### 图表实现

不引入第三方图表库，纯 CSS 实现：
- 柱状图：`div` 高度动态计算 + `transition` 动画
- 分布图：水平 stacked 比例条 + 百分比标签
- 采用 Tailwind v4 实用类

### 状态管理

- 3 个 `useState`：汇总数据、月度数据、最近订单
- 1 个 `useEffect`：初始加载
- 刷新按钮触发重新 fetch

## 导航集成

在 `App.tsx` 的 `ADMIN_NAV` 中插入：

```typescript
{ key: 'revenue', label: '收入看板', icon: BarChart3 }
```

在 `orders`（订单中心）之前，条件渲染：

```tsx
import { BarChart3 } from 'lucide-react';
// ...
{route === 'revenue' && session.role === 'admin' && <AdminRevenueDashboardPage onError={...} />}
```

## API 集成（api.ts）

新增 2 个函数及对应 TypeScript 类型定义：

- `getAdminRevenueSummary()` → `GET /api/admin/revenue/summary`
- `getAdminRevenueMonthly(months?)` → `GET /api/admin/revenue/monthly`

## 零新依赖

- 不引入任何 npm 包
- 不引入任何 Python 包
- 图表使用纯 CSS/Tailwind v4 实现

## 工作量估算

| 部分 | 预估行数 |
|------|---------|
| 后端 `main.py` 路由 | ~60 行 |
| 前端 `api.ts` 类型 + 函数 | ~40 行 |
| 前端 `RevenueDashboard.tsx` 组件 | ~250 行 |
| `App.tsx` 导航集成 | ~10 行 |
| **合计** | **~360 行** |
