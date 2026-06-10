# 支付网关抽象层 + 易支付接入设计方案

## 概述

为 StoryCanvas 设计支付网关抽象层，解耦现有硬编码的支付分支逻辑，同时接入易支付等第三方支付接口，使未来新增支付方式只需添加一个文件 + 一行注册。

## 1. 问题现状

### 1.1 现有支付系统

- **支付方式**：仅支持支付宝当面付（alipay_qr）和模拟支付（mock_qr）；微信支付有配置占位但无实现
- **代码耦合**：支付逻辑全部硬编码在 `main.py`（~9400 行），`_order_checkout_payload()`、`subscribe_plan()` 通过 if-elif 判断 `payment_method` 分发
- **数据结构**：`BillingOrder` 表的 `payment_provider`/`payment_method` 字段 + `extra_json` JSON 字段已预留扩展性
- **支付配置**：存储在 `platform_settings` 表的 `payment.*` 键值中

### 1.2 痛点

- 每新增一个支付方式都需要修改 `main.py` 多处分支
- `main.py` 已过度膨胀（9407 行），增加维护成本
- 微信支付占位已久但无人实现，说明现有模式接入意愿低

## 2. 方案选择：支付网关抽象层

选型理由：
- 支持"易支付等第三方接口"的长期扩展需求
- 解耦 `main.py` 支付逻辑，路由层只负责调度
- 每个支付方式独立文件，可单独测试
- 支付宝和模拟支付同时适配到新接口，验证架构正确性

## 3. 架构设计

### 3.1 包结构

```
backend/services/payment/
├── __init__.py                  # 注册表管理 + 导出
├── base.py                      # PaymentGateway 抽象基类 + 数据类
├── mock_gateway.py              # MockGateway — 模拟支付
├── alipay_gateway.py            # AlipayGateway — 支付宝当面付
├── epay_gateway.py              # EpayGateway — 易支付 (新增)
└── wechat_gateway.py            # WechatGateway — 微信支付 (未来预留)
```

### 3.2 数据类定义 (`base.py`)

```python
@dataclass
class CheckoutResult:
    """创建支付订单的返回结果"""
    mode: str                          # "redirect" / "qrcode" / "mock"
    payment_url: str = ""              # 用户跳转支付链接
    qr_code_text: str = ""             # 二维码内容
    qr_code_url: str = ""              # 二维码图片URL（如有）
    can_mock_confirm: bool = False     # 是否支持前端手动确认支付
    extra: dict = field(default_factory=dict)  # 额外数据存入 order.extra_json

@dataclass
class NotifyResult:
    """异步回调验签结果"""
    verified: bool                     # 签名验证是否通过
    trade_status: str | None = None    # paid / failed
    trade_no: str = ""                 # 支付平台交易号
    amount: str = "0"                  # 实际支付金额
    raw: dict = field(default_factory=dict)

@dataclass
class StatusSyncResult:
    """主动查询支付状态结果"""
    status_changed: bool               # 订单状态是否变更
    new_status: str | None = None      # paid / cancelled
    trade_no: str = ""
```

### 3.3 抽象基类 (`base.py`)

```python
class PaymentGateway(ABC):
    """支付网关抽象基类"""

    @property
    @abstractmethod
    def method_key(self) -> str:
        """支付方式标识，如 'epay_qr'"""

    @property
    @abstractmethod
    def provider(self) -> str:
        """提供商标识，如 'epay'"""

    @property
    def label(self) -> str:
        """前端显示名称"""
        return self.method_key

    def get_config_defaults(self) -> dict:
        """返回该网关所需的配置项及默认值"""
        return {}

    def get_config_meta(self) -> list[dict]:
        """返回配置元数据，供管理后台渲染配置表单"""
        return []

    @abstractmethod
    def create_checkout(
        self,
        order: "BillingOrder",
        plan: "Plan",
        payment_config: dict,
    ) -> CheckoutResult:
        """创建支付订单，返回结账数据"""

    def verify_notify(
        self,
        body: dict,
        payment_config: dict,
    ) -> NotifyResult:
        """验证异步回调通知签名，返回支付结果"""
        raise NotImplementedError

    def sync_status(
        self,
        order: "BillingOrder",
        payment_config: dict,
    ) -> StatusSyncResult | None:
        """主动查询订单支付状态"""
        return None

    def build_checkout_response(
        self,
        order: "BillingOrder",
        plan: "Plan",
        payment_config: dict,
        checkout: CheckoutResult,
    ) -> dict:
        """构建前端的 checkout 响应数据"""
        expire_minutes = int(payment_config.get("order_expire_minutes") or 30)
        expires_at = order.expired_at or (
            datetime.datetime.utcnow() + datetime.timedelta(minutes=expire_minutes)
        )
        return {
            "mode": checkout.mode,
            "method": order.payment_method,
            "provider": order.payment_provider,
            "instructions": str(payment_config.get("instructions") or ""),
            "amount": _money_to_number(order.amount),
            "currency": order.currency,
            "plan_name": plan.name,
            "billing_cycle": order.billing_cycle or "monthly",
            "expires_at": expires_at,
            "qr_code_text": checkout.qr_code_text,
            "payment_url": checkout.payment_url,
            "can_mock_confirm": checkout.can_mock_confirm,
        }
```

