from __future__ import annotations

import datetime
import re
import uuid
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database import get_db
from models import (
    AiChannel,
    AiModel,
    AiModelPrice,
    AiTaskDefault,
    AiUsageEvent,
    BillingOrder,
    CreationStudioJob,
    PlatformSetting,
    PointsLedgerEntry,
    PointsProduct,
    User,
    UserAiPreference,
)
from services.ai import catalog as ai_catalog
from services.ai import bootstrap as ai_bootstrap
from services.ai import channels as ai_channels
from services.ai import credentials as ai_credentials
from services.ai.crypto_secrets import last_four
from services.ai.video_capabilities import validate_video_capability_limits
from services.points import accounts as points_accounts
from services.points.pricing import (
    DEFAULT_TEXT_INPUT_TOKENS,
    DEFAULT_TEXT_MIN_POINTS,
    DEFAULT_TEXT_OUTPUT_TOKENS,
    estimate_points,
    quantize_points,
)
from services.video_adapter import (
    VIDEO_ADAPTER_LINGDONG,
    VIDEO_ADAPTER_OPENAI,
    normalize_video_adapter_type,
)

router = APIRouter(tags=["points-ai"])
_LOCAL_TIMEZONE = ZoneInfo("Asia/Shanghai")
_UTC = datetime.timezone.utc
_VIDEO_RESOLUTIONS = {"480P", "720P", "1080P", "1K", "2K", "4K"}


def _main():
    import sys

    m = sys.modules.get("main") or sys.modules.get("__main__")
    if m is None:
        raise RuntimeError("main module not loaded")
    return m


def _require_user(request: Request, db: Session):
    return _main()._require_user(request, db)


def _require_admin(request: Request, db: Session):
    return _main()._require_admin(request, db)


def _require_user_credential_permission(user: User, db: Session) -> dict[str, bool]:
    capabilities = _main()._user_api_override_capabilities(user, db)
    if not capabilities["can_override_api_key"] and not capabilities["can_override_api_url"]:
        raise HTTPException(403, "管理员未授权当前账号使用自定义 API Key 或上游")
    return capabilities


def _get_platform_setting(key: str, db: Session, default=None):
    return _main()._get_platform_setting(key, db, default)


def _set_platform_setting(key: str, value, db: Session):
    row = db.query(PlatformSetting).filter(PlatformSetting.setting_key == key).first()
    payload = value if isinstance(value, dict) else {"value": value}
    if row:
        row.value_json = payload
    else:
        db.add(PlatformSetting(setting_key=key, value_json=payload))
    db.commit()


def _discovery_path(channel: AiChannel) -> str:
    """读取渠道的模型发现路径，只接受相对 API 路径。"""
    config = channel.extra_config_json or {}
    video_config = config.get("video")
    if not isinstance(video_config, dict):
        video_config = {}
    discovery = video_config.get("discovery")
    if not isinstance(discovery, dict):
        discovery = {}
    path = str(discovery.get("path") or "/models").strip()
    if not path.startswith("/") or path.startswith("//") or "?" in path or "#" in path:
        raise HTTPException(400, "模型发现路径必须是站内相对 API 路径")
    return path


def _parse_discovered_models(payload: Any) -> list[tuple[str, str, dict[str, Any] | None]]:
    """兼容常见模型列表响应，只提取模型标识和受限能力声明。"""
    if isinstance(payload, dict):
        rows = payload.get("data") or payload.get("models") or payload.get("items") or []
    else:
        rows = payload
    if not isinstance(rows, list):
        raise HTTPException(502, "上游模型列表响应格式不支持")

    parsed: list[tuple[str, str, dict[str, Any] | None]] = []
    seen: set[str] = set()
    for row in rows[:500]:
        if isinstance(row, str):
            key, display_name, capabilities = row.strip(), row.strip(), None
        elif isinstance(row, dict):
            key = str(row.get("id") or row.get("model") or row.get("model_key") or "").strip()
            display_name = str(row.get("name") or row.get("display_name") or key).strip()
            candidate = row.get("capabilities") or row.get("video_capabilities")
            if isinstance(candidate, dict):
                capabilities = candidate if isinstance(candidate.get("video"), dict) else {
                    "schema_version": 1,
                    "video": candidate,
                    "meta": {"source": "upstream_discovery"},
                }
            else:
                capabilities = None
        else:
            continue
        if not key or key in seen or len(key) > 191:
            continue
        seen.add(key)
        parsed.append((key, display_name[:191] or key, capabilities))
    return parsed


def _validate_openai_video_capabilities(video: dict[str, Any]) -> None:
    """校验 OpenAI 官方视频能力，禁止混入中转协议字段。"""
    allowed_video_fields = {"input_modes", "defaults", "limits", "wire"}
    if set(video) - allowed_video_fields:
        raise HTTPException(400, "OpenAI 视频模型包含不受支持的能力字段")
    input_modes = video.get("input_modes")
    if input_modes is not None:
        allowed_modes = {"text_to_video", "image_to_video", "text", "image"}
        if (
            not isinstance(input_modes, list)
            or not input_modes
            or not all(isinstance(item, str) and item in allowed_modes for item in input_modes)
        ):
            raise HTTPException(400, "OpenAI 视频模型 input_modes 配置无效")

    limits = video.get("limits")
    if not isinstance(limits, dict):
        raise HTTPException(400, "OpenAI 视频模型必须配置 limits")
    allowed_limit_fields = {
        "aspect_ratios",
        "resolutions",
        "duration_seconds",
        "max_reference_images",
    }
    if set(limits) - allowed_limit_fields:
        raise HTTPException(400, "OpenAI 视频模型 limits 包含不受支持的字段")
    duration_limit = limits.get("duration_seconds")
    if not isinstance(duration_limit, dict) or set(duration_limit) != {"allowed"}:
        raise HTTPException(400, "OpenAI 视频模型 duration_seconds 仅支持 allowed 时长集合")
    allowed_durations = duration_limit.get("allowed") if isinstance(duration_limit, dict) else None
    if (
        not isinstance(allowed_durations, list)
        or not allowed_durations
        or not all(isinstance(item, int) and not isinstance(item, bool) and item > 0 for item in allowed_durations)
    ):
        raise HTTPException(400, "OpenAI 视频模型必须配置显式时长集合")
    max_references = limits.get("max_reference_images", 1)
    if not isinstance(max_references, int) or isinstance(max_references, bool) or not 0 <= max_references <= 1:
        raise HTTPException(400, "OpenAI 视频模型最多支持一张参考图")
    for key in ("aspect_ratios", "resolutions"):
        value = limits.get(key)
        if value is not None and (
            not isinstance(value, list)
            or not value
            or not all(isinstance(item, str) and item.strip() for item in value)
        ):
            raise HTTPException(400, f"OpenAI 视频模型 {key} 必须是非空字符串数组")

    wire = video.get("wire")
    if not isinstance(wire, dict) or set(wire) != {"size_by_resolution_aspect"}:
        raise HTTPException(400, "OpenAI 视频模型 wire 仅支持 size_by_resolution_aspect")
    mapping = wire.get("size_by_resolution_aspect")
    if not isinstance(mapping, dict) or not mapping:
        raise HTTPException(400, "OpenAI 视频模型必须配置 size_by_resolution_aspect")
    resolutions = set(limits.get("resolutions") or [])
    aspect_ratios = set(limits.get("aspect_ratios") or [])
    for key, value in mapping.items():
        if not isinstance(key, str) or "|" not in key:
            raise HTTPException(400, "OpenAI 视频 size 映射键格式无效")
        resolution, aspect_ratio = key.split("|", 1)
        if resolutions and resolution not in resolutions:
            raise HTTPException(400, "OpenAI 视频 size 映射包含未声明清晰度")
        if aspect_ratios and aspect_ratio not in aspect_ratios:
            raise HTTPException(400, "OpenAI 视频 size 映射包含未声明画面比例")
        if not isinstance(value, str) or re.fullmatch(r"[1-9]\d{2,4}x[1-9]\d{2,4}", value) is None:
            raise HTTPException(400, "OpenAI 视频上游 size 必须是像素尺寸")
    _validate_video_defaults(video, provider_name="OpenAI")
    defaults = video.get("defaults")
    if isinstance(defaults, dict):
        default_resolution = defaults.get("resolution")
        default_aspect_ratio = defaults.get("aspect_ratio")
        if (
            isinstance(default_resolution, str)
            and isinstance(default_aspect_ratio, str)
            and f"{default_resolution}|{default_aspect_ratio}" not in mapping
        ):
            raise HTTPException(400, "OpenAI 视频模型默认清晰度与比例缺少上游 size 映射")


