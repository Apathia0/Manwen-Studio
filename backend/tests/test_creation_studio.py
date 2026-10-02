from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import ANY

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from models import CreationStudioJob, User
from services import video_api
from routers.creation_studio import (
    _create_media_access_token,
    _enqueue_job,
    _reserve_job_billing,
    _serialize_job,
    _verify_media_access_token,
)
from services.ai.context import AIExecutionContext
from services.creation_studio import (
    MANGA_OUTPUTS_DIR,
    _create_output_asset,
    _public_media_url,
    _run_video_job,
    fail_interrupted_creation_studio_jobs,
)


def test_creation_studio_tables_can_be_created():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    assert "creation_studio_jobs" in Base.metadata.tables
    assert "creation_studio_assets" in Base.metadata.tables
    assert "creation_studio_job_inputs" in Base.metadata.tables


def test_public_image_url_is_scoped_to_existing_media_mount():
    path = MANGA_OUTPUTS_DIR / "creative_studio" / "user_7" / "job_3.png"

    assert _public_media_url(str(path), "image") == "/static/manga/creative_studio/user_7/job_3.png"


def test_interrupted_job_is_failed_on_service_restart():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    user = User(email="studio@example.com", password_hash="test", name="创作台测试用户")
    db.add(user)
    db.flush()
    job = CreationStudioJob(
        owner_user_id=user.id,
        media_kind="image",
        prompt="测试提示词",
        status="running",
        stage="generating",
    )
    db.add(job)
    db.commit()

    assert fail_interrupted_creation_studio_jobs(db) == 1
    db.refresh(job)
    assert job.status == "failed"
    assert job.stage == "failed"
    assert job.completed_at is not None
    db.close()


def test_output_asset_uses_authenticated_content_endpoint():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    user = User(email="asset@example.com", password_hash="test", name="素材测试用户")
    db.add(user)
    db.flush()
    job = CreationStudioJob(
        owner_user_id=user.id,
        media_kind="image",
        prompt="测试图片",
        status="running",
        stage="materializing",
    )
    db.add(job)
    db.flush()

    asset = _create_output_asset(
        db,
        job=job,
        media_kind="image",
        storage_path=str(MANGA_OUTPUTS_DIR / "creative_studio" / "test.png"),
        public_url="/static/manga/creative_studio/test.png",
    )

    assert asset.public_url == f"/api/creation-studio/assets/{asset.id}/content"
    assert job.output_asset_id == asset.id
    db.close()


def test_media_access_token_is_scoped_to_asset_and_user():
    token = _create_media_access_token(asset_id=12, user_id=7)

    assert _verify_media_access_token(token, asset_id=12) == 7
    assert _verify_media_access_token(token, asset_id=13) is None


@pytest.mark.asyncio
async def test_remote_asset_content_preserves_raw_encoding_and_range(monkeypatch):
    from routers import creation_studio as studio_router

    captured: dict[str, object] = {}

    class FakeUpstream:
        status_code = 206
        headers = {
            "content-type": "image/png",
            "content-length": "6",
            "content-range": "bytes 0-5/12",
            "accept-ranges": "bytes",
            "content-encoding": "gzip",
            "etag": '"asset-etag"',
        }

        async def aiter_raw(self):
            yield b"zipdat"

        async def aiter_bytes(self):
            pytest.fail("远程素材代理不得使用自动解压后的字节流")
            yield b""

        async def aclose(self):
            captured["upstream_closed"] = True

    class FakeClient:
        def __init__(self, *args, **kwargs):
            captured["client_kwargs"] = kwargs

        def build_request(self, method, url, headers):
            captured["request"] = {"method": method, "url": url, "headers": headers}
            return object()

        async def send(self, request, stream):
            captured["stream"] = stream
            return FakeUpstream()

        async def aclose(self):
            captured["client_closed"] = True

    asset = SimpleNamespace(
        id=7,
        media_type="image",
        mime_type="image/png",
        storage_path="https://media.example.com/generated.png",
    )
    request = SimpleNamespace(headers={"range": "bytes=0-5"})
    monkeypatch.setattr(studio_router, "_require_user", lambda *_args: SimpleNamespace(id=3))
    monkeypatch.setattr(studio_router, "_owned_asset", lambda *_args: asset)
    monkeypatch.setattr(studio_router, "validate_remote_media_url", lambda value: value)
    monkeypatch.setattr(studio_router.httpx, "AsyncClient", FakeClient)

    response = await studio_router.get_asset_content(7, request, db=SimpleNamespace())
    body = b"".join([chunk async for chunk in response.body_iterator])

    assert body == b"zipdat"
    assert response.status_code == 206
    assert response.headers["content-length"] == "6"
    assert response.headers["content-encoding"] == "gzip"
    assert response.headers["content-range"] == "bytes 0-5/12"
    assert response.headers["x-accel-buffering"] == "no"
    assert captured["request"] == {
        "method": "GET",
        "url": "https://media.example.com/generated.png",
        "headers": {"Accept-Encoding": "identity", "Range": "bytes=0-5"},
    }
    assert captured["stream"] is True
    assert captured["upstream_closed"] is True
    assert captured["client_closed"] is True