### 3.4 注册表 (`__init__.py`)

```python
_gateways: dict[str, PaymentGateway] = {}

def register_gateway(gateway: PaymentGateway) -> None:
    """注册支付网关"""
    _gateways[gateway.method_key] = gateway

def get_gateway(method_key: str) -> PaymentGateway | None:
    """获取支付网关实例"""
    return _gateways.get(method_key)

def get_method_options(payment_config: dict) -> list[dict]:
    """返回已启用所有支付方式的选项列表"""
    results = []
    for method_key, gateway in _gateways.items():
        enabled_key = f"{gateway.provider}_enabled"
        if bool(payment_config.get(enabled_key, method_key == "mock_qr")):
            results.append({
                "key": method_key,
                "label": getattr(gateway, "label", method_key),
                "enabled": True,
                "provider": gateway.provider,
            })
    return results

def init_gateways() -> None:
    """初始化所有网关（应用启动时调用一次）"""
    from .mock_gateway import MockGateway
    from .alipay_gateway import AlipayGateway
    from .epay_gateway import EpayGateway

    register_gateway(MockGateway())
    register_gateway(AlipayGateway())
    register_gateway(EpayGateway())
```

## 4. 易支付网关详细设计

### 4.1 API 规范（V1 标准，对应 maajiko/Epay 源码）

