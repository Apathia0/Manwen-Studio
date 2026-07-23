import asyncio
import datetime
from decimal import Decimal
from dataclasses import replace
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from models import AiChannel, AiModel, AiModelPrice, AiUsageEvent, BackgroundTask, Chapter, MangaImage, PointsAccount, PointsLedgerEntry, Story, User
from routers import points_ai
from services.ai.bootstrap import ensure_default_channels_and_models, migrate_active_text_per_call_prices
from services.ai.catalog import get_active_price, get_visible_model, list_user_visible_models, serialize_model_for_user
from services.ai.channels import set_platform_key
from services.ai.credentials import save_user_api_key
from services.ai.resolver import begin_ai_call, complete_ai_call, refund_ai_call, resolve_model
from services.points import accounts as points_accounts
from services.points.pricing import estimate_points
from services import deepseek
from services.task_manager import TaskManager


def _billing_session(*, billing_type: str = "per_call", price_config: dict | None = None, modality: str = "text"):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    user = User(
        email="billing@example.com",
        password_hash="test",
        name="billing",
        role="user",
        status="active",
        email_verified=True,
    )
    channel = AiChannel(
        code="billing-test",
        name="计费测试渠道",
        adapter_type="openai_compatible",
        base_url="https://api.example.com/v1",
        modality=modality,
        enabled=True,
    )
    set_platform_key(channel, "sk-platform-test")
    db.add_all([user, channel])
    db.flush()
    model = AiModel(
        channel_id=channel.id,
        model_key="billing-model",
        display_name="计费测试模型",
        modality=modality,
        enabled=True,
        user_visible=True,
    )
    db.add(model)
    db.flush()
    db.add(
        AiModelPrice(
            model_id=model.id,
            billing_type=billing_type,
            price_config_json=price_config or {"points_per_call": 2},
            valid_from=datetime.datetime.utcnow(),
        )
    )
    points_accounts.credit_points(
        db,
        user.id,
        Decimal("20"),
        entry_type="test_grant",
        idempotency_key="test_grant",
    )
    db.commit()
    return db, user, model


def test_user_model_catalog_serializes_intro_tag_price_and_platform_availability():
    db, _user, model = _billing_session(billing_type="per_image", price_config={"points_per_image": 6}, modality="image")
    model.intro_tag = "细节出色"
    model.capabilities_json = {"image": {"defaults": {"quality": "high"}}}
    db.commit()

    result = serialize_model_for_user(db, model)

    assert result["intro_tag"] == "细节出色"
    assert result["image_capabilities"] == {"defaults": {"quality": "high"}}
    assert result["price"]["billing_type"] == "per_image"
    assert result["estimated_points"] == pytest.approx(6)
    assert result["platform_configured"] is True

    model.channel.platform_secret_ciphertext = None
    db.commit()
    assert serialize_model_for_user(db, model)["platform_configured"] is False


def test_disabled_channel_models_are_not_visible_or_selected_as_fallback():
    db, user, model = _billing_session()
    model.channel.enabled = False
    db.commit()

    assert list_user_visible_models(db) == []
    with pytest.raises(HTTPException) as visible_error:
        get_visible_model(db, model.id)
    assert visible_error.value.status_code == 404

    with pytest.raises(HTTPException) as fallback_error:
        resolve_model(db, user.id, modality="text")
    assert fallback_error.value.status_code == 400


def test_reserved_call_failure_releases_all_points_once():
    db, user, model = _billing_session()
    ctx = begin_ai_call(
        db,
        user_id=user.id,
        modality="text",
        task_type="chapter.expand",
        credential_mode="platform",
        model_id=model.id,
        request_id="reserve-release",
    )

    account = db.query(PointsAccount).filter_by(user_id=user.id).one()
    assert account.available_points == Decimal("18.0000")
    assert account.reserved_points == Decimal("2.0000")

    assert refund_ai_call(db, ctx.usage_event_id, error_code="upstream_failed") == Decimal("2.0000")
    assert refund_ai_call(db, ctx.usage_event_id, error_code="duplicate") == Decimal("0")
    db.refresh(account)
    assert account.available_points == Decimal("20.0000")
    assert account.reserved_points == Decimal("0.0000")


