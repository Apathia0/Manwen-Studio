# 支付网关抽象层 + 易支付接入 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 StoryCanvas 建立支付网关抽象层，支持插件式支付方式注册，并接入易支付（V1标准/MD5签名）。

**Architecture:** 新增 `backend/services/payment/` 包，包含 `PaymentGateway` 抽象基类 + 注册表；将现有 `main.py` 中硬编码的支付宝/模拟支付逻辑迁移为独立 gateway；新增 `EpayGateway` 实现易支付集成。`main.py` 路由层通过 `get_gateway(method_key)` 多态调度，不再使用 if-elif 分支。

**Tech Stack:** Python 3.10+, FastAPI, httpx, hashlib (MD5)

---

## 文件变更清单

### 新建文件
| 文件 | 职责 |
|------|------|
| `backend/services/payment/__init__.py` | 注册表 `_gateways`、`register_gateway()`、`get_gateway()`、`get_method_options()`、`init_gateways()` |
| `backend/services/payment/base.py` | `PaymentGateway` 抽象基类、`CheckoutResult`/`NotifyResult`/`StatusSyncResult` 数据类 |
| `backend/services/payment/mock_gateway.py` | `MockGateway` — 从 `main.py` 提取的模拟支付逻辑 |
| `backend/services/payment/alipay_gateway.py` | `AlipayGateway` — 封装 `alipay_f2f` 调用的支付宝网关 |
| `backend/services/payment/epay_gateway.py` | `EpayGateway` — 易支付 V1 标准集成（MD5签名） |
| `backend/tests/test_payment_gateway.py` | 网关单元测试 |

### 修改文件
| 文件 | 改动 |
|------|------|
| `backend/main.py` | ① 导入 `init_gateways` 并在 lifespan 中调用；② `_payment_method_options()` → `get_method_options()`；③ `_order_checkout_payload()` → 通过 gateway 构建；④ `subscribe_plan()` 的 elif 分支 → gateway 调用；⑤ 新增 `/api/payments/{provider}/notify` 统一回调路由；⑥ 删除 `_alipay_precreate`/`_alipay_config`/`_validate_alipay_config`/`_sync_alipay_order_status`；⑦ 保留 `/api/payments/alipay/notify` 兼容 |
| `backend/main.py` 种子数据 | 添加 `payment.epay_*` 6 项默认配置 |
| `frontend/src/api.ts` | `PaymentSettings` 追加易支付配置字段 |
| `frontend/src/components/PaymentCheckoutDialog.tsx` | 适配易支付（跳转链接 + 手动确认） |
| `frontend/src/components/admin/AdminPages.tsx` | 支付配置 tab 添加易支付参数输入区 |
| `frontend/src/lib/format.ts` | 添加 `epay_qr → "易支付"` 映射 |

---

### Task 1: 创建支付网关基础包 (base + registry)

**Files:**
- Create: `backend/services/payment/__init__.py`
- Create: `backend/services/payment/base.py`

- [ ] **Step 1: 创建 `base.py` — 抽象基类和数据结构**

```python
# backend/services/payment/base.py

import datetime
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CheckoutResult:
    """创建支付订单的返回结果"""
    mode: str  # "redirect" / "qrcode" / "mock"
    payment_url: str = ""
    qr_code_text: str = ""
    can_mock_confirm: bool = False
    extra: dict = field(default_factory=dict)


@dataclass
class NotifyResult:
    """异步回调验签结果"""
    verified: bool
    trade_status: str | None = None  # "paid" / "failed"
    trade_no: str = ""
    amount: str = "0"
    raw: dict = field(default_factory=dict)


@dataclass
class StatusSyncResult:
    """主动查询支付状态结果"""
    status_changed: bool
    new_status: str | None = None  # "paid" / "cancelled"
    trade_no: str = ""


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
        return self.method_key

    def get_config_defaults(self) -> dict:
        return {}

    @abstractmethod
    def create_checkout(
        self,
        order: Any,
        plan: Any,
        payment_config: dict,
    ) -> CheckoutResult:
        """创建支付订单，返回结账数据"""

    def verify_notify(
        self,
        body: dict,
        payment_config: dict,
    ) -> NotifyResult:
        raise NotImplementedError

    def sync_status(
        self,
        order: Any,
        payment_config: dict,
    ) -> StatusSyncResult | None:
        return None

    def build_checkout_response(
        self,
        order: Any,
        plan: Any,
        payment_config: dict,
        checkout: CheckoutResult,
    ) -> dict:
        """构建前端可消费的 checkout 响应"""
        expire_minutes = int(payment_config.get("order_expire_minutes") or 30)
        expires_at = order.expired_at or (
            datetime.datetime.utcnow() + datetime.timedelta(minutes=expire_minutes)
        )
        amount_num = float(order.amount) if hasattr(order.amount, "__float__") else float(order.amount or 0)
        return {
            "mode": checkout.mode,
            "method": order.payment_method if hasattr(order, "payment_method") else self.method_key,
            "provider": order.payment_provider if hasattr(order, "payment_provider") else self.provider,
            "instructions": str(payment_config.get("instructions") or ""),
            "amount": amount_num,
            "currency": order.currency if hasattr(order, "currency") else "CNY",
            "plan_name": plan.name if hasattr(plan, "name") else "",
            "billing_cycle": getattr(order, "billing_cycle", None) or "monthly",
            "expires_at": expires_at.isoformat() if hasattr(expires_at, "isoformat") else str(expires_at),
            "qr_code_text": checkout.qr_code_text,
            "payment_url": checkout.payment_url,
            "can_mock_confirm": checkout.can_mock_confirm,
        }
```

