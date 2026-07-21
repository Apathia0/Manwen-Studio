from __future__ import annotations

import uuid
import datetime
from decimal import Decimal
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from models import AiModel, AiTaskDefault, AiUsageEvent, UserAiPreference
from services.ai.catalog import get_active_price, get_visible_model
from services.ai.channels import get_channel, load_platform_key
from services.ai.context import AIExecutionContext
from services.ai.credentials import load_user_api_key_plain
from services.points import accounts as points_accounts
from services.points.pricing import estimate_points, price_snapshot, quantize_points, reserve_points_from_estimate


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _pref(db: Session, user_id: int) -> UserAiPreference | None:
    return db.query(UserAiPreference).filter(UserAiPreference.user_id == user_id).first()


def resolve_credential_mode(db: Session, user_id: int, requested: str | None) -> str:
    mode = (requested or "").strip().lower()
    if mode in {"platform", "user_key"}:
        return mode
    pref = _pref(db, user_id)
    if pref and pref.credential_mode in {"platform", "user_key"}:
        return pref.credential_mode
    return "platform"


def resolve_model(
    db: Session,
    user_id: int,
    *,
    modality: str,
    model_id: int | None = None,
    task_type: str | None = None,
) -> AiModel:
    if model_id:
        model = get_visible_model(db, model_id)
        if model.modality != modality:
            raise HTTPException(400, f"所选模型不是{modality}类型")
        return model

    pref = _pref(db, user_id)
    if pref:
        mid = None
        if modality == "text":
            mid = pref.default_text_model_id
        elif modality == "image":
            mid = pref.default_image_model_id
        elif modality == "video":
            mid = pref.default_video_model_id
        if mid:
            try:
                return get_visible_model(db, mid)
            except HTTPException:
                pass

    if task_type:
        td = db.query(AiTaskDefault).filter(AiTaskDefault.task_type == task_type, AiTaskDefault.enabled.is_(True)).first()
        if td:
            try:
                return get_visible_model(db, td.model_id)
            except HTTPException:
                pass

    model = (
        db.query(AiModel)
        .filter(AiModel.enabled.is_(True), AiModel.user_visible.is_(True), AiModel.modality == modality)
        .order_by(AiModel.sort_order.asc(), AiModel.id.asc())
        .first()
    )
    if not model:
        raise HTTPException(400, f"暂无可用的{modality}模型，请联系管理员上架")
    return model


