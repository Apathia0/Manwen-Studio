# MockGateway — 模拟支付

from typing import Any
from .base import PaymentGateway, CheckoutResult


class MockGateway(PaymentGateway):

    method_key = "mock_qr"
    provider = "mock"
    label = "模拟支付"

    def create_checkout(
        self,
        order,
        plan,
        payment_config: dict[str, Any],
    ) -> CheckoutResult:
        return CheckoutResult(
            mode="mock",
            payment_url=f"/mock-pay/{order.order_no}",
            qr_code_text=f"STORYCANVAS:mock_qr:{order.order_no}:{order.amount}",
            can_mock_confirm=True,
        )