- [ ] **Step 2: 创建 `__init__.py` — 注册表管理**

```python
# backend/services/payment/__init__.py

from .base import PaymentGateway, CheckoutResult, NotifyResult, StatusSyncResult

_gateways: dict[str, PaymentGateway] = {}


def register_gateway(gateway: PaymentGateway) -> None:
    """注册支付网关"""
    _gateways[gateway.method_key] = gateway


def get_gateway(method_key: str) -> PaymentGateway | None:
    """根据 method_key 获取网关实例"""
    return _gateways.get(method_key)


def get_gateway_by_provider(provider: str) -> PaymentGateway | None:
    """根据 provider 获取网关实例"""
    for g in _gateways.values():
        if g.provider == provider:
            return g
    return None


def all_gateways() -> list[PaymentGateway]:
    """获取所有已注册网关"""
    return list(_gateways.values())


def get_method_options(payment_config: dict) -> list[dict]:
    """返回所有已启用的支付方式选项"""
    results = []
    for method_key, gateway in _gateways.items():
        enabled_key = f"{gateway.provider}_enabled"
        # mock 支付默认启用
        if gateway.provider == "mock":
            if bool(payment_config.get("mock_enabled", True)):
                results.append({
                    "key": method_key,
                    "label": getattr(gateway, "label", method_key),
                    "enabled": True,
                    "provider": gateway.provider,
                })
        elif bool(payment_config.get(enabled_key, False)):
            results.append({
                "key": method_key,
                "label": getattr(gateway, "label", method_key),
                "enabled": True,
                "provider": gateway.provider,
            })
    return results


def init_gateways() -> None:
    """初始化所有网关（应用启动时调用）"""
    # 延迟导入避免循环依赖
    from .mock_gateway import MockGateway
    from .alipay_gateway import AlipayGateway
    from .epay_gateway import EpayGateway

    register_gateway(MockGateway())
    register_gateway(AlipayGateway())
    register_gateway(EpayGateway())


__all__ = [
    "PaymentGateway", "CheckoutResult", "NotifyResult", "StatusSyncResult",
    "register_gateway", "get_gateway", "get_gateway_by_provider", "all_gateways",
    "get_method_options", "init_gateways",
]
```

- [ ] **Step 3: 创建空的 `__init__.py` 让 payment 成为包**

确保 `backend/services/payment/` 目录存在，且不含其他 `__init__.py`。

- [ ] **Step 4: 验证导入**

运行: `cd backend && python -c "from services.payment import PaymentGateway, CheckoutResult, init_gateways; print('OK')"`
预期输出: `OK`

- [ ] **Step 5: Commit**

```bash
git add backend/services/payment/
git commit -m "feat: 创建支付网关抽象层 base + registry"
```

---

### Task 2: 实现 MockGateway

**Files:**
- Create: `backend/services/payment/mock_gateway.py`

- [ ] **Step 1: 创建 MockGateway**

```python
# backend/services/payment/mock_gateway.py

from .base import PaymentGateway, CheckoutResult


class MockGateway(PaymentGateway):

    method_key = "mock_qr"
    provider = "mock"
    label = "模拟支付"

    def create_checkout(
        self,
        order,
        plan,
        payment_config: dict,
    ) -> CheckoutResult:
        return CheckoutResult(
            mode="mock",
            payment_url=f"/mock-pay/{order.order_no}",
            qr_code_text=f"STORYCANVAS:mock_qr:{order.order_no}:{order.amount}",
            can_mock_confirm=True,
        )
```

- [ ] **Step 2: 验证导入**

运行: `cd backend && python -c "from services.payment import init_gateways, get_gateway; init_gateways(); g = get_gateway('mock_qr'); print(g.method_key, g.provider)"`
预期输出: `mock_qr mock`

- [ ] **Step 3: Commit**

```bash
git add backend/services/payment/mock_gateway.py
git commit -m "feat: 实现 MockGateway (模拟支付)"
```

---

### Task 3: 实现 AlipayGateway

**Files:**
- Create: `backend/services/payment/alipay_gateway.py`

- [ ] **Step 1: 创建 AlipayGateway**