def test_reservation_settlement_rejects_cross_event_reserve_key():
    db, user, model = _billing_session()
    first = begin_ai_call(
        db,
        user_id=user.id,
        modality="text",
        task_type="billing.first",
        credential_mode="platform",
        model_id=model.id,
        request_id="cross-event-first",
    )
    second = begin_ai_call(
        db,
        user_id=user.id,
        modality="text",
        task_type="billing.second",
        credential_mode="platform",
        model_id=model.id,
        request_id="cross-event-second",
    )
    with pytest.raises(RuntimeError, match="用量事件不匹配"):
        points_accounts.settle_reservation(
            db,
            user.id,
            reserved_amount=first.reserved_points,
            actual_amount=first.reserved_points,
            reserve_idempotency_key=f"reserve:{second.request_id}",
            settle_idempotency_key="settle:cross-event",
            release_idempotency_key="release:cross-event",
            usage_event_id=first.usage_event_id,
        )


def test_settlement_idempotency_key_cannot_cross_usage_events():
    db, user, model = _billing_session()
    first = begin_ai_call(db, user_id=user.id, modality="text", task_type="billing.first", credential_mode="platform", model_id=model.id, request_id="idem-first")
    second = begin_ai_call(db, user_id=user.id, modality="text", task_type="billing.second", credential_mode="platform", model_id=model.id, request_id="idem-second")
    points_accounts.settle_reservation(
        db, user.id, reserved_amount=first.reserved_points, actual_amount=first.reserved_points,
        reserve_idempotency_key=f"reserve:{first.request_id}", settle_idempotency_key="settle:shared",
        release_idempotency_key="release:shared", usage_event_id=first.usage_event_id,
    )
    with pytest.raises(RuntimeError, match="结算幂等流水与用量事件不匹配"):
        points_accounts.settle_reservation(
            db, user.id, reserved_amount=second.reserved_points, actual_amount=second.reserved_points,
            reserve_idempotency_key=f"reserve:{second.request_id}", settle_idempotency_key="settle:shared",
            release_idempotency_key="release:shared-2", usage_event_id=second.usage_event_id,
        )


def test_insufficient_points_rejects_request_before_reservation():
    db, user, model = _billing_session()
    account = db.query(PointsAccount).filter_by(user_id=user.id).one()
    account.available_points = Decimal("1.0000")
    db.commit()

    with pytest.raises(HTTPException) as exc_info:
        begin_ai_call(
            db,
            user_id=user.id,
            modality="text",
            task_type="chapter.expand",
            credential_mode="platform",
            model_id=model.id,
            request_id="insufficient-reservation",
        )

    assert exc_info.value.status_code == 402
    db.rollback()
    db.refresh(account)
    assert account.available_points == Decimal("1.0000")
    assert account.reserved_points == Decimal("0.0000")
    assert db.query(AiUsageEvent).filter_by(request_id="insufficient-reservation").count() == 0


def test_settled_call_refund_uses_original_event_and_is_idempotent():
    db, user, model = _billing_session()
    ctx = begin_ai_call(
        db,
        user_id=user.id,
        modality="text",
        task_type="agent.chat",
        credential_mode="platform",
        model_id=model.id,
        request_id="settle-refund",
    )
    complete_ai_call(db, ctx, success=True, usage_source="estimated")

    assert refund_ai_call(db, ctx.usage_event_id, error_code="stream_failed") == Decimal("2.0000")
    assert refund_ai_call(db, ctx.usage_event_id, error_code="duplicate") == Decimal("0")
    account = db.query(PointsAccount).filter_by(user_id=user.id).one()
    refunds = db.query(PointsLedgerEntry).filter_by(entry_type="refund", usage_event_id=ctx.usage_event_id).all()
    ledger_total = sum(
        (entry.amount for entry in db.query(PointsLedgerEntry).filter_by(usage_event_id=ctx.usage_event_id)),
        Decimal("0"),
    )
    assert account.available_points == Decimal("20.0000")
    assert len(refunds) == 1
    assert ledger_total == Decimal("0.0000")
    assert db.get(AiUsageEvent, ctx.usage_event_id).status == "refunded"


