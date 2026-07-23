from __future__ import annotations

import datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from models import AiChannel, AiModel, AiModelPrice
from services.points.pricing import estimate_points


def _public_video_capabilities(raw: dict[str, Any] | None) -> dict[str, Any]:
    """仅向普通用户暴露用于表单约束的模型能力，绝不返回上游请求映射。"""
    video = (raw or {}).get("video")
    if not isinstance(video, dict):
        return {}
    result: dict[str, Any] = {}
    for key in ("input_modes", "defaults"):
        value = video.get(key)
        if isinstance(value, (list, dict)):
            result[key] = value
    limits = video.get("limits")
    if isinstance(limits, dict):
        result["limits"] = limits
    return result


def _public_image_capabilities(raw: dict[str, Any] | None) -> dict[str, Any]:
    """只向普通用户暴露图片质量选择所需的受控字段。"""
    image = (raw or {}).get("image")
    if not isinstance(image, dict):
        return {}
    result: dict[str, Any] = {}
    defaults = image.get("defaults")
    limits = image.get("limits")
    if isinstance(defaults, dict):
        public_defaults = {key: defaults[key] for key in ("quality",) if isinstance(defaults.get(key), str)}
        if public_defaults:
            result["defaults"] = public_defaults
    if isinstance(limits, dict):
        public_limits = {key: list(limits[key]) for key in ("qualities",) if isinstance(limits.get(key), list)}
        if public_limits:
            result["limits"] = public_limits
    return result


def get_active_price(db: Session, model_id: int) -> AiModelPrice | None:
    now = datetime.datetime.utcnow()
    return (
        db.query(AiModelPrice)
        .filter(
            AiModelPrice.model_id == model_id,
            AiModelPrice.valid_from <= now,
            or_(AiModelPrice.valid_to.is_(None), AiModelPrice.valid_to > now),
        )
        .order_by(AiModelPrice.valid_from.desc())
        .first()
    )


def list_user_visible_models(db: Session, modality: str | None = None) -> list[AiModel]:
    q = (
        db.query(AiModel)
        .join(AiChannel, AiChannel.id == AiModel.channel_id)
        .filter(
            AiModel.enabled.is_(True),
            AiModel.user_visible.is_(True),
            AiChannel.enabled.is_(True),
        )
    )
    if modality:
        q = q.filter(AiModel.modality == modality)
    return q.order_by(AiModel.sort_order.asc(), AiModel.id.asc()).all()


def get_visible_model(db: Session, model_id: int) -> AiModel:
    model = (
        db.query(AiModel)
        .join(AiChannel, AiChannel.id == AiModel.channel_id)
        .filter(
            AiModel.id == model_id,
            AiModel.enabled.is_(True),
            AiModel.user_visible.is_(True),
            AiChannel.enabled.is_(True),
        )
        .first()
    )
    if not model:
        raise HTTPException(404, "模型不存在或不可用")
    return model


def serialize_model_for_user(db: Session, model: AiModel) -> dict[str, Any]:
    price = get_active_price(db, model.id)
    price_summary = None
    estimated = None
    if price:
        cfg = price.price_config_json or {}
        estimated = float(
            estimate_points(
                billing_type=price.billing_type,
                price_config=cfg,
                use_estimate_defaults=True,
            )
        )
        price_summary = {
            "billing_type": price.billing_type,
            "price_config": cfg,
            "estimated_points": estimated,
        }
    return {
        "id": model.id,
        "model_key": model.model_key,
        "display_name": model.display_name,
        "intro_tag": model.intro_tag or "",
        "modality": model.modality,
        "channel_id": model.channel_id,
        "sort_order": model.sort_order,
        "video_capabilities": _public_video_capabilities(model.capabilities_json),
        "image_capabilities": _public_image_capabilities(model.capabilities_json),
        "price": price_summary,
        "estimated_points": estimated,
        "platform_configured": bool(price and model.channel.platform_secret_ciphertext),
    }


def serialize_model_admin(db: Session, model: AiModel) -> dict[str, Any]:
    price = get_active_price(db, model.id)
    return {
        "id": model.id,
        "channel_id": model.channel_id,
        "model_key": model.model_key,
        "display_name": model.display_name,
        "intro_tag": model.intro_tag or "",
        "modality": model.modality,
        "enabled": model.enabled,
        "user_visible": model.user_visible,
        "sort_order": model.sort_order,
        "capabilities_json": model.capabilities_json or {},
        "active_price": (
            {
                "id": price.id,
                "billing_type": price.billing_type,
                "price_config_json": price.price_config_json or {},
                "valid_from": price.valid_from.isoformat() if price.valid_from else None,
            }
            if price
            else None
        ),
    }
