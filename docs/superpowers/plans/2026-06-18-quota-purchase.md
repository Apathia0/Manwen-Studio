# 独立配额购买功能实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 允许用户在「账户与用量」页面直接购买单个功能的额外配额（如生图次数、扩写次数），复用现有支付流程，购买后自动追加到当月额度。

**Architecture:** 在 FEATURE_CATALOG 中标记可购买的功能和单价，配置存储在 PlatformSetting 中。新增 `POST /api/billing/purchase-quota` 创建订单，扩展 `_mark_order_paid` 处理配额购买订单（追加 UserQuotaGrantMonthly 而非改套餐）。前端在现有额度表格每行加「购买」按钮，弹出数量选择弹窗。

**Tech Stack:** Python/FastAPI/SQLAlchemy (backend), React/TypeScript/Tailwind v4 (frontend)

---

### Task 1: 后端 — FEATURE_CATALOG 添加可购买标记和默认单价

**Files:**
- Modify: `backend/main.py:168-241` (FEATURE_CATALOG 定义)
- Modify: `backend/main.py:1244-1290` (_seed_platform_settings 写入定价)
- Test: 无独立测试（通过 Task 3 的 API 测试验证）

- [ ] **Step 1: 在 FEATURE_CATALOG 中为 7 个可消耗功能添加 `purchasable: true` 和 `price_per_unit`**

在 `backend/main.py` 的 FEATURE_CATALOG 列表中，为以下 7 个功能添加字段：
```python
# 改动：在每个可购买功能的 dict 中添加：
{
    "key": "manga.image.generate.monthly_limit",
    "name": "生图配额",
    ...
    "purchasable": True,
    "price_per_unit": 0.2,  # 0.2 元/张
},
```

各功能默认单价：
| feature_key | `price_per_unit` |
|---|---|
| `manga.image.generate.monthly_limit` | 0.2 |
| `chapter.expand.monthly_limit` | 0.5 |
| `scene.generate.monthly_limit` | 0.3 |
| `framework.generate.monthly_limit` | 1.0 |
| `ai.text.advanced_calls.monthly_limit` | 0.3 |
| `video.shot.split.monthly_limit` | 1.0 |
| `video.generate.count.monthly_limit` | 2.0 |

- [ ] **Step 2: 在 `_seed_platform_settings` 中写入默认定价到 PlatformSetting**

在 `backend/main.py` 的 `_seed_platform_settings` 函数中的 defaults dict 添加：
```python
# 配额购买默认定价
"pricing.quota.manga.image.generate.monthly_limit": "0.2",
"pricing.quota.chapter.expand.monthly_limit": "0.5",
"pricing.quota.scene.generate.monthly_limit": "0.3",
"pricing.quota.framework.generate.monthly_limit": "1.0",
"pricing.quota.ai.text.advanced_calls.monthly_limit": "0.3",
"pricing.quota.video.shot.split.monthly_limit": "1.0",
"pricing.quota.video.generate.count.monthly_limit": "2.0",
```

- [ ] **Step 3: 定义 `PURCHASABLE_FEATURE_KEYS` 集合供 API 使用**

在 `FEATURE_CATALOG` 定义之后添加：
```python
PURCHASABLE_FEATURE_KEYS = {f["key"] for f in FEATURE_CATALOG if f.get("purchasable")}
```

- [ ] **Step 4: Commit**

```bash
git add backend/main.py
git commit -m "feat: add purchasable flag and default pricing to FEATURE_CATALOG"
```

---

### Task 2: 后端 — 新增 `GET /api/billing/quota-prices` 端点

**Files:**
- Modify: `backend/main.py` — 新增路由（在 billing 路由区域）

- [ ] **Step 1: 添加路由函数**

在 `billing_payment_config` 路由（约 4188 行）后面添加：