def test_user_key_failure_never_credits_platform_points():
    db, user, model = _billing_session()
    save_user_api_key(db, user.id, "sk-user-test")
    ctx = begin_ai_call(
        db,
        user_id=user.id,
        modality="text",
        task_type="agent.chat",
        credential_mode="user_key",
        model_id=model.id,
        request_id="user-key-failure",
    )

    assert refund_ai_call(db, ctx.usage_event_id, error_code="upstream_failed") == Decimal("0")
    account = db.query(PointsAccount).filter_by(user_id=user.id).one()
    assert account.available_points == Decimal("20.0000")
    assert db.query(PointsLedgerEntry).filter_by(entry_type="refund").count() == 0


def test_token_call_reserves_configured_ceiling_and_settles_actual_usage():
    db, user, model = _billing_session(
        billing_type="per_1k_tokens",
        price_config={
            "input_points_per_1k": 1,
            "output_points_per_1k": 1,
            "estimate_default_input_tokens": 100,
            "estimate_default_output_tokens": 100,
            "reservation_max_input_tokens": 2000,
            "reservation_max_output_tokens": 2000,
        },
    )
    ctx = begin_ai_call(
        db,
        user_id=user.id,
        modality="text",
        task_type="chapter.expand",
        credential_mode="platform",
        model_id=model.id,
        request_id="actual-over-reserve",
    )
    complete_ai_call(db, ctx, success=True, input_tokens=2000, output_tokens=2000)

    event = db.get(AiUsageEvent, ctx.usage_event_id)
    account = db.query(PointsAccount).filter_by(user_id=user.id).one()
    settlement = db.query(PointsLedgerEntry).filter_by(
        usage_event_id=ctx.usage_event_id,
        entry_type="settle",
    ).one()
    ledger_total = sum(
        (entry.amount for entry in db.query(PointsLedgerEntry).filter_by(usage_event_id=ctx.usage_event_id)),
        Decimal("0"),
    )
    assert event.settled_points == Decimal("4.0000")
    assert settlement.amount == Decimal("0.0000")
    assert ledger_total == Decimal("-4.0000")
    assert account.available_points == Decimal("16.0000")
    assert account.reserved_points == Decimal("0.0000")


def test_per_1m_token_call_reserves_ceiling_and_settles_actual_usage():
    db, user, model = _billing_session(
        billing_type="per_1m_tokens",
        price_config={
            "input_points_per_1m": 100,
            "output_points_per_1m": 200,
            "estimate_default_input_tokens": 20000,
            "estimate_default_output_tokens": 8192,
            "reservation_max_input_tokens": 20000,
            "reservation_max_output_tokens": 8192,
            "min_points_per_call": 0.1,
        },
    )
    ctx = begin_ai_call(
        db,
        user_id=user.id,
        modality="text",
        task_type="chapter.expand",
        credential_mode="platform",
        model_id=model.id,
        request_id="per-1m-reserve-settle",
    )

    assert ctx.estimated_points == Decimal("3.6384")
    assert ctx.reserved_points == Decimal("3.6384")
    assert ctx.price_snapshot["reservation_max_input_tokens"] == 20000
    assert ctx.price_snapshot["reservation_max_output_tokens"] == 8192

    complete_ai_call(db, ctx, success=True, input_tokens=1000, output_tokens=500)

    event = db.get(AiUsageEvent, ctx.usage_event_id)
    account = db.query(PointsAccount).filter_by(user_id=user.id).one()
    assert event.settled_points == Decimal("0.2000")
    assert account.available_points == Decimal("19.8000")
    assert account.reserved_points == Decimal("0.0000")


def test_per_1m_token_formula_uses_separate_usage_rates_and_legacy_fallback():
    config = {"input_points_per_1m": 2000, "output_points_per_1m": 4000, "min_points_per_call": 0.1}
    assert estimate_points(
        billing_type="per_1m_tokens",
        price_config=config,
        input_tokens=1000,
        output_tokens=500,
        use_estimate_defaults=False,
    ) == Decimal("4.0000")
    assert estimate_points(
        billing_type="per_1m_tokens",
        price_config=config,
        input_tokens=10,
        output_tokens=10,
        use_estimate_defaults=False,
    ) == Decimal("0.1000")

    config = {"points_per_1m_tokens": 2000, "min_points_per_call": 0.1}
    assert estimate_points(
        billing_type="per_1m_tokens",
        price_config=config,
        input_tokens=1000,
        output_tokens=500,
        use_estimate_defaults=False,
    ) == Decimal("3.0000")
    assert estimate_points(
        billing_type="per_1m_tokens",
        price_config=config,
        input_tokens=10,
        output_tokens=10,
        use_estimate_defaults=False,
    ) == Decimal("0.1000")