def _validate_video_defaults(video: dict[str, Any], *, provider_name: str) -> None:
    """校验视频默认参数必须落在模型声明的可选范围内。"""
    defaults = video.get("defaults")
    if defaults is None:
        return
    if not isinstance(defaults, dict) or set(defaults) - {
        "aspect_ratio",
        "resolution",
        "duration_seconds",
    }:
        raise HTTPException(400, f"{provider_name} 视频模型 defaults 配置无效")

    limits = video.get("limits")
    limits = limits if isinstance(limits, dict) else {}
    for default_key, limit_key in (
        ("aspect_ratio", "aspect_ratios"),
        ("resolution", "resolutions"),
    ):
        value = defaults.get(default_key)
        allowed = limits.get(limit_key)
        if value is not None and (
            not isinstance(value, str)
            or not isinstance(allowed, list)
            or value not in allowed
        ):
            raise HTTPException(400, f"{provider_name} 视频模型 defaults.{default_key} 未包含在 limits 中")

    duration = defaults.get("duration_seconds")
    if duration is None:
        return
    if not isinstance(duration, int) or isinstance(duration, bool) or duration <= 0:
        raise HTTPException(400, f"{provider_name} 视频模型 defaults.duration_seconds 必须是正整数")
    duration_limit = limits.get("duration_seconds")
    duration_limit = duration_limit if isinstance(duration_limit, dict) else {}
    allowed = duration_limit.get("allowed")
    minimum = duration_limit.get("min")
    maximum = duration_limit.get("max")
    if isinstance(allowed, list):
        valid_duration = duration in allowed
    else:
        valid_duration = (
            isinstance(minimum, int)
            and isinstance(maximum, int)
            and minimum <= duration <= maximum
        )
    if not valid_duration:
        raise HTTPException(400, f"{provider_name} 视频模型默认时长未包含在 limits 中")


def _validate_lingdong_video_capabilities(video: dict[str, Any]) -> None:
    """校验 Lingdong 中转能力并保留现有受控 profile。"""
    allowed_video_fields = {"payload_profile", "input_modes", "defaults", "limits", "wire"}
    if set(video) - allowed_video_fields:
        raise HTTPException(400, "Lingdong 视频模型包含不受支持的能力字段")
    profile = video.get("payload_profile", "legacy_lingdong")
    if not isinstance(profile, str) or profile not in {"legacy_lingdong", "seedance_fast", "sora_v2"}:
        raise HTTPException(400, "视频模型 payload_profile 不受支持")
    input_modes = video.get("input_modes")
    if input_modes is not None and (
        not isinstance(input_modes, list)
        or not all(isinstance(item, str) for item in input_modes)
    ):
        raise HTTPException(400, "视频模型 input_modes 必须是字符串数组")
    limits = video.get("limits")
    if limits is None:
        limits = {}
    elif not isinstance(limits, dict):
        raise HTTPException(400, "视频模型 limits 必须是对象")
    allowed_limit_fields = {
        "aspect_ratios",
        "resolutions",
        "duration_seconds",
        "max_reference_images",
    }
    if set(limits) - allowed_limit_fields:
        raise HTTPException(400, "Lingdong 视频模型 limits 包含不受支持的字段")
    for key in ("aspect_ratios", "resolutions"):
        value = limits.get(key)
        if value is not None and (
            not isinstance(value, list)
            or not value
            or not all(isinstance(item, str) and item.strip() for item in value)
        ):
            raise HTTPException(400, f"Lingdong 视频模型 {key} 必须是非空字符串数组")
    resolutions = limits.get("resolutions")
    if isinstance(resolutions, list) and any(item not in _VIDEO_RESOLUTIONS for item in resolutions):
        raise HTTPException(400, "Lingdong 视频模型包含不受支持的清晰度")
    max_references = limits.get("max_reference_images")
    if max_references is not None and (
        not isinstance(max_references, int)
        or isinstance(max_references, bool)
        or max_references < 0
    ):
        raise HTTPException(400, "Lingdong 视频模型 max_reference_images 必须是非负整数")
    duration_limit = limits.get("duration_seconds")
    if duration_limit is not None:
        if not isinstance(duration_limit, dict):
            raise HTTPException(400, "Lingdong 视频模型 duration_seconds 必须是对象")
        if set(duration_limit) - {"allowed", "min", "max"}:
            raise HTTPException(400, "Lingdong 视频模型 duration_seconds 包含不受支持的字段")
        allowed = duration_limit.get("allowed")
        if allowed is not None and ("min" in duration_limit or "max" in duration_limit):
            raise HTTPException(400, "Lingdong 视频模型时长请配置 allowed 或 min/max 其中一种")
        if allowed is not None and (
            not isinstance(allowed, list)
            or not allowed
            or not all(isinstance(item, int) and not isinstance(item, bool) and item > 0 for item in allowed)
        ):
            raise HTTPException(400, "Lingdong 视频模型 allowed 时长必须是非空正整数数组")
        for key in ("min", "max"):
            value = duration_limit.get(key)
            if value is not None and (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value <= 0
            ):
                raise HTTPException(400, f"Lingdong 视频模型 {key} 时长必须是正整数")
        if allowed is None and not (
            isinstance(duration_limit.get("min"), int)
            and isinstance(duration_limit.get("max"), int)
            and duration_limit["min"] <= duration_limit["max"]
        ):
            raise HTTPException(400, "Lingdong 视频模型必须配置 allowed 时长集合或合法 min/max")
    _validate_video_defaults(video, provider_name="Lingdong")
    wire = video.get("wire")
    if wire is not None and not isinstance(wire, dict):
        raise HTTPException(400, "视频模型 wire 必须是对象")
    if isinstance(wire, dict):
        allowed_wire_fields = {
            "duration_field",
            "duration_as_string",
            "reference_field",
            "resolution_field",
            "ratio_field",
            "size_by_resolution_aspect",
        }
        if set(wire) - allowed_wire_fields:
            raise HTTPException(400, "Lingdong 视频模型 wire 包含不受支持的字段")
        reference_field = wire.get("reference_field", "input_reference")
        if reference_field != "input_reference":
            raise HTTPException(400, "Lingdong reference_field 仅支持 input_reference")
        duration_field = wire.get("duration_field")
        if duration_field is not None and duration_field not in {"duration", "seconds"}:
            raise HTTPException(400, "Lingdong duration_field 仅支持 duration 或 seconds")
        duration_as_string = wire.get("duration_as_string")
        if duration_as_string is not None and not isinstance(duration_as_string, bool):
            raise HTTPException(400, "Lingdong duration_as_string 必须是布尔值")
        resolution_field = wire.get("resolution_field")
        if resolution_field is not None and resolution_field not in {"resolution", "size"}:
            raise HTTPException(400, "Lingdong resolution_field 仅支持 resolution 或 size")
        ratio_field = wire.get("ratio_field")
        if ratio_field is not None and ratio_field not in {"ratio", "orientation"}:
            raise HTTPException(400, "Lingdong ratio_field 仅支持 ratio 或 orientation")
        mapping = wire.get("size_by_resolution_aspect")
        if mapping is not None and (
            not isinstance(mapping, dict)
            or not all(
                isinstance(key, str)
                and "|" in key
                and isinstance(value, str)
                and value.strip()
                for key, value in mapping.items()
            )
        ):
            raise HTTPException(400, "Lingdong size_by_resolution_aspect 配置无效")
    if profile == "sora_v2":
        wire_config = wire if isinstance(wire, dict) else {}
        mapping = wire_config.get("size_by_resolution_aspect")
        if not isinstance(mapping, dict) or not mapping or not all(isinstance(key, str) and isinstance(value, str) and value.strip() for key, value in mapping.items()):
            raise HTTPException(400, "Sora 模型必须配置 wire.size_by_resolution_aspect")
        duration_field = wire_config.get("duration_field", "duration")
        if duration_field not in {"duration", "seconds"}:
            raise HTTPException(400, "Sora duration_field 仅支持 duration 或 seconds")
        reference_field = wire_config.get("reference_field", "input_reference")
        if reference_field != "input_reference":
            raise HTTPException(400, "Sora reference_field 仅支持 input_reference")


