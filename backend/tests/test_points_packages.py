import asyncio
import datetime
from decimal import Decimal
from types import SimpleNamespace
from urllib.parse import urlencode

import httpx
import pytest
from fastapi import HTTPException, Request
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import main
from database import Base
from models import AiChannel, AiModel, AuditLog, BillingOrder, Plan, PointsAccount, PointsLedgerEntry, PointsProduct, User
from routers import points_ai
from services import alipay_f2f
from services.video_adapter import (
    VIDEO_ADAPTER_LINGDONG,
    VIDEO_ADAPTER_OPENAI,
    normalize_video_adapter_type,
)
from services.payment import init_gateways
from services.payment.alipay_gateway import AlipayGateway
from services.payment.epay_gateway import EpayGateway, _paid_amount_matches as epay_amount_matches
from services.payment.epay_gateway import _epay_sign
from services.payment.mapay_gateway import MaPayGateway, _mapay_sign, _paid_amount_matches as mapay_amount_matches


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def _request() -> Request:
    return Request({"type": "http", "method": "PUT", "path": "/", "headers": []})


def _user(db, *, email: str, role: str = "user") -> User:
    user = User(
        email=email,
        password_hash="test",
        name=email.split("@", 1)[0],
        role=role,
        status="active",
        email_verified=True,
    )
    db.add(user)
    db.commit()
    return user


def _product(db) -> PointsProduct:
    product = PointsProduct(
        code="creator_pack",
        name="创作积分包",
        description="测试积分套餐",
        price_cny=Decimal("50.00"),
        points=Decimal("550"),
        bonus_points=Decimal("50"),
        is_visible=True,
        is_recommended=True,
        sort_order=1,
    )
    db.add(product)
    db.commit()
    return product


@pytest.mark.parametrize(
    ("adapter_type", "legacy_default", "expected"),
    [
        (VIDEO_ADAPTER_OPENAI, False, VIDEO_ADAPTER_OPENAI),
        (VIDEO_ADAPTER_LINGDONG, False, VIDEO_ADAPTER_LINGDONG),
        (None, True, VIDEO_ADAPTER_LINGDONG),
        ("", True, VIDEO_ADAPTER_LINGDONG),
    ],
)
def test_normalize_video_adapter_type_accepts_authoritative_values(
    adapter_type,
    legacy_default,
    expected,
):
    assert normalize_video_adapter_type(adapter_type, legacy_default=legacy_default) == expected


@pytest.mark.parametrize("adapter_type", [None, "", "openai_compatible", "sora_v2", "unknown"])
def test_normalize_video_adapter_type_rejects_non_authoritative_values(adapter_type):
    with pytest.raises(ValueError, match="视频适配器"):
        normalize_video_adapter_type(adapter_type)