```python
@app.get("/api/billing/quota-prices")
def billing_quota_prices(db: Session = Depends(get_db)):
    """返回可购买的配额清单及单价"""
    _ensure_platform_seed(db)
    prices = []
    for feature in FEATURE_CATALOG:
        if not feature.get("purchasable"):
            continue
        key = str(feature["key"])
        # 读 PlatformSetting，回退到 FEATURE_CATALOG 默认值
        price_str = _get_platform_setting(f"pricing.quota.{key}", db)
        if not price_str:
            price = float(feature.get("price_per_unit", 0))
        else:
            try:
                price = float(price_str)
            except (ValueError, TypeError):
                price = float(feature.get("price_per_unit", 0))
        prices.append({
            "feature_key": key,
            "name": feature.get("name", key),
            "description": feature.get("description", ""),
            "category": feature.get("category", ""),
            "price_per_unit": price,
            "unit": "次" if "count" in key or "calls" in key or "split" in key else "张",
        })
    return prices
```

- [ ] **Step 2: Commit**

```
git add backend/main.py
git commit -m "feat: add GET /api/billing/quota-prices endpoint"
```

---

### Task 3: 后端 — 新增 `POST /api/billing/purchase-quota` 端点

**Files:**
- Modify: `backend/main.py` — 新增路由

- [ ] **Step 1: 添加路由函数**

在 `billing_quota_prices` 路由后面添加：

```python
@app.post("/api/billing/purchase-quota")
def purchase_quota(body: dict, request: Request, db: Session = Depends(get_db)):
    """用户自助购买配额"""
    _ensure_platform_seed(db)
    user = _require_user(request, db)
    payment = _payment_settings_snapshot(db)
    if not bool(payment.get("enabled")):
        raise HTTPException(400, "支付当前已禁用")

    feature_key = str(body.get("feature_key") or "").strip()
    amount = int(body.get("amount") or 0)

    if not feature_key:
        raise HTTPException(400, "feature_key 必填")
    if feature_key not in PURCHASABLE_FEATURE_KEYS:
        raise HTTPException(400, "该功能不支持配额购买")
    if amount <= 0:
        raise HTTPException(400, "购买数量必须大于 0")

    # 获取单价
    price_str = _get_platform_setting(f"pricing.quota.{feature_key}", db)
    if not price_str:
        catalogue_item = next((f for f in FEATURE_CATALOG if f["key"] == feature_key), None)
        unit_price = float(catalogue_item.get("price_per_unit", 0)) if catalogue_item else 0
    else:
        try:
            unit_price = float(price_str)
        except (ValueError, TypeError):
            unit_price = 0

    if unit_price <= 0:
        raise HTTPException(400, "该功能暂未定价，无法购买")

    total_price = round(unit_price * amount, 2)
    payment_method = str(body.get("payment_method") or payment.get("default_method") or "mock_qr").strip()
    method_options = _payment_method_options(db)
    selected_method = next((item for item in method_options if item["key"] == payment_method), None)
    if not selected_method:
        raise HTTPException(400, "支付方式不可用")

    expire_minutes = int(payment.get("order_expire_minutes") or 30)
    expires_at = datetime.datetime.utcnow() + datetime.timedelta(minutes=expire_minutes)
    period_key = _subscription_period_key(user.id, db)
    current_plan = _active_plan_for_user(user.id, db)

    # 取消旧的待支付配额订单
    stale_orders = (
        db.query(BillingOrder)
        .filter(
            BillingOrder.user_id == user.id,
            BillingOrder.status == "pending",
            BillingOrder.source == "quota_purchase",
        )
        .all()
    )
    for stale_order in stale_orders:
        _mark_order_cancelled(stale_order, db, operator_user_id=user.id, note="Superseded by a newer quota purchase request")

    order = BillingOrder(
        order_no=f"LVQP{datetime.datetime.utcnow().strftime('%Y%m%d%H%M%S')}{secrets.randbelow(10000):04d}",
        user_id=user.id,
        plan_id=current_plan.id,
        amount=_coerce_money(total_price),
        currency="CNY",
        status="pending",
        source="quota_purchase",
        billing_cycle="monthly",
        payment_provider=str(selected_method["provider"]),
        payment_method=selected_method_key if (selected_method_key := str(selected_method["key"])) else str(selected_method["key"]),
        operator_user_id=user.id,
        note=f"购买 {feature_key} 配额 x{amount}",
        extra_json={
            "action": "quota_purchase",
            "feature_key": feature_key,
            "amount": amount,
            "unit_price": unit_price,
            "total_price": total_price,
            "period_key": period_key,
        },
        expired_at=expires_at,
    )
    db.add(order)

    checkout_override = None
    if _coerce_money(total_price) <= Decimal("0.00"):
        _mark_order_paid(order, db, operator_user_id=user.id, note=f"Zero-amount quota purchase auto-confirmed")
    else:
        gateway = get_gateway(str(selected_method["key"]))
        if gateway is not None:
            try:
                plan_for_checkout = current_plan
                payment_with_ip = dict(payment)
                payment_with_ip["client_ip"] = request.client.host if request.client else ""
                checkout_data = gateway.create_checkout(order, plan_for_checkout, payment_with_ip)
                if checkout_data.extra:
                    merged = dict(order.extra_json or {})
                    merged.update(checkout_data.extra)
                    order.extra_json = merged
                checkout_override = gateway.build_checkout_response(order, plan_for_checkout, payment, checkout_data)
            except RuntimeError as exc:
                raise HTTPException(502, f"{gateway.label} checkout failed: {exc}") from exc

    _write_audit_log(user, "purchase_quota", "billing_order", order.order_no,
                     f"购买 {feature_key} 配额 x{amount}，金额 {total_price} 元", db, {
        "feature_key": feature_key,
        "amount": amount,
        "unit_price": unit_price,
        "total_price": total_price,
        "payment_method": str(selected_method["key"]),
    })
    db.commit()
    db.refresh(order)

    return {
        "ok": True,
        "message": "配额购买订单已创建",
        "status": order.status,
        "order": _serialize_order_with_db(order, db),
        "checkout": checkout_override or _order_checkout_payload(order, current_plan, db),
    }
```

