from __future__ import annotations

import datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from models import AiModel, AiModelPrice
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
    q = db.query(AiModel).filter(AiModel.enabled.is_(True), AiModel.user_visible.is_(True))
    if modality:
        q = q.filter(AiModel.modality == modality)
    return q.order_by(AiModel.sort_order.asc(), AiModel.id.asc()).all()


def get_visible_model(db: Session, model_id: int) -> AiModel:
    model = db.get(AiModel, model_id)
    if not model or not model.enabled or not model.user_visible:
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
        "modality": model.modality,
        "channel_id": model.channel_id,
        "sort_order": model.sort_order,
        "video_capabilities": _public_video_capabilities(model.capabilities_json),
        "price": price_summary,
        "estimated_points": estimated,
    }


def serialize_model_admin(db: Session, model: AiModel) -> dict[str, Any]:
    price = get_active_price(db, model.id)
    return {
        "id": model.id,
        "channel_id": model.channel_id,
        "model_key": model.model_key,
        "display_name": model.display_name,
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