def test_bootstrap_creates_default_text_per_1m_price():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()

    ensure_default_channels_and_models(db)

    model = db.query(AiModel).filter(AiModel.modality == "text").one()
    price = get_active_price(db, model.id)
    assert price.billing_type == "per_1m_tokens"
    assert price.price_config_json == {
        "input_points_per_1m": 2000.0,
        "output_points_per_1m": 2000.0,
        "estimate_default_input_tokens": 20000,
        "estimate_default_output_tokens": 8192,
        "reservation_max_input_tokens": 20000,
        "reservation_max_output_tokens": 8192,
        "min_points_per_call": 0.1,
    }


def test_per_call_price_migration_preserves_gradient_and_is_idempotent():
    db, _user, first_model = _billing_session()
    first_price = get_active_price(db, first_model.id)
    first_price.price_config_json = {"points_per_call": 4}
    now = datetime.datetime.utcnow()

    second_channel = AiChannel(
        code="migration-second",
        name="迁移测试渠道二",
        adapter_type="openai_compatible",
        base_url="https://api.example.com/v1",
        modality="text",
        enabled=True,
    )
    custom_channel = AiChannel(
        code="migration-custom",
        name="迁移自定义渠道",
        adapter_type="openai_compatible",
        base_url="https://api.example.com/v1",
        modality="text",
        enabled=True,
    )
    db.add_all([second_channel, custom_channel])
    db.flush()
    second_model = AiModel(
        channel_id=second_channel.id,
        model_key="migration-second",
        display_name="迁移模型二",
        modality="text",
        enabled=True,
        user_visible=True,
    )
    custom_model = AiModel(
        channel_id=custom_channel.id,
        model_key="migration-custom",
        display_name="迁移自定义模型",
        modality="text",
        enabled=True,
        user_visible=True,
    )
    db.add_all([second_model, custom_model])
    db.flush()
    db.add_all(
        [
            AiModelPrice(
                model_id=second_model.id,
                billing_type="per_call",
                price_config_json={"points_per_call": 2},
                valid_from=now - datetime.timedelta(minutes=1),
            ),
            AiModelPrice(
                model_id=custom_model.id,
                billing_type="per_1k_tokens",
                price_config_json={"input_points_per_1k": 1, "output_points_per_1k": 2},
                valid_from=now - datetime.timedelta(minutes=1),
            ),
        ]
    )
    db.commit()

    assert migrate_active_text_per_call_prices(db, now=now) == 3
    db.commit()
    assert migrate_active_text_per_call_prices(db, now=now + datetime.timedelta(seconds=1)) == 0
    db.commit()

    assert get_active_price(db, first_model.id).price_config_json["input_points_per_1m"] == pytest.approx(4 * 1_000_000 / 28_192)
    assert get_active_price(db, first_model.id).price_config_json["output_points_per_1m"] == pytest.approx(4 * 1_000_000 / 28_192)
    assert get_active_price(db, second_model.id).price_config_json["input_points_per_1m"] == pytest.approx(2 * 1_000_000 / 28_192)
    assert get_active_price(db, custom_model.id).price_config_json["input_points_per_1m"] == pytest.approx(1000)
    assert get_active_price(db, custom_model.id).price_config_json["output_points_per_1m"] == pytest.approx(2000)


