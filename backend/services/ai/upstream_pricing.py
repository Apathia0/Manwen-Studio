from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlparse, urlunparse

import httpx
from fastapi import HTTPException

from models import AiChannel, AiModel
from services.ai import channels as ai_channels
from services.points.pricing import quantize_points


_MAX_RESPONSE_BYTES = 1024 * 1024
_MAX_YUAN_TO_POINTS = Decimal("1000000000")
_DEFAULT_STATUS_PATH = "/api/status"
_DEFAULT_PRICING_PATH = "/api/pricing"


@dataclass(frozen=True)
class UpstreamPricingSnapshot:
    quota_display_type: str
    quota_per_unit: Decimal
    group: str
    group_ratio: Decimal
    pricing_version: str
    rows_by_model_key: dict[str, dict[str, Any]]


def _decimal(value: Any, label: str, *, positive: bool = False) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"{label}必须是有限数字")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{label}必须是有限数字") from exc
    if not number.is_finite() or number < 0 or (positive and number <= 0):
        qualifier = "正数" if positive else "非负数字"
        raise ValueError(f"{label}必须是有限{qualifier}")
    return number


def validate_yuan_to_points(value: Any) -> Decimal:
    """校验人民币到积分的换算比例。"""
    try:
        number = _decimal(value, "人民币积分换算比例", positive=True)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if number > _MAX_YUAN_TO_POINTS or not math.isfinite(float(number)):
        raise HTTPException(400, f"人民币积分换算比例不能超过 {_MAX_YUAN_TO_POINTS}")
    return number


def _relative_path(value: Any, label: str, default: str) -> str:
    path = str(value or default).strip()
    if not path.startswith("/") or path.startswith("//") or "?" in path or "#" in path:
        raise HTTPException(400, f"{label}必须是无查询参数和片段的站内相对路径")
    return path


def _pricing_config(channel: AiChannel) -> tuple[str, str, str]:
    extra = channel.extra_config_json if isinstance(channel.extra_config_json, dict) else {}
    pricing = extra.get("pricing") if isinstance(extra.get("pricing"), dict) else {}
    protocol = str(pricing.get("protocol") or "new_api_v1").strip()
    if protocol != "new_api_v1":
        raise HTTPException(400, "仅支持 new_api_v1 价格同步协议")
    status_path = _relative_path(pricing.get("status_path"), "状态接口路径", _DEFAULT_STATUS_PATH)
    pricing_path = _relative_path(pricing.get("pricing_path"), "价格接口路径", _DEFAULT_PRICING_PATH)
    group = str(pricing.get("group") or "default").strip()
    if not group or len(group) > 64:
        raise HTTPException(400, "价格同步分组无效")
    return status_path, pricing_path, group


def _origin(base_url: str) -> str:
    parsed = urlparse((base_url or "").strip())
    if parsed.scheme != "https" or not parsed.hostname:
        raise HTTPException(400, "渠道 Base URL 无效，无法同步价格")
    return urlunparse((parsed.scheme, parsed.netloc, "", "", "", ""))


async def _get_json(client: httpx.AsyncClient, url: str, headers: dict[str, str]) -> dict[str, Any]:
    try:
        response = await client.get(url, headers=headers)
    except httpx.HTTPError as exc:
        raise HTTPException(502, "上游价格接口连接失败") from exc
    if not response.is_success:
        raise HTTPException(502, f"上游价格接口请求失败（HTTP {response.status_code}）")
    if len(response.content) > _MAX_RESPONSE_BYTES:
        raise HTTPException(502, "上游价格接口响应超过 1MiB 限制")
    try:
        payload = response.json()
    except ValueError as exc:
        raise HTTPException(502, "上游价格接口返回了无效 JSON") from exc
    if not isinstance(payload, dict):
        raise HTTPException(502, "上游价格接口响应格式无效")
    return payload


def _response_data(payload: dict[str, Any], label: str) -> Any:
    if payload.get("success") is False:
        raise HTTPException(502, f"上游{label}接口返回失败状态")
    if "data" not in payload:
        raise HTTPException(502, f"上游{label}接口缺少 data")
    return payload["data"]