```python
# backend/services/payment/alipay_gateway.py

import datetime
from services import alipay_f2f
from .base import PaymentGateway, CheckoutResult, NotifyResult, StatusSyncResult


def _alipay_config(payment_config: dict) -> dict:
    return {
        "app_id": str(payment_config.get("alipay_app_id") or "").strip(),
        "seller_id": str(payment_config.get("alipay_pid") or "").strip(),
        "gateway": str(payment_config.get("alipay_gateway") or "https://openapi.alipay.com/gateway.do").strip(),
        "sign_type": str(payment_config.get("alipay_sign_type") or "RSA2").strip() or "RSA2",
        "app_private_key": str(payment_config.get("alipay_app_private_key") or "").strip(),
        "alipay_public_key": str(payment_config.get("alipay_public_key") or "").strip(),
        "notify_url": str(payment_config.get("alipay_notify_url") or "").strip(),
    }


class AlipayGateway(PaymentGateway):

    method_key = "alipay_qr"
    provider = "alipay"
    label = "支付宝扫码"

    def get_config_defaults(self) -> dict:
        return {
            "payment.alipay_enabled": False,
            "payment.alipay_app_id": "",
            "payment.alipay_pid": "",
            "payment.alipay_gateway": "https://openapi.alipay.com/gateway.do",
            "payment.alipay_sign_type": "RSA2",
            "payment.alipay_app_private_key": "",
            "payment.alipay_public_key": "",
            "payment.alipay_notify_url": "",
        }

    def _validate_config(self, payment_config: dict) -> dict:
        config = _alipay_config(payment_config)
        required = {
            "app_id": "alipay_app_id",
            "gateway": "alipay_gateway",
            "app_private_key": "alipay_app_private_key",
            "alipay_public_key": "alipay_public_key",
            "notify_url": "alipay_notify_url",
        }
        missing = [setting_key for field, setting_key in required.items() if not config.get(field)]
        if missing:
            raise RuntimeError(f"Alipay configuration incomplete: {', '.join(missing)}")
        if config["sign_type"].upper() != "RSA2":
            raise RuntimeError("Only RSA2 is supported for Alipay face-to-face payment")
        return config

    def create_checkout(
        self,
        order,
        plan,
        payment_config: dict,
    ) -> CheckoutResult:
        config = self._validate_config(payment_config)
        expire_minutes = max(1, int(payment_config.get("order_expire_minutes") or 30))
        timeout_express = f"{expire_minutes}m"
        subject = f"{plan.name} {('年付' if (order.billing_cycle or 'monthly') == 'yearly' else '月付')}"
        total_amount = f"{float(order.amount or 0):.2f}"

        result = alipay_f2f.precreate(
            gateway=config["gateway"],
            app_id=config["app_id"],
            private_key=config["app_private_key"],
            notify_url=config["notify_url"],
            out_trade_no=order.order_no,
            total_amount=total_amount,
            subject=subject[:256],
            seller_id=config["seller_id"] or None,
            timeout_express=timeout_express,
            body=(plan.description or f"StoryCanvas subscription for {plan.name}")[:128],
            store_id="StoryCanvas",
        )

        qr_code = result["result"].get("qr_code") or ""
        return CheckoutResult(
            mode="qrcode",
            payment_url=qr_code,
            qr_code_text=qr_code,
            can_mock_confirm=False,
            extra={
                "alipay_qr_code": qr_code,
                "alipay_payment_url": qr_code,
                "alipay_precreate_response": result["result"],
            },
        )

    def verify_notify(
        self,
        body: dict,
        payment_config: dict,
    ) -> NotifyResult:
        config = _alipay_config(payment_config)
        signature = body.get("sign", "")
        if not signature:
            return NotifyResult(verified=False)

        params = {k: v for k, v in body.items() if k not in {"sign", "sign_type"}}
        sign_content = "&".join(
            f"{k}={params[k]}"
            for k in sorted(params.keys())
            if params[k] is not None and params[k] != ""
        )
        try:
            alipay_f2f.rsa2_verify(sign_content, signature, config["alipay_public_key"])
        except Exception:
            return NotifyResult(verified=False)

        trade_status = body.get("trade_status", "").strip()
        if trade_status in {"TRADE_SUCCESS", "TRADE_FINISHED"}:
            return NotifyResult(
                verified=True,
                trade_status="paid",
                trade_no=body.get("trade_no", ""),
                amount=body.get("total_amount", "0"),
                raw=body,
            )
        elif trade_status == "TRADE_CLOSED":
            return NotifyResult(
                verified=True,
                trade_status="failed",
                trade_no=body.get("trade_no", ""),
                raw=body,
            )
        return NotifyResult(verified=True, raw=body)

    def sync_status(
        self,
        order,
        payment_config: dict,
    ) -> StatusSyncResult | None:
        config = _alipay_config(payment_config)
        if not config.get("app_id") or not config.get("gateway"):
            return None

        try:
            result = alipay_f2f.trade_query(
                gateway=config["gateway"],
                app_id=config["app_id"],
                private_key=config["app_private_key"],
                out_trade_no=order.order_no,
                seller_id=config["seller_id"] or None,
            )
        except (alipay_f2f.AlipayApiError, alipay_f2f.AlipayConfigError):
            return None

        query_result = result.get("result", {})
        trade_status = str(query_result.get("trade_status") or "").strip()
        trade_no = str(query_result.get("trade_no") or "").strip()

        if trade_status in {"TRADE_SUCCESS", "TRADE_FINISHED"}:
            expected_amount = f"{float(order.amount or 0):.2f}"
            total_amount = str(query_result.get("total_amount") or "").strip()
            if total_amount and total_amount == expected_amount:
                return StatusSyncResult(
                    status_changed=True,
                    new_status="paid",
                    trade_no=trade_no,
                )
        elif trade_status == "TRADE_CLOSED":
            return StatusSyncResult(
                status_changed=True,
                new_status="cancelled",
                trade_no=trade_no,
            )
        return StatusSyncResult(status_changed=False)
```