def test_admin_text_price_api_forces_per_1m_defaults(monkeypatch):
    db, admin, model = _billing_session()
    monkeypatch.setattr(points_ai, "_require_admin", lambda *_args: admin)

    result = points_ai.admin_set_price(
        model.id,
        points_ai.PriceIn(
            billing_type="per_call",
            price_config_json={"points_per_1m_tokens": 2500, "points_per_call": 999},
        ),
        SimpleNamespace(),
        db,
    )

    assert result["billing_type"] == "per_1m_tokens"
    assert result["price_config_json"] == {
        "input_points_per_1m": 2500.0,
        "output_points_per_1m": 2500.0,
        "estimate_default_input_tokens": 20000,
        "estimate_default_output_tokens": 8192,
        "reservation_max_input_tokens": 20000,
        "reservation_max_output_tokens": 8192,
        "min_points_per_call": 0.1,
    }
    split_result = points_ai.admin_set_price(
        model.id,
        points_ai.PriceIn(
            price_config_json={
                "input_points_per_1m": 1200,
                "output_points_per_1m": 3600,
            }
        ),
        SimpleNamespace(),
        db,
    )
    assert split_result["price_config_json"]["input_points_per_1m"] == 1200.0
    assert split_result["price_config_json"]["output_points_per_1m"] == 3600.0
    with pytest.raises(HTTPException, match="非负数字"):
        points_ai.admin_set_price(
            model.id,
            points_ai.PriceIn(price_config_json={"points_per_1m_tokens": -1}),
            SimpleNamespace(),
            db,
        )


def test_token_ceiling_above_total_balance_rejects_before_upstream_call():
    db, user, model = _billing_session(
        billing_type="per_1k_tokens",
        price_config={
            "input_points_per_1k": 1,
            "output_points_per_1k": 1,
            "estimate_default_input_tokens": 100,
            "estimate_default_output_tokens": 100,
            "reservation_max_input_tokens": 50000,
            "reservation_max_output_tokens": 50000,
        },
    )
    with pytest.raises(HTTPException) as exc_info:
        begin_ai_call(
            db,
            user_id=user.id,
            modality="text",
            task_type="chapter.expand",
            credential_mode="platform",
            model_id=model.id,
            request_id="actual-over-balance",
        )
    assert exc_info.value.status_code == 402
    db.rollback()

    account = db.query(PointsAccount).filter_by(user_id=user.id).one()
    assert db.query(AiUsageEvent).filter_by(request_id="actual-over-balance").count() == 0
    assert account.available_points == Decimal("20.0000")
    assert account.reserved_points == Decimal("0.0000")


def test_text_call_count_expands_reservation_and_per_call_settlement():
    db, user, model = _billing_session()
    ctx = begin_ai_call(
        db,
        user_id=user.id,
        modality="text",
        task_type="import.story_bible.generate",
        credential_mode="platform",
        model_id=model.id,
        request_id="multi-call-reservation",
        estimate_kwargs={"call_count": 3},
    )

    account = db.query(PointsAccount).filter_by(user_id=user.id).one()
    assert ctx.estimated_points == Decimal("2.0000")
    assert ctx.reserved_points == Decimal("6.0000")
    assert account.available_points == Decimal("14.0000")

    complete_ai_call(db, ctx, success=True)

    event = db.get(AiUsageEvent, ctx.usage_event_id)
    db.refresh(account)
    assert event.settled_points == Decimal("6.0000")
    assert event.price_snapshot_json["actual_call_count"] == 3
    assert account.available_points == Decimal("14.0000")
    assert account.reserved_points == Decimal("0.0000")


def test_per_call_settlement_prefers_actual_call_count():
    db, user, model = _billing_session()
    ctx = begin_ai_call(
        db,
        user_id=user.id,
        modality="text",
        task_type="import.story_bible.generate",
        credential_mode="platform",
        model_id=model.id,
        request_id="actual-multi-call-settlement",
        estimate_kwargs={"call_count": 3},
    )

    complete_ai_call(db, ctx, success=True, actual_call_count=2)

    event = db.get(AiUsageEvent, ctx.usage_event_id)
    account = db.query(PointsAccount).filter_by(user_id=user.id).one()
    assert event.settled_points == Decimal("4.0000")
    assert event.price_snapshot_json["call_count"] == 3
    assert event.price_snapshot_json["actual_call_count"] == 2
    assert account.available_points == Decimal("16.0000")
    assert account.reserved_points == Decimal("0.0000")


def test_per_call_zero_actual_calls_releases_full_reservation():
    db, user, model = _billing_session()
    ctx = begin_ai_call(
        db,
        user_id=user.id,
        modality="text",
        task_type="import.story_bible.generate",
        credential_mode="platform",
        model_id=model.id,
        request_id="zero-actual-call-settlement",
        estimate_kwargs={"call_count": 3},
    )

    complete_ai_call(db, ctx, success=True, actual_call_count=0)

    event = db.get(AiUsageEvent, ctx.usage_event_id)
    account = db.query(PointsAccount).filter_by(user_id=user.id).one()
    assert event.settled_points == Decimal("0.0000")
    assert event.price_snapshot_json["actual_call_count"] == 0
    assert account.available_points == Decimal("20.0000")
    assert account.reserved_points == Decimal("0.0000")