易支付 V1 是最常见的开源易支付聚合平台标准。本设计基于 [maajiko/Epay](https://github.com/maajiko/Epay) 源码分析。

#### 签名算法（核心）

```php
// Payment.php — makeSign 方法
static private function getSignContent($data) {
    ksort($data);
    $signStr = '';
    foreach ($data as $k => $v) {
        // 跳过 sign、sign_type、空值、数组
        if (is_array($v) || isEmpty($v) || $k == 'sign' || $k == 'sign_type') continue;
        $signStr .= $k . '=' . $v . '&';
    }
    return substr($signStr, 0, -1);  // 去掉末尾 &
}
// sign = md5( "k1=v1&k2=v2" . 商户密钥 )
$sign = md5($signStr . $md5key);
```

> ⚠️ 注意：标准文档常描述为 `&key=密钥`，但 maajiko/Epay 源码实际实现是**直接拼接密钥字符串**，不含 `&` 前缀。实现时必须严格遵守此算法，否则签名验证失败。

#### 下单 API — 推荐使用 `mapi.php`（JSON 接口）

`submit.php` 返回 HTML 页面，不适合程序化调用。`mapi.php` 返回 JSON，作为网关后端调用：

**POST** `{gateway_url}/mapi.php` (form-data)

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `pid` | int | 是 | 商户ID |
| `type` | string | 是 | 支付方式: alipay/wxpay/qqpay |
| `out_trade_no` | string | 是 | 商户订单号 |
| `notify_url` | string | 是 | 异步通知地址 |
| `return_url` | string | 否 | 同步跳转地址 |
| `name` | string | 是 | 商品名称 |
| `money` | string | 是 | 金额（元），如 `59.00` |
| `sitename` | string | 否 | 网站名称 |
| `sign` | string | 是 | MD5 签名（不含 sign/sign_type 参数排序后 + key MD5） |
| `sign_type` | string | 是 | `MD5` |

**成功响应** (`code=0` 表示 V1 API 成功，`code=1` 表示 V2 API)：
```json
// V1 成功
{"code": 0, "trade_no": "2025010112345678", "payurl": "https://...", "qrcode": ""}

// V1 失败  
{"code": -1, "msg": "签名错误"}
{"code": -4, "msg": "请填写pid"}
```

从响应中取 `payurl` 作为前端跳转链接（适用于支付宝/QQ钱包）或 `qrcode` 作为二维码内容（适用于微信扫码）。

#### 异步通知回调

易支付在用户完成支付后，POST 到 `notify_url`（form-data）：

| 参数 | 类型 | 说明 |
|------|------|------|
| `out_trade_no` | string | 商户订单号 |
| `trade_no` | string | 易支付平台交易号（`2025010112345678`） |
| `trade_status` | string | `TRADE_SUCCESS` 表示成功 |
| `money` | string | 实际支付金额（元），如 `59.00` |
| `sign` | string | MD5 签名 |
| `sign_type` | string | `MD5` |

**验签**：同样移除 `sign` 和 `sign_type`，剩余参数排序拼接后 `md5(str + key)`。

接收到有效通知后必须**响应纯文本 `success`**（HTTP 200, Content-Type: text/plain），易支付收到 `success` 后停止重试。其他响应会继续重试（间隔递增，持续约 24 小时）。

#### 订单查询

**GET** `{gateway_url}/api.php?act=order&pid={pid}&key={key}&out_trade_no={out_trade_no}`

注意：该接口不通过 sign 验证，而是直接传递 `key`（商户密钥原文）作为参数，查询成功返回订单信息。

**成功响应**：
```json
{"code": 0, "data": {"status": 1, "trade_no": "...", "out_trade_no": "...", "money": "59.00"}}
```
其中 `status` 为 `0`（未支付）或 `1`（已支付）。

### 4.2 `EpayGateway` 实现

```python
# backend/services/payment/epay_gateway.py

import hashlib
import httpx
from urllib.parse import urlencode
from .base import PaymentGateway, CheckoutResult, NotifyResult, StatusSyncResult


def _epay_sign(params: dict, key: str) -> str:
    """易支付 MD5 签名：参数排序后拼接 + 密钥直接拼接，不含 & 前缀

    对应 maajiko/Epay Payment::makeSign:
        sign = md5( "k1=v1&k2=v2" + key )
    """
    items = []
    for k in sorted(params.keys()):
        v = params[k]
        if v is None or v == "" or isinstance(v, (list, dict)):
            continue
        if k in ("sign", "sign_type"):
            continue
        items.append(f"{k}={v}")
    sign_str = "&".join(items)  # 末尾无 &
    return hashlib.md5((sign_str + key).encode("utf-8")).hexdigest()


class EpayGateway(PaymentGateway):

    method_key = "epay_qr"
    provider = "epay"
    label = "易支付"

    def get_config_defaults(self) -> dict:
        return {
            "payment.epay_enabled": False,
            "payment.epay_gateway": "",
            "payment.epay_pid": "",
            "payment.epay_key": "",
            "payment.epay_type": "alipay",
            "payment.epay_notify_url": "",
            "payment.epay_return_url": "",
        }

    def get_config_meta(self) -> list[dict]:
        return [
            {"key": "epay_enabled", "label": "启用易支付", "type": "boolean"},
            {"key": "epay_gateway", "label": "易支付网关地址", "type": "string",
             "placeholder": "https://your-epay.com"},
            {"key": "epay_pid", "label": "商户ID", "type": "string"},
            {"key": "epay_key", "label": "商户密钥", "type": "password"},
            {"key": "epay_type", "label": "默认支付方式", "type": "select",
             "options": [{"alipay": "支付宝"}, {"wxpay": "微信支付"}, {"qqpay": "QQ钱包"}]},
            {"key": "epay_notify_url", "label": "异步通知地址", "type": "string",
             "placeholder": "https://your-site.com/api/payments/epay/notify"},
            {"key": "epay_return_url", "label": "同步跳转地址", "type": "string"},
        ]

    def create_checkout(
        self, order, plan, payment_config
    ) -> CheckoutResult:
        gateway_url = str(payment_config.get("epay_gateway") or "").rstrip("/")
        pid = str(payment_config.get("epay_pid") or "").strip()
        key = str(payment_config.get("epay_key") or "").strip()
        pay_type = str(payment_config.get("epay_type") or "alipay").strip()

        if not gateway_url or not pid or not key:
            raise RuntimeError("易支付配置不完整")

        # 下单参数（sign/sign_type 在排序签名后添加）
        params = {
            "pid": pid,
            "type": pay_type,
            "out_trade_no": order.order_no,
            "notify_url": str(payment_config.get("epay_notify_url") or "").strip(),
            "return_url": str(payment_config.get("epay_return_url") or "").strip(),
            "name": f"{plan.name}订阅"[:32],
            "money": f"{float(order.amount or 0):.2f}",
        }
        params["sign"] = _epay_sign(params, key)
        params["sign_type"] = "MD5"

        # 使用 mapi.php（JSON 接口），避免 submit.php 返回 HTML
        api_url = f"{gateway_url}/mapi.php"
        try:
            response = httpx.post(api_url, data=params, timeout=15)
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            raise RuntimeError(f"易支付下单失败: {exc}") from exc

        # V1 标准: code=0 成功, 否则失败
        if data.get("code") != 0:
            raise RuntimeError(f"易支付返回错误: {data.get('msg', '未知错误')}")

        pay_url = data.get("payurl", "")
        qr_code = data.get("qrcode", "")
        trade_no = data.get("trade_no", "")

        if qr_code:
            return CheckoutResult(
                mode="qrcode",
                qr_code_text=qr_code,
                can_mock_confirm=True,
                extra={"epay_trade_no": trade_no},
            )
        return CheckoutResult(
            mode="redirect",
            payment_url=pay_url,
            can_mock_confirm=False if pay_type == "wxpay" else True,
            extra={"epay_trade_no": trade_no},
        )

    def verify_notify(self, body: dict, payment_config: dict) -> NotifyResult:
        """验证异步回调签名（不修改传入的 body 字典）"""
        key = str(payment_config.get("epay_key") or "").strip()
        sign = body.get("sign", "")

        # _epay_sign 内部会自动跳过 sign/sign_type
        expected = _epay_sign(body, key)
        if sign != expected:
            return NotifyResult(verified=False)

        return NotifyResult(
            verified=True,
            trade_status="paid" if body.get("trade_status") == "TRADE_SUCCESS" else "failed",
            trade_no=body.get("trade_no", ""),
            amount=body.get("money", "0"),
            raw=dict(body),
        )

    def sync_status(self, order, payment_config) -> StatusSyncResult | None:
        """主动查询订单支付状态"""
        gateway_url = str(payment_config.get("epay_gateway") or "").rstrip("/")
        pid = str(payment_config.get("epay_pid") or "").strip()
        key_str = str(payment_config.get("epay_key") or "").strip()

        if not gateway_url or not pid or not key_str:
            return None

        # api.php?act=order 使用 key 原文作为查询参数（非 sign 模式）
        params = {
            "act": "order",
            "pid": pid,
            "key": key_str,
            "out_trade_no": order.order_no,
        }
        try:
            response = httpx.get(f"{gateway_url}/api.php", params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
        except Exception:
            return None

        # 查询结果: code=1 表示查到订单, data.status=1 表示已支付
        order_data = data.get("data") or {}
        if data.get("code") != 1:
            return None

        trade_status = order_data.get("status", 0)
        if trade_status == 1:
            return StatusSyncResult(
                status_changed=True,
                new_status="paid",
                trade_no=order_data.get("trade_no", ""),
            )
        return None
```

## 5. 改造计划

### 5.1 新建文件清单

| 文件 | 说明 |
|------|------|
| `backend/services/payment/__init__.py` | 注册表 + 初始化 |
| `backend/services/payment/base.py` | 抽象基类 + 数据类 |
| `backend/services/payment/mock_gateway.py` | 模拟支付网关 |
| `backend/services/payment/alipay_gateway.py` | 支付宝网关 |
| `backend/services/payment/epay_gateway.py` | 易支付网关 |

### 5.2 现有文件修改清单

| 文件 | 改动 |
|------|------|
| `backend/main.py` | ① 删除 `_alipay_precreate`、`_alipay_config`、`_validate_alipay_config`、`_sync_alipay_order_status` ② 简化 `_order_checkout_payload()` ③ 简化 `subscribe_plan()` ④ 新增统一回调路由 ⑤ 启动时调用 `init_gateways()` |
| `backend/services/alipay_f2f.py` | **保留不动**，作为 AlipayGateway 的底层 SDK |
| `frontend/src/api.ts` | `PaymentSettings` 添加易支付配置字段 |
| `frontend/src/components/PaymentCheckoutDialog.tsx` | 适配易支付（跳转链接+二维码） |
| `frontend/src/components/admin/AdminPages.tsx` | 支付配置 tab 添加易支付参数输入 |
| `frontend/src/lib/format.ts` | 添加 `paymentMethodLabel` 映射 |

### 5.3 `main.py` 核心改动

**启动时注册网关**（在 `lifespan` 中）：
```python
from services.payment import init_gateways
init_gateways()
```

**统一支付路由**替换多个 if-elif：
```python
def _order_checkout_payload(order, plan, db):
    payment = _payment_settings_snapshot(db)
    method = order.payment_method or "mock_qr"
    gateway = get_gateway(method)

    if gateway:
        checkout = gateway.create_checkout(order, plan, payment)
        order.extra_json = {**(order.extra_json or {}), **checkout.extra}
        return gateway.build_checkout_response(order, plan, payment, checkout)

    # fallback
    ...
```

**统一异步回调路由**：
```python
@app.post("/api/payments/{provider}/notify")
async def payment_notify(provider: str, request: Request, db: Session = Depends(get_db)):
    # 查找对应 provider 的网关
    gateway = next((g for g in all_gateways() if g.provider == provider), None)
    if not gateway:
        return Response("unknown provider", status_code=404)

    body = await request.form()
    payment = _payment_settings_snapshot(db)
    result = gateway.verify_notify(dict(body), payment)

    if not result.verified:
        return Response("failure", media_type="text/plain", status_code=400)

    order = db.query(BillingOrder).filter(BillingOrder.order_no == ...).first()
    if result.trade_status == "paid":
        _mark_order_paid(order, db, note=f"{provider} notify confirmed")
    return Response("success", media_type="text/plain")
```

### 5.4 回调路由兼容性

- `POST /api/payments/alipay/notify` → 保留，或改为转发到统一路由
- `POST /alipay/notify` → 保留兼容
- `POST /api/payments/epay/notify` → 新增

### 5.5 种子数据更新

在 `_seed_platform_settings()` 中添加易支付的默认配置键：
```python
"payment.epay_enabled": False,
"payment.epay_gateway": "",
"payment.epay_pid": "",
"payment.epay_key": "",
"payment.epay_type": "alipay",
"payment.epay_notify_url": "",
"payment.epay_return_url": "",
```

## 6. 前端改动

### 6.1 PaymentCheckoutDialog

```typescript
// 易支付模式下显示"前往支付"按钮
{checkout.provider === 'epay' ? (
  <a
    href={checkout.payment_url}
    target="_blank"
    rel="noreferrer"
    className="...">
    前往易支付完成付款
  </a>
) : null}

// 统一显示"手动确认"按钮（支付宝和易支付都可用）
{['alipay_qr', 'epay_qr'].includes(checkout.method) ? (
  <button onClick={() => confirmPaid()}>我已完成支付</button>
) : null}
```

### 6.2 AdminPages 支付配置

在 `AdminPlatformSettingsPage` 的 `payment` 配置渲染中，添加易支付折叠面板：
```tsx
<EpayConfigSection
  config={payment}
  onChange={(key, value) => updatePayment(`epay_${key}`, value)}
/>
```

## 7. 实施步骤

| 步骤 | 内容 | 依赖 |
|------|------|------|
| 1 | 创建 `backend/services/payment/` 包 + `base.py`（抽象基类+数据类） | 无 |
| 2 | 实现 `mock_gateway.py` — 从 `main.py` 提取模拟支付逻辑 | 步骤 1 |
| 3 | 实现 `alipay_gateway.py` — 封装 `alipay_f2f` 调用 | 步骤 1 |
| 4 | 修改 `main.py` 路由使用 gateway 调用 | 步骤 2, 3 |
| 5 | 实现 `epay_gateway.py` — 易支付完整集成 | 步骤 1 |
| 6 | 添加易支付回调路由 `/api/payments/epay/notify` | 步骤 5 |
| 7 | 更新种子数据 + 数据库迁移 | 步骤 5 |
| 8 | 前端 API 类型 + `PaymentCheckoutDialog` 适配 | 步骤 5 |
| 9 | 管理后台易支付配置 UI | 步骤 5 |
| 10 | 测试：模拟支付正常、支付宝回归覆盖、易支付端到端 | 全部完成 |

## 8. 安全考虑

- **密钥存储**：易支付商户密钥存于 `platform_settings` 表（加密字段），仅在 `EpayGateway` 内部使用
- **回调验签**：严格 MD5 签名验证，防止伪造回调
- **金额校验**：回调中验证 `money` 与订单金额一致
- **防重放**：易支付回调自带 `out_trade_no`，使用 `_mark_order_paid` 的幂等保护（已实现）
- **HTTPS**：所有回调 URL 强制使用 HTTPS

## 9. 未来扩展

- **微信支付网关**：已有配置占位，实现时只需添加 `wechat_gateway.py` + 一行 `register_gateway(WechatGateway())`
- **更多聚合平台**：实现各自 gateway 后注册，`main.py` 无需修改
- **支付方式动态发现**：前端从 `/api/platform/settings/public` 获取已启用的支付方式列表