def _validate_model_capabilities(
    raw: dict[str, Any] | None,
    modality: str,
    adapter_type: str,
) -> None:
    """在保存边界校验受控模型能力配置，避免异步任务才暴露配置错误。"""
    if modality == "image":
        _validate_image_model_capabilities(raw)
        return
    if modality != "video":
        return
    if raw is None:
        if adapter_type == VIDEO_ADAPTER_OPENAI:
            raise HTTPException(400, "OpenAI 视频模型必须配置能力参数")
        return
    video = raw.get("video")
    if not isinstance(video, dict):
        raise HTTPException(400, "视频模型参数配置必须包含 video 对象")
    try:
        adapter = normalize_video_adapter_type(adapter_type)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if adapter == VIDEO_ADAPTER_OPENAI:
        _validate_openai_video_capabilities(video)
    elif adapter == VIDEO_ADAPTER_LINGDONG:
        _validate_lingdong_video_capabilities(video)


def _validate_image_model_capabilities(raw: dict[str, Any] | None) -> None:
    """校验图片模型可安全下发的默认质量与可选质量。"""
    if raw is None:
        # 历史模型与上游发现记录可能没有 image 节点，保持兼容。
        return
    if not isinstance(raw, dict):
        raise HTTPException(400, "图片模型能力配置必须是 JSON 对象")
    if "image" not in raw:
        # 历史模型与上游发现记录可能没有 image 节点，保持兼容。
        return
    if not isinstance(raw["image"], dict):
        raise HTTPException(400, "图片模型参数配置必须包含 image 对象")
    if set(raw) - {"schema_version", "image", "meta"}:
        raise HTTPException(400, "图片模型包含不受支持的能力字段")
    schema_version = raw.get("schema_version", 1)
    if schema_version != 1:
        raise HTTPException(400, "图片模型 schema_version 仅支持 1")
    image = raw["image"]
    if set(image) - {"defaults", "limits"}:
        raise HTTPException(400, "图片模型 image 仅支持 defaults 和 limits")
    allowed_qualities = {"auto", "low", "medium", "high"}
    defaults = image.get("defaults", {})
    limits = image.get("limits", {})
    if not isinstance(defaults, dict) or set(defaults) - {"quality"}:
        raise HTTPException(400, "图片模型 defaults 仅支持 quality")
    if not isinstance(limits, dict) or set(limits) - {"qualities"}:
        raise HTTPException(400, "图片模型 limits 仅支持 qualities")
    quality = defaults.get("quality")
    if quality is not None and (not isinstance(quality, str) or quality not in allowed_qualities):
        raise HTTPException(400, "图片模型默认 quality 不受支持")
    qualities = limits.get("qualities")
    if qualities is not None:
        if (
            not isinstance(qualities, list)
            or not qualities
            or not all(isinstance(item, str) and item in allowed_qualities for item in qualities)
            or len(set(qualities)) != len(qualities)
        ):
            raise HTTPException(400, "图片模型 qualities 必须是无重复的受支持质量列表")
        if quality is not None and quality not in qualities:
            raise HTTPException(400, "图片模型默认 quality 必须包含在 qualities 中")


def _validate_channel_adapter(modality: str, adapter_type: str) -> None:
    """校验渠道最终形态；非视频渠道沿用既有适配器规则。"""
    if modality != "video":
        return
    try:
        normalize_video_adapter_type(adapter_type)
    except ValueError as exc:
        raise HTTPException(400, f"视频渠道适配器无效：{exc}") from exc


class CredentialIn(BaseModel):
    api_key: str = Field(min_length=1)


class CredentialTestIn(BaseModel):
    api_key: str | None = None


class PreferencesIn(BaseModel):
    credential_mode: str | None = None
    default_text_model_id: int | None = None
    default_image_model_id: int | None = None
    default_video_model_id: int | None = None


class EstimateIn(BaseModel):
    model_config = {"protected_namespaces": ()}

    model_id: int
    input_tokens: int = 0
    output_tokens: int = 0
    image_count: int = 1
    video_seconds: float = 0


class ChannelIn(BaseModel):
    code: str
    name: str
    adapter_type: str = "openai_compatible"
    base_url: str
    modality: str = "text"
    platform_api_key: str | None = None
    enabled: bool = True
    timeout_seconds: int = 120
    extra_config_json: dict[str, Any] | None = None


class ChannelUpdateIn(BaseModel):
    name: str | None = None
    adapter_type: str | None = None
    base_url: str | None = None
    modality: str | None = None
    platform_api_key: str | None = None
    enabled: bool | None = None
    timeout_seconds: int | None = None
    extra_config_json: dict[str, Any] | None = None


class ModelIn(BaseModel):
    model_config = {"protected_namespaces": ()}

    channel_id: int
    model_key: str
    display_name: str
    modality: str = "text"
    enabled: bool = True
    user_visible: bool = True
    sort_order: int = 0
    capabilities_json: dict[str, Any] | None = None


class ModelUpdateIn(BaseModel):
    display_name: str | None = None
    enabled: bool | None = None
    user_visible: bool | None = None
    sort_order: int | None = None
    modality: str | None = None
    capabilities_json: dict[str, Any] | None = None


class DiscoveredModelIn(BaseModel):
    """管理员从发现结果中选中的模型。"""

    key: str = Field(min_length=1, max_length=191)
    display_name: str | None = Field(default=None, max_length=191)
    capabilities: dict[str, Any] | None = None


class ChannelModelsAddIn(BaseModel):
    """向渠道批量添加已选择的发现模型。"""

    models: list[DiscoveredModelIn] = Field(min_length=1, max_length=500)


