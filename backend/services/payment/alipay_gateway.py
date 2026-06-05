# AlipayGateway — 支付宝当面付封装

from typing import Any

import httpx
from .. import alipay_f2f
from .base import PaymentGateway, CheckoutResult, NotifyResult, StatusSyncResult


def _alipay_config(payment_config: dict[str, Any]) -> dict[str, Any]:
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

    def get_config_defaults(self) -> dict[str, Any]:
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

    def _validate_config(self, payment_config: dict[str, Any]) -> dict[str, Any]:
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
        payment_config: dict[str, Any],
    ) -> CheckoutResult:
        config = self._validate_config(payment_config)
        expire_minutes = max(1, int(payment_config.get("order_expire_minutes") or 30))
        timeout_express = f"{expire_minutes}m"
        subject = f"{plan.name} {('年付' if (order.billing_cycle or 'monthly') == 'yearly' else '月付')}"
        total_amount = f"{float(order.amount or 0):.2f}"

        try:
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
        except alipay_f2f.AlipayApiError as exc:
            raise RuntimeError(f"支付宝预创建订单失败: {exc}") from exc
        except alipay_f2f.AlipayConfigError as exc:
            raise RuntimeError(f"支付宝配置无效: {exc}") from exc
        except httpx.HTTPError as exc:
            raise RuntimeError(f"支付宝网关请求失败: {exc}") from exc

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
        body: dict[str, Any],
        payment_config: dict[str, Any],
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
        payment_config: dict[str, Any],
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