def test_legacy_video_channel_adapter_migration_is_idempotent_and_scoped():
    from database import _migrate_legacy_video_channel_adapters

    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE ai_channels (
                id INTEGER PRIMARY KEY,
                modality VARCHAR(20) NOT NULL,
                adapter_type VARCHAR(64)
            )
        """))
        conn.execute(text("""
            INSERT INTO ai_channels (id, modality, adapter_type) VALUES
                (1, 'video', 'openai_compatible'),
                (2, 'video', ''),
                (3, 'video', NULL),
                (4, 'video', 'lingdong_video'),
                (5, 'video', 'openai_video'),
                (6, 'video', 'unknown_custom'),
                (7, 'text', 'openai_compatible'),
                (8, 'image', '')
        """))

    _migrate_legacy_video_channel_adapters(engine)
    with engine.connect() as conn:
        first = conn.execute(text(
            "SELECT id, adapter_type FROM ai_channels ORDER BY id"
        )).all()
    _migrate_legacy_video_channel_adapters(engine)
    with engine.connect() as conn:
        second = conn.execute(text(
            "SELECT id, adapter_type FROM ai_channels ORDER BY id"
        )).all()

    assert first == second
    assert first == [
        (1, "lingdong_video"),
        (2, "lingdong_video"),
        (3, "lingdong_video"),
        (4, "lingdong_video"),
        (5, "openai_video"),
        (6, "unknown_custom"),
        (7, "openai_compatible"),
        (8, ""),
    ]


def test_migrate_unlocked_invokes_legacy_video_channel_adapter_migration(monkeypatch):
    import database

    engine = create_engine("sqlite:///:memory:")
    calls = []
    monkeypatch.setattr(
        database,
        "_migrate_legacy_video_channel_adapters",
        lambda target_engine: calls.append(target_engine),
    )
    for name in (
        "_migrate_video_tables",
        "_migrate_video_character_tables",
        "_seed_video_style_presets",
        "_normalize_video_style_names",
        "_migrate_money_columns",
        "_assert_no_duplicate_content",
        "_add_unique_constraints",
        "_migrate_prompt_templates",
        "_migrate_agent_pending_changes",
        "_migrate_deconstruction_tables",
        "_migrate_deconstruction_library_tables",
    ):
        monkeypatch.setattr(database, name, lambda target_engine: None)

    database._migrate_unlocked(engine)
    database._migrate_unlocked(engine)

    assert calls == [engine, engine]


@pytest.mark.parametrize("adapter_type", [VIDEO_ADAPTER_OPENAI, VIDEO_ADAPTER_LINGDONG])
def test_admin_create_video_channel_accepts_supported_adapter(monkeypatch, adapter_type):
    db = _session()
    monkeypatch.setattr(main, "_require_admin", lambda request, session: SimpleNamespace(id=1))
    monkeypatch.setattr(points_ai.ai_channels, "validate_base_url", lambda value, **kwargs: value)

    result = points_ai.admin_create_channel(
        points_ai.ChannelIn(
            code=f"video-{adapter_type}",
            name="视频渠道",
            adapter_type=adapter_type,
            base_url="https://api.example.com/v1",
            modality="video",
        ),
        SimpleNamespace(),
        db,
    )

    assert result["adapter_type"] == adapter_type


def test_admin_create_video_channel_rejects_non_video_adapter(monkeypatch):
    db = _session()
    monkeypatch.setattr(main, "_require_admin", lambda request, session: SimpleNamespace(id=1))

    with pytest.raises(HTTPException, match="视频渠道"):
        points_ai.admin_create_channel(
            points_ai.ChannelIn(
                code="invalid-video-adapter",
                name="错误视频渠道",
                adapter_type="openai_compatible",
                base_url="https://api.example.com/v1",
                modality="video",
            ),
            SimpleNamespace(),
            db,
        )


def test_admin_update_channel_validates_final_modality_adapter_combination(monkeypatch):
    db = _session()
    channel = AiChannel(
        code="text-to-video",
        name="待转换渠道",
        adapter_type="openai_compatible",
        base_url="https://api.example.com/v1",
        modality="text",
        enabled=True,
    )
    db.add(channel)
    db.commit()
    monkeypatch.setattr(main, "_require_admin", lambda request, session: SimpleNamespace(id=1))

    with pytest.raises(HTTPException, match="视频渠道"):
        points_ai.admin_update_channel(
            channel.id,
            points_ai.ChannelUpdateIn(modality="video"),
            SimpleNamespace(),
            db,
        )


def test_admin_text_channel_keeps_existing_adapter_rule(monkeypatch):
    db = _session()
    monkeypatch.setattr(main, "_require_admin", lambda request, session: SimpleNamespace(id=1))
    monkeypatch.setattr(points_ai.ai_channels, "validate_base_url", lambda value, **kwargs: value)

    result = points_ai.admin_create_channel(
        points_ai.ChannelIn(
            code="text-openai-compatible",
            name="文本渠道",
            adapter_type="openai_compatible",
            base_url="https://api.example.com/v1",
            modality="text",
        ),
        SimpleNamespace(),
        db,
    )

    assert result["adapter_type"] == "openai_compatible"


def _openai_video_capabilities(**video_overrides):
    video = {
        "input_modes": ["text_to_video", "image_to_video"],
        "limits": {
            "duration_seconds": {"allowed": [5, 10]},
            "max_reference_images": 1,
            "aspect_ratios": ["16:9"],
            "resolutions": ["720P"],
        },
        "wire": {"size_by_resolution_aspect": {"720P|16:9": "1280x720"}},
    }
    video.update(video_overrides)
    return {"schema_version": 1, "video": video}


def test_openai_video_capabilities_accept_controlled_manual_subset():
    points_ai._validate_model_capabilities(
        _openai_video_capabilities(),
        "video",
        VIDEO_ADAPTER_OPENAI,
    )


@pytest.mark.parametrize(
    "video_overrides",
    [
        {"payload_profile": "sora_v2"},
        {"limits": {"duration_seconds": {"allowed": [5]}, "max_reference_images": 2}},
        {"wire": {"reference_field": "input_reference", "size_by_resolution_aspect": {"720P|16:9": "1280x720"}}},
        {"wire": {"size_by_resolution_aspect": {"720P|16:9": "large"}}},
        {"wire": {"size_by_resolution_aspect": {"720P|16:9": "1280x720"}, "arbitrary_field": "unsafe"}},
    ],
)
def test_openai_video_capabilities_reject_relay_or_unsupported_values(video_overrides):
    with pytest.raises(HTTPException):
        points_ai._validate_model_capabilities(
            _openai_video_capabilities(**video_overrides),
            "video",
            VIDEO_ADAPTER_OPENAI,
        )


def test_lingdong_video_capabilities_keep_sora_v2_profile():
    points_ai._validate_model_capabilities(
        {
            "video": {
                "payload_profile": "sora_v2",
                "wire": {
                    "duration_field": "seconds",
                    "reference_field": "input_reference",
                    "size_by_resolution_aspect": {"720P|16:9": "1280x720"},
                },
            }
        },
        "video",
        VIDEO_ADAPTER_LINGDONG,
    )


def test_admin_create_model_uses_owning_channel_adapter(monkeypatch):
    db = _session()
    channel = AiChannel(
        code="native-openai-video",
        name="OpenAI 原生视频",
        adapter_type=VIDEO_ADAPTER_OPENAI,
        base_url="https://api.openai.com/v1",
        modality="video",
        enabled=True,
    )
    db.add(channel)
    db.commit()
    monkeypatch.setattr(main, "_require_admin", lambda request, session: SimpleNamespace(id=1))

    with pytest.raises(HTTPException):
        points_ai.admin_create_model(
            points_ai.ModelIn(
                channel_id=channel.id,
                model_key="invalid-relay-profile",
                display_name="错误中转配置",
                modality="video",
                capabilities_json=_openai_video_capabilities(payload_profile="sora_v2"),
            ),
            SimpleNamespace(),
            db,
        )


def test_admin_update_video_channel_rejects_incompatible_existing_model(monkeypatch):
    db = _session()
    channel = AiChannel(
        code="relay-with-model",
        name="中转视频渠道",
        adapter_type=VIDEO_ADAPTER_LINGDONG,
        base_url="https://relay.example.com/v1",
        modality="video",
        enabled=True,
    )
    db.add(channel)
    db.flush()
    model = AiModel(
        channel_id=channel.id,
        model_key="relay-sora",
        display_name="旧版 Sora 中转模型",
        modality="video",
        capabilities_json={
            "video": {
                "payload_profile": "sora_v2",
                "wire": {"size_by_resolution_aspect": {"720P|16:9": "1280x720"}},
            }
        },
    )
    db.add(model)
    db.commit()
    monkeypatch.setattr(main, "_require_admin", lambda request, session: SimpleNamespace(id=1))

    with pytest.raises(HTTPException, match="旧版 Sora 中转模型"):
        points_ai.admin_update_channel(
            channel.id,
            points_ai.ChannelUpdateIn(adapter_type=VIDEO_ADAPTER_OPENAI),
            _request(),
            db,
        )

    db.refresh(channel)
    assert channel.adapter_type == VIDEO_ADAPTER_LINGDONG


def test_admin_update_video_channel_rejects_openai_model_without_capabilities(monkeypatch):
    db = _session()
    channel = AiChannel(
        code="relay-with-unconfigured-model",
        name="未配置能力的中转渠道",
        adapter_type=VIDEO_ADAPTER_LINGDONG,
        base_url="https://relay.example.com/v1",
        modality="video",
        enabled=True,
    )
    db.add(channel)
    db.flush()
    db.add(
        AiModel(
            channel_id=channel.id,
            model_key="unconfigured-video",
            display_name="未配置能力的视频模型",
            modality="video",
            capabilities_json=None,
        )
    )
    db.commit()
    monkeypatch.setattr(main, "_require_admin", lambda request, session: SimpleNamespace(id=1))

    with pytest.raises(HTTPException, match="未配置能力的视频模型"):
        points_ai.admin_update_channel(
            channel.id,
            points_ai.ChannelUpdateIn(adapter_type=VIDEO_ADAPTER_OPENAI),
            _request(),
            db,
        )


@pytest.mark.parametrize(
    "video",
    [
        {"payload_profile": "legacy_lingdong", "unknown": True},
        {"payload_profile": "legacy_lingdong", "input_modes": "text_to_video"},
        {"payload_profile": "legacy_lingdong", "limits": {"unknown": 1}},
        {"payload_profile": "legacy_lingdong", "limits": {"max_reference_images": "9"}},
        {"payload_profile": "legacy_lingdong", "limits": {"resolutions": ["ultra"]}},
        {"payload_profile": "legacy_lingdong", "limits": {"duration_seconds": {"allowed": [5], "unknown": 1}}},
        {"payload_profile": "legacy_lingdong", "wire": {"unknown": "field"}},
        {"payload_profile": "legacy_lingdong", "wire": {"resolution_field": "quality"}},
        {"payload_profile": "legacy_lingdong", "wire": {"ratio_field": "aspect_ratio"}},
        {
            "payload_profile": "legacy_lingdong",
            "defaults": {"resolution": "1080P"},
            "limits": {
                "aspect_ratios": ["16:9"],
                "resolutions": ["720P"],
                "duration_seconds": {"allowed": [15]},
            },
        },
        {"payload_profile": "sora_v2", "wire": {"reference_field": "images", "size_by_resolution_aspect": {"720P|16:9": "1280x720"}}},
    ],
)
def test_lingdong_capabilities_reject_unknown_or_invalid_fields(video):
    with pytest.raises(HTTPException):
        points_ai._validate_model_capabilities(
            {"video": video},
            "video",
            VIDEO_ADAPTER_LINGDONG,
        )


@pytest.mark.parametrize(
    "video",
    [
        {
            "payload_profile": "legacy_lingdong",
            "defaults": {
                "aspect_ratio": "16:9",
                "resolution": "720P",
                "duration_seconds": 15,
            },
            "input_modes": ["text_to_video", "image_to_video"],
            "limits": {
                "aspect_ratios": ["16:9"],
                "resolutions": ["720P"],
                "max_reference_images": 9,
                "duration_seconds": {"min": 4, "max": 15},
            },
            "wire": {
                "reference_field": "input_reference",
                "resolution_field": "resolution",
                "ratio_field": "ratio",
            },
        },
        {
            "payload_profile": "seedance_fast",
            "limits": {"duration_seconds": {"allowed": [5, 10]}},
        },
        {
            "payload_profile": "sora_v2",
            "wire": {
                "duration_field": "seconds",
                "duration_as_string": True,
                "reference_field": "input_reference",
                "size_by_resolution_aspect": {"720P|16:9": "1280x720"},
            },
        },
    ],
)
def test_lingdong_capabilities_keep_documented_profiles(video):
    points_ai._validate_model_capabilities(
        {"video": video},
        "video",
        VIDEO_ADAPTER_LINGDONG,
    )


def test_metadata_supports_points_orders_without_legacy_plan():
    db = _session()
    user = _user(db, email="buyer@example.com")
    product = _product(db)
    order = BillingOrder(
        order_no="PTS-METADATA-1",
        user_id=user.id,
        plan_id=None,
        points_product_id=product.id,
        amount=product.price_cny,
        currency="CNY",
        status="pending",
        source="points_purchase",
        billing_cycle="one_time",
    )
    db.add(order)
    db.commit()

    assert order.plan_id is None
    assert order.points_product_id == product.id


def test_channel_model_discovery_does_not_write_models(monkeypatch):
    db = _session()
    channel = AiChannel(
        code="discovery-channel",
        name="发现渠道",
        adapter_type="openai_compatible",
        base_url="https://api.example.com/v1",
        modality="text",
        enabled=True,
    )
    db.add(channel)
    db.commit()
    monkeypatch.setattr(main, "_require_admin", lambda request, session: SimpleNamespace(id=1))
    monkeypatch.setattr(points_ai.ai_channels, "load_platform_key", lambda current_channel: "test-key")

    class Response:
        is_success = True
        content = b'{"data": [{"id": "alpha", "name": "Alpha"}]}'

        @staticmethod
        def json():
            return {"data": [{"id": "alpha", "name": "Alpha"}]}

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, *args, **kwargs):
            return Response()

    monkeypatch.setattr(points_ai.httpx, "AsyncClient", lambda **kwargs: Client())

    result = asyncio.run(points_ai.admin_sync_channel_models(channel.id, SimpleNamespace(), db))

    assert result == {
        "upstream_count": 1,
        "candidates": [{"key": "alpha", "display_name": "Alpha", "capabilities": None}],
    }
    assert db.query(AiModel).filter(AiModel.channel_id == channel.id).count() == 0


def test_admin_add_channel_models_hides_new_models_and_preserves_existing(monkeypatch):
    db = _session()
    channel = AiChannel(
        code="batch-add-channel",
        name="批量添加渠道",
        adapter_type="openai_compatible",
        base_url="https://api.example.com/v1",
        modality="text",
        enabled=True,
    )
    db.add(channel)
    db.commit()
    existing_model = AiModel(
        channel_id=channel.id,
        model_key="configured",
        display_name="人工配置名称",
        modality="text",
        enabled=False,
        user_visible=True,
        sort_order=9,
        capabilities_json={"manual": True},
    )
    db.add(existing_model)
    db.commit()
    monkeypatch.setattr(main, "_require_admin", lambda request, session: SimpleNamespace(id=1))

    result = points_ai.admin_add_channel_models(
        channel.id,
        points_ai.ChannelModelsAddIn(
            models=[
                points_ai.DiscoveredModelIn(key="configured", display_name="上游名称"),
                points_ai.DiscoveredModelIn(key="new-model", display_name="新模型"),
                points_ai.DiscoveredModelIn(key="new-model", display_name="重复选择"),
            ]
        ),
        SimpleNamespace(),
        db,
    )

    db.refresh(existing_model)
    new_model = db.query(AiModel).filter(AiModel.channel_id == channel.id, AiModel.model_key == "new-model").one()
    assert result == {"added": ["new-model"], "existing": ["configured", "new-model"]}
    assert existing_model.display_name == "人工配置名称"
    assert existing_model.enabled is False
    assert existing_model.user_visible is True
    assert existing_model.capabilities_json == {"manual": True}
    assert new_model.enabled is True
    assert new_model.user_visible is False


def test_legacy_order_serialization_keeps_plan_name():
    db = _session()
    user = _user(db, email="legacy@example.com")
    plan = Plan(code="legacy-pro", name="历史专业版", monthly_price=Decimal("59.00"))
    db.add(plan)
    db.commit()
    order = BillingOrder(
        order_no="LEGACY-ORDER-1",
        user_id=user.id,
        plan_id=plan.id,
        amount=Decimal("59.00"),
        currency="CNY",
        status="paid",
        source="subscription",
    )
    db.add(order)
    db.commit()

    assert main._serialize_order_with_db(order, db)["plan_name"] == plan.name


def test_points_purchase_payment_is_idempotent():
    db = _session()
    user = _user(db, email="paid@example.com")
    product = _product(db)
    order = BillingOrder(
        order_no="PTS-PAID-1",
        user_id=user.id,
        plan_id=None,
        points_product_id=product.id,
        amount=product.price_cny,
        currency="CNY",
        status="pending",
        source="points_purchase",
        billing_cycle="one_time",
        extra_json={
            "product_id": product.id,
            "product_name": product.name,
            "points": "550",
            "bonus_points": "50",
        },
    )
    db.add(order)
    db.commit()

    main._mark_order_paid(order, db)
    db.commit()
    main._mark_order_paid(order, db)
    db.commit()

    account = db.query(PointsAccount).filter(PointsAccount.user_id == user.id).one()
    entries = db.query(PointsLedgerEntry).filter(PointsLedgerEntry.order_id == order.id).all()
    assert account.available_points == Decimal("600.0000")
    assert len(entries) == 1
    assert entries[0].idempotency_key == f"points_purchase:{order.order_no}"


def test_admin_grant_points_is_retry_safe(monkeypatch):
    db = _session()
    admin = _user(db, email="admin@example.com", role="admin")
    user = _user(db, email="reader@example.com")
    monkeypatch.setattr(main, "_require_admin", lambda request, session: admin)
    body = points_ai.GrantPointsIn(amount=Decimal("88.5"), note="活动补发", request_id="grant-1")

    first = points_ai.admin_grant_user_points(user.id, body, SimpleNamespace(), db)
    second = points_ai.admin_grant_user_points(user.id, body, SimpleNamespace(), db)

    assert first["available_points"] == 88.5
    assert second["available_points"] == 88.5
    assert db.query(PointsLedgerEntry).filter(PointsLedgerEntry.entry_type == "admin_grant").count() == 1
    assert db.query(AuditLog).filter(AuditLog.action == "admin_points_grant").count() == 1


def test_admin_grant_points_rejects_unknown_user(monkeypatch):
    db = _session()
    admin = _user(db, email="admin2@example.com", role="admin")
    monkeypatch.setattr(main, "_require_admin", lambda request, session: admin)

    with pytest.raises(HTTPException) as exc_info:
        points_ai.admin_grant_user_points(
            9999,
            points_ai.GrantPointsIn(amount=Decimal("10"), request_id="missing-user"),
            SimpleNamespace(),
            db,
        )

    assert exc_info.value.status_code == 404


def test_purchase_points_creates_one_time_checkout(monkeypatch):
    db = _session()
    user = _user(db, email="checkout@example.com")
    product = _product(db)
    init_gateways()
    monkeypatch.setattr(main, "_require_user", lambda request, session: user)
    monkeypatch.setattr(main, "_mock_payments_enabled", lambda: True)
    monkeypatch.setattr(main, "_payment_settings_snapshot", lambda session: {
        "enabled": True,
        "default_method": "mock_qr",
        "order_expire_minutes": 30,
        "instructions": "测试支付",
    })
    monkeypatch.setattr(main, "_payment_method_options", lambda session: [])

    result = points_ai.purchase_points(
        points_ai.PurchasePointsIn(product_id=product.id, payment_method="mock_qr"),
        SimpleNamespace(client=SimpleNamespace(host="127.0.0.1")),
        db,
    )

    order = db.query(BillingOrder).filter(BillingOrder.order_no == result["order_no"]).one()
    assert order.plan_id is None
    assert order.points_product_id == product.id
    assert order.billing_cycle == "one_time"
    assert result["checkout"]["source"] == "points_purchase"
    assert result["checkout"]["plan_name"] == product.name
    assert result["checkout"]["can_mock_confirm"] is True


def test_purchase_points_rejects_mock_payment_by_default(monkeypatch):
    db = _session()
    user = _user(db, email="secure-checkout@example.com")
    product = _product(db)
    init_gateways()
    monkeypatch.setattr(main, "_require_user", lambda request, session: user)
    monkeypatch.setattr(main, "_mock_payments_enabled", lambda: False)
    monkeypatch.setattr(main, "_payment_settings_snapshot", lambda session: {
        "enabled": True,
        "default_method": "mock_qr",
        "order_expire_minutes": 30,
        "instructions": "",
    })
    monkeypatch.setattr(main, "_payment_method_options", lambda session: [])

    with pytest.raises(HTTPException) as exc_info:
        points_ai.purchase_points(
            points_ai.PurchasePointsIn(product_id=product.id, payment_method="mock_qr"),
            SimpleNamespace(client=SimpleNamespace(host="127.0.0.1")),
            db,
        )

    assert exc_info.value.status_code == 403


def test_admin_can_manage_points_products(monkeypatch):
    db = _session()
    admin = _user(db, email="product-admin@example.com", role="admin")
    monkeypatch.setattr(main, "_require_admin", lambda request, session: admin)

    created = points_ai.admin_create_points_product(
        points_ai.PointsProductIn(
            code="starter_pack",
            name="入门积分包",
            description="适合首次购买",
            price_cny=Decimal("20"),
            points=Decimal("220"),
            bonus_points=Decimal("20"),
            is_visible=True,
            is_recommended=False,
            sort_order=2,
        ),
        SimpleNamespace(),
        db,
    )
    updated = points_ai.admin_update_points_product(
        created["id"],
        points_ai.PointsProductUpdateIn(is_recommended=True, points=Decimal("240")),
        SimpleNamespace(),
        db,
    )
    deleted = points_ai.admin_delete_points_product(created["id"], SimpleNamespace(), db)

    assert updated["points"] == 240
    assert updated["is_recommended"] is True
    assert deleted == {"ok": True, "archived": False}
    assert db.get(PointsProduct, created["id"]) is None


@pytest.mark.parametrize("matcher", [epay_amount_matches, mapay_amount_matches])
def test_payment_sync_requires_exact_reported_amount(matcher):
    order = SimpleNamespace(amount=Decimal("59.00"))

    assert matcher(order, "59.00") is True
    assert matcher(order, "58.99") is False
    assert matcher(order, "") is False


def test_alipay_checkout_allows_missing_seller_id(monkeypatch):
    captured = {}

    def fake_precreate(**kwargs):
        captured.update(kwargs)
        return {"result": {"code": "10000", "qr_code": "https://qr.example/order"}}

    monkeypatch.setattr("services.alipay_f2f.precreate", fake_precreate)
    gateway = AlipayGateway()
    order = SimpleNamespace(order_no="PTS-ALIPAY-1", amount=Decimal("50.00"))
    product = SimpleNamespace(name="50 元档", description="积分套餐")
    config = {
        "alipay_app_id": "app-id",
        "alipay_gateway": "https://openapi.alipay.com/gateway.do",
        "alipay_sign_type": "RSA2",
        "alipay_app_private_key": "private-key",
        "alipay_public_key": "public-key",
        "alipay_notify_url": "https://example.com/api/payments/alipay/notify",
        "order_expire_minutes": 30,
    }

    checkout = gateway.create_checkout(order, product, config)

    assert captured["seller_id"] is None
    assert checkout.qr_code_text == "https://qr.example/order"


def test_alipay_notify_allows_unconfigured_seller_id(monkeypatch):
    monkeypatch.setattr("services.alipay_f2f.rsa2_verify", lambda *args, **kwargs: True)
    gateway = AlipayGateway()
    result = gateway.verify_notify(
        {
            "sign": "valid-signature",
            "app_id": "app-expected",
            "seller_id": "seller-from-alipay",
            "trade_status": "TRADE_SUCCESS",
            "trade_no": "trade-1",
            "total_amount": "50.00",
        },
        {
            "alipay_app_id": "app-expected",
            "alipay_pid": "",
            "alipay_public_key": "public-key",
        },
    )

    assert result.verified is True
    assert result.trade_status == "paid"


def test_alipay_network_error_does_not_expose_signed_url(monkeypatch):
    request = httpx.Request(
        "POST",
        "https://openapi.alipay.com/gateway.do?app_id=app-id&sign=sensitive-signature",
    )

    def fake_precreate(**kwargs):
        raise httpx.ConnectError("连接失败", request=request)

    monkeypatch.setattr("services.alipay_f2f.precreate", fake_precreate)
    gateway = AlipayGateway()
    order = SimpleNamespace(order_no="PTS-ALIPAY-2", amount=Decimal("50.00"))
    product = SimpleNamespace(name="50 元档", description="积分套餐")
    config = {
        "alipay_app_id": "app-id",
        "alipay_gateway": "https://openapi.alipay.com/gateway.do",
        "alipay_sign_type": "RSA2",
        "alipay_app_private_key": "private-key",
        "alipay_public_key": "public-key",
        "alipay_notify_url": "https://example.com/api/payments/alipay/notify",
    }

    with pytest.raises(RuntimeError) as exc_info:
        gateway.create_checkout(order, product, config)

    assert str(exc_info.value) == "支付宝网关请求失败，请检查网关地址和网络连接"
    assert "sensitive-signature" not in str(exc_info.value)


def test_alipay_business_error_does_not_expose_response_signature(monkeypatch):
    def fake_precreate(**kwargs):
        raise alipay_f2f.AlipayApiError(
            '{"sign":"sensitive-response-signature","sub_msg":"参数无效"}'
        )

    monkeypatch.setattr("services.alipay_f2f.precreate", fake_precreate)
    gateway = AlipayGateway()
    order = SimpleNamespace(order_no="PTS-ALIPAY-SAFE", amount=Decimal("50.00"))
    product = SimpleNamespace(name="50 元档", description="积分套餐")
    config = {
        "alipay_app_id": "app-id",
        "alipay_gateway": "https://openapi.alipay.com/gateway.do",
        "alipay_sign_type": "RSA2",
        "alipay_app_private_key": "private-key",
        "alipay_public_key": "public-key",
        "alipay_notify_url": "https://example.com/api/payments/alipay/notify",
    }

    with pytest.raises(RuntimeError) as exc_info:
        gateway.create_checkout(order, product, config)

    message = str(exc_info.value)
    assert message == "支付宝预创建订单失败: 支付宝拒绝了预创建请求，请检查应用配置和当面付权限"
    assert "sensitive-response-signature" not in message


def test_alipay_api_error_only_exposes_safe_response_fields(monkeypatch):
    class FakeResponse:
        content = b""

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "error_response": {
                    "code": "40004",
                    "sub_code": "ACQ.INVALID_PARAMETER",
                    "sub_msg": "参数无效",
                },
                "sign": "sensitive-response-signature",
            }

    monkeypatch.setattr(alipay_f2f, "_rsa2_sign", lambda *args, **kwargs: "request-signature")
    monkeypatch.setattr(alipay_f2f.httpx, "post", lambda *args, **kwargs: FakeResponse())

    with pytest.raises(alipay_f2f.AlipayApiError) as exc_info:
        alipay_f2f.call_api(
            gateway="https://openapi.alipay.com/gateway.do",
            app_id="app-id",
            private_key="unused-in-test",
            method="alipay.trade.precreate",
            biz_content={"out_trade_no": "PTS-ALIPAY-3"},
        )

    message = str(exc_info.value)
    assert message == "ACQ.INVALID_PARAMETER: 参数无效"
    assert "sensitive-response-signature" not in message


def test_alipay_api_rejects_non_object_json_response(monkeypatch):
    class FakeResponse:
        content = b"null"

        def raise_for_status(self):
            return None

        def json(self):
            return None

    monkeypatch.setattr(alipay_f2f, "_rsa2_sign", lambda *args, **kwargs: "request-signature")
    monkeypatch.setattr(alipay_f2f.httpx, "post", lambda *args, **kwargs: FakeResponse())

    with pytest.raises(alipay_f2f.AlipayApiError, match="支付宝响应格式无效"):
        alipay_f2f.call_api(
            gateway="https://openapi.alipay.com/gateway.do",
            app_id="app-id",
            private_key="unused-in-test",
            method="alipay.trade.precreate",
            biz_content={"out_trade_no": "PTS-ALIPAY-4"},
        )


def test_checkout_payload_can_surface_gateway_error(monkeypatch):
    class FailingGateway:
        def create_checkout(self, order, item, payment):
            raise RuntimeError("支付宝配置不完整：alipay_app_private_key")

    order = SimpleNamespace(
        payment_method="alipay_qr",
        payment_provider="alipay",
        extra_json={},
        source="points_purchase",
        amount=Decimal("50.00"),
        currency="CNY",
        billing_cycle="one_time",
        expired_at=None,
    )
    product = SimpleNamespace(name="50 元档", description="积分套餐")
    monkeypatch.setattr(main, "get_gateway", lambda method: FailingGateway())

    with pytest.raises(RuntimeError, match="支付宝配置不完整"):
        main._order_checkout_payload(
            order,
            product,
            None,
            payment_override={"order_expire_minutes": 30},
            raise_gateway_errors=True,
        )


@pytest.mark.parametrize(
    ("gateway", "signer", "prefix"),
    [(EpayGateway(), _epay_sign, "epay"), (MaPayGateway(), _mapay_sign, "mapay")],
)
def test_payment_notify_rejects_wrong_merchant_pid(gateway, signer, prefix):
    key = "merchant-signing-key"
    payload = {
        "pid": "attacker-pid",
        "trade_no": "TRADE-1",
        "trade_status": "TRADE_SUCCESS",
        "money": "50.00",
    }
    payload["sign"] = signer(payload, key)

    result = gateway.verify_notify(
        payload,
        {f"{prefix}_key": key, f"{prefix}_pid": "expected-pid"},
    )

    assert result.verified is False


def test_revenue_uses_paid_month_for_cross_month_order(monkeypatch):
    db = _session()
    admin = _user(db, email="revenue-admin@example.com", role="admin")
    user = _user(db, email="revenue-user@example.com")
    now = main._utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    order = BillingOrder(
        order_no="PTS-CROSS-MONTH",
        user_id=user.id,
        plan_id=None,
        amount=Decimal("99.00"),
        currency="CNY",
        status="paid",
        source="points_purchase",
        billing_cycle="one_time",
        created_at=month_start - datetime.timedelta(days=1),
        paid_at=now,
    )
    db.add(order)
    db.commit()
    monkeypatch.setattr(main, "_require_admin", lambda request, session: admin)

    summary = main.admin_revenue_summary(SimpleNamespace(), db)
    monthly = main.admin_revenue_monthly(months=2, request=SimpleNamespace(), db=db)

    assert summary["monthly_orders"] == 0
    assert summary["monthly_paid_orders"] == 1
    assert summary["monthly_revenue"] == 99
    assert monthly[-1]["paid"] == 1
    assert monthly[-1]["revenue"] == 99


def test_epay_notify_credits_points_once(monkeypatch):
    db = _session()
    user = _user(db, email="epay-user@example.com")
    product = _product(db)
    order = BillingOrder(
        order_no="PTS-EPAY-NOTIFY",
        user_id=user.id,
        plan_id=None,
        points_product_id=product.id,
        amount=Decimal("50.00"),
        currency="CNY",
        status="pending",
        source="points_purchase",
        billing_cycle="one_time",
        payment_provider="epay",
        payment_method="epay_alipay",
        extra_json={"product_id": product.id, "product_name": product.name, "points": "550", "bonus_points": "50"},
    )
    db.add(order)
    db.commit()
    init_gateways()
    key = "epay-test-key"
    payload = {
        "pid": "epay-test-pid",
        "out_trade_no": order.order_no,
        "trade_no": "EPAY-TRADE-1",
        "trade_status": "TRADE_SUCCESS",
        "money": "50.00",
    }
    payload["sign"] = _epay_sign(payload, key)
    payload["sign_type"] = "MD5"

    class _Request:
        async def body(self):
            return urlencode(payload).encode("utf-8")

    monkeypatch.setattr(main, "_ensure_platform_seed", lambda session: None)
    monkeypatch.setattr(
        main,
        "_payment_settings_snapshot",
        lambda session: {"epay_key": key, "epay_pid": "epay-test-pid"},
    )

    first = asyncio.run(main.epay_notify(_Request(), db))
    second = asyncio.run(main.epay_notify(_Request(), db))

    account = db.query(PointsAccount).filter(PointsAccount.user_id == user.id).one()
    assert first.body == b"success"
    assert second.body == b"success"
    assert account.available_points == Decimal("600.0000")
    assert db.query(PointsLedgerEntry).filter(PointsLedgerEntry.order_id == order.id).count() == 1
    assert db.query(AuditLog).filter(AuditLog.action == "epay_notify_paid").count() == 1
