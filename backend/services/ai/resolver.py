from __future__ import annotations

import contextlib
import contextvars
import uuid
import datetime
from decimal import Decimal
from typing import Any, Literal

from fastapi import HTTPException
from sqlalchemy.orm import Session

from models import AiChannel, AiModel, AiTaskDefault, AiUsageEvent, UserAiPreference
from services.ai.catalog import get_active_price, get_visible_model
from services.ai.channels import get_channel, load_platform_key
from services.ai.context import AIExecutionContext
from services.ai.credentials import load_user_api_key_plain
from services.points import accounts as points_accounts
from services.points.pricing import (
    TOKEN_BILLING_TYPES,
    estimate_points,
    price_snapshot,
    quantize_points,
    reserve_points_from_estimate,
)


# 视频按次计价时，一次预留可能覆盖多个片段（旧章节工作流一次批量生成多个镜头）。
# 调用方只知道总秒数，片段数通过这个上下文变量传给 begin_ai_call；按秒计价的模型不受影响。
_video_clip_count_var: contextvars.ContextVar[int] = contextvars.ContextVar("video_clip_count", default=1)


@contextlib.contextmanager
def video_clip_count(count: int):
    """在 with 块内发起的视频计费预留，按 count 个片段计次（仅对按次计价的视频模型生效）。"""
    token = _video_clip_count_var.set(max(1, int(count or 1)))
    try:
        yield
    finally:
        _video_clip_count_var.reset(token)


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


ModelSelectionPolicy = Literal["fallback", "interactive_strict"]


def _model_selection_error(modality: str, reason: str) -> HTTPException:
    label = {"text": "文本", "image": "图片", "video": "视频"}.get(modality, modality)
    messages = {
        "missing": f"请先选择并保存默认{label}模型",
        "deleted": f"已选择的{label}模型不存在，请重新选择",
        "disabled": f"已选择的{label}模型已停用，请重新选择",
        "hidden": f"已选择的{label}模型已下架，请重新选择",
        "channel_disabled": f"已选择的{label}模型所属渠道已停用，请重新选择",
        "modality_mismatch": f"已选择的模型不是{label}类型，请重新选择",
    }
    return HTTPException(
        status_code=409,
        detail={
            "code": "AI_MODEL_SELECTION_REQUIRED",
            "message": messages.get(reason, "请重新选择并保存默认模型"),
            "modality": modality,
            "reason": reason,
            "action": {"type": "open_ai_settings", "tab": "models"},
        },
    )


def _strict_visible_model(db: Session, model_id: int, modality: str) -> AiModel:
    model = db.get(AiModel, model_id)
    if not model:
        raise _model_selection_error(modality, "deleted")
    if model.modality != modality:
        raise _model_selection_error(modality, "modality_mismatch")
    if not model.enabled:
        raise _model_selection_error(modality, "disabled")
    if not model.user_visible:
        raise _model_selection_error(modality, "hidden")
    channel = db.get(AiChannel, model.channel_id)
    if not channel or not channel.enabled:
        raise _model_selection_error(modality, "channel_disabled")
    return model


def _has_selectable_model(db: Session, modality: str) -> bool:
    return (
        db.query(AiModel.id)
        .join(AiChannel, AiChannel.id == AiModel.channel_id)
        .filter(
            AiModel.enabled.is_(True),
            AiModel.user_visible.is_(True),
            AiModel.modality == modality,
            AiChannel.enabled.is_(True),
        )
        .first()
        is not None
    )


