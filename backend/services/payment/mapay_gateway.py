# MaPayGateway — 码支付开放接口（mapi.php / api.php）

import hashlib
from typing import Any

import httpx
from .base import PaymentGateway, CheckoutResult, NotifyResult, StatusSyncResult


def _mapay_sign(params: dict[str, Any], key: str) -> str:
    """Build the 码支付 MD5 signature.

    The open API signs all non-empty scalar params except sign/sign_type, sorted by
    ASCII key, then appends the merchant key directly before MD5 hashing.
    """
    items = []
    for name in sorted(params.keys()):
        value = params[name]
        if name in {"sign", "sign_type"} or value is None or isinstance(value, (list, dict)):
            continue
        text = str(value).strip()
        if not text:
            continue
        items.append(f"{name}={text}")
    return hashlib.md5(("&".join(items) + key).encode("utf-8")).hexdigest()


class MaPayGateway(PaymentGateway):
    method_key = "mapay_qr"
    provider = "mapay"
    label = "码支付"

    TYPE_LABELS: dict[str, str] = {
        "alipay": "支付宝",
        "wxpay": "微信支付",
        "qqpay": "QQ钱包",
        "usdt": "USDT",
    }

    @classmethod
    def get_type_options(cls, payment_config: dict[str, Any]) -> list[dict[str, Any]]:
        types_str = str(payment_config.get("mapay_type", "alipay"))
        types = [item.strip() for item in types_str.split(",") if item.strip()]
        return [
            {
                "key": f"mapay_{pay_type}",
                "label": f"码支付({cls.TYPE_LABELS.get(pay_type, pay_type)})",
                "provider": cls.provider,
            }
            for pay_type in types
        ]

    @classmethod
    def type_from_method_key(cls, method_key: str) -> str:
        parts = method_key.split("_", 1)
        return parts[1] if len(parts) > 1 else "alipay"

    def get_config_defaults(self) -> dict[str, Any]:
        return {
            "payment.mapay_enabled": False,
            "payment.mapay_gateway": "https://pay.21lili.cn",
            "payment.mapay_pid": "",
            "payment.mapay_key": "",
            "payment.mapay_type": "alipay",
            "payment.mapay_notify_url": "",
            "payment.mapay_return_url": "",
        }

    def create_checkout(
        self,
        order,
        plan,
        payment_config: dict[str, Any],
    ) -> CheckoutResult:
        gateway_url = str(payment_config.get("mapay_gateway") or "https://pay.21lili.cn").rstrip("/")
        pid = str(payment_config.get("mapay_pid") or "").strip()
        key = str(payment_config.get("mapay_key") or "").strip()
        pay_type = self.type_from_method_key(order.payment_method or "")
        if not pay_type or pay_type == "qr":
            configured = str(payment_config.get("mapay_type") or "alipay")
            pay_type = configured.split(",")[0].strip() or "alipay"

        if not gateway_url or not pid or not key:
            raise RuntimeError("码支付配置不完整: 缺少网关地址、商户ID或商户密钥")

        params: dict[str, Any] = {
            "pid": pid,
            "type": pay_type,
            "out_trade_no": order.order_no,
            "name": f"{plan.name}订阅"[:32],
            "money": f"{float(order.amount or 0):.2f}",
        }
        notify_url = str(payment_config.get("mapay_notify_url") or "").strip()
        return_url = str(payment_config.get("mapay_return_url") or "").strip()
        if notify_url:
            params["notify_url"] = notify_url
        if return_url:
            params["return_url"] = return_url

        client_ip = payment_config.get("client_ip", "")
        if client_ip:
            params["clientip"] = client_ip

        params["sign"] = _mapay_sign(params, key)
        params["sign_type"] = "MD5"

        try:
            response = httpx.post(f"{gateway_url}/mapi.php", data=params, timeout=15)
            response.raise_for_status()
            data = response.json()
        except httpx.TimeoutException:
            raise RuntimeError("码支付网关请求超时")
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(f"码支付网关返回错误状态码: {exc.response.status_code}") from exc
        except Exception as exc:
            raise RuntimeError(f"码支付下单失败: {exc}") from exc

        response_code = str(data.get("code") or "").strip()
        if response_code != "1":
            error_msg = data.get("msg") or "未知错误"
            raise RuntimeError(f"码支付返回错误(code={response_code or 'empty'}): {error_msg}")

        pay_url = str(data.get("payurl") or "")
        qr_code = str(data.get("qrcode") or "")
        trade_no = str(data.get("trade_no") or "")

        if qr_code:
            return CheckoutResult(
                mode="qrcode",
                payment_url=pay_url or qr_code,
                qr_code_text=qr_code,
                can_mock_confirm=False,
                extra={
                    "mapay_trade_no": trade_no,
                    "mapay_qr_code": qr_code,
                    "mapay_payment_url": pay_url or qr_code,
                },
            )
        return CheckoutResult(
            mode="redirect",
            payment_url=pay_url,
            qr_code_text="",
            can_mock_confirm=False,
            extra={"mapay_trade_no": trade_no, "mapay_payment_url": pay_url},
        )

    def verify_notify(
        self,
        body: dict[str, Any],
        payment_config: dict[str, Any],
    ) -> NotifyResult:
        key = str(payment_config.get("mapay_key") or "").strip()
        if not key:
            return NotifyResult(verified=False)

        expected = _mapay_sign(body, key)
        sign = str(body.get("sign") or "")
        if not sign or sign.lower() != expected.lower():
            return NotifyResult(verified=False)

        trade_status = str(body.get("trade_status") or "").strip()
        if trade_status == "TRADE_SUCCESS":
            return NotifyResult(
                verified=True,
                trade_status="paid",
                trade_no=str(body.get("trade_no") or ""),
                amount=str(body.get("money") or "0"),
                raw=dict(body),
            )
        if trade_status in {"TRADE_CLOSED", "TRADE_FAILED"}:
            return NotifyResult(
                verified=True,
                trade_status="failed",
                trade_no=str(body.get("trade_no") or ""),
                amount=str(body.get("money") or "0"),
                raw=dict(body),
            )
        return NotifyResult(
            verified=True,
            trade_no=str(body.get("trade_no") or ""),
            amount=str(body.get("money") or "0"),
            raw=dict(body),
        )

    def sync_status(
        self,
        order,
        payment_config: dict[str, Any],
    ) -> StatusSyncResult | None:
        gateway_url = str(payment_config.get("mapay_gateway") or "https://pay.21lili.cn").rstrip("/")
        pid = str(payment_config.get("mapay_pid") or "").strip()
        key = str(payment_config.get("mapay_key") or "").strip()
        if not gateway_url or not pid or not key:
            return None

        params = {
            "act": "order",
            "pid": pid,
            "key": key,
            "out_trade_no": order.order_no,
        }
        try:
            response = httpx.get(f"{gateway_url}/api.php", params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
        except Exception:
            return None

        if str(data.get("code") or "").strip() != "1":
            return None

        if str(data.get("status") or "").strip() == "1":
            return StatusSyncResult(
                status_changed=True,
                new_status="paid",
                trade_no=str(data.get("trade_no") or ""),
            )
        return StatusSyncResult(status_changed=False)
