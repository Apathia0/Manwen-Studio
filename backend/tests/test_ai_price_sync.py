import asyncio
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from models import AiChannel, AiModel, AiModelPrice, User
from routers import points_ai
from services.ai import upstream_pricing


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def _channel(db, *, modality="text", extra_config=None):
    channel = AiChannel(
        code=f"channel-{modality}",
        name=f"{modality} 渠道",
        adapter_type="openai_compatible",
        base_url="https://prices.example.com/v1",
        modality=modality,
        timeout_seconds=120,
        extra_config_json=extra_config or {},
    )
    db.add(channel)
    db.commit()
    return channel


def _model(db, channel, key, modality=None):
    model = AiModel(
        channel_id=channel.id,
        model_key=key,
        display_name=key,
        modality=modality or channel.modality,
        enabled=True,
        user_visible=True,
    )
    db.add(model)
    db.commit()
    return model


def _snapshot(rows, *, version="version-1", quota="500000", group_ratio="1.2"):
    return upstream_pricing.UpstreamPricingSnapshot(
        quota_display_type="CNY",
        quota_per_unit=Decimal(quota),
        group="default",
        group_ratio=Decimal(group_ratio),
        pricing_version=version,
        rows_by_model_key={row["model_name"]: row for row in rows},
    )


def test_text_price_conversion_ignores_cache_ratios_and_requires_completion_ratio():
    db = _session()
    channel = _channel(db)
    model = _model(db, channel, "deepseek-chat")
    snapshot = _snapshot([
        {
            "model_name": "deepseek-chat",
            "quota_type": 0,
            "model_ratio": 2,
            "completion_ratio": 3,
            "cache_ratio": 0.1,
            "create_cache_ratio": 2,
        }
    ])

    proposal = upstream_pricing.propose_model_price(model, snapshot, Decimal("10"))

    assert proposal["billing_type"] == "per_1m_tokens"
    assert proposal["price_config_json"] == {
        "input_points_per_1m": 48.0,
        "output_points_per_1m": 144.0,
    }
    assert proposal["cache_ignored"] is True
    snapshot.rows_by_model_key[model.model_key].pop("completion_ratio")
    assert upstream_pricing.propose_model_price(model, snapshot, Decimal("10"))["status"] == "skipped"


@pytest.mark.parametrize(
    ("modality", "expected_type", "expected_config"),
    [
        ("image", "per_image", {"points_per_image": 30.0}),
        ("video", "per_call", {"points_per_call": 30.0}),
    ],
)
def test_fixed_price_conversion_for_image_and_video(modality, expected_type, expected_config):
    db = _session()
    channel = _channel(db, modality=modality)
    model = _model(db, channel, f"{modality}-model")
    snapshot = _snapshot([
        {"model_name": model.model_key, "quota_type": 1, "model_price": 2.5}
    ])

    proposal = upstream_pricing.propose_model_price(model, snapshot, Decimal("10"))

    assert proposal["billing_type"] == expected_type
    assert proposal["price_config_json"] == expected_config


def test_only_exact_local_model_keys_are_proposed_and_bad_rows_are_skipped():
    db = _session()
    channel = _channel(db)
    exact = _model(db, channel, "exact")
    missing = _model(db, channel, "Exact")
    snapshot = _snapshot([
        {"model_name": "exact", "quota_type": 0, "model_ratio": "NaN", "completion_ratio": 1},
        {"model_name": "upstream-only", "quota_type": 0, "model_ratio": 1, "completion_ratio": 1},
    ])

    assert upstream_pricing.propose_model_price(exact, snapshot, Decimal("10"))["status"] == "skipped"
    assert "没有精确匹配" in upstream_pricing.propose_model_price(missing, snapshot, Decimal("10"))["reason"]


def test_fetch_uses_origin_custom_paths_group_and_optional_bearer(monkeypatch):
    db = _session()
    channel = _channel(
        db,
        extra_config={
            "pricing": {
                "protocol": "new_api_v1",
                "status_path": "/status",
                "pricing_path": "/pricing",
                "group": "vip",
            }
        },
    )
    calls = []

    class Client:
        def __init__(self, **kwargs):
            assert kwargs["follow_redirects"] is False

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, url, headers):
            calls.append((url, headers))
            if url.endswith("/status"):
                return httpx.Response(200, json={"success": True, "data": {
                    "quota_display_type": "CNY", "quota_per_unit": 500000,
                }})
            return httpx.Response(200, json={
                "success": True,
                "group_ratio": {"vip": 1.5},
                "data": [{"model_name": "exact", "quota_type": 0, "model_ratio": 1, "completion_ratio": 1}],
            })

    monkeypatch.setattr(upstream_pricing.httpx, "AsyncClient", Client)
    monkeypatch.setattr(upstream_pricing.ai_channels, "load_platform_key", lambda _channel: "secret")
    monkeypatch.setattr(
        upstream_pricing.ai_channels,
        "validate_base_url",
        lambda value, **_kwargs: value,
    )
    snapshot = asyncio.run(upstream_pricing.fetch_new_api_pricing(channel))

    assert [call[0] for call in calls] == [
        "https://prices.example.com/status",
        "https://prices.example.com/pricing",
    ]
    assert all(call[1]["Authorization"] == "Bearer secret" for call in calls)
    assert snapshot.group == "vip"
    assert snapshot.group_ratio == Decimal("1.5")
    assert len(snapshot.pricing_version) == 64