def test_per_call_settlement_uses_persisted_actual_call_count():
    db, user, model = _billing_session()
    ctx = begin_ai_call(
        db,
        user_id=user.id,
        modality="text",
        task_type="import.story_bible.generate",
        credential_mode="platform",
        model_id=model.id,
        request_id="persisted-actual-call-settlement",
        estimate_kwargs={"call_count": 3},
    )
    ctx = replace(ctx, price_snapshot={**ctx.price_snapshot, "actual_call_count": 2})

    complete_ai_call(db, ctx, success=True)

    event = db.get(AiUsageEvent, ctx.usage_event_id)
    assert event.settled_points == Decimal("4.0000")
    assert event.price_snapshot_json["actual_call_count"] == 2


def test_deepseek_usage_accumulator_collects_and_clears_provider_usage():
    class Response:
        text = '{"choices": [], "usage": {"prompt_tokens": 120, "completion_tokens": 80}}'
        status_code = 200
        headers = {"content-type": "application/json"}

    deepseek.reset_usage_accumulator()
    deepseek._response_json(Response())

    assert deepseek.consume_usage_accumulator() == {"input_tokens": 120, "output_tokens": 80}
    assert deepseek.consume_usage_accumulator() == {"input_tokens": 0, "output_tokens": 0}


@pytest.mark.asyncio
async def test_deepseek_usage_accumulator_merges_parallel_child_tasks():
    async def record_usage(input_tokens: int, output_tokens: int) -> None:
        await asyncio.sleep(0)
        deepseek._record_response_usage(
            {"usage": {"prompt_tokens": input_tokens, "completion_tokens": output_tokens}}
        )

    deepseek.reset_usage_accumulator()
    await asyncio.gather(
        record_usage(100, 20),
        record_usage(200, 30),
        record_usage(300, 40),
    )

    assert deepseek.consume_usage_accumulator() == {
        "input_tokens": 600,
        "output_tokens": 90,
    }


def test_detached_stream_reservation_settles_provider_usage(monkeypatch):
    import main as main_mod

    db, user, model = _billing_session(
        billing_type="per_1k_tokens",
        price_config={
            "input_points_per_1k": 1,
            "output_points_per_1k": 1,
            "estimate_default_input_tokens": 1000,
            "estimate_default_output_tokens": 2000,
            "reservation_max_input_tokens": 5000,
            "reservation_max_output_tokens": 5000,
        },
    )
    ctx = begin_ai_call(
        db,
        user_id=user.id,
        modality="text",
        task_type="agent.chat",
        credential_mode="platform",
        model_id=model.id,
        request_id="detached-stream",
    )
    request = SimpleNamespace(
        state=SimpleNamespace(
            points_pending_charges=[{"usage_event_id": ctx.usage_event_id, "ctx": ctx}],
        )
    )
    detached = main_mod._detach_pending_platform_points(request, ctx.usage_event_id)
    session_factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False)
    monkeypatch.setattr(main_mod, "SessionLocal", session_factory)
    deepseek.reset_usage_accumulator()
    deepseek._record_response_usage(
        {"usage": {"prompt_tokens": 1200, "completion_tokens": 800}}
    )

    main_mod._finish_streaming_platform_points(
        detached,
        success=True,
        input_text="ignored",
        output_text="ignored",
    )

    check_db = session_factory()
    try:
        event = check_db.get(AiUsageEvent, ctx.usage_event_id)
        account = check_db.query(PointsAccount).filter_by(user_id=user.id).one()
        assert request.state.points_pending_charges == []
        assert event.status == "succeeded"
        assert event.settled_points == Decimal("2.0000")
        assert account.available_points == Decimal("18.0000")
        assert account.reserved_points == Decimal("0.0000")
    finally:
        check_db.close()


