# 支付网关抽象基类与数据结构

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
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class NotifyResult:
    """异步回调验签结果"""
    verified: bool
    trade_status: str | None = None  # "paid" / "failed"
    trade_no: str = ""
    amount: str = "0"
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class StatusSyncResult:
    """主动查询支付状态结果"""
    status_changed: bool
    new_status: str | None = None  # "paid" / "cancelled"
    trade_no: str = ""


class PaymentGateway(ABC):
    """支付网关抽象基类"""

    method_key: str = ""
    provider: str = ""
    label: str = ""

    def get_config_defaults(self) -> dict[str, Any]:
        return {}

    @abstractmethod
    def create_checkout(
        self,
        order: Any,
        plan: Any,
        payment_config: dict[str, Any],
    ) -> CheckoutResult:
        """创建支付订单，返回结账数据"""

    def verify_notify(
        self,
        body: dict[str, Any],
        payment_config: dict[str, Any],
    ) -> NotifyResult:
        raise NotImplementedError

    def sync_status(
        self,
        order: Any,
        payment_config: dict[str, Any],
    ) -> StatusSyncResult | None:
        return None

    def build_checkout_response(
        self,
        order: Any,
        plan: Any,
        payment_config: dict[str, Any],
        checkout: CheckoutResult,
    ) -> dict[str, Any]:
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
            "source": getattr(order, "source", "") or "",
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