- [ ] **Step 2: Commit**

```
git add backend/main.py
git commit -m "feat: add POST /api/billing/purchase-quota endpoint"
```

---

### Task 4: 后端 — 扩展 `_mark_order_paid` 处理配额购买

**Files:**
- Modify: `backend/main.py` — `_mark_order_paid` 函数

- [ ] **Step 1: 修改 `_mark_order_paid` 函数**

找到 `_mark_order_paid` 函数（约 4680 行附近），在函数体中找到处理订阅更新的部分，在之前或之后添加配额购买分支：

```python
def _mark_order_paid(order: BillingOrder, db: Session, *, operator_user_id: int | None = None, note: str | None = None) -> None:
    if order.status == "paid":
        return
    order.status = "paid"
    order.paid_at = _utcnow()
    if note:
        order.note = (order.note or "") + " | " + note if order.note else note

    # ── 配额购买订单：追加配额，不改套餐订阅 ──
    if order.source == "quota_purchase":
        extra = order.extra_json or {}
        feature_key = extra.get("feature_key", "")
        amount = int(extra.get("amount") or 0)
        period_key = extra.get("period_key") or _subscription_period_key(order.user_id, db)
        if feature_key and amount > 0:
            grant = db.query(UserQuotaGrantMonthly).filter(
                UserQuotaGrantMonthly.user_id == order.user_id,
                UserQuotaGrantMonthly.feature_key == feature_key,
                UserQuotaGrantMonthly.period_key == period_key,
            ).first()
            if grant:
                grant.granted_amount += amount
            else:
                db.add(UserQuotaGrantMonthly(
                    user_id=order.user_id,
                    feature_key=feature_key,
                    period_key=period_key,
                    granted_amount=amount,
                ))
            _write_audit_log(None, "quota_purchase_credited", "billing_order", order.order_no,
                             f"配额购买到账：{feature_key} +{amount}", db, {
                "feature_key": feature_key,
                "amount": amount,
                "period_key": period_key,
            })
        return  # 配额购买不处理订阅变更

    # ── 普通套餐订阅订单：更新订阅 ──
    ...原有逻辑继续...
```