def test_background_task_failure_refunds_bound_usage_event_once(monkeypatch):
    db, user, model = _billing_session()
    ctx = begin_ai_call(
        db,
        user_id=user.id,
        modality="text",
        task_type="deconstruction.run",
        credential_mode="platform",
        model_id=model.id,
        request_id="background-refund",
    )
    complete_ai_call(db, ctx, success=True, usage_source="estimated")
    task = BackgroundTask(
        task_id="billing-background-task",
        task_type="deconstruction",
        status="running",
        quota_user_id=user.id,
        quota_feature_key="deconstruction.run",
        quota_amount=1,
        metadata_json={"billing_usage_event_id": ctx.usage_event_id},
    )
    db.add(task)
    db.commit()

    import services.task_manager as task_manager_module

    session_factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False)
    monkeypatch.setattr(task_manager_module, "SessionLocal", session_factory)
    manager = TaskManager(max_concurrent=1)
    manager._mark_task_failed(task.task_id, "upstream failed")
    manager._mark_task_failed(task.task_id, "duplicate callback")

    check_db = session_factory()
    try:
        account = check_db.query(PointsAccount).filter_by(user_id=user.id).one()
        event = check_db.get(AiUsageEvent, ctx.usage_event_id)
        refunds = check_db.query(PointsLedgerEntry).filter_by(
            usage_event_id=ctx.usage_event_id,
            entry_type="refund",
        ).all()
        assert account.available_points == Decimal("20.0000")
        assert event.status == "refunded"
        assert len(refunds) == 1
    finally:
        check_db.close()


def test_video_missing_result_marks_failed_and_refunds_persisted_usage_event_once():
    from routers import video as video_router

    db, user, model = _billing_session()
    ctx = begin_ai_call(
        db,
        user_id=user.id,
        modality="text",
        task_type="video.generate",
        credential_mode="platform",
        model_id=model.id,
        request_id="video-final-failure",
    )
    complete_ai_call(db, ctx, success=True, usage_source="estimated")
    job = SimpleNamespace(
        provider_payload_json={"billing_usage_event_id": ctx.usage_event_id},
        status="succeeded",
        error_message=None,
        completed_at=None,
    )

    video_router._fail_video_job_and_refund(
        db,
        job,
        error_message="视频生成成功但未返回可下载文件",
        reason="result_missing_video_path",
    )
    video_router._refund_video_billing(db, job=job, reason="duplicate")

    account = db.query(PointsAccount).filter_by(user_id=user.id).one()
    refunds = db.query(PointsLedgerEntry).filter_by(
        usage_event_id=ctx.usage_event_id,
        entry_type="refund",
    ).all()
    assert job.status == "failed"
    assert job.error_message == "视频生成成功但未返回可下载文件"
    assert job.completed_at is not None
    assert account.available_points == Decimal("20.0000")
    assert db.get(AiUsageEvent, ctx.usage_event_id).status == "refunded"
    assert len(refunds) == 1


def test_cancel_manga_generation_defers_settlement_until_worker_stops(monkeypatch):
    import main as main_mod

    db, user, model = _billing_session()
    ctx = begin_ai_call(
        db,
        user_id=user.id,
        modality="text",
        task_type="manga.image.generate.monthly_limit",
        credential_mode="platform",
        model_id=model.id,
        request_id="cancel-manga-reservation",
    )
    task = BackgroundTask(
        task_id="manga_generation_cancel_test",
        task_type="manga_generation",
        status="running",
        chapter_id=99,
        quota_user_id=user.id,
        quota_feature_key="manga.image.generate.monthly_limit",
        quota_amount=1,
        metadata_json={"billing_usage_event_id": ctx.usage_event_id},
    )
    db.add(task)
    db.commit()
    monkeypatch.setattr(main_mod, "_require_user", lambda request, session: user)
    monkeypatch.setattr(
        main_mod,
        "_require_chapter_for_user",
        lambda chapter_id, current_user, session: SimpleNamespace(id=chapter_id),
    )

    result = asyncio.run(main_mod.cancel_manga_generation(99, SimpleNamespace(), db))

    account = db.query(PointsAccount).filter_by(user_id=user.id).one()
    event = db.get(AiUsageEvent, ctx.usage_event_id)
    assert result["ok"] is True
    assert task.status == "cancel_requested"
    assert event.status == "reserved"
    assert account.available_points == Decimal("18.0000")
    assert account.reserved_points == Decimal("2.0000")


