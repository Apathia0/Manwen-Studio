import base64
import datetime
import json
from typing import Any
from urllib.parse import quote_plus

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding


class AlipayConfigError(RuntimeError):
    pass


class AlipayApiError(RuntimeError):
    pass


def _strip_pem_markers(raw: str) -> str:
    text = (raw or "").strip().replace("\r", "")
    if "BEGIN" in text:
        return text
    body = "".join(line.strip() for line in text.split("\n") if line.strip())
    return body


def normalize_private_key(raw: str) -> str:
    text = _strip_pem_markers(raw)
    if "BEGIN" in text:
        return text
    return "-----BEGIN PRIVATE KEY-----\n" + text + "\n-----END PRIVATE KEY-----"


def normalize_public_key(raw: str) -> str:
    text = _strip_pem_markers(raw)
    if "BEGIN" in text:
        return text
    return "-----BEGIN PUBLIC KEY-----\n" + text + "\n-----END PUBLIC KEY-----"


def _ordered_sign_content(params: dict[str, Any]) -> str:
    items = []
    for key in sorted(params.keys()):
        value = params[key]
        if value is None or value == "":
            continue
        items.append(f"{key}={value}")
    return "&".join(items)


def _rsa2_sign(content: str, private_key: str, charset: str = "utf-8") -> str:
    signer = serialization.load_pem_private_key(normalize_private_key(private_key).encode(charset), password=None)
    signature = signer.sign(content.encode(charset), padding.PKCS1v15(), hashes.SHA256())
    return base64.b64encode(signature).decode(charset)


def rsa2_verify(content: str, signature: str, public_key: str, charset: str = "utf-8") -> bool:
    verifier = serialization.load_pem_public_key(normalize_public_key(public_key).encode(charset))
    verifier.verify(
        base64.b64decode(signature.encode(charset)),
        content.encode(charset),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
    return True


def build_gateway_url(gateway: str, params: dict[str, Any]) -> str:
    query = "&".join(
        f"{quote_plus(str(key))}={quote_plus(str(value))}"
        for key, value in params.items()
        if value is not None and value != ""
    )
    return f"{gateway}?{query}"


def call_api(
    *,
    gateway: str,
    app_id: str,
    private_key: str,
    method: str,
    biz_content: dict[str, Any],
    notify_url: str | None = None,
    charset: str = "utf-8",
    sign_type: str = "RSA2",
    version: str = "1.0",
    timeout_seconds: int = 15,
) -> dict[str, Any]:
    if sign_type.upper() != "RSA2":
        raise AlipayConfigError("Only RSA2 is supported by the current integration")
    params: dict[str, Any] = {
        "app_id": app_id.strip(),
        "method": method,
        "format": "JSON",
        "charset": charset,
        "sign_type": sign_type,
        "timestamp": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        "version": version,
        "biz_content": json.dumps(biz_content, ensure_ascii=False, separators=(",", ":")),
    }
    if notify_url:
        params["notify_url"] = notify_url.strip()
    params["sign"] = _rsa2_sign(_ordered_sign_content(params), private_key, charset=charset)

    # 支付宝官方规范：公共参数放 URL query string，biz_content 放 POST body。
    # charset 必须出现在 URL query 中，否则支付宝服务端无法确定编码导致验签失败。
    gateway_url = gateway.strip().rstrip("?")
    public_params = {k: v for k, v in params.items() if k != "biz_content"}
    url = build_gateway_url(gateway_url, public_params)
    body = {"biz_content": params["biz_content"]}

    response = httpx.post(url, data=body, timeout=timeout_seconds)
    response.raise_for_status()
    try:
        payload = response.json()
    except (UnicodeDecodeError, json.JSONDecodeError):
        content = response.content
        for enc in ("gbk", "gb2312", "utf-8"):
            try:
                payload = json.loads(content.decode(enc))
                break
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
        else:
            raise AlipayApiError("支付宝返回了无法解析的响应")
    if not isinstance(payload, dict):
        raise AlipayApiError("支付宝响应格式无效")
    response_key = f"{method.replace('.', '_')}_response"
    if response_key not in payload:
        error = payload.get("error_response") if isinstance(payload, dict) else None
        if isinstance(error, dict):
            message = error.get("sub_msg") or error.get("msg") or "支付宝请求失败"
            error_code = str(error.get("sub_code") or error.get("code") or "").strip()
            raise AlipayApiError(f"{error_code}: {message}" if error_code else message)
        raise AlipayApiError(f"支付宝响应缺少字段 {response_key}")
    result = payload[response_key]
    if not isinstance(result, dict):
        raise AlipayApiError(f"支付宝响应字段 {response_key} 格式无效")
    if result.get("code") != "10000":
        message = result.get("sub_msg") or result.get("msg") or "Unknown Alipay error"
        sub_code = str(result.get("sub_code") or "").strip()
        raise AlipayApiError(f"{sub_code}: {message}" if sub_code else message)
    return {"request": params, "response": payload, "result": result}


def precreate(
    *,
    gateway: str,
    app_id: str,
    private_key: str,
    notify_url: str,
    out_trade_no: str,
    total_amount: str,
    subject: str,
    seller_id: str | None = None,
    timeout_express: str | None = None,
    body: str | None = None,
    store_id: str | None = None,
) -> dict[str, Any]:
    biz_content: dict[str, Any] = {
        "out_trade_no": out_trade_no,
        "total_amount": total_amount,
        "subject": subject,
    }
    if seller_id:
        biz_content["seller_id"] = seller_id.strip()
    if timeout_express:
        biz_content["timeout_express"] = timeout_express.strip()
    if body:
        biz_content["body"] = body.strip()
    if store_id:
        biz_content["store_id"] = store_id.strip()
    return call_api(
        gateway=gateway,
        app_id=app_id,
        private_key=private_key,
        method="alipay.trade.precreate",
        biz_content=biz_content,
        notify_url=notify_url,
    )


def trade_query(
    *,
    gateway: str,
    app_id: str,
    private_key: str,
    out_trade_no: str,
    seller_id: str | None = None,
) -> dict[str, Any]:
    biz_content: dict[str, Any] = {
        "out_trade_no": out_trade_no,
    }
    if seller_id:
        biz_content["seller_id"] = seller_id.strip()
    return call_api(
        gateway=gateway,
        app_id=app_id,
        private_key=private_key,
        method="alipay.trade.query",
        biz_content=biz_content,
    )
