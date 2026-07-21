# EpayGateway — 易支付集成（V1 MD5 签名，对应 maajiko/Epay）

import hashlib
import hmac
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx
from .base import PaymentGateway, CheckoutResult, NotifyResult, StatusSyncResult


def _paid_amount_matches(order, raw_amount: Any) -> bool:
    try:
        expected = Decimal(str(order.amount or 0)).quantize(Decimal("0.01"))
        actual = Decimal(str(raw_amount or "")).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return False
    return actual == expected


def _epay_sign(params: dict[str, Any], key: str) -> str:
    """彩虹易支付 V1 MD5 签名

    对应 maajiko/Epay Payment::makeSign:
        sign = md5( "k1=v1&k2=v2" + 商户密钥 )
    参数排序后拼接，排除 sign/sign_type/空值/数组，末尾直接拼接密钥（无 & 前缀）。
    """
    items = []
    for k in sorted(params.keys()):
        v = params[k]
        if v is None or v == "" or isinstance(v, (list, dict)):
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

    TYPE_LABELS: dict[str, str] = {
        "alipay": "支付宝",
        "wxpay": "微信支付",
        "qqpay": "QQ钱包",
        "tenpay": "财付通",
    }

    @classmethod
    def get_type_options(cls, payment_config: dict[str, Any]) -> list[dict[str, Any]]:
        """根据管理员配置的 epay_type 返回每个通道对应的支付方式选项"""
        types_str = str(payment_config.get("epay_type", "alipay"))
        types = [t.strip() for t in types_str.split(",") if t.strip()]
        return [
            {
                "key": f"epay_{t}",
                "label": f"易支付({cls.TYPE_LABELS.get(t, t)})",
                "provider": "epay",
            }
            for t in types
        ]

    @classmethod
    def type_from_method_key(cls, method_key: str) -> str:
        """从 method_key (如 epay_alipay) 提取通道类型 (alipay)"""
        parts = method_key.split("_", 1)
        return parts[1] if len(parts) > 1 else "alipay"

    def get_config_defaults(self) -> dict[str, Any]:
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
        payment_config: dict[str, Any],
    ) -> CheckoutResult:
        gateway_url = str(payment_config.get("epay_gateway") or "").rstrip("/")
        pid = str(payment_config.get("epay_pid") or "").strip()
        key = str(payment_config.get("epay_key") or "").strip()
        # 从 method_key 派生通道类型
        pay_type = self.type_from_method_key(order.payment_method or "")
        # epay_qr 是通用占位 → 使用配置的第一个通道
        if not pay_type or pay_type == "qr":
            configured = str(payment_config.get("epay_type") or "alipay")
            pay_type = configured.split(",")[0].strip()

        if not gateway_url or not pid or not key:
            raise RuntimeError("易支付配置不完整: 缺少网关地址、商户ID或商户密钥")

        params = {
            "pid": pid,
            "type": pay_type,
            "out_trade_no": order.order_no,
            "notify_url": str(payment_config.get("epay_notify_url") or "").strip(),
            "return_url": str(payment_config.get("epay_return_url") or "").strip(),
            "name": str(plan.name)[:32],
            "money": f"{float(order.amount or 0):.2f}",
        }
        # 易支付要求传递客户端 IP
        client_ip = payment_config.get("client_ip", "")
        if client_ip:
            params["clientip"] = client_ip
        params["sign"] = _epay_sign(params, key)
        params["sign_type"] = "MD5"

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

        # V1 API: code=1 为成功，code=-2 为错误
        response_code = data.get("code")
        if response_code != 1:
            error_msg = data.get("msg") or "未知错误"
            raise RuntimeError(f"易支付返回错误 (code={response_code}): {error_msg}")

        pay_url = str(data.get("payurl") or "")
        qr_code = str(data.get("qrcode") or "")
        trade_no = str(data.get("trade_no") or "")

        if qr_code:
            return CheckoutResult(
                mode="qrcode",
                payment_url=pay_url,
                qr_code_text=qr_code,
                can_mock_confirm=False,
                extra={
                    "epay_trade_no": trade_no,
                    "epay_qr_code": qr_code,
                    "epay_payment_url": pay_url,
                },
            )
        return CheckoutResult(
            mode="redirect",
            payment_url=pay_url,
            can_mock_confirm=False,
            extra={"epay_trade_no": trade_no, "epay_payment_url": pay_url},
        )

    def verify_notify(
        self,
        body: dict[str, Any],
        payment_config: dict[str, Any],
    ) -> NotifyResult:
        key = str(payment_config.get("epay_key") or "").strip()
        configured_pid = str(payment_config.get("epay_pid") or "").strip()
        callback_pid = str(body.get("pid") or "").strip()
        if not key or not configured_pid or callback_pid != configured_pid:
            return NotifyResult(verified=False)

        expected = _epay_sign(body, key)
        sign = body.get("sign", "")
        if not sign or not hmac.compare_digest(str(sign).lower(), expected.lower()):
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
        payment_config: dict[str, Any],
    ) -> StatusSyncResult | None:
        gateway_url = str(payment_config.get("epay_gateway") or "").rstrip("/")
        pid = str(payment_config.get("epay_pid") or "").strip()
        key_str = str(payment_config.get("epay_key") or "").strip()

        if not gateway_url or not pid or not key_str:
            return None

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

        if data.get("code") != 1:
            return None

        # api.php?act=order 返回扁平 JSON，status 在顶层而非 data 子对象
        status = data.get("status", 0)
        if status == 1 and _paid_amount_matches(order, data.get("money")):
            return StatusSyncResult(
                status_changed=True,
                new_status="paid",
                trade_no=str(data.get("trade_no") or ""),
            )
        return StatusSyncResult(status_changed=False)