def test_manga_batch_settlement_charges_only_new_images(monkeypatch):
    import main as main_mod

    db, user, model = _billing_session(
        billing_type="per_image",
        price_config={"points_per_image": 5},
        modality="image",
    )
    story = Story(title="漫画结算测试", owner_user_id=user.id)
    db.add(story)
    db.flush()
    chapter = Chapter(story_id=story.id, chapter_number=1, title="第一章")
    db.add(chapter)
    db.flush()
    db.add(MangaImage(chapter_id=chapter.id, image_number=1, image_path="manga_outputs/test.png"))
    db.commit()
    ctx = begin_ai_call(
        db,
        user_id=user.id,
        modality="image",
        task_type="manga.image.generate.monthly_limit",
        credential_mode="platform",
        model_id=model.id,
        request_id="partial-manga-settlement",
        estimate_kwargs={"image_count": 2},
    )
    session_factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False)
    monkeypatch.setattr(main_mod, "SessionLocal", session_factory)
    metadata_updates = {}
    monkeypatch.setattr(
        main_mod.task_manager,
        "update_task_metadata",
        lambda task_id, **values: metadata_updates.update(values),
    )

    generated = main_mod._finish_manga_batch_billing(
        ctx,
        chapter_id=chapter.id,
        initial_existing_numbers=set(),
        task_id="manga-partial",
    )

    db.expire_all()
    account = db.query(PointsAccount).filter_by(user_id=user.id).one()
    event = db.get(AiUsageEvent, ctx.usage_event_id)
    assert generated == 1
    assert event.settled_points == Decimal("5.0000")
    assert account.available_points == Decimal("15.0000")
    assert account.reserved_points == Decimal("0.0000")
    assert metadata_updates["billing_usage_event_id"] == 0


def test_interrupted_manga_task_settles_persisted_partial_images(monkeypatch):
    """进程中断后应按已落库的新图片结算，不能整单退款形成免费产物。"""
    import services.task_manager as task_manager_module

    db, user, model = _billing_session(
        billing_type="per_image",
        price_config={"points_per_image": 5},
        modality="image",
    )
    story = Story(title="中断结算测试", owner_user_id=user.id)
    db.add(story)
    db.flush()
    chapter = Chapter(story_id=story.id, chapter_number=1, title="第一章")
    db.add(chapter)
    db.flush()
    db.add(MangaImage(chapter_id=chapter.id, image_number=1, image_path="manga_outputs/existing.png"))
    db.commit()
    ctx = begin_ai_call(
        db,
        user_id=user.id,
        modality="image",
        task_type="manga.image.generate.monthly_limit",
        credential_mode="platform",
        model_id=model.id,
        request_id="interrupted-manga-settlement",
        estimate_kwargs={"image_count": 2},
    )
    task = BackgroundTask(
        task_id="interrupted-manga",
        task_type="manga_generation",
        status="running",
        chapter_id=chapter.id,
        quota_user_id=user.id,
        quota_feature_key="manga.image.generate.monthly_limit",
        quota_amount=2,
        metadata_json={
            "billing_usage_event_id": ctx.usage_event_id,
            "initial_existing_numbers": [1],
        },
    )
    db.add_all([
        task,
        MangaImage(chapter_id=chapter.id, image_number=2, image_path="manga_outputs/generated.png"),
    ])
    db.commit()
    monkeypatch.setattr(
        task_manager_module,
        "SessionLocal",
        sessionmaker(bind=db.get_bind(), expire_on_commit=False),
    )

    TaskManager()._mark_task_failed(task.task_id, "服务中断")

    db.expire_all()
    account = db.query(PointsAccount).filter_by(user_id=user.id).one()
    event = db.get(AiUsageEvent, ctx.usage_event_id)
    saved_task = db.query(BackgroundTask).filter_by(task_id=task.task_id).one()
    assert event.status == "succeeded"
    assert event.image_count == 1
    assert event.settled_points == Decimal("5.0000")
    assert account.available_points == Decimal("15.0000")
    assert account.reserved_points == Decimal("0.0000")
    assert saved_task.metadata_json["billing_usage_event_id"] == 0
    assert saved_task.metadata_json["billing_settled_images"] == 1