def begin_ai_call(
    db: Session,
    *,
    user_id: int,
    modality: str,
    task_type: str,
    credential_mode: str | None = None,
    model_id: int | None = None,
    request_id: str | None = None,
    story_id: int | None = None,
    chapter_id: int | None = None,
    estimate_kwargs: dict[str, Any] | None = None,
) -> AIExecutionContext:
    rid = (request_id or "").strip() or str(uuid.uuid4())
    existing = db.query(AiUsageEvent).filter(AiUsageEvent.request_id == rid).first()
    if existing:
        raise HTTPException(409, f"重复请求: {rid}，状态={existing.status}")

    mode = resolve_credential_mode(db, user_id, credential_mode)
    model = resolve_model(db, user_id, modality=modality, model_id=model_id, task_type=task_type)
    channel = get_channel(db, model.channel_id)
    base_url = (channel.base_url or "").rstrip("/")
    if not base_url:
        raise HTTPException(500, "渠道 Base URL 未配置")

    api_key: str | None = None
    estimated = None
    reserved = None
    price_snap = None

    if mode == "user_key":
        api_key = load_user_api_key_plain(db, user_id)
        if not api_key:
            raise HTTPException(403, "请先在用户中心配置 API Key，或切换到平台账户模式")
    else:
        api_key = load_platform_key(channel)
        if not api_key:
            raise HTTPException(500, "平台渠道 API Key 未配置")
        price = get_active_price(db, model.id)
        if not price:
            raise HTTPException(400, "该模型尚未配置积分价格")
        ek = estimate_kwargs or {}
        call_count = max(1, int(ek.get("call_count") or 1))
        estimated = estimate_points(
            billing_type=price.billing_type,
            price_config=price.price_config_json,
            input_tokens=int(ek.get("input_tokens") or 0),
            output_tokens=int(ek.get("output_tokens") or 0),
            image_count=int(ek.get("image_count") or 1),
            video_seconds=ek.get("video_seconds") or 0,
            use_estimate_defaults=True,
        )
        reservation_estimate = estimated
        if price.billing_type == "per_1k_tokens":
            estimated = quantize_points(estimated * call_count)
            reservation_max_input_tokens = max(
                _positive_int(ek.get("reservation_max_input_tokens"), 1),
                _positive_int(price.price_config_json.get("reservation_max_input_tokens"), 200000),
            )
            reservation_max_output_tokens = max(
                _positive_int(ek.get("reservation_max_output_tokens"), 1),
                _positive_int(price.price_config_json.get("reservation_max_output_tokens"), 100000),
            )
            reservation_estimate = quantize_points(
                estimate_points(
                    billing_type=price.billing_type,
                    price_config=price.price_config_json,
                    input_tokens=reservation_max_input_tokens,
                    output_tokens=reservation_max_output_tokens,
                    use_estimate_defaults=False,
                )
                * call_count
            )
        elif price.billing_type == "per_call":
            reservation_estimate = quantize_points(estimated * call_count)
        reserved = reserve_points_from_estimate(reservation_estimate)
        price_snap = price_snapshot(price.billing_type, price.price_config_json, price.id)
        price_snap["call_count"] = call_count
        if price.billing_type == "per_1k_tokens":
            price_snap["reservation_max_input_tokens"] = reservation_max_input_tokens
            price_snap["reservation_max_output_tokens"] = reservation_max_output_tokens

    event = AiUsageEvent(
        request_id=rid,
        user_id=user_id,
        story_id=story_id,
        chapter_id=chapter_id,
        task_type=task_type,
        credential_mode=mode,
        model_id=model.id,
        model_key=model.model_key,
        channel_id=channel.id,
        status="reserved" if mode == "platform" else "running",
        estimated_points=estimated,
        reserved_points=reserved,
        price_snapshot_json=price_snap,
    )
    db.add(event)
    db.flush()

    if mode == "platform" and reserved is not None:
        points_accounts.reserve_points(
            db,
            user_id,
            reserved,
            idempotency_key=f"reserve:{rid}",
            usage_event_id=event.id,
            metadata={"task_type": task_type, "model_id": model.id},
        )

    db.commit()
    db.refresh(event)

    return AIExecutionContext(
        request_id=rid,
        user_id=user_id,
        task_type=task_type,
        credential_mode=mode,
        channel_id=channel.id,
        model_id=model.id,
        model_key=model.model_key,
        modality=model.modality,
        base_url=base_url,
        api_key=api_key or "",
        adapter_type=channel.adapter_type,
        price_snapshot=price_snap,
        estimated_points=estimated,
        reserved_points=reserved,
        usage_event_id=event.id,
    )


def complete_ai_call(
    db: Session,
    ctx: AIExecutionContext,
    *,
    success: bool,
    input_tokens: int = 0,
    output_tokens: int = 0,
    image_count: int = 0,
    video_seconds: float | Decimal = 0,
    error_code: str | None = None,
    usage_source: str = "provider",
    commit: bool = True,
) -> None:
    event = (
        db.query(AiUsageEvent)
        .filter(AiUsageEvent.id == ctx.usage_event_id)
        .with_for_update()
        .first()
        if ctx.usage_event_id
        else None
    )
    if not event:
        return
    if event.status in {"succeeded", "failed", "refunded"}:
        return

    if ctx.credential_mode == "user_key":
        event.status = "succeeded" if success else "failed"
        event.input_tokens = input_tokens
        event.output_tokens = output_tokens
        event.image_count = image_count
        event.video_seconds = Decimal(str(video_seconds or 0))
        event.settled_points = Decimal("0")
        event.error_code = error_code
        event.usage_source = usage_source
        event.completed_at = datetime.datetime.utcnow()
        if commit:
            db.commit()
        return

    reserved = quantize_points(Decimal(str(ctx.reserved_points or 0)))
    if not success:
        points_accounts.release_reservation(
            db,
            ctx.user_id,
            reserved,
            idempotency_key=f"release:{ctx.request_id}",
            usage_event_id=event.id,
        )
        event.status = "failed"
        event.error_code = error_code
        event.settled_points = Decimal("0")
        event.completed_at = datetime.datetime.utcnow()
        if commit:
            db.commit()
        return

    snap = ctx.price_snapshot or {}
    billing_type = str(snap.get("billing_type") or "per_call")
    if ctx.modality == "image" and image_count <= 0:
        actual = Decimal("0")
    elif ctx.modality == "video" and Decimal(str(video_seconds or 0)) <= 0:
        actual = Decimal("0")
    else:
        actual = estimate_points(
            billing_type=billing_type,
            price_config=snap.get("price_config") or {},
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            image_count=image_count or 1,
            video_seconds=video_seconds,
            use_estimate_defaults=False,
        )
    measured_zero = (
        (ctx.modality == "image" and image_count <= 0)
        or (ctx.modality == "video" and Decimal(str(video_seconds or 0)) <= 0)
    )
    if actual <= 0 and ctx.estimated_points and not measured_zero:
        actual = quantize_points(Decimal(str(ctx.estimated_points)))
    charged = points_accounts.settle_reservation(
        db,
        ctx.user_id,
        reserved_amount=reserved,
        actual_amount=actual,
        reserve_idempotency_key=f"reserve:{ctx.request_id}",
        settle_idempotency_key=f"settle:{ctx.request_id}",
        release_idempotency_key=f"release:{ctx.request_id}",
        usage_event_id=event.id,
    )
    event.status = "succeeded" if charged >= actual else "failed"
    event.input_tokens = input_tokens
    event.output_tokens = output_tokens
    event.image_count = image_count
    event.video_seconds = Decimal(str(video_seconds or 0))
    event.settled_points = charged
    if charged < actual:
        event.error_code = "insufficient_settlement_balance"
    event.usage_source = usage_source
    event.completed_at = datetime.datetime.utcnow()
    if commit:
        db.commit()