@pytest.mark.asyncio
async def test_analyze_assets_settles_provider_tokens(monkeypatch, tmp_path):
    from routers import creation_studio as studio_router

    image_path = tmp_path / "reference.jpg"
    image_path.write_bytes(b"image")
    asset = SimpleNamespace(id=3, mime_type="image/jpeg", storage_path=str(image_path))
    runtime = {
        "mode": "user_key",
        "base_url": "https://vision.example.com/v1",
        "model_key": "vision-model",
        "model_id": 12,
        "api_key": "user-secret",
    }
    ctx = SimpleNamespace(request_id="analyze-1")
    begin_calls = []
    completed = []

    class FakeImage:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def convert(self, _mode):
            return self

        def thumbnail(self, _size):
            return None

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [{"message": {"content": "分析结果"}}],
                "usage": {"prompt_tokens": 321, "completion_tokens": 45},
            }

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, *_args, **_kwargs):
            return FakeResponse()

    main_mod = SimpleNamespace(
        _resolve_dual_track_runtime=lambda *_args, **_kwargs: runtime,
    )
    monkeypatch.setattr(studio_router, "_require_user", lambda *_args: SimpleNamespace(id=7))
    monkeypatch.setattr(studio_router, "_owned_asset", lambda *_args: asset)
    monkeypatch.setattr(studio_router, "_main", lambda: main_mod)
    monkeypatch.setattr(studio_router.Path, "is_file", lambda _path: True)
    monkeypatch.setattr(studio_router.Path, "is_relative_to", lambda _path, _root: True)
    monkeypatch.setattr(studio_router.Image, "open", lambda _path: FakeImage())
    monkeypatch.setattr(studio_router, "_encode_analysis_image", lambda _image: b"jpeg")
    monkeypatch.setattr(
        studio_router,
        "begin_ai_call",
        lambda *args, **kwargs: begin_calls.append((args, kwargs)) or ctx,
    )
    monkeypatch.setattr(
        studio_router,
        "complete_ai_call",
        lambda *args, **kwargs: completed.append((args, kwargs)),
    )
    monkeypatch.setattr(studio_router.httpx, "AsyncClient", FakeClient)

    result = await studio_router.analyze_assets(
        studio_router.CreationStudioAnalyzeIn(asset_ids=[3]),
        SimpleNamespace(),
        SimpleNamespace(),
    )

    assert result["analysis"] == "分析结果"
    assert begin_calls[0][1]["credential_mode"] == "user_key"
    assert begin_calls[0][1]["model_id"] == 12
    assert completed == [
        (
            (ANY, ctx),
            {
                "success": True,
                "input_tokens": 321,
                "output_tokens": 45,
                "usage_source": "provider",
            },
        )
    ]


@pytest.mark.asyncio
async def test_analyze_assets_releases_reservation_on_empty_response(monkeypatch, tmp_path):
    from routers import creation_studio as studio_router

    image_path = tmp_path / "reference.jpg"
    image_path.write_bytes(b"image")
    asset = SimpleNamespace(id=4, mime_type="image/jpeg", storage_path=str(image_path))
    ctx = SimpleNamespace(request_id="analyze-2")
    completed = []

    class FakeImage:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def convert(self, _mode):
            return self

        def thumbnail(self, _size):
            return None

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": ""}}], "usage": {}}

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, *_args, **_kwargs):
            return FakeResponse()

    runtime = {
        "mode": "platform", "base_url": "https://vision.example.com/v1",
        "model_key": "vision-model", "model_id": 12, "api_key": "platform-secret",
    }
    monkeypatch.setattr(studio_router, "_require_user", lambda *_args: SimpleNamespace(id=7))
    monkeypatch.setattr(studio_router, "_owned_asset", lambda *_args: asset)
    monkeypatch.setattr(
        studio_router,
        "_main",
        lambda: SimpleNamespace(_resolve_dual_track_runtime=lambda *_args, **_kwargs: runtime),
    )
    monkeypatch.setattr(studio_router.Path, "is_file", lambda _path: True)
    monkeypatch.setattr(studio_router.Path, "is_relative_to", lambda _path, _root: True)
    monkeypatch.setattr(studio_router.Image, "open", lambda _path: FakeImage())
    monkeypatch.setattr(studio_router, "_encode_analysis_image", lambda _image: b"jpeg")
    monkeypatch.setattr(studio_router, "begin_ai_call", lambda *_args, **_kwargs: ctx)
    monkeypatch.setattr(
        studio_router,
        "complete_ai_call",
        lambda *args, **kwargs: completed.append((args, kwargs)),
    )
    monkeypatch.setattr(studio_router.httpx, "AsyncClient", FakeClient)

    with pytest.raises(HTTPException, match="未返回分析结果"):
        await studio_router.analyze_assets(
            studio_router.CreationStudioAnalyzeIn(asset_ids=[4]),
            SimpleNamespace(),
            SimpleNamespace(),
        )

    assert completed == [
        ((ANY, ctx), {"success": False, "error_code": "empty_response"})
    ]


def test_video_estimate_rejects_duration_not_supported_by_fixed_15_second_model(monkeypatch):
    from routers import points_ai

    model = SimpleNamespace(
        id=9,
        modality="video",
        capabilities_json={
            "video": {
                "limits": {
                    "resolutions": ["720P"],
                    "duration_seconds": {"allowed": [15]},
                }
            }
        },
    )
    monkeypatch.setattr(points_ai, "_require_user", lambda *_args: SimpleNamespace(id=7))
    monkeypatch.setattr(points_ai.ai_catalog, "get_visible_model", lambda *_args: model)
    monkeypatch.setattr(
        points_ai.ai_catalog,
        "get_active_price",
        lambda *_args: pytest.fail("时长校验失败时不应查询价格"),
    )

    with pytest.raises(HTTPException, match="不支持该时长"):
        points_ai.estimate(
            points_ai.EstimateIn(model_id=9, video_seconds=5),
            SimpleNamespace(),
            SimpleNamespace(),
        )