- [ ] **Step 2: 验证导入**

运行: `cd backend && python -c "from services.payment import init_gateways, get_gateway; init_gateways(); g = get_gateway('alipay_qr'); print(g.method_key, g.provider)"`
预期输出: `alipay_qr alipay`

- [ ] **Step 3: Commit**

```bash
git add backend/services/payment/alipay_gateway.py
git commit -m "feat: 实现 AlipayGateway (封装 alipay_f2f)"
```

---

### Task 4: 实现 EpayGateway

**Files:**
- Create: `backend/services/payment/epay_gateway.py`

- [ ] **Step 1: 创建 EpayGateway**

```python
# backend/services/payment/epay_gateway.py

import hashlib
import httpx
from .base import PaymentGateway, CheckoutResult, NotifyResult, StatusSyncResult


def _epay_sign(params: dict, key: str) -> str:
    """彩虹易支付 V1 MD5 签名: 参数按 key 排序拼接，末尾直接拼接密钥再 MD5

    签名算法 (对应 maajiko/Epay Payment::makeSign):
        sign = md5( "k1=v1&k2=v2" + 商户密钥 )
    """
    items = []
    for k in sorted(params.keys()):
        v = params[k]
        if v is None or v == "" or isinstance(v, list) or isinstance(v, dict):
            continue
        if k in ("sign", "sign_type"):
            continue
        items.append(f"{k}={v}")
    sign_str = "&".join(items)
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

    def create_checkout(
        self,
        order,
        plan,
        payment_config: dict,
    ) -> CheckoutResult:
        gateway_url = str(payment_config.get("epay_gateway") or "").rstrip("/")
        pid = str(payment_config.get("epay_pid") or "").strip()
        key = str(payment_config.get("epay_key") or "").strip()
        pay_type = str(payment_config.get("epay_type") or "alipay").strip()

        if not gateway_url or not pid or not key:
            raise RuntimeError("易支付配置不完整: 缺少网关地址、商户ID或商户密钥")

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
        except httpx.TimeoutException:
            raise RuntimeError("易支付网关请求超时")
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(f"易支付网关返回错误状态码: {exc.response.status_code}")
        except Exception as exc:
            raise RuntimeError(f"易支付下单失败: {exc}") from exc

        # maajiko/Epay mapi.php V1: code=0 成功
        if data.get("code") != 0:
            raise RuntimeError(f"易支付返回错误: {data.get('msg', '未知错误')}")

        # payurl = 跳转链接（支付宝/QQ钱包），qrcode = 二维码（微信扫码）
        pay_url = str(data.get("payurl") or "")
        qr_code = str(data.get("qrcode") or "")
        trade_no = str(data.get("trade_no") or "")

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

    def verify_notify(
        self,
        body: dict,
        payment_config: dict,
    ) -> NotifyResult:
        key = str(payment_config.get("epay_key") or "").strip()
        if not key:
            return NotifyResult(verified=False)

        # 传入 body 给 _epay_sign，内部跳过 sign/sign_type
        expected = _epay_sign(body, key)
        sign = body.get("sign", "")
        if not sign or sign.lower() != expected.lower():
            return NotifyResult(verified=False)

        trade_status = str(body.get("trade_status") or "").strip()
        if trade_status == "TRADE_SUCCESS":
            return NotifyResult(
                verified=True,
                trade_status="paid",
                trade_no=body.get("trade_no", ""),
                amount=body.get("money", "0"),
                raw=dict(body),
            )
        return NotifyResult(
            verified=True,
            trade_status="failed",
            trade_no=body.get("trade_no", ""),
            raw=dict(body),
        )

    def sync_status(
        self,
        order,
        payment_config: dict,
    ) -> StatusSyncResult | None:
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

        # maajiko/Epay: code=1 查到订单, code=-1 未查到
        order_data = data.get("data") or {}
        if data.get("code") != 1:
            return None

        status = order_data.get("status", 0)
        if status == 1:
            return StatusSyncResult(
                status_changed=True,
                new_status="paid",
                trade_no=str(order_data.get("trade_no") or ""),
            )
        return StatusSyncResult(status_changed=False)
```

- [ ] **Step 2: 验证导入**

运行: `cd backend && python -c "from services.payment import init_gateways, get_gateway; init_gateways(); g = get_gateway('epay_qr'); print(g.method_key, g.provider, g.label)"`
预期输出: `epay_qr epay 易支付`

- [ ] **Step 3: Commit**

```bash
git add backend/services/payment/epay_gateway.py
git commit -m "feat: 实现 EpayGateway (易支付 V1 MD5签名)"
```

---

### Task 5: 重构 main.py — 集成支付网关

**Files:**
- Modify: `backend/main.py`