class PriceIn(BaseModel):
    billing_type: str = "per_call"
    price_config_json: dict[str, Any] = Field(default_factory=dict)


def _normalize_model_price(model: AiModel, body: PriceIn) -> tuple[str, dict[str, Any]]:
    if model.modality == "text":
        legacy_rate = body.price_config_json.get("points_per_1m_tokens")
        rates: dict[str, Decimal] = {}
        for key, label in (
            ("input_points_per_1m", "输入"),
            ("output_points_per_1m", "输出"),
        ):
            raw_rate = body.price_config_json.get(key, legacy_rate)
            try:
                rate = Decimal(str(raw_rate))
            except Exception as exc:
                raise HTTPException(400, f"文本模型每百万 Token {label}积分价必须是非负数字") from exc
            if not rate.is_finite() or rate < 0:
                raise HTTPException(400, f"文本模型每百万 Token {label}积分价必须是非负数字")
            rates[key] = rate
        return "per_1m_tokens", {
            "input_points_per_1m": float(rates["input_points_per_1m"]),
            "output_points_per_1m": float(rates["output_points_per_1m"]),
            "estimate_default_input_tokens": DEFAULT_TEXT_INPUT_TOKENS,
            "estimate_default_output_tokens": DEFAULT_TEXT_OUTPUT_TOKENS,
            "reservation_max_input_tokens": DEFAULT_TEXT_INPUT_TOKENS,
            "reservation_max_output_tokens": DEFAULT_TEXT_OUTPUT_TOKENS,
            "min_points_per_call": float(DEFAULT_TEXT_MIN_POINTS),
        }
    if model.modality == "image":
        return "per_image", dict(body.price_config_json)
    if model.modality == "video":
        return "per_second", dict(body.price_config_json)
    return body.billing_type, dict(body.price_config_json)


class AdjustPointsIn(BaseModel):
    user_id: int
    amount: Decimal = Field(gt=Decimal("-1000000000"), lt=Decimal("1000000000"))
    note: str = Field(default="", max_length=255)
    request_id: str = Field(min_length=1, max_length=64)


class GrantPointsIn(BaseModel):
    amount: Decimal = Field(gt=0, le=Decimal("1000000000"))
    note: str = Field(default="", max_length=255)
    request_id: str = Field(min_length=1, max_length=64)


class PointsSettingsIn(BaseModel):
    yuan_to_points: float | None = None
    register_grant_enabled: bool | None = None
    register_grant_amount: float | None = None
    dual_track_enabled: bool | None = None


class PurchasePointsIn(BaseModel):
    product_id: int
    payment_method: str | None = None


class PointsProductIn(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=1000)
    price_cny: Decimal = Field(gt=0, le=Decimal("99999999.99"))
    points: Decimal = Field(gt=0, le=Decimal("1000000000"))
    bonus_points: Decimal = Field(default=Decimal("0"), ge=0, le=Decimal("1000000000"))
    is_visible: bool = True
    is_recommended: bool = False
    sort_order: int = Field(default=0, ge=-100000, le=100000)


class PointsProductUpdateIn(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=64)
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=1000)
    price_cny: Decimal | None = Field(default=None, gt=0, le=Decimal("99999999.99"))
    points: Decimal | None = Field(default=None, gt=0, le=Decimal("1000000000"))
    bonus_points: Decimal | None = Field(default=None, ge=0, le=Decimal("1000000000"))
    is_visible: bool | None = None
    is_recommended: bool | None = None
    sort_order: int | None = Field(default=None, ge=-100000, le=100000)


def _serialize_points_product(product: PointsProduct) -> dict[str, Any]:
    return {
        "id": product.id,
        "code": product.code,
        "name": product.name,
        "description": product.description or "",
        "price_cny": float(product.price_cny),
        "points": float(product.points),
        "bonus_points": float(product.bonus_points),
        "is_visible": bool(product.is_visible),
        "is_recommended": bool(product.is_recommended),
        "sort_order": int(product.sort_order or 0),
    }


