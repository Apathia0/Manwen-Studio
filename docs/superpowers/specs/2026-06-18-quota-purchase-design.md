# 独立配额购买功能设计

## 概述

允许用户在保持当前套餐的情况下，单独购买特定功能的额外配额（如购买更多生图次数）。配额购买使用独立的按量定价，通过现有支付系统完成交易，购买后自动追加到用户当月的 `UserQuotaGrantMonthly`。

## 架构改动

### 后端改动

#### 1. 配额定价配置

在 `FEATURE_CATALOG` 中为每个可购买的「可消耗型」功能添加 `purchasable` 和 `price_per_unit` 字段。

可购买的功能清单（仅「可消耗型」配额）：
- `manga.image.generate.monthly_limit` — 生图配额
- `chapter.expand.monthly_limit` — 章节扩写次数
- `scene.generate.monthly_limit` — 分镜生成次数
- `framework.generate.monthly_limit` — 小说框架生成次数
- `ai.text.advanced_calls.monthly_limit` — 高级文本 AI 调用次数
- `video.shot.split.monthly_limit` — 拆镜次数
- `video.generate.count.monthly_limit` — 视频生成次数

价格存储在 `PlatformSetting` 中，key 为 `pricing.quota.{feature_key}`，value 为数字单价（元/单位）。
默认价格在种子函数中写入，管理员可通过平台设置 API 修改。

#### 2. 新增 API 端点

| 方法 | 路径 | 用途 |
|------|------|------|
| GET | `/api/billing/quota-prices` | 返回可购买的配额清单（功能名、单价、说明） |
| POST | `/api/billing/purchase-quota` | 创建配额购买订单 |

**`POST /api/billing/purchase-quota` 请求/响应：**
```json
请求: { "feature_key": "manga.image.generate.monthly_limit", "amount": 50 }
响应: {
  "ok": true,
  "order": { "order_no": "...", "amount": 10.0, ... },
  "checkout": { "method": "alipay_qr", "qr_code_text": "...", ... }
}
```

创建订单时会校验：
- `feature_key` 是否在可购买清单中
- `amount` 是否为正整数
- 单价是否存在且有效

之后完全复用现有支付流程（创建 `BillingOrder` → 返回 checkout → 用户支付）。

#### 3. `_mark_order_paid` 扩展

当 `order.source == "quota_purchase"` 时：

1. 不调用 `_upsert_user_subscription`（不变更套餐）
2. 从 `order.extra_json` 读取 `feature_key` 和 `amount`
3. 在 `UserQuotaGrantMonthly` 中追加额度（同现有 `admin_grant_user_quota` 逻辑）
4. 产生审计日志

#### 4. `BillingOrder` 使用规范

```
source = "quota_purchase"
plan_id = 用户当前套餐的 plan_id
extra_json = {
  "action": "quota_purchase",
  "feature_key": "manga.image.generate.monthly_limit",
  "amount": 50,
  "unit_price": 0.2,
  "total_price": 10.0,
  "period_key": "202606"
}
```

### 前端改动

#### 1. `UserAccountUsagePage.tsx` 修改

在「本月核心额度」表格的「剩余」列之后增加「操作」列，每行显示「购买」按钮。

点击「购买」→ 触发购买弹窗。

#### 2. 新增 `QuotaPurchaseDialog.tsx` 组件

购买弹窗内容：
- 功能名称和当前用量状态
- 数量输入框（步进器 + 手动输入）
- 实时价格计算（数量 × 单价）
- 合计金额显示
- 「确认购买」按钮

点击「确认购买」后：
1. 调用 `POST /api/billing/purchase-quota`
2. 返回 checkout 信息后显示现有的 `PaymentCheckoutDialog`
3. 支付成功后调用 `refreshUsage()` 刷新额度

#### 3. API 客户端（`api.ts`）新增

```
getQuotaPrices(): Promise<QuotaPriceItem[]>
purchaseQuota(featureKey: string, amount: number): Promise<{ ok, order, checkout }>
QuotaPriceItem: { feature_key, name, description, price_per_unit, unit }
```

### 数据流

```
用户点击「购买」→ 弹出 QuotaPurchaseDialog → 输入数量 → 确认
  → POST /api/billing/purchase-quota { feature_key, amount }
    → 后端创建 BillingOrder (source="quota_purchase")
    → 返回 { order, checkout }
  → 显示 PaymentCheckoutDialog
  → 用户支付 → 后端 _mark_order_paid
    → source == "quota_purchase" → 追加 UserQuotaGrantMonthly
  → 前端轮询 syncMyOrder → 支付成功
  → refreshUsage() 刷新额度表格
```

## 未改动部分

- 现有套餐订阅流程不变
- 现有配额扣减逻辑（`_check_and_consume_quota`）不变 — 它已支持 `granted` 追加
- 现有用户订阅表不变
- 现有支付网关/回调不变

## 安全与限制

- 单价由管理员在平台设置中配置，用户不可修改
- `amount` 须为正整数
- 支付完成后立即生效，不可退款
- 购买配额跟随当月周期，月底清零（与现有配额周期一致）