def test_fetch_rejects_unknown_currency_and_unsafe_paths(monkeypatch):
    db = _session()
    channel = _channel(db)

    class Client:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, url, headers):
            if url.endswith("/api/status"):
                return httpx.Response(200, json={"data": {
                    "quota_display_type": "USD", "quota_per_unit": 500000,
                }})
            return httpx.Response(200, json={"data": [], "group_ratio": {"default": 1}})

    monkeypatch.setattr(upstream_pricing.httpx, "AsyncClient", Client)
    monkeypatch.setattr(upstream_pricing.ai_channels, "load_platform_key", lambda _channel: None)
    monkeypatch.setattr(
        upstream_pricing.ai_channels,
        "validate_base_url",
        lambda value, **_kwargs: value,
    )
    with pytest.raises(HTTPException, match="币种不是 CNY"):
        asyncio.run(upstream_pricing.fetch_new_api_pricing(channel))

    channel.extra_config_json = {"pricing": {"status_path": "/api/status?token=secret"}}
    with pytest.raises(HTTPException, match="站内相对路径"):
        asyncio.run(upstream_pricing.fetch_new_api_pricing(channel))


@pytest.mark.parametrize("base_url", ["http://public.example.com/v1", "https://127.0.0.1/v1"])
def test_fetch_revalidates_https_public_base_url_before_loading_key(monkeypatch, base_url):
    db = _session()
    channel = _channel(db)
    channel.base_url = base_url
    key_loaded = False

    def load_key(_channel):
        nonlocal key_loaded
        key_loaded = True
        return "secret"

    monkeypatch.setattr(upstream_pricing.ai_channels, "load_platform_key", load_key)
    with pytest.raises(HTTPException):
        asyncio.run(upstream_pricing.fetch_new_api_pricing(channel))
    assert key_loaded is False


def test_preview_and_sync_append_versions_then_become_idempotent(monkeypatch):
    db = _session()
    channel = _channel(db)
    model = _model(db, channel, "deepseek-chat")
    admin = User(
        email="admin@example.com",
        password_hash="test",
        name="admin",
        role="admin",
        status="active",
        email_verified=True,
    )
    db.add(admin)
    db.commit()
    snapshot = _snapshot([
        {"model_name": model.model_key, "quota_type": 0, "model_ratio": 2, "completion_ratio": 3}
    ])
    monkeypatch.setattr(points_ai, "_require_admin", lambda *_args: admin)
    monkeypatch.setattr(points_ai, "_get_platform_setting", lambda *_args: 10)
    monkeypatch.setattr(upstream_pricing, "fetch_new_api_pricing", lambda _channel: _awaitable(snapshot))

    preview = asyncio.run(points_ai.admin_preview_channel_prices(channel.id, SimpleNamespace(), db))
    assert preview["summary"] == {"total": 1, "ready": 1, "unchanged": 0, "skipped": 0}
    assert set(preview["upstream"]) == {
        "currency", "quota_per_unit", "group", "group_ratio", "pricing_version",
    }
    assert preview["items"][0]["current_price"] is None
    assert preview["items"][0]["proposed_price"]["billing_type"] == "per_1m_tokens"

    body = points_ai.ChannelPriceSyncIn(
        model_ids=[model.id],
        expected_price_ids={model.id: None},
        expected_pricing_version=snapshot.pricing_version,
        expected_yuan_to_points=Decimal("10"),
    )
    first = asyncio.run(points_ai.admin_sync_channel_prices(channel.id, body, SimpleNamespace(), db))
    second = asyncio.run(points_ai.admin_sync_channel_prices(channel.id, body, SimpleNamespace(), db))

    assert first == {"updated": [model.id], "unchanged": [], "skipped": []}
    assert second == {"updated": [], "unchanged": [model.id], "skipped": []}
    assert db.query(AiModelPrice).filter(AiModelPrice.model_id == model.id).count() == 1