def complete_ai_call_by_usage_event(
    db: Session,
    usage_event_id: int | None,
    *,
    success: bool,
    input_tokens: int = 0,
    output_tokens: int = 0,
    image_count: int = 0,
    video_seconds: float | Decimal = 0,
    error_code: str | None = None,
    usage_source: str = "provider",
    commit: bool = True,
) -> None:
    """根据持久化用量事件恢复最小计费上下文并完成结算。"""
    if not usage_event_id:
        return
    event = db.query(AiUsageEvent).filter(AiUsageEvent.id == usage_event_id).first()
    if not event or event.status in {"succeeded", "failed", "refunded"}:
        return
    model = db.get(AiModel, event.model_id) if event.model_id else None
    ctx = AIExecutionContext(
        request_id=event.request_id,
        user_id=event.user_id,
        task_type=event.task_type,
        credential_mode=event.credential_mode,
        channel_id=event.channel_id or 0,
        model_id=event.model_id or 0,
        model_key=event.model_key or "",
        modality=model.modality if model else "text",
        base_url="",
        api_key="",
        adapter_type="",
        price_snapshot=event.price_snapshot_json,
        estimated_points=event.estimated_points,
        reserved_points=event.reserved_points,
        usage_event_id=event.id,
    )
    complete_ai_call(
        db,
        ctx,
        success=success,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        image_count=image_count,
        video_seconds=video_seconds,
        error_code=error_code,
        usage_source=usage_source,
        commit=commit,
    )


def refund_ai_call(
    db: Session,
    usage_event_id: int | None,
    *,
    error_code: str = "refunded",
    commit: bool = True,
) -> Decimal:
    """按原始用量事件幂等退款，禁止根据当前模型价格重新估算。"""
    if not usage_event_id:
        return Decimal("0")

    event = (
        db.query(AiUsageEvent)
        .filter(AiUsageEvent.id == usage_event_id)
        .with_for_update()
        .first()
    )
    if not event or event.status in {"failed", "refunded"}:
        return Decimal("0")

    refunded = Decimal("0")
    if event.credential_mode == "platform":
        if event.status in {"reserved", "running"}:
            reserved = quantize_points(Decimal(str(event.reserved_points or 0)))
            if reserved > 0:
                points_accounts.release_reservation(
                    db,
                    event.user_id,
                    reserved,
                    idempotency_key=f"release:{event.request_id}",
                    usage_event_id=event.id,
                    metadata={"reason": error_code},
                )
                refunded = reserved
            event.status = "failed"
        elif event.status == "succeeded":
            settled = quantize_points(Decimal(str(event.settled_points or 0)))
            if settled > 0:
                points_accounts.credit_points(
                    db,
                    event.user_id,
                    settled,
                    entry_type="refund",
                    idempotency_key=f"refund_usage:{event.id}",
                    usage_event_id=event.id,
                    metadata={
                        "reason": error_code,
                        "request_id": event.request_id,
                        "task_type": event.task_type,
                        "usage_event_id": event.id,
                    },
                )
                refunded = settled
            event.status = "refunded"
    else:
        # 用户自带 Key 从未扣平台积分，只记录失败状态，绝不生成退款流水。
        event.status = "failed"

    event.error_code = error_code
    event.completed_at = datetime.datetime.utcnow()
    if commit:
        db.commit()
    return refunded