这是最核心的改造步骤。我们需要：
1. 在文件顶部导入 gateway 相关模块
2. 在 `lifespan` 中调用 `init_gateways()`
3. 替换 `_payment_method_options()` 为 gateway 版本
4. 替换 `_order_checkout_payload()` 为 gateway 版本
5. 简化 `subscribe_plan()` 中的支付分支
6. 新增统一回调路由（保留旧路由做兼容转发）
7. 在种子数据中添加易支付配置项
8. 删除不再需要的旧函数

- [ ] **Step 1: 在文件头部（import 区域）添加 gateway 导入**

在 `backend/main.py` 的 import 部分（约第 50-70 行）添加：
```python
from services.payment import (
    init_gateways, get_gateway, get_gateway_by_provider,
    get_method_options, all_gateways,
    PaymentGateway, CheckoutResult,
)
```

- [ ] **Step 2: 在 `lifespan` 启动时注册网关**

在 `lifespan` 函数中（`SYSTEM_READY = True` 之前）添加：
```python
try:
    init_gateways()
except Exception as exc:
    logger.warning("Payment gateway initialization failed: %s", exc)
```

- [ ] **Step 3: 替换 `_payment_method_options()`**

将原有的 `_payment_method_options` 函数（约行698-705）替换为 gateway 版本：
```python
def _payment_method_options(db: Session) -> list[dict]:
    payment = _payment_settings_snapshot(db)
    return get_method_options(payment)
```

- [ ] **Step 4: 替换 `_order_checkout_payload()`**

将原有的 `_order_checkout_payload` 函数（约行2325-2352）替换为 gateway 版本：
```python
def _order_checkout_payload(order: BillingOrder, plan: Plan, db: Session) -> dict:
    payment = _payment_settings_snapshot(db)
    method = order.payment_method or str(payment.get("default_method") or "mock_qr")
    provider = order.payment_provider or "mock"
    gateway = get_gateway(method)

    if gateway is not None:
        checkout = gateway.create_checkout(order, plan, payment)
        if checkout.extra:
            merged = dict(order.extra_json or {})
            merged.update(checkout.extra)
            order.extra_json = merged
        return gateway.build_checkout_response(order, plan, payment, checkout)

    # Fallback — 无对应 gateway 时返回基本数据
    expire_minutes = int(payment.get("order_expire_minutes") or 30)
    expires_at = order.expired_at or (datetime.datetime.utcnow() + datetime.timedelta(minutes=expire_minutes))
    amount_num = float(order.amount or 0)
    return {
        "mode": str(payment.get("mode") or "mock"),
        "method": method,
        "provider": provider,
        "instructions": str(payment.get("instructions") or ""),
        "amount": amount_num,
        "currency": order.currency,
        "plan_name": plan.name,
        "billing_cycle": order.billing_cycle or "monthly",
        "expires_at": expires_at,
        "qr_code_text": "",
        "payment_url": "",
        "can_mock_confirm": False,
    }
```

- [ ] **Step 5: 简化 `subscribe_plan()` 中的支付分支**

将 `subscribe_plan` 函数（约行4151-4161）中的 if-elif 分支替换为：
```python
    db.add(order)
    checkout_override = None
    if _coerce_money(amount) <= Decimal("0.00") and bool(payment.get("auto_activate_free_plan", True)):
        _mark_order_paid(order, db, operator_user_id=user.id, note=f"Auto-activated free plan {plan.name}")
    else:
        gateway = get_gateway(payment_method)
        if gateway is not None:
            try:
                checkout_data = gateway.create_checkout(order, plan, payment)
                if checkout_data.extra:
                    merged = dict(order.extra_json or {})
                    merged.update(checkout_data.extra)
                    order.extra_json = merged
                checkout_override = gateway.build_checkout_response(order, plan, payment, checkout_data)
            except RuntimeError as exc:
                raise HTTPException(502, f"{gateway.label} checkout failed: {exc}") from exc
```

- [ ] **Step 6: 替换 `my_order_sync` 中的硬编码支付宝查询**

在 `my_order_sync` 路由（约行4084-4100）中，将：
```python
    if order.payment_method == "alipay_qr" and order.status == "pending":
        order = _sync_alipay_order_status(order, db)
```
替换为 gateway 调用：
```python
    if order.status == "pending":
        gateway = get_gateway(order.payment_method or "")
        if gateway is not None:
            payment = _payment_settings_snapshot(db)
            sync_result = gateway.sync_status(order, payment)
            if sync_result and sync_result.status_changed:
                if sync_result.new_status == "paid":
                    _mark_order_paid(order, db, note=f"{gateway.provider} sync confirmed trade {sync_result.trade_no}")
                elif sync_result.new_status == "cancelled":
                    _mark_order_cancelled(order, db, note=f"{gateway.provider} sync closed trade {sync_result.trade_no}")
                db.commit()
                db.refresh(order)
```

- [ ] **Step 7: 新增统一回调路由**