**注意：** 需要在 `_write_audit_log` 导入确认没问题，以及需要在函数顶部确保 `_subscription_period_key` 可用。由于该函数内部使用 db query，需要确保 db session 有效。

- [ ] **Step 2: Commit**

```
git add backend/main.py
git commit -m "feat: handle quota_purchase orders in _mark_order_paid"
```

---

### Task 5: 后端 — 添加字段到 `admin_save_platform_settings` 使管理员可修改定价

**Files:**
- Modify: `backend/main.py` — 平台设置保存逻辑

- [ ] **Step 1: 确认现有逻辑已支持**

检查 `admin_save_platform_settings` 函数。如果它已经支持任意 key-value 保存（直接存入 PlatformSetting 表），则无需改动。单价定价将以 `pricing.quota.*` 为 key 自动被平台设置管理页面覆盖。

- [ ] **Step 2: 验证**

阅读 `admin_save_platform_settings` 和 `_platform_settings_snapshot` 逻辑，确认 `pricing.quota.*` 会被正确读取和写入。

---

### Task 6: 前端 — API 客户端新增类型和函数

**Files:**
- Modify: `frontend/src/api.ts` — 类型定义和 API 函数

- [ ] **Step 1: 添加 QuotaPriceItem 类型和购买响应类型**

在 `frontend/src/api.ts` 中，在 `PaymentSettings` 类型后添加：

```typescript
export interface QuotaPriceItem {
  feature_key: string;
  name: string;
  description: string;
  category: string;
  price_per_unit: number;
  unit: string;
}

export interface PurchaseQuotaResponse {
  ok: boolean;
  message: string;
  status: string;
  order: AdminOrderItem;
  checkout: BillingCheckout;
}
```

- [ ] **Step 2: 添加 getQuotaPrices 和 purchaseQuota 函数**

在 `frontend/src/api.ts` 中，在 `getPaymentConfig` 函数后添加：

```typescript
export async function getQuotaPrices(): Promise<QuotaPriceItem[]> {
  const res = await fetch(`${BASE}/api/billing/quota-prices`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function purchaseQuota(
  featureKey: string,
  amount: number,
  paymentMethod?: string,
): Promise<PurchaseQuotaResponse> {
  const body: Record<string, unknown> = { feature_key: featureKey, amount };
  if (paymentMethod) body.payment_method = paymentMethod;
  const res = await fetch(`${BASE}/api/billing/purchase-quota`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...apiHeaders() },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}
```

- [ ] **Step 3: Commit**

```
git add frontend/src/api.ts
git commit -m "feat: add quota price types and API functions"
```

---

### Task 7: 前端 — 新建 QuotaPurchaseDialog 组件

**Files:**
- Create: `frontend/src/components/QuotaPurchaseDialog.tsx`

- [ ] **Step 1: 创建组件文件**

```tsx
import { useState, useEffect } from 'react';
import type { QuotaPriceItem, UsageItem, BillingCheckout, AdminOrderItem } from '../api';
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
```

- [ ] **Step 2: Commit**

```
git add frontend/src/components/QuotaPurchaseDialog.tsx
git commit -m "feat: add QuotaPurchaseDialog component"
```

---

### Task 8: 前端 — 修改 UserAccountUsagePage 添加购买按钮

**Files:**
- Modify: `frontend/src/components/UserAccountUsagePage.tsx`

- [ ] **Step 1: 在额度表格每行添加「购买」按钮**

在 `UserAccountUsagePage.tsx` 中修改额度表格的 thead 和 tbody：