def test_video_estimate_rejects_fractional_duration(monkeypatch):
    from routers import points_ai

    model = SimpleNamespace(
        id=9,
        modality="video",
        capabilities_json={
            "video": {
                "limits": {
                    "resolutions": ["720P"],
                    "duration_seconds": {"min": 4, "max": 15},
                }
            }
        },
    )
    monkeypatch.setattr(points_ai, "_require_user", lambda *_args: SimpleNamespace(id=7))
    monkeypatch.setattr(points_ai.ai_catalog, "get_visible_model", lambda *_args: model)
    monkeypatch.setattr(
        points_ai.ai_catalog,
        "get_active_price",
        lambda *_args: pytest.fail("时长校验失败时不应查询价格"),
    )

    with pytest.raises(HTTPException, match="正整数秒"):
        points_ai.estimate(
            points_ai.EstimateIn(model_id=9, video_seconds=5.5),
            SimpleNamespace(),
            SimpleNamespace(),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("duration_seconds", "asset_ids", "error_text"),
    [
        (15, [], "不支持该时长"),
        (5, [1, 2], "参考图数量超过当前视频模型限制"),
    ],
)
async def test_default_openai_video_model_is_validated_before_begin_ai_call(
    monkeypatch, duration_seconds, asset_ids, error_text
):
    from routers import creation_studio as studio_router

    default_model = SimpleNamespace(
        id=9,
        channel_id=3,
        capabilities_json={
            "video": {
                "limits": {
                    "duration_seconds": {"allowed": [5]},
                    "resolutions": ["720P"],
                    "max_reference_images": 1,
                },
                "input_modes": ["text_to_video", "image_to_video"],
                "wire": {"size_by_resolution_aspect": {"720P|16:9": "1280x720"}},
            }
        },
    )
    assets = {asset_id: SimpleNamespace(id=asset_id, media_type="image") for asset_id in asset_ids}

    class Db:
        next_id = 1

        def get(self, model, pk):
            if model.__name__ == "CreationStudioAsset":
                return assets.get(pk)
            if model.__name__ == "AiChannel" and pk == 3:
                return SimpleNamespace(adapter_type="openai_video")
            return None

        def add(self, value):
            if getattr(value, "id", None) is None:
                value.id = self.next_id
                self.next_id += 1

        def flush(self):
            return None

        def commit(self):
            return None

    main_mod = SimpleNamespace(
        _request_credential_mode=lambda *_args: "platform",
        _resolve_user_upstream_override=lambda *_args, **_kwargs: None,
        _user_api_override_capabilities=lambda *_args: {"can_override_api_key": True},
    )
    monkeypatch.setattr(studio_router, "_require_user", lambda *_args: SimpleNamespace(id=7))
    monkeypatch.setattr(studio_router, "_main", lambda: main_mod)
    monkeypatch.setattr(studio_router, "_owned_asset", lambda _db, _user_id, asset_id: assets[asset_id])
    monkeypatch.setattr(studio_router, "resolve_model", lambda *_args, **_kwargs: default_model, raising=False)
    monkeypatch.setattr(
        studio_router,
        "begin_ai_call",
        lambda *_args, **_kwargs: pytest.fail("协议能力校验失败时不应调用 begin_ai_call"),
    )

    with pytest.raises((ValueError, HTTPException), match=error_text):
        await studio_router.create_jobs(
            studio_router.CreationStudioJobCreate(
                media_kind="video",
                prompt="测试",
                duration_seconds=duration_seconds,
                asset_ids=asset_ids,
            ),
            SimpleNamespace(),
            Db(),
        )


@pytest.mark.asyncio
async def test_custom_seedance_duration_is_validated_before_begin_ai_call(monkeypatch):
    from routers import creation_studio as studio_router

    platform_model = SimpleNamespace(
        id=2,
        channel_id=3,
        model_key="openai-video",
        modality="video",
        enabled=True,
        user_visible=True,
        capabilities_json={
            "video": {
                "payload_profile": "openai_native",
                "limits": {"duration_seconds": {"allowed": [5, 15]}, "resolutions": ["720P"]},
            }
        },
    )

    class Db:
        def get(self, model_type, pk):
            if model_type.__name__ == "AiChannel" and pk == 3:
                return SimpleNamespace(adapter_type="openai_video", enabled=True)
            if model_type.__name__ == "AiModel" and pk == 2:
                return platform_model
            return None

        def add(self, _value):
            pytest.fail("时长校验失败时不应写入任务")

    main_mod = SimpleNamespace(
        _request_credential_mode=lambda *_args: "user_key",
        _resolve_user_upstream_override=lambda *_args, **_kwargs: {
            "base_url": "https://relay.example.com/v1",
            "model_key": "seedance-1.5",
        },
        _user_api_override_capabilities=lambda *_args: {"can_override_api_key": True},
    )
    monkeypatch.setattr(studio_router, "_require_user", lambda *_args: SimpleNamespace(id=7))
    monkeypatch.setattr(studio_router, "_main", lambda: main_mod)
    monkeypatch.setattr(
        studio_router,
        "begin_ai_call",
        lambda *_args, **_kwargs: pytest.fail("时长校验失败时不应调用 begin_ai_call"),
    )

    with pytest.raises(ValueError, match="最大时长为 12 秒"):
        await studio_router.create_jobs(
            studio_router.CreationStudioJobCreate(
                media_kind="video",
                model_id=2,
                prompt="测试自定义 Seedance",
                duration_seconds=15,
            ),
            SimpleNamespace(),
            Db(),
        )