在 `/api/payments/alipay/notify` 路由附近添加统一回调路由：
```python
@app.post("/api/payments/{provider}/notify")
async def payment_notify(provider: str, request: Request, db: Session = Depends(get_db)):
    """统一支付回调入口 — 自动分派到对应 gateway"""
    _ensure_platform_seed(db)
    gateway = get_gateway_by_provider(provider)
    if not gateway:
        return Response("unknown provider", media_type="text/plain", status_code=404)

    # 解析请求体（form-urlencoded）
    raw_body = (await request.body()).decode("utf-8", errors="ignore")
    body = {key: value for key, value in parse_qsl(raw_body, keep_blank_values=True)}
    payment = _payment_settings_snapshot(db)

    result = gateway.verify_notify(body, payment)
    if not result.verified:
        return Response("failure", media_type="text/plain", status_code=400)

    order_no = body.get("out_trade_no", "").strip()
    if not order_no:
        return Response("failure", media_type="text/plain", status_code=400)

    order = db.query(BillingOrder).filter(BillingOrder.order_no == order_no).first()
    if not order:
        return Response("failure", media_type="text/plain", status_code=404)

    # 金额校验
    if result.trade_status == "paid":
        expected_amount = f"{float(order.amount or 0):.2f}"
        if result.amount and result.amount != expected_amount:
            return Response("failure", media_type="text/plain", status_code=400)

        extra = dict(order.extra_json or {})
        extra[f"{provider}_trade_no"] = result.trade_no
        extra[f"{provider}_notify_payload"] = result.raw
        order.extra_json = extra

        _mark_order_paid(order, db, note=f"{provider} notify confirmed trade {result.trade_no}")
        _write_audit_log(None, f"{provider}_notify_paid", "billing_order", order.order_no,
                         f"{provider} async notify marked order paid", db, {
                             "order_no": order.order_no,
                             "trade_no": result.trade_no,
                             "plan_id": order.plan_id,
                         })
    elif result.trade_status == "failed":
        _mark_order_cancelled(order, db, note=f"{provider} notify closed trade {result.trade_no}")

    db.commit()
    return Response("success", media_type="text/plain")
```

- [ ] **Step 8: 保留支付宝旧回调的兼容转发**

- [ ] **Step 9: 删除不再需要的旧函数**

- [ ] **Step 10: 在种子数据中添加易支付配置**

- [ ] **Step 11: 验证 Python 语法**

- [ ] **Step 12: Commit**

```bash
git add backend/main.py
git commit -m "refactor: main.py 支付逻辑改为通过 gateway 调度，新增易支付种子数据"
```

---

### Task 6: 前端 API 类型更新

**Files:**
- Modify: `frontend/src/api.ts`

- [ ] **Step 1: 在 `PaymentSettings` 接口添加易支付字段**

找到 `PaymentSettings` 接口（约行554-575），在 `wechat_*` 字段之后添加：
```typescript
  epay_enabled?: boolean;
  epay_gateway?: string;
  epay_pid?: string;
  epay_key?: string;
  epay_type?: string;
  epay_notify_url?: string;
  epay_return_url?: string;
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/api.ts
git commit -m "feat: PaymentSettings 添加易支付配置字段"
```

---

### Task 7: 前端 PaymentCheckoutDialog 适配

**Files:**
- Modify: `frontend/src/components/PaymentCheckoutDialog.tsx`

- [ ] **Step 1: 修改支付方式判断逻辑**

找到 `{checkout.provider === 'alipay' ? ...}` 的提示文字（约行92），改为包含易支付：
```tsx
            <div className="mt-4 text-center text-sm text-slate-600">
              {checkout.provider === 'alipay'
                ? '打开支付宝扫一扫完成付款'
                : checkout.provider === 'epay'
                  ? '将在新页面跳转到易支付收银台'
                  : '请使用对应支付 App 扫码完成付款'}
            </div>
```

- [ ] **Step 2: 修改"我已完成支付"按钮的显示条件**

找到 `{checkout.method === 'alipay_qr' ? (`（约行134），改为：
```tsx
              {['alipay_qr', 'epay_qr'].includes(checkout.method) ? (
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/PaymentCheckoutDialog.tsx
git commit -m "feat: PaymentCheckoutDialog 适配易支付显示"
```

---

### Task 8: 前端 fromat.ts 添加易支付 label

**Files:**
- Modify: `frontend/src/lib/format.ts`

- [ ] **Step 1: 在 `paymentMethodLabel` 函数中添加 `epay_qr`**

找到 `paymentMethodLabel` 函数，添加：
```typescript
export function paymentMethodLabel(method: string): string {
  const labels: Record<string, string> = {
    mock_qr: '模拟支付',
    alipay_qr: '支付宝',
    wechat_qr: '微信支付',
    epay_qr: '易支付',
  };
  return labels[method] || method;
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/lib/format.ts
git commit -m "feat: format.ts 添加易支付标签映射"
```

---

### Task 9: 管理后台易支付配置 UI

**Files:**
- Modify: `frontend/src/components/admin/AdminPages.tsx`

- [ ] **Step 1: 在支付配置 tab 添加易支付配置区**

在 `AdminPlatformSettingsPage` 中找到支付配置渲染部分（约行1091附近），在支付宝配置之后添加易支付配置折叠面板：

查找 `AdminPlatformSettingsPage` 函数中的支付配置部分，添加以下 JSX：