def _awaitable(value):
    async def result():
        return value

    return result()


def test_sync_rejects_version_or_points_ratio_drift(monkeypatch):
    db = _session()
    channel = _channel(db)
    model = _model(db, channel, "deepseek-chat")
    snapshot = _snapshot([
        {"model_name": model.model_key, "quota_type": 0, "model_ratio": 1, "completion_ratio": 1}
    ])
    monkeypatch.setattr(points_ai, "_require_admin", lambda *_args: SimpleNamespace(id=1))
    monkeypatch.setattr(points_ai, "_get_platform_setting", lambda *_args: 10)
    monkeypatch.setattr(upstream_pricing, "fetch_new_api_pricing", lambda _channel: _awaitable(snapshot))

    with pytest.raises(HTTPException) as version_error:
        asyncio.run(points_ai.admin_sync_channel_prices(
            channel.id,
            points_ai.ChannelPriceSyncIn(
                model_ids=[model.id],
                expected_price_ids={model.id: None},
                expected_pricing_version="stale",
                expected_yuan_to_points=10,
            ),
            SimpleNamespace(),
            db,
        ))
    assert version_error.value.status_code == 409

    with pytest.raises(HTTPException) as ratio_error:
        asyncio.run(points_ai.admin_sync_channel_prices(
            channel.id,
            points_ai.ChannelPriceSyncIn(
                model_ids=[model.id],
                expected_price_ids={model.id: None},
                expected_pricing_version=snapshot.pricing_version,
                expected_yuan_to_points=11,
            ),
            SimpleNamespace(),
            db,
        ))
    assert ratio_error.value.status_code == 409


def test_sync_rejects_local_price_drift_after_preview(monkeypatch):
    db = _session()
    channel = _channel(db)
    model = _model(db, channel, "deepseek-chat")
    snapshot = _snapshot([
        {"model_name": model.model_key, "quota_type": 0, "model_ratio": 1, "completion_ratio": 2}
    ])
    monkeypatch.setattr(points_ai, "_require_admin", lambda *_args: SimpleNamespace(id=1))
    monkeypatch.setattr(points_ai, "_get_platform_setting", lambda *_args: 10)
    monkeypatch.setattr(upstream_pricing, "fetch_new_api_pricing", lambda _channel: _awaitable(snapshot))
    db.add(AiModelPrice(
        model_id=model.id,
        billing_type="per_1m_tokens",
        price_config_json={"input_points_per_1m": 999, "output_points_per_1m": 999},
    ))
    db.commit()

    with pytest.raises(HTTPException) as error:
        asyncio.run(points_ai.admin_sync_channel_prices(
            channel.id,
            points_ai.ChannelPriceSyncIn(
                model_ids=[model.id],
                expected_price_ids={model.id: None},
                expected_pricing_version=snapshot.pricing_version,
                expected_yuan_to_points=10,
            ),
            SimpleNamespace(),
            db,
        ))

    assert error.value.status_code == 409
    assert "本地模型价格已变化" in str(error.value.detail)


@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf"), "1e10000"])
def test_yuan_to_points_requires_finite_positive_value(value):
    with pytest.raises(ValidationError):
        points_ai.PointsSettingsIn(yuan_to_points=value)


def test_video_manual_price_accepts_per_call_and_rejects_invalid_values():
    model = SimpleNamespace(modality="video")
    assert points_ai._normalize_model_price(
        model,
        points_ai.PriceIn(billing_type="per_call", price_config_json={"points_per_call": 12.5}),
    ) == ("per_call", {"points_per_call": 12.5})
    with pytest.raises(HTTPException):
        points_ai._normalize_model_price(
            model,
            points_ai.PriceIn(billing_type="per_call", price_config_json={"points_per_call": "NaN"}),
        )


def test_price_update_lock_helpers_use_stable_lock_order():
    calls = []

    class Query:
        def filter(self, *_args):
            calls.append("filter")
            return self

        def order_by(self, *_args):
            calls.append("order_by")
            return self

        def with_for_update(self):
            calls.append("with_for_update")
            return self

        def all(self):
            calls.append("all")
            return []

        def first(self):
            calls.append("first")
            return None

    db = SimpleNamespace(query=lambda _model: Query())
    assert points_ai._lock_models_for_price_sync(db, [2, 1]) == []
    assert calls == ["filter", "order_by", "with_for_update", "all"]

    calls.clear()
    assert points_ai._lock_model_for_price_update(db, 1) is None
    assert calls == ["filter", "with_for_update", "first"]