```tsx
// 在 import 区域添加 QuotaPurchaseDialog 导入
import { QuotaPurchaseDialog } from './QuotaPurchaseDialog';
import { getQuotaPrices, type QuotaPriceItem } from '../api';

// 在函数体开头添加 state
const [showQuotaDialog, setShowQuotaDialog] = useState<string | null>(null);
const [quotaPrices, setQuotaPrices] = useState<QuotaPriceItem[]>([]);

// 在 useEffect 中获取定价
useEffect(() => {
  getQuotaPrices().then(setQuotaPrices).catch(() => {});
}, []);

// 修改表格 thead，添加「操作」列：
<thead className="bg-[#f8fbff] text-slate-500">
  <tr>
    <th className="px-4 py-3 font-medium">能力项</th>
    <th className="px-4 py-3 font-medium">总量</th>
    <th className="px-4 py-3 font-medium">已用</th>
    <th className="px-4 py-3 font-medium">剩余</th>
    <th className="px-4 py-3 font-medium">操作</th>
  </tr>
</thead>

// 在 tbody 中每个 tr 末尾的 <td className="px-4 py-3"> 之后添加「操作」列：
<td className="px-4 py-3">
  {quotaPrices.some(p => p.feature_key === item.feature_key) ? (
    <button
      onClick={() => setShowQuotaDialog(item.feature_key)}
      className="rounded-xl bg-[#1d4ed8] px-3 py-1.5 text-xs font-medium text-white hover:bg-[#1d4ed8]/90"
    >
      购买
    </button>
  ) : null}
</td>

// 在 return 末尾添加 QuotaPurchaseDialog 渲染：
{showQuotaDialog ? (
  <QuotaPurchaseDialog
    featureKey={showQuotaDialog}
    usage={usage?.items?.find(i => i.feature_key === showQuotaDialog) || null}
    onClose={() => setShowQuotaDialog(null)}
    onSuccess={() => { refreshUsage(); }}
  />
) : null}
```

- [ ] **Step 2: 添加 `refreshUsage` 回调和导入**

由于 `UserAccountUsagePage` 目前没有 `refreshUsage` prop，需要从 parent 传入，或在页面内自行调用 `getMyUsage()`。

在 `App.tsx` 中给 `UserAccountUsagePage` 添加 `onRefreshUsage` prop。

先在 `api.ts` 确认 `getMyUsage` 已导出。

然后修改 `App.tsx` 传递 `onRefreshUsage`:
```tsx
<UserAccountUsagePage
  ...
  onRefreshUsage={refreshUsage}
/>
```

在 `UserAccountUsagePage.tsx` 添加 prop:
```tsx
onRefreshUsage?: () => void;
```
并在 QuotaPurchaseDialog 的 `onSuccess` 中调用:
```tsx
onSuccess={() => { onRefreshUsage?.(); refreshOrders?.(); }}
```

- [ ] **Step 3: Commit**

```
git add frontend/src/components/UserAccountUsagePage.tsx frontend/src/App.tsx
git commit -m "feat: add quota purchase button to usage table"
```

---

### Task 9: 验证 — 端到端测试

**Files:**
- Test: 手动验证

- [ ] **Step 1: 启动后端并验证 API**

```bash
cd backend
python -c "
from main import app, FEATURE_CATALOG, PURCHASABLE_FEATURE_KEYS
print('可购买功能数:', len(PURCHASABLE_FEATURE_KEYS))
for f in FEATURE_CATALOG:
    if f.get('purchasable'):
        print(f'  {f[\"key\"]}: {f[\"price_per_unit\"]} 元')
"
```

运行后端：`python main.py`，然后测试：
```bash
curl http://localhost:8000/api/billing/quota-prices
```
期望返回 7 个可购买功能。

- [ ] **Step 2: 测试前端构建**

```bash
cd frontend
npm run build 2>&1 | tail -20
```
期望无 TypeScript/构建错误。

- [ ] **Step 3: 手动验证支付流程**

1. 登录系统 → 进入「账户与用量」
2. 确认看到配额表格每行末尾有「购买」按钮
3. 点击「购买」→ 弹出购买弹窗
4. 调整数量 → 确认价格实时更新
5. 点击「确认购买」→ 进入支付弹窗
6. 使用模拟支付完成 → 返回后配额刷新

- [ ] **Step 4: 最终 commit**

```
git add -A
git commit -m "feat: complete standalone quota purchase feature"
```