```tsx
              {/* 易支付配置 */}
              <div className="rounded-2xl border border-[#d7e3f4] bg-white p-5">
                <div className="flex items-center gap-3">
                  <input
                    type="checkbox"
                    checked={!!payment.epay_enabled}
                    onChange={(e) => updateSettings('payment', 'epay_enabled', e.target.checked)}
                    className="h-4 w-4 rounded border-slate-300"
                  />
                  <div>
                    <div className="text-sm font-semibold text-slate-900">易支付</div>
                    <div className="text-xs text-slate-500">接入易支付聚合平台（V1 协议，MD5 签名）</div>
                  </div>
                </div>
                {payment.epay_enabled ? (
                  <div className="mt-4 grid gap-4 sm:grid-cols-2">
                    <div>
                      <label className="text-xs text-slate-500">网关地址</label>
                      <input
                        type="text"
                        value={payment.epay_gateway || ''}
                        onChange={(e) => updateSettings('payment', 'epay_gateway', e.target.value)}
                        placeholder="https://your-epay.com"
                        className="mt-1 w-full rounded-xl border border-[#d7e3f4] px-3 py-2 text-sm"
                      />
                    </div>
                    <div>
                      <label className="text-xs text-slate-500">商户ID</label>
                      <input
                        type="text"
                        value={payment.epay_pid || ''}
                        onChange={(e) => updateSettings('payment', 'epay_pid', e.target.value)}
                        className="mt-1 w-full rounded-xl border border-[#d7e3f4] px-3 py-2 text-sm"
                      />
                    </div>
                    <div>
                      <label className="text-xs text-slate-500">商户密钥</label>
                      <input
                        type="password"
                        value={payment.epay_key || ''}
                        onChange={(e) => updateSettings('payment', 'epay_key', e.target.value)}
                        className="mt-1 w-full rounded-xl border border-[#d7e3f4] px-3 py-2 text-sm"
                      />
                    </div>
                    <div>
                      <label className="text-xs text-slate-500">默认支付方式</label>
                      <select
                        value={payment.epay_type || 'alipay'}
                        onChange={(e) => updateSettings('payment', 'epay_type', e.target.value)}
                        className="mt-1 w-full rounded-xl border border-[#d7e3f4] px-3 py-2 text-sm"
                      >
                        <option value="alipay">支付宝</option>
                        <option value="wxpay">微信支付</option>
                        <option value="qqpay">QQ钱包</option>
                      </select>
                    </div>
                    <div>
                      <label className="text-xs text-slate-500">异步通知地址</label>
                      <input
                        type="text"
                        value={payment.epay_notify_url || ''}
                        onChange={(e) => updateSettings('payment', 'epay_notify_url', e.target.value)}
                        placeholder="https://your-site.com/api/payments/epay/notify"
                        className="mt-1 w-full rounded-xl border border-[#d7e3f4] px-3 py-2 text-sm"
                      />
                    </div>
                    <div>
                      <label className="text-xs text-slate-500">同步跳转地址</label>
                      <input
                        type="text"
                        value={payment.epay_return_url || ''}
                        onChange={(e) => updateSettings('payment', 'epay_return_url', e.target.value)}
                        className="mt-1 w-full rounded-xl border border-[#d7e3f4] px-3 py-2 text-sm"
                      />
                    </div>
                  </div>
                ) : null}
              </div>
```

- [ ] **Step 2: LSP 检查**

运行: LSP 诊断检查 `AdminPages.tsx`

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/admin/AdminPages.tsx
git commit -m "feat: 管理后台添加易支付配置面板"
```

---

### Task 10: 单元测试

**Files:**
- Create: `backend/tests/test_payment_gateway.py`

- [ ] **Step 1: 编写网关注册和基础测试**

```python
# backend/tests/test_payment_gateway.py

"""支付网关单元测试"""

from services.payment import (
    PaymentGateway, CheckoutResult, NotifyResult, StatusSyncResult,
    register_gateway, get_gateway, get_gateway_by_provider,
    get_method_options, all_gateways, init_gateways,
)


class TestGatewayRegistry:
    """测试网关注册表"""

    def test_register_and_get(self):
        init_gateways()
        assert get_gateway("mock_qr") is not None
        assert get_gateway("alipay_qr") is not None
        assert get_gateway("epay_qr") is not None
        assert get_gateway("nonexistent") is None

    def test_get_gateway_by_provider(self):
        init_gateways()
        assert get_gateway_by_provider("mock") is not None
        assert get_gateway_by_provider("alipay") is not None
        assert get_gateway_by_provider("epay") is not None
        assert get_gateway_by_provider("unknown") is None

    def test_all_gateways(self):
        init_gateways()
        gateways = all_gateways()
        methods = {g.method_key for g in gateways}
        assert "mock_qr" in methods
        assert "alipay_qr" in methods
        assert "epay_qr" in methods

    def test_get_method_options_mock_only(self):
        init_gateways()
        config = {"mock_enabled": True}
        options = get_method_options(config)
        keys = {o["key"] for o in options}
        assert "mock_qr" in keys
        assert "alipay_qr" not in keys
        assert "epay_qr" not in keys

    def test_get_method_options_all_enabled(self):
        init_gateways()
        config = {
            "mock_enabled": True,
            "alipay_enabled": True,
            "epay_enabled": True,
        }
        options = get_method_options(config)
        keys = {o["key"] for o in options}
        assert "mock_qr" in keys
        assert "alipay_qr" in keys
        assert "epay_qr" in keys


