import asyncio
import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from models import AiChannel, AiModel, AiModelPrice, AiUsageEvent, BackgroundTask, Chapter, MangaImage, PointsAccount, PointsLedgerEntry, Story, User
from services.ai.channels import set_platform_key
from services.ai.credentials import save_user_api_key
from services.ai.resolver import begin_ai_call, complete_ai_call, refund_ai_call
from services.points import accounts as points_accounts
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


def test_text_call_count_expands_reservation_without_overcharging_per_call():
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
    assert event.settled_points == Decimal("2.0000")
    assert account.available_points == Decimal("18.0000")
    assert account.reserved_points == Decimal("0.0000")


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