def _pricing_version(
    *,
    status_data: dict[str, Any],
    pricing_rows: list[Any],
    group: str,
    group_ratio: Decimal,
) -> str:
    canonical = json.dumps(
        {
            "quota_display_type": status_data.get("quota_display_type"),
            "quota_per_unit": status_data.get("quota_per_unit"),
            "group": group,
            "group_ratio": str(group_ratio),
            "pricing": pricing_rows,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def fetch_new_api_pricing(channel: AiChannel) -> UpstreamPricingSnapshot:
    """抓取并验证 New API 状态与价格快照。"""
    status_path, pricing_path, group = _pricing_config(channel)
    validated_base_url = ai_channels.validate_base_url(channel.base_url, allow_http=False)
    origin = _origin(validated_base_url)
    api_key = ai_channels.load_platform_key(channel)
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    timeout_seconds = min(max(int(channel.timeout_seconds or 20), 5), 30)
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(timeout_seconds),
        follow_redirects=False,
    ) as client:
        status_payload = await _get_json(client, f"{origin}{status_path}", headers)
        pricing_payload = await _get_json(client, f"{origin}{pricing_path}", headers)

    status_data = _response_data(status_payload, "状态")
    pricing_rows = _response_data(pricing_payload, "价格")
    if not isinstance(status_data, dict) or not isinstance(pricing_rows, list):
        raise HTTPException(502, "上游价格接口响应格式无效")
    if str(status_data.get("quota_display_type") or "").upper() != "CNY":
        raise HTTPException(502, "上游额度币种不是 CNY，无法同步")
    try:
        quota_per_unit = _decimal(status_data.get("quota_per_unit"), "quota_per_unit", positive=True)
    except ValueError as exc:
        raise HTTPException(502, f"上游状态数据无效：{exc}") from exc

    group_ratios = pricing_payload.get("group_ratio")
    if not isinstance(group_ratios, dict):
        group_ratios = status_data.get("group_ratio")
    if not isinstance(group_ratios, dict):
        group_ratios = {}
    raw_group_ratio = group_ratios.get(group, 1 if group == "default" else None)
    try:
        group_ratio = _decimal(raw_group_ratio, f"分组 {group} 的 group_ratio")
    except ValueError as exc:
        raise HTTPException(502, f"上游价格分组数据无效：{exc}") from exc

    rows_by_model_key: dict[str, dict[str, Any]] = {}
    for row in pricing_rows:
        if not isinstance(row, dict):
            continue
        model_key = str(row.get("model_name") or "").strip()
        if model_key and model_key not in rows_by_model_key:
            rows_by_model_key[model_key] = row

    return UpstreamPricingSnapshot(
        quota_display_type="CNY",
        quota_per_unit=quota_per_unit,
        group=group,
        group_ratio=group_ratio,
        pricing_version=_pricing_version(
            status_data=status_data,
            pricing_rows=pricing_rows,
            group=group,
            group_ratio=group_ratio,
        ),
        rows_by_model_key=rows_by_model_key,
    )


def _finite_float(value: Decimal) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("换算结果超出可用范围")
    return result


def propose_model_price(
    model: AiModel,
    snapshot: UpstreamPricingSnapshot,
    yuan_to_points: Decimal,
) -> dict[str, Any]:
    """将单个本地模型的上游人民币价格换算为积分价格。"""
    row = snapshot.rows_by_model_key.get(model.model_key)
    if row is None:
        return {"status": "skipped", "reason": "上游价格表中没有精确匹配的模型"}
    try:
        quota_type = int(row.get("quota_type"))
    except (TypeError, ValueError):
        return {"status": "skipped", "reason": "上游 quota_type 无效"}

    try:
        if quota_type == 0:
            if model.modality != "text":
                return {"status": "skipped", "reason": "倍率计费仅支持文本模型"}
            if "completion_ratio" not in row:
                return {"status": "skipped", "reason": "上游未提供 completion_ratio"}
            model_ratio = _decimal(row.get("model_ratio"), "model_ratio")
            completion_ratio = _decimal(row.get("completion_ratio"), "completion_ratio")
            input_cny = Decimal("1000000") / snapshot.quota_per_unit * model_ratio * snapshot.group_ratio
            output_cny = input_cny * completion_ratio
            input_points = quantize_points(input_cny * yuan_to_points)
            output_points = quantize_points(output_cny * yuan_to_points)
            cache_ignored = "cache_ratio" in row or "create_cache_ratio" in row
            return {
                "status": "ready",
                "billing_type": "per_1m_tokens",
                "price_config_json": {
                    "input_points_per_1m": _finite_float(input_points),
                    "output_points_per_1m": _finite_float(output_points),
                },
                "upstream_price": {
                    "input_cny_per_1m": _finite_float(input_cny),
                    "output_cny_per_1m": _finite_float(output_cny),
                },
                "cache_ignored": cache_ignored,
            }
        if quota_type == 1:
            if model.modality not in {"image", "video"}:
                return {"status": "skipped", "reason": "固定价格仅支持图片或视频模型"}
            model_price = _decimal(row.get("model_price"), "model_price")
            cny_per_call = model_price * snapshot.group_ratio
            points_per_call = quantize_points(cny_per_call * yuan_to_points)
            billing_type = "per_image" if model.modality == "image" else "per_call"
            price_key = "points_per_image" if model.modality == "image" else "points_per_call"
            return {
                "status": "ready",
                "billing_type": billing_type,
                "price_config_json": {price_key: _finite_float(points_per_call)},
                "upstream_price": {"cny_per_call": _finite_float(cny_per_call)},
                "cache_ignored": False,
            }
        return {"status": "skipped", "reason": f"不支持的 quota_type：{quota_type}"}
    except (ValueError, InvalidOperation, ArithmeticError) as exc:
        return {"status": "skipped", "reason": f"上游价格数据无效：{exc}"}
