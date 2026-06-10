# 管理后台收入看板 → 订单管理合并设计

## 目标

将现有的独立「订单中心」页面（`AdminOrdersPage`）合并到收入看板底部，在看板页面实现完整的订单查看、筛选、分页、状态管理功能，实现一个页面的收入+订单全视图。

## 变更范围

### 后端

新增 **`GET /api/admin/orders/search`** 分页查询接口：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `page` | int | 否 | 页码，默认 1 |
| `page_size` | int | 否 | 每页条数，默认 20，最大 100 |
| `status` | string | 否 | 筛选：`paid` / `pending` / `cancelled` / `expired`，空=全部 |
| `start_date` | string | 否 | 开始日期 `YYYY-MM-DD` |
| `end_date` | string | 否 | 结束日期 `YYYY-MM-DD` |

返回格式：

```json
{
  "items": [ ... ],
  "total": 283,
  "page": 1,
  "page_size": 20,
  "total_pages": 15
}
```

- 使用 SQLAlchemy ORM 查询 `BillingOrder`
- 按 `created_at` 降序排列
- 每个订单调用 `_sync_order_status` 同步状态
- `_serialize_order_with_db` 序列化

现有 `GET /api/admin/orders`（无分页，100条上限）保留供看板顶部「最近收入订单」使用。

### 前端

#### 1. 新增类型与 API 函数（`api.ts`）

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

export async function searchAdminOrders(
  params: AdminOrderSearchParams
): Promise<AdminOrderSearchResult>
```

#### 2. RevenueDashboard 底部订单管理区

现有组件 `RevenueDashboard.tsx` 保留全部仪表盘内容，在底部新增完整订单管理区域：

**筛选工具栏**（横向布局）：
- 状态下拉选择：全部 / 待支付 / 已支付 / 已取消 / 已过期
- 时间快捷选择：全部时间 / 近7天 / 近30天 / 近90天 / 近1年
- 刷新按钮

**订单表格**（复用现有样式）：
- 列：订单号、用户（ID + 名称）、金额（货币+金额）、状态（带颜色标签）、来源、创建时间、操作
- 操作：标记已支付 / 取消 / 过期（与 `AdminOrdersPage` 一致）
- 状态标签颜色：已支付=绿色、待支付=黄色、已取消=红色、已过期=橙色
- 空状态显示「暂无匹配订单」

**分页控件**：
- 上一页 / 下一页按钮
- 页码数字显示（当前页/总页数）
- "共 N 条" 统计
- 筛选条件变化时重置到第 1 页

#### 3. 路由与导航调整（`App.tsx`）

- 从 `ADMIN_NAV` 中移除 `orders` 条目
- 从 `App.tsx` 中移除 `AdminOrdersPage` 的 import 和条件渲染
- `revenue` 路由标签改为「收入与订单」

#### 4. 移除的文件/代码

- `AdminPages.tsx` 中删除 `AdminOrdersPage` 组件（line 1439-1544）
- 删除 `App.tsx` 中 `AdminOrdersPage` 的引入
- 删除 `App.tsx` 中 `route === 'orders'` 的渲染分支
- `ADMIN_NAV` 中移除 `orders` 条目

### 不变的部分

- 看板顶部的概览卡片、月度趋势图、套餐分布、状态分布完全不变
- 现有 `getAdminOrders()` API 函数保留，仅用于看板顶部「最近收入订单」
- 现有 `updateAdminOrderStatus()` API 函数保留

## 数据流

```
用户操作筛选/翻页
  → searchAdminOrders(params)
    → GET /api/admin/orders/search?page=1&status=paid&start_date=...
      → 后端聚合查询 + 分页
    → 更新 state: ordersResult, currentFilters
  → 重新渲染订单表格 + 分页控件
```

- 筛选条件改变时：重置 `page = 1`，重新请求
- 页码改变时：只改 `page` 参数，保留筛选条件
- 刷新按钮：用当前筛选 + 页码重新请求

## 分页实现

后端分页使用 SQLAlchemy 的 `.offset().limit()`。
前端分页控件显示：
- `< 上一页` 按钮（第1页时 disabled）
- `第 X / Y 页` 文字
- `下一页 >` 按钮（最后一页时 disabled）
- `共 N 条` 统计

## 实施任务

1. **Task 1**: 后端新增 `GET /api/admin/orders/search` 分页查询接口
2. **Task 2**: 前端新增 `AdminOrderSearchParams`、`AdminOrderSearchResult` 类型和 `searchAdminOrders` API 函数
3. **Task 3**: RevenueDashboard 底部增强为完整订单管理区（筛选栏 + 分页表格 + 状态操作）
4. **Task 4**: 路由/导航调整，删除独立订单中心页
5. **验证**: pytest + tsc + build