@pytest.mark.asyncio
async def test_custom_video_upstream_snapshots_and_executes_lingdong_without_openai_capabilities(
    monkeypatch,
):
    from routers import creation_studio as studio_router
    from services import creation_studio

    openai_capabilities = {
        "video": {
            "payload_profile": "openai_native",
            "limits": {"duration_seconds": {"allowed": [5]}, "resolutions": ["720P"]},
            "wire": {"size_by_resolution_aspect": {"720P|16:9": "1280x720"}},
        }
    }
    model = SimpleNamespace(
        id=2,
        channel_id=3,
        model_key="platform-openai-video",
        modality="video",
        enabled=True,
        user_visible=True,
        capabilities_json=openai_capabilities,
    )
    created_jobs: list = []
    captured: dict[str, dict] = {}

    class Db:
        next_id = 1

        def get(self, model_type, pk):
            if model_type.__name__ == "AiChannel" and pk == 3:
                return SimpleNamespace(adapter_type="openai_video")
            if model_type.__name__ == "AiModel" and pk == 2:
                return model
            return None

        def add(self, value):
            if getattr(value, "id", None) is None:
                value.id = self.next_id
                self.next_id += 1
            if isinstance(value, CreationStudioJob):
                created_jobs.append(value)

        def flush(self):
            return None

        def commit(self):
            return None

        def query(self, model_type):
            class Query:
                def filter(self, *args):
                    return self

                def order_by(self, *args):
                    return self

                def all(self):
                    return []

            return Query()

    ctx = AIExecutionContext(
        request_id="studio-video-1",
        user_id=7,
        task_type="creation_studio.video",
        credential_mode="user_key",
        channel_id=3,
        model_id=2,
        model_key="custom-relay-model",
        modality="video",
        base_url="https://relay.example.com/v1",
        api_key="custom-secret",
        adapter_type="openai_video",
        price_snapshot={},
        estimated_points=Decimal("5"),
        reserved_points=Decimal("6"),
        usage_event_id=11,
    )
    main_mod = SimpleNamespace(
        _request_credential_mode=lambda *_args: "user_key",
        _resolve_user_upstream_override=lambda *_args, **_kwargs: {
            "base_url": "https://relay.example.com/v1",
            "model_key": "custom-relay-model",
        },
        _user_api_override_capabilities=lambda *_args: {"can_override_api_key": True},
    )

    monkeypatch.setattr(studio_router, "_require_user", lambda *_args: SimpleNamespace(id=7))
    monkeypatch.setattr(studio_router, "_main", lambda: main_mod)
    monkeypatch.setattr(studio_router, "resolve_model", lambda *_args, **_kwargs: model)
    monkeypatch.setattr(studio_router, "begin_ai_call", lambda *_args, **_kwargs: ctx)

    async def fake_enqueue(job, db, billing_ctx):
        job.background_task_id = "task-1"

    monkeypatch.setattr(studio_router, "_enqueue_job", fake_enqueue)

    response = await studio_router.create_jobs(
        studio_router.CreationStudioJobCreate(media_kind="video", prompt="测试中转视频", duration_seconds=5),
        SimpleNamespace(),
        Db(),
    )
    job = created_jobs[0]
    runtime = job.parameters_json["_runtime"]
    assert runtime["adapter_type"] == "lingdong_video"
    assert runtime["video_capabilities"] is None
    assert "custom-secret" not in str(response)
    assert "_runtime" not in response["jobs"][0]["parameters"]

    class ExecutionDb:
        def get(self, model_type, pk):
            return job

        def commit(self):
            return None

        def close(self):
            return None

    async def fake_create(**kwargs):
        captured["create"] = kwargs
        return {"provider_job_id": "provider-1", "status": "queued"}

    async def fake_query(job_id, **kwargs):
        captured["query"] = {"job_id": job_id, **kwargs}
        return {"status": "completed"}

    async def fake_materialize(**kwargs):
        captured["materialize"] = kwargs
        return "https://cdn.example.com/result.mp4"

    monkeypatch.setattr(creation_studio, "SessionLocal", ExecutionDb)
    monkeypatch.setattr(creation_studio, "_load_job_inputs", lambda *_args: [])
    monkeypatch.setattr(
        creation_studio,
        "_create_output_asset",
        lambda *args, **kwargs: SimpleNamespace(id=21),
    )
    monkeypatch.setattr(creation_studio, "complete_ai_call", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        creation_studio.task_manager,
        "is_cancellation_requested",
        lambda _task_id: False,
    )
    monkeypatch.setattr(
        creation_studio.task_manager,
        "update_task_metadata",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        creation_studio.task_manager,
        "clear_cancellation_flag",
        lambda _task_id: None,
    )
    monkeypatch.setattr(creation_studio.video_adapter, "create_video_job", fake_create)
    monkeypatch.setattr(creation_studio.video_adapter, "query_video_job", fake_query)
    monkeypatch.setattr(creation_studio.video_adapter, "materialize_video_job", fake_materialize)

    await _run_video_job(job.id, "task-1", ctx)
    assert captured["create"]["adapter_type"] == "lingdong_video"
    assert captured["create"]["video_capabilities"] is None
    assert captured["query"]["adapter_type"] == "lingdong_video"
    assert captured["materialize"]["adapter_type"] == "lingdong_video"