class TestMockGateway:
    """测试模拟支付网关"""

    def test_create_checkout(self):
        init_gateways()
        gateway = get_gateway("mock_qr")

        class MockOrder:
            order_no = "TEST123"
            amount = 5900
            currency = "CNY"
            billing_cycle = "monthly"
            payment_method = "mock_qr"
            payment_provider = "mock"
            expired_at = None
            extra_json = {}

        class MockPlan:
            name = "Pro"

        result = gateway.create_checkout(MockOrder(), MockPlan(), {})
        assert result.mode == "mock"
        assert result.can_mock_confirm is True
        assert "TEST123" in result.qr_code_text

    def test_build_checkout_response(self):
        init_gateways()
        gateway = get_gateway("mock_qr")

        class MockOrder:
            order_no = "TEST123"
            amount = 5900
            currency = "CNY"
            billing_cycle = "monthly"
            payment_method = "mock_qr"
            payment_provider = "mock"
            expired_at = None
            extra_json = {}

        class MockPlan:
            name = "Pro"

        checkout = gateway.create_checkout(MockOrder(), MockPlan(), {})
        resp = gateway.build_checkout_response(MockOrder(), MockPlan(), {}, checkout)
        assert resp["method"] == "mock_qr"
        assert resp["provider"] == "mock"
        assert resp["can_mock_confirm"] is True
        assert resp["amount"] == 5900.0
        assert resp["plan_name"] == "Pro"


class TestEpayGateway:
    """测试易支付网关"""

    def test_config_defaults(self):
        init_gateways()
        gateway = get_gateway("epay_qr")
        defaults = gateway.get_config_defaults()
        assert "payment.epay_enabled" in defaults
        assert "payment.epay_gateway" in defaults
        assert "payment.epay_pid" in defaults
        assert "payment.epay_key" in defaults

    def test_epay_sign(self):
        """验证易支付 MD5 签名算法"""
        from services.payment.epay_gateway import _epay_sign
        params = {
            "pid": "1001",
            "type": "alipay",
            "out_trade_no": "TEST202501010001",
            "money": "59.00",
        }
        sign = _epay_sign(params, "test_key_123")
        assert isinstance(sign, str)
        assert len(sign) == 32  # MD5 hex is always 32 chars

    def test_verify_notify_valid(self):
        init_gateways()
        gateway = get_gateway("epay_qr")

        from services.payment.epay_gateway import _epay_sign
        params = {
            "out_trade_no": "TEST123",
            "trade_no": "EPAY202501010001",
            "trade_status": "TRADE_SUCCESS",
            "money": "59.00",
        }
        key = "test_key"
        params["sign"] = _epay_sign(params, key)
        params["sign_type"] = "MD5"

        config = {"epay_key": key}
        result = gateway.verify_notify(params, config)
        assert result.verified is True
        assert result.trade_status == "paid"
        assert result.trade_no == "EPAY202501010001"

    def test_verify_notify_invalid_sign(self):
        init_gateways()
        gateway = get_gateway("epay_qr")

        params = {
            "out_trade_no": "TEST123",
            "trade_no": "EPAY202501010001",
            "trade_status": "TRADE_SUCCESS",
            "sign": "invalid_sign",
            "sign_type": "MD5",
        }
        config = {"epay_key": "test_key"}
        result = gateway.verify_notify(params, config)
        assert result.verified is False

    def test_create_checkout_missing_config(self):
        init_gateways()
        gateway = get_gateway("epay_qr")

        class MockOrder:
            order_no = "TEST123"
            amount = 5900
            billing_cycle = "monthly"
            payment_method = "epay_qr"
            payment_provider = "epay"
            expired_at = None
            extra_json = {}

        class MockPlan:
            name = "Pro"

        import pytest
        with pytest.raises(RuntimeError, match="易支付配置不完整"):
            gateway.create_checkout(MockOrder(), MockPlan(), {})
```

- [ ] **Step 2: 运行测试**

运行: `cd backend && pytest tests/test_payment_gateway.py -v`
预期输出: 所有 test 通过

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_payment_gateway.py
git commit -m "test: 支付网关单元测试"
```

---

### Task 11: 集成验证

**Files:**
- Modify: `backend/main.py` (如果发现问题)

- [ ] **Step 1: 运行所有后端测试，确保不破坏现有功能**

运行: `cd backend && pytest tests/ -v`
预期: 所有既有测试通过 + 新测试通过

- [ ] **Step 2: 全局 LSP 诊断检查**

运行: 对 `backend/` 和 `frontend/src/` 分别执行 LSP 诊断

- [ ] **Step 3: 前端项目编译**

运行: `cd frontend && npx tsc --noEmit`
预期: 没有类型错误

- [ ] **Step 4: 最终提交**

```bash
git add -A
git commit -m "feat: 支付网关抽象层 + 易支付接入完成"
```