def resolve_model(
    db: Session,
    user_id: int,
    *,
    modality: str,
    model_id: int | None = None,
    task_type: str | None = None,
    selection_policy: ModelSelectionPolicy = "fallback",
) -> AiModel:
    if selection_policy not in {"fallback", "interactive_strict"}:
        raise ValueError(f"未知模型选择策略: {selection_policy}")

    if selection_policy == "interactive_strict" and model_id is not None:
        return _strict_visible_model(db, model_id, modality)

    if model_id:
        model = get_visible_model(db, model_id)
        if model.modality != modality:
            raise HTTPException(400, f"所选模型不是{modality}类型")
        return model

    pref = _pref(db, user_id)
    preference_model_id = None
    if pref:
        if modality == "text":
            preference_model_id = pref.default_text_model_id
        elif modality == "image":
            preference_model_id = pref.default_image_model_id
        elif modality == "video":
            preference_model_id = pref.default_video_model_id
        if preference_model_id:
            if selection_policy == "interactive_strict":
                return _strict_visible_model(db, preference_model_id, modality)
            try:
                return get_visible_model(db, preference_model_id)
            except HTTPException:
                pass

    if selection_policy == "interactive_strict" and _has_selectable_model(db, modality):
        raise _model_selection_error(modality, "missing")

    if task_type:
        td = db.query(AiTaskDefault).filter(AiTaskDefault.task_type == task_type, AiTaskDefault.enabled.is_(True)).first()
        if td:
            try:
                return get_visible_model(db, td.model_id)
            except HTTPException:
                pass

    model = (
        db.query(AiModel)
        .join(AiChannel, AiChannel.id == AiModel.channel_id)
        .filter(
            AiModel.enabled.is_(True),
            AiModel.user_visible.is_(True),
            AiModel.modality == modality,
            AiChannel.enabled.is_(True),
        )
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
        api_key = load_user_api_key_plain(db, user_id, modality)
        if not api_key:
            labels = {"text": "文本", "image": "图片", "video": "视频"}
            raise HTTPException(403, f"请先在用户中心配置{labels.get(modality, modality)} API Key，或切换到平台账户模式")
    else:
        api_key = load_platform_key(channel)
        if not api_key:
            raise HTTPException(500, "平台渠道 API Key 未配置")
        price = get_active_price(db, model.id)
        if not price:
            raise HTTPException(400, "该模型尚未配置积分价格")
        ek = estimate_kwargs or {}
        call_count = max(1, int(ek.get("call_count") or 1))
        if modality == "video":
            call_count = max(call_count, _video_clip_count_var.get())
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
        if price.billing_type in TOKEN_BILLING_TYPES:
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
            if modality == "video":
                # 视频按次计价：预估也按片段数放大，与按次结算（单价 × 片段数）口径一致。
                estimated = reservation_estimate
        streaming = bool(ek.get("streaming")) and modality == "text"
        reserved = Decimal("0") if streaming else reserve_points_from_estimate(reservation_estimate)
        price_snap = price_snapshot(price.billing_type, price.price_config_json, price.id)
        price_snap["call_count"] = call_count
        price_snap["streaming"] = streaming
        if price.billing_type in TOKEN_BILLING_TYPES:
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

    if mode == "platform" and reserved is not None and reserved > 0:
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


def charge_streaming_tokens(
    db: Session,
    ctx: AIExecutionContext,
    *,
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> Decimal:
    """按累计 Token 增量扣除流式文本费用，调用可安全重复。"""
    if ctx.credential_mode != "platform" or ctx.modality != "text":
        return Decimal("0")
    snap = ctx.price_snapshot or {}
    if not snap.get("streaming"):
        return Decimal("0")
    event = db.query(AiUsageEvent).filter(AiUsageEvent.id == ctx.usage_event_id).with_for_update().first()
    if not event or event.status in {"succeeded", "failed", "refunded"}:
        return Decimal("0")
    cfg = {**(snap.get("price_config") or {}), "min_points_per_call": 0}
    total = estimate_points(
        billing_type=str(snap.get("billing_type") or "per_1m_tokens"),
        price_config=cfg,
        input_tokens=max(0, int(input_tokens or 0)),
        output_tokens=max(0, int(output_tokens or 0)),
        use_estimate_defaults=False,
    )
    metadata = event.price_snapshot_json if isinstance(event.price_snapshot_json, dict) else dict(snap)
    charged_before = Decimal(str(metadata.get("stream_charged_points") or 0))
    delta = quantize_points(max(Decimal("0"), total - charged_before))
    if delta <= 0:
        return Decimal("0")
    charged = points_accounts.charge_points(
        db,
        ctx.user_id,
        delta,
        idempotency_key=f"stream:{ctx.request_id}:{max(0, int(output_tokens or 0))}",
        usage_event_id=event.id,
        metadata={"input_tokens": int(input_tokens or 0), "output_tokens": int(output_tokens or 0)},
    )
    event.price_snapshot_json = {**metadata, "stream_charged_points": str(quantize_points(charged_before + charged))}
    event.input_tokens = max(event.input_tokens or 0, int(input_tokens or 0))
    event.output_tokens = max(event.output_tokens or 0, int(output_tokens or 0))
    db.commit()
    return charged


def complete_ai_call(
    db: Session,
    ctx: AIExecutionContext,
    *,
    success: bool,
    input_tokens: int = 0,
    output_tokens: int = 0,
    image_count: int = 0,
    video_seconds: float | Decimal = 0,
    actual_call_count: int | None = None,
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
        if (ctx.price_snapshot or {}).get("streaming"):
            metadata = event.price_snapshot_json if isinstance(event.price_snapshot_json, dict) else {}
            captured = quantize_points(Decimal(str(metadata.get("stream_charged_points") or 0)))
            event.status = "failed"
            event.input_tokens = input_tokens
            event.output_tokens = output_tokens
            event.settled_points = captured
            event.error_code = error_code
            event.usage_source = usage_source
            event.completed_at = datetime.datetime.utcnow()
            if commit:
                db.commit()
            return
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
    elif (
        ctx.modality == "video"
        and billing_type == "per_second"
        and Decimal(str(video_seconds or 0)) <= 0
    ):
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
        if billing_type == "per_call":
            snapshot_actual_count = snap.get("actual_call_count")
            selected_call_count = (
                actual_call_count
                if actual_call_count is not None
                else snapshot_actual_count
            )
            call_count = (
                max(0, int(selected_call_count))
                if selected_call_count is not None
                else _positive_int(snap.get("call_count"), 1)
            )
            actual = quantize_points(actual * call_count)
            event.price_snapshot_json = {**snap, "actual_call_count": call_count}
    measured_zero = (
        (ctx.modality == "image" and image_count <= 0)
        or (
            ctx.modality == "video"
            and billing_type == "per_second"
            and Decimal(str(video_seconds or 0)) <= 0
        )
        or (
            billing_type == "per_call"
            and (
                (actual_call_count is not None and actual_call_count <= 0)
                or (
                    actual_call_count is None
                    and snap.get("actual_call_count") is not None
                    and int(snap.get("actual_call_count")) <= 0
                )
            )
        )
    )
    if actual <= 0 and ctx.estimated_points and not measured_zero:
        actual = quantize_points(Decimal(str(ctx.estimated_points)))
    if snap.get("streaming") and billing_type in TOKEN_BILLING_TYPES:
        metadata = event.price_snapshot_json if isinstance(event.price_snapshot_json, dict) else dict(snap)
        captured = quantize_points(Decimal(str(metadata.get("stream_charged_points") or 0)))
        remainder = quantize_points(max(Decimal("0"), actual - captured))
        if captured > actual:
            refund = quantize_points(captured - actual)
            points_accounts.credit_points(
                db,
                ctx.user_id,
                refund,
                entry_type="stream_reconcile",
                idempotency_key=f"stream:{ctx.request_id}:final-refund",
                usage_event_id=event.id,
                metadata={"captured": str(captured), "actual": str(actual)},
            )
            captured = actual
        if remainder > 0:
            charged = points_accounts.charge_points(
                db,
                ctx.user_id,
                remainder,
                idempotency_key=f"stream:{ctx.request_id}:final",
                usage_event_id=event.id,
                metadata={"final": True, "input_tokens": input_tokens, "output_tokens": output_tokens},
            )
            captured = quantize_points(captured + charged)
        event.price_snapshot_json = {**metadata, "stream_charged_points": str(captured)}
        event.status = "succeeded" if captured >= actual else "failed"
        event.input_tokens = input_tokens
        event.output_tokens = output_tokens
        event.settled_points = captured
        event.error_code = None if captured >= actual else "insufficient_settlement_balance"
        event.usage_source = usage_source
        event.completed_at = datetime.datetime.utcnow()
        if commit:
            db.commit()
        return
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
    actual_call_count: int | None = None,
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
        actual_call_count=actual_call_count,
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