@pytest.mark.asyncio
async def test_enqueue_job_reuses_reserved_billing_context(monkeypatch):
    captured: dict = {}

    async def fake_submit_task(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return args[0]

    monkeypatch.setattr("routers.creation_studio.task_manager.submit_task", fake_submit_task)
    job = SimpleNamespace(
        id=9,
        owner_user_id=7,
        media_kind="image",
        background_task_id=None,
        status="created",
        stage="created",
        progress=0,
    )
    db = SimpleNamespace(commit=lambda: None)
    billing_ctx = AIExecutionContext(
        request_id="studio-image-9",
        user_id=7,
        task_type="creation_studio.image",
        credential_mode="platform",
        channel_id=1,
        model_id=2,
        model_key="image-model",
        modality="image",
        base_url="https://example.com",
        api_key="secret",
        adapter_type="openai",
        price_snapshot={"billing_type": "per_image", "price_config": {"points_per_image": 3}},
        estimated_points=Decimal("3"),
        reserved_points=Decimal("3.6"),
        usage_event_id=11,
    )

    await _enqueue_job(job, db, billing_ctx)

    assert captured["kwargs"]["billing_ctx"] is billing_ctx
    assert captured["kwargs"]["quota_usage_event_id"] == 11
    assert captured["kwargs"]["quota_user_id"] == 7
    assert captured["kwargs"]["quota_feature_key"] == "creation_studio.image"


@pytest.mark.asyncio
async def test_video_job_uses_context_adapter_for_create_query_and_materialize(monkeypatch):
    from services import creation_studio
    from services.ai.crypto_secrets import encrypt_secret

    captured: dict[str, dict] = {}
    job = SimpleNamespace(
        id=9,
        owner_user_id=7,
        prompt="生成视频",
        negative_prompt=None,
        parameters_json={
            "duration_seconds": 10,
            "resolution": "720P",
            "_runtime": {
                "adapter_type": "openai_video",
                "base_url": "https://example.com/v1",
                "model": "video-model",
                "model_id": 2,
                "video_capabilities": {"limits": {}},
                "secret_ciphertext": encrypt_secret("secret"),
            },
        },
        model_id=None,
        model_key=None,
        provider_job_id=None,
        progress=0,
    )
    model = SimpleNamespace(capabilities_json={"video": {"limits": {}}})

    class FakeDb:
        def get(self, model_type, key):
            return model if model_type.__name__ == "AiModel" else job

        def commit(self):
            pass

        def close(self):
            pass

    async def fake_create(**kwargs):
        captured["create"] = kwargs
        return {"provider_job_id": "provider-1", "status": "queued"}

    async def fake_query(job_id, **kwargs):
        captured["query"] = {"job_id": job_id, **kwargs}
        return {"status": "completed"}

    async def fake_materialize(**kwargs):
        captured["materialize"] = kwargs
        return "https://example.com/result.mp4"

    monkeypatch.setattr(creation_studio, "SessionLocal", FakeDb)
    monkeypatch.setattr(creation_studio, "_load_job_inputs", lambda db, current_job: [])
    monkeypatch.setattr(creation_studio, "_create_output_asset", lambda *args, **kwargs: SimpleNamespace(id=21))
    monkeypatch.setattr(creation_studio, "complete_ai_call", lambda *args, **kwargs: None)
    monkeypatch.setattr(creation_studio.task_manager, "is_cancellation_requested", lambda task_id: False)
    monkeypatch.setattr(creation_studio.task_manager, "update_task_metadata", lambda *args, **kwargs: None)
    monkeypatch.setattr(creation_studio.task_manager, "clear_cancellation_flag", lambda task_id: None)
    monkeypatch.setattr(creation_studio.video_adapter, "create_video_job", fake_create)
    monkeypatch.setattr(creation_studio.video_adapter, "query_video_job", fake_query)
    monkeypatch.setattr(creation_studio.video_adapter, "materialize_video_job", fake_materialize)

    ctx = AIExecutionContext(
        request_id="studio-video-9",
        user_id=7,
        task_type="creation_studio.video",
        credential_mode="platform",
        channel_id=1,
        model_id=2,
        model_key="video-model",
        modality="video",
        base_url="https://example.com/v1",
        api_key="secret",
        adapter_type="openai_video",
        price_snapshot={"billing_type": "per_second", "price_config": {"points_per_second": 1}},
        estimated_points=Decimal("10"),
        reserved_points=Decimal("12"),
        usage_event_id=11,
    )

    result = await _run_video_job(9, "task-9", ctx)

    assert result["asset_id"] == 21
    assert captured["create"]["adapter_type"] == "openai_video"
    assert captured["query"]["adapter_type"] == "openai_video"
    assert captured["materialize"]["adapter_type"] == "openai_video"
    assert captured["materialize"]["query_result"] == {"status": "completed"}


@pytest.mark.asyncio
async def test_video_reference_payload_uses_input_reference(monkeypatch):
    captured: dict = {}

    class FakeResponse:
        is_success = True
        status_code = 200
        text = ""

        @staticmethod
        def json():
            return {"task_id": "task-1", "status": "queued"}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        async def post(self, url, json, headers):
            captured.update(json)
            return FakeResponse()

    monkeypatch.setattr(video_api.httpx, "AsyncClient", FakeClient)

    await video_api.create_video_job(
        model="sd-2-vip-720",
        prompt="镜头缓慢向前推进",
        images=["https://example.com/a.png", "https://example.com/b.png"],
        api_key="test-key",
        base_url="https://example.com",
    )

    assert captured["input_reference"] == "https://example.com/a.png|https://example.com/b.png"
    assert "images" not in captured
    assert captured["size"] == "large"
    assert captured["orientation"] == "landscape"


@pytest.mark.asyncio
async def test_custom_video_payload_uses_configured_newapi_fields(monkeypatch):
    captured: dict = {}

    class FakeResponse:
        is_success = True
        status_code = 200
        text = ""

        @staticmethod
        def json():
            return {"task_id": "task-grok", "status": "queued"}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        async def post(self, url, json, headers):
            captured.update(json)
            return FakeResponse()

    monkeypatch.setattr(video_api.httpx, "AsyncClient", FakeClient)

    await video_api.create_video_job(
        model="grok-imagine-video-1.5",
        prompt="人物自然回头，镜头缓慢推进",
        aspect_ratio="16:9",
        size="720P",
        duration_seconds=15,
        images=["https://cdn.example.com/reference.png"],
        api_key="test-key",
        base_url="https://example.com",
        video_capabilities={
            "payload_profile": "custom",
            "limits": {
                "aspect_ratios": ["16:9"],
                "resolutions": ["720P"],
                "duration_seconds": {"allowed": [15]},
            },
            "wire": {
                "duration_field": "duration",
                "resolution_field": "resolution",
                "resolution_case": "lower",
                "ratio_field": "aspect_ratio",
                "reference_field": "reference_images",
            },
        },
    )

    assert captured == {
        "model": "grok-imagine-video-1.5",
        "prompt": "人物自然回头，镜头缓慢推进",
        "duration": 15,
        "aspect_ratio": "16:9",
        "resolution": "720p",
        "reference_images": ["https://cdn.example.com/reference.png"],
    }


@pytest.mark.asyncio
async def test_legacy_video_payload_uses_configured_resolution_and_ratio_fields(monkeypatch):
    captured: dict = {}

    class FakeResponse:
        is_success = True
        status_code = 200
        text = ""

        @staticmethod
        def json():
            return {"task_id": "task-resolution", "status": "queued"}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        async def post(self, url, json, headers):
            captured.update(json)
            return FakeResponse()

    monkeypatch.setattr(video_api.httpx, "AsyncClient", FakeClient)

    await video_api.create_video_job(
        model="gz-video-720",
        prompt="测试视频",
        aspect_ratio="16:9",
        size="720P",
        duration_seconds=15,
        api_key="test-key",
        base_url="https://example.com",
        video_capabilities={
            "payload_profile": "legacy_lingdong",
            "limits": {
                "aspect_ratios": ["16:9"],
                "resolutions": ["720P"],
                "duration_seconds": {"allowed": [15]},
            },
            "wire": {
                "duration_field": "duration",
                "resolution_field": "resolution",
                "ratio_field": "ratio",
            },
        },
    )

    assert captured["duration"] == 15
    assert captured["resolution"] == "720P"
    assert captured["ratio"] == "16:9"
    assert "size" not in captured
    assert "orientation" not in captured


@pytest.mark.asyncio
async def test_sora_video_payload_uses_configured_wire_size(monkeypatch):
    captured: dict = {}

    class FakeResponse:
        is_success = True
        status_code = 200
        text = ""

        @staticmethod
        def json():
            return {"task_id": "task-sora", "status": "queued"}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        async def post(self, url, json, headers):
            captured.update(json)
            return FakeResponse()

    monkeypatch.setattr(video_api.httpx, "AsyncClient", FakeClient)

    await video_api.create_video_job(
        model="sora-model",
        prompt="测试视频",
        aspect_ratio="16:9",
        size="720P",
        duration_seconds=8,
        api_key="test-key",
        base_url="https://example.com",
        video_capabilities={
            "payload_profile": "sora_v2",
            "limits": {"duration_seconds": {"allowed": [8]}, "aspect_ratios": ["16:9"]},
            "wire": {
                "duration_field": "seconds",
                "duration_as_string": True,
                "size_by_resolution_aspect": {"720P|16:9": "provider-size"},
            },
        },
    )

    assert captured["size"] == "provider-size"
    assert captured["seconds"] == "8"
    assert "duration" not in captured
    assert "orientation" not in captured


@pytest.mark.asyncio
async def test_sora_video_payload_requires_configured_wire_size(monkeypatch):
    with pytest.raises(ValueError, match="size_by_resolution_aspect"):
        await video_api.create_video_job(
            model="sora-model",
            prompt="测试视频",
            api_key="test-key",
            base_url="https://example.com",
            video_capabilities={"payload_profile": "sora_v2"},
        )


@pytest.mark.asyncio
async def test_video_download_sanitizes_provider_job_id(monkeypatch, tmp_path):
    class FakeResponse:
        is_success = True
        headers = {"content-type": "video/mp4"}

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        async def aiter_bytes(self):
            yield b"video"

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        def stream(self, method, url):
            return FakeResponse()

    monkeypatch.setattr(video_api.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(video_api, "_upload_video_url_to_oss", lambda source_url, remote_key: None)
    monkeypatch.setattr(video_api, "_upload_to_oss_if_enabled", lambda path: None)

    result = await video_api.download_video(
        "https://example.com/video.mp4",
        shot_id=9,
        job_id="../../escape",
        output_dir=tmp_path,
    )
    result_path = Path(result)

    assert result_path.parent == tmp_path / "shot_9"
    assert result_path.name == "escape.mp4"


@pytest.mark.asyncio
async def test_legacy_seedance_15_seconds_is_rejected_before_billing(monkeypatch):
    from routers import creation_studio as studio_router

    selected_model = SimpleNamespace(
        id=9,
        channel_id=3,
        model_key="seedance-1.5-pro",
        capabilities_json={
            "video": {
                "limits": {
                    "resolutions": ["720P"],
                    "duration_seconds": {"min": 4, "max": 15},
                }
            }
        },
    )

    class Db:
        def get(self, model_type, pk):
            if model_type.__name__ == "AiChannel":
                return SimpleNamespace(adapter_type="lingdong_video")
            return None

    main_mod = SimpleNamespace(
        _request_credential_mode=lambda *_args: "platform",
        _resolve_user_upstream_override=lambda *_args, **_kwargs: None,
        _user_api_override_capabilities=lambda *_args: {"can_override_api_key": True},
    )
    monkeypatch.setattr(studio_router, "_require_user", lambda *_args: SimpleNamespace(id=7))
    monkeypatch.setattr(studio_router, "_main", lambda: main_mod)
    monkeypatch.setattr(studio_router, "resolve_model", lambda *_args, **_kwargs: selected_model)
    monkeypatch.setattr(
        studio_router,
        "begin_ai_call",
        lambda *_args, **_kwargs: pytest.fail("不支持的 15 秒请求不应进入预扣"),
    )
    with pytest.raises((ValueError, HTTPException), match="最大时长为 12 秒"):
        await studio_router.create_jobs(
            studio_router.CreationStudioJobCreate(
                media_kind="video", prompt="测试", duration_seconds=15
            ),
            SimpleNamespace(),
            Db(),
        )


def test_creation_studio_video_runtime_snapshot_is_encrypted_deep_copied_and_hidden(monkeypatch):
    from routers import creation_studio as studio_router

    capabilities = {
        "video": {
            "payload_profile": "legacy_lingdong",
            "limits": {"duration_seconds": {"allowed": [15]}},
        }
    }
    model = SimpleNamespace(id=2, capabilities_json=capabilities)
    job = SimpleNamespace(
        id=9, owner_user_id=7, media_kind="video", model_id=2,
        model_key=None, parameters_json={"duration_seconds": 15},
    )
    ctx = AIExecutionContext(
        request_id="studio-video-9", user_id=7,
        task_type="creation_studio.video", credential_mode="platform",
        channel_id=1, model_id=2, model_key="seedance-2.0", modality="video",
        base_url="https://original.example.com/v1", api_key="snapshot-secret",
        adapter_type="lingdong_video", price_snapshot={},
        estimated_points=Decimal("15"), reserved_points=Decimal("18"), usage_event_id=11,
    )

    class Db:
        def get(self, model_type, pk):
            return model if model_type.__name__ == "AiModel" else None

        def commit(self):
            pass

    monkeypatch.setattr(studio_router, "begin_ai_call", lambda *args, **kwargs: ctx)
    assert _reserve_job_billing(job, Db()) is ctx
    snapshot = job.parameters_json["_runtime"]
    capabilities["video"]["payload_profile"] = "sora_v2"
    assert snapshot["adapter_type"] == "lingdong_video"
    assert snapshot["base_url"] == "https://original.example.com/v1"
    assert snapshot["model"] == "seedance-2.0"
    assert snapshot["model_id"] == 2
    assert snapshot["video_capabilities"]["payload_profile"] == "legacy_lingdong"
    assert snapshot["secret_ciphertext"] != "snapshot-secret"
    assert "snapshot-secret" not in str(job.parameters_json)

    serialized_job = SimpleNamespace(
        id=9, media_kind="video", generation_mode="text_to_video", prompt="测试",
        negative_prompt=None, model_id=2, model_key="seedance-2.0",
        parameters_json=job.parameters_json, status="queued", stage="queued", progress=0,
        background_task_id=None, provider_job_id=None, error_message=None,
        retry_of_job_id=None, output_asset_id=None, created_at=None, started_at=None,
        completed_at=None, updated_at=None,
    )

    class SerializeDb:
        def get(self, model_type, pk):
            return None

        def query(self, model_type):
            class Query:
                def filter(self, *args):
                    return self

                def order_by(self, *args):
                    return self

                def all(self):
                    return []

            return Query()

    serialized = _serialize_job(SerializeDb(), serialized_job)
    assert "_runtime" not in serialized["parameters"]
    assert "snapshot-secret" not in str(serialized)


def test_creation_studio_retry_reservation_preserves_original_runtime_snapshot(monkeypatch):
    from routers import creation_studio as studio_router

    original_runtime = {
        "adapter_type": "lingdong_video",
        "base_url": "https://original.example.com/v1",
        "model": "original-model",
        "model_id": 2,
        "video_capabilities": {"payload_profile": "legacy_lingdong"},
        "secret_ciphertext": "original-ciphertext",
    }
    job = SimpleNamespace(
        id=10, owner_user_id=7, media_kind="video", model_id=2,
        model_key="original-model",
        parameters_json={"duration_seconds": 10, "_runtime": original_runtime.copy()},
    )
    changed_ctx = AIExecutionContext(
        request_id="studio-video-10", user_id=7,
        task_type="creation_studio.video", credential_mode="platform",
        channel_id=9, model_id=2, model_key="changed-model", modality="video",
        base_url="https://changed.example.com/v1", api_key="changed-secret",
        adapter_type="openai_video", price_snapshot={}, estimated_points=Decimal("10"),
        reserved_points=Decimal("12"), usage_event_id=12,
    )

    class Db:
        def get(self, model_type, pk):
            return SimpleNamespace(capabilities_json={"video": {"payload_profile": "sora_v2"}})

        def commit(self):
            pass

    monkeypatch.setattr(studio_router, "begin_ai_call", lambda *args, **kwargs: changed_ctx)
    _reserve_job_billing(job, Db())
    assert job.parameters_json["_runtime"] == original_runtime
    assert job.model_id == 2
    assert job.model_key == "original-model"


@pytest.mark.asyncio
async def test_creation_studio_retry_returns_selection_required_for_stale_model(monkeypatch):
    from routers import creation_studio as studio_router

    user = SimpleNamespace(id=7)
    source = SimpleNamespace(
        id=10,
        owner_user_id=7,
        media_kind="video",
        model_id=2,
        status="failed",
    )
    expected_error = HTTPException(
        status_code=409,
        detail={
            "code": "AI_MODEL_SELECTION_REQUIRED",
            "message": "已选择的模型已下架，请重新选择",
            "modality": "video",
            "reason": "hidden",
        },
    )
    monkeypatch.setattr(studio_router, "_require_user", lambda request, db: user)
    monkeypatch.setattr(studio_router, "_owned_job", lambda db, user_id, job_id: source)

    def reject_stale_model(*args, **kwargs):
        assert kwargs["model_id"] == source.model_id
        assert kwargs["selection_policy"] == "interactive_strict"
        raise expected_error

    monkeypatch.setattr(studio_router, "resolve_model", reject_stale_model)

    with pytest.raises(HTTPException) as exc_info:
        await studio_router.retry_job(source.id, SimpleNamespace(), SimpleNamespace())

    assert exc_info.value is expected_error


@pytest.mark.asyncio
async def test_video_job_uses_persisted_runtime_snapshot_after_model_changes(monkeypatch):
    from services import creation_studio
    from services.ai.crypto_secrets import encrypt_secret

    captured: dict[str, dict] = {}
    original_capabilities = {"payload_profile": "legacy_lingdong", "limits": {}}
    job = SimpleNamespace(
        id=9, owner_user_id=7, prompt="生成视频", negative_prompt=None,
        parameters_json={
            "duration_seconds": 10, "resolution": "720P",
            "_runtime": {
                "adapter_type": "lingdong_video",
                "base_url": "https://original.example.com/v1",
                "model": "original-model", "model_id": 2,
                "video_capabilities": original_capabilities,
                "secret_ciphertext": encrypt_secret("original-secret"),
            },
        },
        model_id=2, model_key="original-model", provider_job_id=None, progress=0,
    )
    changed_model = SimpleNamespace(
        capabilities_json={"video": {"payload_profile": "sora_v2"}}
    )

    class FakeDb:
        def get(self, model_type, key):
            return changed_model if model_type.__name__ == "AiModel" else job

        def commit(self):
            pass

        def close(self):
            pass

    async def fake_create(**kwargs):
        captured["create"] = kwargs
        return {"provider_job_id": "provider-1", "status": "queued"}

    async def fake_query(job_id, **kwargs):
        captured["query"] = {"job_id": job_id, **kwargs}
        return {"status": "completed"}

    async def fake_materialize(**kwargs):
        captured["materialize"] = kwargs
        return "https://example.com/result.mp4"

    monkeypatch.setattr(creation_studio, "SessionLocal", FakeDb)
    monkeypatch.setattr(creation_studio, "_load_job_inputs", lambda *args: [])
    monkeypatch.setattr(creation_studio, "_create_output_asset", lambda *args, **kwargs: SimpleNamespace(id=21))
    monkeypatch.setattr(creation_studio, "complete_ai_call", lambda *args, **kwargs: None)
    monkeypatch.setattr(creation_studio.task_manager, "is_cancellation_requested", lambda task_id: False)
    monkeypatch.setattr(creation_studio.task_manager, "update_task_metadata", lambda *args, **kwargs: None)
    monkeypatch.setattr(creation_studio.task_manager, "clear_cancellation_flag", lambda task_id: None)
    monkeypatch.setattr(creation_studio.video_adapter, "create_video_job", fake_create)
    monkeypatch.setattr(creation_studio.video_adapter, "query_video_job", fake_query)
    monkeypatch.setattr(creation_studio.video_adapter, "materialize_video_job", fake_materialize)
    stale_ctx = AIExecutionContext(
        request_id="studio-video-9", user_id=7,
        task_type="creation_studio.video", credential_mode="platform",
        channel_id=99, model_id=2, model_key="changed-model", modality="video",
        base_url="https://changed.example.com/v1", api_key="changed-secret",
        adapter_type="openai_video", price_snapshot={}, estimated_points=Decimal("10"),
        reserved_points=Decimal("12"), usage_event_id=11,
    )
    await _run_video_job(9, "task-9", stale_ctx)
    assert captured["create"]["adapter_type"] == "lingdong_video"
    assert captured["create"]["base_url"] == "https://original.example.com/v1"
    assert captured["create"]["model"] == "original-model"
    assert captured["create"]["api_key"] == "original-secret"
    assert captured["create"]["video_capabilities"] == original_capabilities
    assert captured["query"]["adapter_type"] == "lingdong_video"
    assert captured["materialize"]["base_url"] == "https://original.example.com/v1"
    assert job.model_id == 2
    assert job.model_key == "original-model"