@router.get("/api/ai/credential")
def get_credential(request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    row = ai_credentials.get_credential_row(db, user.id)
    return ai_credentials.serialize_credential(row)


@router.put("/api/ai/credential")
def put_credential(body: CredentialIn, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    _require_user_credential_permission(user, db)
    row = ai_credentials.save_user_api_key(db, user.id, body.api_key)
    db.commit()
    return ai_credentials.serialize_credential(row)


@router.delete("/api/ai/credential")
def delete_credential(request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    ai_credentials.clear_user_api_key(db, user.id)
    db.commit()
    return {"ok": True}


@router.post("/api/ai/credential/test")
async def test_credential(
    request: Request,
    body: CredentialTestIn | None = None,
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    capabilities = _require_user_credential_permission(user, db)
    draft_key = body.api_key.strip() if body and body.api_key is not None else ""
    if body and body.api_key is not None and not draft_key:
        raise HTTPException(400, "API Key 不能为空")
    if draft_key and not capabilities["can_override_api_key"]:
        raise HTTPException(403, "管理员未授权当前账号使用自定义 API Key")
    key = draft_key or ai_credentials.load_user_api_key_plain(db, user.id)
    if not key:
        raise HTTPException(400, "尚未配置 API Key")
    persist_validation = not bool(draft_key)
    ch = (
        db.query(AiChannel)
        .filter(AiChannel.enabled.is_(True), AiChannel.modality.in_(["text", "multi"]))
        .order_by(AiChannel.id.asc())
        .first()
    )
    if not ch or not ch.base_url:
        raise HTTPException(400, "管理员尚未配置文本渠道 Base URL")
    custom_upstream = _main()._resolve_user_upstream_override(
        request,
        db,
        user=user,
        modality="text",
        mode="user_key",
        api_key_override=draft_key or None,
    )
    if not custom_upstream and not capabilities["can_override_api_key"]:
        raise HTTPException(403, "仅有 URL 权限时，请先配置文本模型自定义上游")
    base_url = (custom_upstream or {}).get("base_url") or ch.base_url
    url = base_url.rstrip("/") + "/models"
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(url, headers={"Authorization": f"Bearer {key}"})
        ok = resp.status_code < 400
        if persist_validation:
            ai_credentials.mark_credential_validated(db, user.id, ok)
        db.commit()
        if not ok:
            raise HTTPException(400, f"上游返回 {resp.status_code}，Key 可能无效")
        return {"ok": True, "status_code": resp.status_code}
    except HTTPException:
        raise
    except Exception as exc:
        if persist_validation:
            ai_credentials.mark_credential_validated(db, user.id, False)
        db.commit()
        raise HTTPException(400, f"测试失败: {exc}") from exc


@router.get("/api/ai/preferences")
def get_preferences(request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    pref = db.query(UserAiPreference).filter(UserAiPreference.user_id == user.id).first()
    if not pref:
        return {
            "credential_mode": "platform",
            "default_text_model_id": None,
            "default_image_model_id": None,
            "default_video_model_id": None,
        }
    return {
        "credential_mode": pref.credential_mode,
        "default_text_model_id": pref.default_text_model_id,
        "default_image_model_id": pref.default_image_model_id,
        "default_video_model_id": pref.default_video_model_id,
    }


@router.put("/api/ai/preferences")
def put_preferences(body: PreferencesIn, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    pref = db.query(UserAiPreference).filter(UserAiPreference.user_id == user.id).first()
    if not pref:
        pref = UserAiPreference(user_id=user.id)
        db.add(pref)
    if body.credential_mode is not None:
        mode = body.credential_mode.strip().lower()
        if mode not in {"platform", "user_key"}:
            raise HTTPException(400, "credential_mode 只能是 platform 或 user_key")
        if mode == "user_key":
            _require_user_credential_permission(user, db)
        pref.credential_mode = mode
    if body.default_text_model_id is not None:
        model = ai_catalog.get_visible_model(db, body.default_text_model_id)
        if model.modality != "text":
            raise HTTPException(400, "默认文本模型必须是 text 类型")
        pref.default_text_model_id = body.default_text_model_id or None
    if body.default_image_model_id is not None:
        model = ai_catalog.get_visible_model(db, body.default_image_model_id)
        if model.modality != "image":
            raise HTTPException(400, "默认图片模型必须是 image 类型")
        pref.default_image_model_id = body.default_image_model_id or None
    if body.default_video_model_id is not None:
        model = ai_catalog.get_visible_model(db, body.default_video_model_id)
        if model.modality != "video":
            raise HTTPException(400, "默认视频模型必须是 video 类型")
        pref.default_video_model_id = body.default_video_model_id or None
    db.commit()
    return get_preferences(request, db)


@router.get("/api/ai/models")
def list_models(request: Request, modality: str | None = None, db: Session = Depends(get_db)):
    _require_user(request, db)
    models = ai_catalog.list_user_visible_models(db, modality=modality)
    return {"models": [ai_catalog.serialize_model_for_user(db, m) for m in models]}


@router.post("/api/ai/estimate")
def estimate(body: EstimateIn, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    model = ai_catalog.get_visible_model(db, body.model_id)
    if model.modality == "video":
        raw_capabilities = model.capabilities_json
        video_capabilities = raw_capabilities.get("video") if isinstance(raw_capabilities, dict) else None
        validate_video_capability_limits(
            video_capabilities,
            duration_seconds=body.video_seconds,
        )
    price = ai_catalog.get_active_price(db, model.id)
    if not price:
        raise HTTPException(400, "模型未配置积分价")
    pts = estimate_points(
        billing_type=price.billing_type,
        price_config=price.price_config_json,
        input_tokens=body.input_tokens,
        output_tokens=body.output_tokens,
        image_count=body.image_count,
        video_seconds=body.video_seconds,
        use_estimate_defaults=True,
    )
    account = points_accounts.ensure_account(db, user.id)
    db.commit()
    return {
        "model_id": model.id,
        "estimated_points": float(pts),
        "available_points": float(quantize_points(account.available_points)),
        "sufficient": account.available_points >= pts,
    }


@router.get("/api/points/account")
def points_account(request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    account = points_accounts.ensure_account(db, user.id)
    db.commit()
    return points_accounts.serialize_account(account)


@router.get("/api/points/ledger")
def points_ledger(
    request: Request,
    page: int = Query(1, ge=1, le=1_000_000),
    page_size: int | None = Query(None, ge=1, le=200),
    start_date: datetime.date | None = None,
    end_date: datetime.date | None = None,
    entry_type: str | None = Query(None, min_length=1, max_length=64),
    direction: str | None = Query(None, pattern="^(income|expense)$"),
    limit: int | None = Query(None, ge=1, le=200),
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    account = points_accounts.ensure_account(db, user.id)
    db.commit()
    # 直接调用路由函数时，FastAPI 的 Query 默认值不会自动解析。
    if not isinstance(page, int):
        page = 1
    if not isinstance(limit, int):
        limit = None
    if not isinstance(page_size, int):
        page_size = limit or 20
    if start_date and end_date and start_date > end_date:
        raise HTTPException(400, "开始日期不能晚于结束日期")
    query = db.query(PointsLedgerEntry).filter(PointsLedgerEntry.account_id == account.id)
    if start_date:
        local_start = datetime.datetime.combine(start_date, datetime.time.min, tzinfo=_LOCAL_TIMEZONE)
        query = query.filter(PointsLedgerEntry.created_at >= local_start.astimezone(_UTC).replace(tzinfo=None))
    if end_date:
        if end_date == datetime.date.max:
            query = query.filter(PointsLedgerEntry.created_at <= datetime.datetime.max)
        else:
            local_next_day = datetime.datetime.combine(end_date + datetime.timedelta(days=1), datetime.time.min, tzinfo=_LOCAL_TIMEZONE)
            query = query.filter(PointsLedgerEntry.created_at < local_next_day.astimezone(_UTC).replace(tzinfo=None))
    if entry_type:
        query = query.filter(PointsLedgerEntry.entry_type == entry_type)
    if direction == "income":
        query = query.filter(PointsLedgerEntry.amount > 0)
    elif direction == "expense":
        query = query.filter(PointsLedgerEntry.amount < 0)

    total = query.count()
    total_pages = (total + page_size - 1) // page_size
    rows = (
        query
        .order_by(PointsLedgerEntry.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    usage_ids = {r.usage_event_id for r in rows if r.usage_event_id}
    usage_map = {
        event.id: event
        for event in db.query(AiUsageEvent).filter(AiUsageEvent.id.in_(usage_ids)).all()
    } if usage_ids else {}
    return {
        "items": [
            {
                "id": r.id,
                "entry_type": r.entry_type,
                "amount": float(r.amount),
                "balance_after": float(r.balance_after) if r.balance_after is not None else None,
                "created_at": r.created_at.replace(tzinfo=_UTC).isoformat() if r.created_at else None,
                "metadata": r.metadata_json or {},
                "usage_event_id": r.usage_event_id,
                "usage_detail": (
                    {
                        "request_id": event.request_id,
                        "model_key": event.model_key,
                        "task_type": event.task_type,
                        "status": event.status,
                        "input_tokens": event.input_tokens or 0,
                        "output_tokens": event.output_tokens or 0,
                        "settled_points": float(event.settled_points or 0),
                        "stream_charged_points": (
                            float((event.price_snapshot_json or {}).get("stream_charged_points"))
                            if (event.price_snapshot_json or {}).get("stream_charged_points") is not None
                            else None
                        ),
                        "billing_type": (event.price_snapshot_json or {}).get("billing_type"),
                        "points_per_1m_tokens": (event.price_snapshot_json or {}).get("price_config", {}).get("points_per_1m_tokens"),
                        "input_points_per_1m": (event.price_snapshot_json or {}).get("price_config", {}).get("input_points_per_1m"),
                        "output_points_per_1m": (event.price_snapshot_json or {}).get("price_config", {}).get("output_points_per_1m"),
                        "streaming": bool((event.price_snapshot_json or {}).get("streaming")),
                    }
                    if (event := usage_map.get(r.usage_event_id))
                    else None
                ),
            }
            for r in rows
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }


@router.get("/api/points/products")
def points_products(db: Session = Depends(get_db)):
    rows = (
        db.query(PointsProduct)
        .filter(PointsProduct.is_visible.is_(True))
        .order_by(PointsProduct.sort_order.asc(), PointsProduct.id.asc())
        .all()
    )
    return {"products": [_serialize_points_product(product) for product in rows]}


@router.post("/api/points/purchase")
def purchase_points(body: PurchasePointsIn, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    product = db.get(PointsProduct, body.product_id)
    if not product or not product.is_visible:
        raise HTTPException(404, "积分套餐不存在")

    main = _main()
    payment = main._payment_settings_snapshot(db)
    if not bool(payment.get("enabled", True)):
        raise HTTPException(503, "支付功能暂未开放")

    method = str(body.payment_method or payment.get("default_method") or "").strip()
    gateway = main.get_gateway(method)
    if not method or gateway is None:
        raise HTTPException(400, "支付方式不可用")
    available_methods = {item["key"] for item in main._payment_method_options(db)}
    if method != "mock_qr" and method not in available_methods:
        raise HTTPException(400, "支付方式未启用")
    if method == "mock_qr" and not main._mock_payments_enabled():
        raise HTTPException(403, "模拟支付仅允许在显式启用的开发环境中使用")

    now = datetime.datetime.utcnow()
    expire_minutes = max(1, int(payment.get("order_expire_minutes") or 30))
    stale_orders = (
        db.query(BillingOrder)
        .filter(
            BillingOrder.user_id == user.id,
            BillingOrder.source == "points_purchase",
            BillingOrder.status == "pending",
        )
        .all()
    )
    for stale in stale_orders:
        stale.status = "cancelled"
        stale.note = "创建新的积分套餐订单时自动取消"

    order_no = f"PTS{datetime.datetime.utcnow().strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:8].upper()}"
    order = BillingOrder(
        order_no=order_no,
        user_id=user.id,
        plan_id=None,
        points_product_id=product.id,
        amount=product.price_cny,
        currency="CNY",
        status="pending",
        source="points_purchase",
        billing_cycle="one_time",
        payment_provider=gateway.provider,
        payment_method=method,
        expired_at=now + datetime.timedelta(minutes=expire_minutes),
        extra_json={
            "product_id": product.id,
            "product_code": product.code,
            "product_name": product.name,
            "product_description": product.description or "",
            "points": str(product.points),
            "bonus_points": str(product.bonus_points),
        },
    )
    db.add(order)
    db.flush()

    item = SimpleNamespace(name=product.name, description=product.description or "积分套餐")
    payment_with_ip = dict(payment)
    payment_with_ip["client_ip"] = request.client.host if request.client else ""
    try:
        checkout = main._order_checkout_payload(
            order,
            item,
            db,
            payment_override=payment_with_ip,
            raise_gateway_errors=True,
        )
    except RuntimeError as exc:
        raise HTTPException(502, str(exc)) from exc
    if method != "mock_qr" and not checkout.get("qr_code_text") and not checkout.get("payment_url"):
        raise HTTPException(502, "支付通道未返回可用的收款信息")

    main._write_audit_log(
        user,
        "purchase_points_package",
        "billing_order",
        order.order_no,
        f"创建积分套餐订单 {product.name}",
        db,
        {
            "product_id": product.id,
            "product_name": product.name,
            "points": str(product.points),
            "bonus_points": str(product.bonus_points),
            "payment_method": method,
        },
    )
    db.commit()
    db.refresh(order)
    return {
        "ok": True,
        "order_no": order.order_no,
        "amount": float(order.amount),
        "status": order.status,
        "product_id": product.id,
        "points": float(product.points + product.bonus_points),
        "checkout": checkout,
    }


@router.get("/api/admin/points/products")
def admin_list_points_products(request: Request, db: Session = Depends(get_db)):
    _require_admin(request, db)
    rows = db.query(PointsProduct).order_by(PointsProduct.sort_order.asc(), PointsProduct.id.asc()).all()
    return {"products": [_serialize_points_product(product) for product in rows]}


@router.post("/api/admin/points/products")
def admin_create_points_product(body: PointsProductIn, request: Request, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    code = body.code.strip().lower()
    if db.query(PointsProduct).filter(PointsProduct.code == code).first():
        raise HTTPException(409, "积分套餐代码已存在")
    product = PointsProduct(
        code=code,
        name=body.name.strip(),
        description=body.description.strip(),
        price_cny=body.price_cny,
        points=quantize_points(body.points),
        bonus_points=quantize_points(body.bonus_points),
        is_visible=body.is_visible,
        is_recommended=body.is_recommended,
        sort_order=body.sort_order,
    )
    db.add(product)
    db.flush()
    _main()._write_audit_log(
        admin,
        "create_points_product",
        "points_product",
        product.id,
        f"创建积分套餐 {product.name}",
        db,
        _serialize_points_product(product),
    )
    db.commit()
    db.refresh(product)
    return _serialize_points_product(product)


@router.put("/api/admin/points/products/{product_id}")
def admin_update_points_product(
    product_id: int,
    body: PointsProductUpdateIn,
    request: Request,
    db: Session = Depends(get_db),
):
    admin = _require_admin(request, db)
    product = db.get(PointsProduct, product_id)
    if not product:
        raise HTTPException(404, "积分套餐不存在")
    if body.code is not None:
        code = body.code.strip().lower()
        duplicate = (
            db.query(PointsProduct)
            .filter(PointsProduct.code == code, PointsProduct.id != product.id)
            .first()
        )
        if duplicate:
            raise HTTPException(409, "积分套餐代码已存在")
        product.code = code
    if body.name is not None:
        product.name = body.name.strip()
    if body.description is not None:
        product.description = body.description.strip()
    if body.price_cny is not None:
        product.price_cny = body.price_cny
    if body.points is not None:
        product.points = quantize_points(body.points)
    if body.bonus_points is not None:
        product.bonus_points = quantize_points(body.bonus_points)
    if body.is_visible is not None:
        product.is_visible = body.is_visible
    if body.is_recommended is not None:
        product.is_recommended = body.is_recommended
    if body.sort_order is not None:
        product.sort_order = body.sort_order
    _main()._write_audit_log(
        admin,
        "update_points_product",
        "points_product",
        product.id,
        f"更新积分套餐 {product.name}",
        db,
        _serialize_points_product(product),
    )
    db.commit()
    db.refresh(product)
    return _serialize_points_product(product)


@router.delete("/api/admin/points/products/{product_id}")
def admin_delete_points_product(product_id: int, request: Request, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    product = db.get(PointsProduct, product_id)
    if not product:
        raise HTTPException(404, "积分套餐不存在")
    historical_orders = db.query(BillingOrder).filter(BillingOrder.points_product_id == product.id).count()
    if historical_orders:
        product.is_visible = False
        summary = f"下架积分套餐 {product.name}，保留 {historical_orders} 笔历史订单"
    else:
        summary = f"删除积分套餐 {product.name}"
        db.delete(product)
    _main()._write_audit_log(
        admin,
        "delete_points_product",
        "points_product",
        product_id,
        summary,
        db,
        {"historical_orders": historical_orders},
    )
    db.commit()
    return {"ok": True, "archived": historical_orders > 0}


@router.get("/api/admin/ai/channels")
def admin_list_channels(request: Request, db: Session = Depends(get_db)):
    _require_admin(request, db)
    return {"channels": [ai_channels.serialize_channel(c) for c in ai_channels.list_channels(db)]}


@router.post("/api/admin/ai/channels")
def admin_create_channel(body: ChannelIn, request: Request, db: Session = Depends(get_db)):
    _require_admin(request, db)
    if db.query(AiChannel).filter(AiChannel.code == body.code).first():
        raise HTTPException(400, "渠道编码已存在")
    _validate_channel_adapter(body.modality, body.adapter_type)
    base_url = ai_channels.validate_base_url(body.base_url, allow_http=True)
    ch = AiChannel(
        code=body.code.strip(),
        name=body.name.strip(),
        adapter_type=body.adapter_type,
        base_url=base_url,
        modality=body.modality,
        enabled=body.enabled,
        timeout_seconds=body.timeout_seconds,
        extra_config_json=body.extra_config_json,
    )
    ai_channels.set_platform_key(ch, body.platform_api_key)
    db.add(ch)
    db.commit()
    db.refresh(ch)
    return ai_channels.serialize_channel(ch)


@router.put("/api/admin/ai/channels/{channel_id}")
def admin_update_channel(channel_id: int, body: ChannelUpdateIn, request: Request, db: Session = Depends(get_db)):
    _require_admin(request, db)
    ch = db.get(AiChannel, channel_id)
    if not ch:
        raise HTTPException(404, "渠道不存在")
    target_modality = body.modality if body.modality is not None else ch.modality
    target_adapter_type = body.adapter_type if body.adapter_type is not None else ch.adapter_type
    _validate_channel_adapter(target_modality, target_adapter_type)
    if target_modality == "video" and target_adapter_type != ch.adapter_type:
        models = db.query(AiModel).filter(AiModel.channel_id == ch.id).order_by(AiModel.id.asc()).all()
        for model in models:
            try:
                _validate_model_capabilities(
                    model.capabilities_json,
                    model.modality,
                    target_adapter_type,
                )
            except HTTPException as exc:
                model_name = model.display_name or model.model_key
                raise HTTPException(
                    400,
                    f"模型 {model_name} 与目标视频适配器不兼容：{exc.detail}",
                ) from exc
    if body.name is not None:
        ch.name = body.name
    if body.adapter_type is not None:
        ch.adapter_type = body.adapter_type
    if body.base_url is not None:
        ch.base_url = ai_channels.validate_base_url(body.base_url, allow_http=True)
    if body.modality is not None:
        ch.modality = body.modality
    if body.enabled is not None:
        ch.enabled = body.enabled
    if body.timeout_seconds is not None:
        ch.timeout_seconds = body.timeout_seconds
    if body.extra_config_json is not None:
        ch.extra_config_json = body.extra_config_json
    if body.platform_api_key is not None and body.platform_api_key.strip() != "":
        ai_channels.set_platform_key(ch, body.platform_api_key)
    db.commit()
    db.refresh(ch)
    return ai_channels.serialize_channel(ch)


@router.get("/api/admin/ai/models")
def admin_list_models(request: Request, channel_id: int | None = None, db: Session = Depends(get_db)):
    _require_admin(request, db)
    q = db.query(AiModel)
    if channel_id:
        q = q.filter(AiModel.channel_id == channel_id)
    models = q.order_by(AiModel.sort_order.asc(), AiModel.id.asc()).all()
    return {"models": [ai_catalog.serialize_model_admin(db, m) for m in models]}


@router.post("/api/admin/ai/models")
def admin_create_model(body: ModelIn, request: Request, db: Session = Depends(get_db)):
    _require_admin(request, db)
    ch = db.get(AiChannel, body.channel_id)
    if not ch:
        raise HTTPException(404, "渠道不存在")
    if body.modality != ch.modality:
        raise HTTPException(400, "模型能力类型必须与所属渠道一致")
    exists = (
        db.query(AiModel)
        .filter(AiModel.channel_id == body.channel_id, AiModel.model_key == body.model_key)
        .first()
    )
    if exists:
        raise HTTPException(400, "同渠道下模型 key 已存在")
    _validate_model_capabilities(body.capabilities_json, body.modality, ch.adapter_type)
    model = AiModel(
        channel_id=body.channel_id,
        model_key=body.model_key.strip(),
        display_name=body.display_name.strip(),
        modality=body.modality,
        enabled=body.enabled,
        user_visible=body.user_visible,
        sort_order=body.sort_order,
        capabilities_json=body.capabilities_json,
    )
    db.add(model)
    db.commit()
    db.refresh(model)
    return ai_catalog.serialize_model_admin(db, model)


@router.put("/api/admin/ai/models/{model_id}")
def admin_update_model(model_id: int, body: ModelUpdateIn, request: Request, db: Session = Depends(get_db)):
    _require_admin(request, db)
    model = db.get(AiModel, model_id)
    if not model:
        raise HTTPException(404, "模型不存在")
    if body.modality is not None and body.modality != model.modality:
        raise HTTPException(400, "模型能力类型创建后不可修改，请新建模型迁移")
    target_modality = body.modality if body.modality is not None else model.modality
    if body.capabilities_json is not None:
        channel = db.get(AiChannel, model.channel_id)
        if not channel:
            raise HTTPException(404, "模型所属渠道不存在")
        _validate_model_capabilities(body.capabilities_json, target_modality, channel.adapter_type)
    if body.display_name is not None:
        model.display_name = body.display_name
    if body.enabled is not None:
        model.enabled = body.enabled
    if body.user_visible is not None:
        model.user_visible = body.user_visible
    if body.sort_order is not None:
        model.sort_order = body.sort_order
    if body.modality is not None:
        model.modality = body.modality
    if body.capabilities_json is not None:
        model.capabilities_json = body.capabilities_json
    db.commit()
    db.refresh(model)
    return ai_catalog.serialize_model_admin(db, model)


@router.delete("/api/admin/ai/models/{model_id}")
def admin_delete_model(model_id: int, request: Request, db: Session = Depends(get_db)):
    """删除未被业务数据引用的 AI 模型。"""
    _require_admin(request, db)
    model = db.get(AiModel, model_id)
    if not model:
        raise HTTPException(404, "模型不存在")

    references = {
        "任务默认模型": db.query(AiTaskDefault).filter(AiTaskDefault.model_id == model_id).count(),
        "用户默认模型": db.query(UserAiPreference).filter(
            or_(
                UserAiPreference.default_text_model_id == model_id,
                UserAiPreference.default_image_model_id == model_id,
                UserAiPreference.default_video_model_id == model_id,
            )
        ).count(),
        "创作台任务": db.query(CreationStudioJob).filter(CreationStudioJob.model_id == model_id).count(),
        "计费用量记录": db.query(AiUsageEvent).filter(AiUsageEvent.model_id == model_id).count(),
    }
    active_references = [f"{label}（{count}）" for label, count in references.items() if count]
    if active_references:
        raise HTTPException(409, f"模型仍被引用，无法删除：{'、'.join(active_references)}")

    db.delete(model)
    db.commit()
    return {"ok": True, "model_id": model_id}


@router.post("/api/admin/ai/channels/{channel_id}/models/sync")
async def admin_sync_channel_models(channel_id: int, request: Request, db: Session = Depends(get_db)):
    """从渠道的受限发现端点获取模型候选，不写入数据库。"""
    _require_admin(request, db)
    channel = db.get(AiChannel, channel_id)
    if not channel:
        raise HTTPException(404, "渠道不存在")
    if not channel.enabled:
        raise HTTPException(400, "渠道已停用，无法同步模型")
    api_key = ai_channels.load_platform_key(channel)
    if not api_key:
        raise HTTPException(400, "渠道未配置平台 API Key，无法同步模型")

    path = _discovery_path(channel)
    url = f"{channel.base_url.rstrip('/')}{path}"
    timeout_seconds = min(max(int(channel.timeout_seconds or 20), 5), 30)
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_seconds), follow_redirects=False) as client:
            response = await client.get(
                url,
                headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
            )
        if not response.is_success:
            raise HTTPException(502, f"上游模型发现失败 (HTTP {response.status_code})")
        if len(response.content) > 1024 * 1024:
            raise HTTPException(502, "上游模型列表响应过大")
        discovered = _parse_discovered_models(response.json())
    except HTTPException:
        raise
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(502, "无法获取或解析上游模型列表") from exc

    candidates = [
        {
            "key": key,
            "display_name": display_name,
            "capabilities": capabilities,
        }
        for key, display_name, capabilities in discovered
    ]
    return {"upstream_count": len(candidates), "candidates": candidates}


@router.post("/api/admin/ai/channels/{channel_id}/models")
def admin_add_channel_models(
    channel_id: int,
    body: ChannelModelsAddIn,
    request: Request,
    db: Session = Depends(get_db),
):
    """添加管理员选中的模型，不修改同渠道已有模型配置。"""
    _require_admin(request, db)
    channel = db.get(AiChannel, channel_id)
    if not channel:
        raise HTTPException(404, "渠道不存在")

    existing_keys = {
        model_key
        for (model_key,) in db.query(AiModel.model_key)
        .filter(AiModel.channel_id == channel.id)
        .all()
    }
    added: list[str] = []
    existing: list[str] = []
    selected_keys: set[str] = set()
    reported_existing_keys: set[str] = set()
    now = datetime.datetime.utcnow()

    for candidate in body.models:
        key = candidate.key.strip()
        display_name = (candidate.display_name or key).strip()
        if not key or not display_name:
            raise HTTPException(400, "模型 key 和显示名称不能为空")
        if key in selected_keys or key in existing_keys:
            if key not in reported_existing_keys:
                existing.append(key)
                reported_existing_keys.add(key)
            selected_keys.add(key)
            continue
        _validate_model_capabilities(candidate.capabilities, channel.modality, channel.adapter_type)
        try:
            with db.begin_nested():
                db.add(
                    AiModel(
                        channel_id=channel.id,
                        model_key=key,
                        display_name=display_name,
                        modality=channel.modality,
                        enabled=True,
                        user_visible=False,
                        sort_order=0,
                        capabilities_json=candidate.capabilities,
                        synced_at=now,
                    )
                )
                db.flush()
        except IntegrityError:
            if key not in reported_existing_keys:
                existing.append(key)
                reported_existing_keys.add(key)
            selected_keys.add(key)
            continue
        selected_keys.add(key)
        added.append(key)

    if added:
        db.commit()
    return {"added": added, "existing": existing}


@router.post("/api/admin/ai/models/{model_id}/prices")
def admin_set_price(model_id: int, body: PriceIn, request: Request, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    model = db.get(AiModel, model_id)
    if not model:
        raise HTTPException(404, "模型不存在")
    billing_type, price_config = _normalize_model_price(model, body)
    now = datetime.datetime.utcnow()
    active = ai_catalog.get_active_price(db, model_id)
    if active:
        active.valid_to = now
    price = AiModelPrice(
        model_id=model_id,
        billing_type=billing_type,
        price_config_json=price_config,
        valid_from=now,
        created_by=admin.id,
    )
    db.add(price)
    db.commit()
    db.refresh(price)
    return {
        "id": price.id,
        "model_id": model_id,
        "billing_type": price.billing_type,
        "price_config_json": price.price_config_json,
    }


@router.get("/api/admin/points/settings")
def admin_get_points_settings(request: Request, db: Session = Depends(get_db)):
    _require_admin(request, db)
    return {
        "yuan_to_points": float(_get_platform_setting("points.yuan_to_points", db, 10) or 10),
        "register_grant_enabled": bool(_get_platform_setting("points.register_grant_enabled", db, False)),
        "register_grant_amount": float(_get_platform_setting("points.register_grant_amount", db, 0) or 0),
        "dual_track_enabled": bool(_get_platform_setting("points.dual_track_enabled", db, True)),
    }


@router.put("/api/admin/points/settings")
def admin_put_points_settings(body: PointsSettingsIn, request: Request, db: Session = Depends(get_db)):
    _require_admin(request, db)
    if body.yuan_to_points is not None:
        _set_platform_setting("points.yuan_to_points", body.yuan_to_points, db)
    if body.register_grant_enabled is not None:
        _set_platform_setting("points.register_grant_enabled", body.register_grant_enabled, db)
    if body.register_grant_amount is not None:
        _set_platform_setting("points.register_grant_amount", body.register_grant_amount, db)
    if body.dual_track_enabled is not None:
        _set_platform_setting("points.dual_track_enabled", body.dual_track_enabled, db)
    return admin_get_points_settings(request, db)


@router.post("/api/admin/points/adjust")
def admin_adjust_points(body: AdjustPointsIn, request: Request, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    user = db.get(User, body.user_id)
    if not user:
        raise HTTPException(404, "用户不存在")
    amount = quantize_points(Decimal(body.amount))
    if amount == 0:
        raise HTTPException(400, "调整金额不能为 0")
    operation_id = body.request_id
    key = f"admin_adjust:{admin.id}:{user.id}:{operation_id}"
    account = points_accounts.get_account_for_update(db, user.id)
    existing_entry = db.query(PointsLedgerEntry).filter(PointsLedgerEntry.idempotency_key == key).first()
    if existing_entry:
        return points_accounts.serialize_account(account)
    if amount > 0:
        points_accounts.credit_points(
            db,
            user.id,
            amount,
            entry_type="admin_grant",
            idempotency_key=key,
            metadata={"note": body.note, "admin_id": admin.id},
        )
    else:
        need = quantize_points(-amount)
        if account.available_points < need:
            raise HTTPException(400, "用户可用积分不足，无法扣减")
        account.available_points = quantize_points(account.available_points - need)
        account.version = int(account.version or 0) + 1
        db.add(
            PointsLedgerEntry(
                account_id=account.id,
                entry_type="adjust",
                amount=-need,
                balance_after=account.available_points,
                idempotency_key=key,
                metadata_json={"note": body.note, "admin_id": admin.id},
            )
        )
    if not existing_entry:
        _main()._write_audit_log(
            admin,
            "admin_points_adjust",
            "user",
            user.id,
            f"调整用户 {user.email} 积分 {amount}",
            db,
            {"amount": str(amount), "note": body.note, "operation_id": operation_id},
        )
    db.commit()
    account = points_accounts.ensure_account(db, user.id)
    return points_accounts.serialize_account(account)


@router.post("/api/admin/users/{user_id}/points")
def admin_grant_user_points(
    user_id: int,
    body: GrantPointsIn,
    request: Request,
    db: Session = Depends(get_db),
):
    admin = _require_admin(request, db)
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "用户不存在")
    amount = quantize_points(body.amount)
    operation_id = body.request_id
    key = f"admin_grant:{admin.id}:{user.id}:{operation_id}"
    account = points_accounts.get_account_for_update(db, user.id)
    existing_entry = db.query(PointsLedgerEntry).filter(PointsLedgerEntry.idempotency_key == key).first()
    if existing_entry:
        return points_accounts.serialize_account(account)
    account = points_accounts.credit_points(
        db,
        user.id,
        amount,
        entry_type="admin_grant",
        idempotency_key=key,
        metadata={"note": body.note, "admin_id": admin.id, "operation_id": operation_id},
    )
    _main()._write_audit_log(
        admin,
        "admin_points_grant",
        "user",
        user.id,
        f"为用户 {user.email} 添加 {amount} 积分",
        db,
        {"amount": str(amount), "note": body.note, "operation_id": operation_id},
    )
    db.commit()
    return points_accounts.serialize_account(account)
