import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import main as main_mod
from routers import points_ai
from routers import video as video_router
from services.ai import channels, credentials
from services.ai.crypto_secrets import encrypt_secret
from services.ai import resolver as ai_resolver
from services import deepseek, image2, video_api
from schemas import VideoShotUpdate


def test_validate_user_base_url_accepts_public_https(monkeypatch):
    monkeypatch.setattr(
        channels.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(channels.socket.AF_INET, channels.socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))],
    )

    assert channels.validate_user_base_url("https://api.example.com/v1/") == "https://api.example.com/v1"


def test_validate_remote_media_url_allows_signed_public_url(monkeypatch):
    monkeypatch.setattr(
        channels.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(channels.socket.AF_INET, channels.socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))],
    )

    url = "https://cdn.example.com/video.mp4?signature=test#preview"
    assert channels.validate_remote_media_url(url) == "https://cdn.example.com/video.mp4?signature=test"


def test_validate_remote_media_url_allows_only_explicit_http_download_host(monkeypatch):
    monkeypatch.setattr(
        channels.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(channels.socket.AF_INET, channels.socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80))],
    )

    url = "http://nana.code2alita.com/generated-images/example.jpg#fragment"
    assert channels.validate_remote_media_url(url, allow_http_hosts={"nana.code2alita.com"}) == "http://nana.code2alita.com/generated-images/example.jpg"
    with pytest.raises(HTTPException):
        channels.validate_remote_media_url("http://cdn.example.com/image.png", allow_http_hosts={"nana.code2alita.com"})


@pytest.mark.parametrize(
    "url",
    [
        "http://cdn.example.com/image.png",
        "https://127.0.0.1/image.png",
        "https://169.254.169.254/latest/meta-data",
        "https://[::1]/video.mp4",
    ],
)
def test_validate_remote_media_url_rejects_unsafe_targets(url):
    with pytest.raises(HTTPException):
        channels.validate_remote_media_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://api.example.com/v1",
        "https://127.0.0.1/v1",
        "https://10.0.0.8/v1",
        "https://[::1]/v1",
        "https://user:pass@example.com/v1",
        "https://api.example.com/v1?token=secret",
    ],
)
def test_validate_user_base_url_rejects_unsafe_addresses(url):
    with pytest.raises(HTTPException):
        channels.validate_user_base_url(url)


def test_user_upstream_override_is_ignored_without_permission(monkeypatch):
    monkeypatch.setattr(main_mod, "_user_api_override_capabilities", lambda user, db: {"can_override_api_key": True, "can_override_api_url": False})
    request = SimpleNamespace(headers={"x-deepseek-base-url": "https://api.example.com/v1"})

    result = main_mod._resolve_user_upstream_override(
        request,
        object(),
        user=SimpleNamespace(id=7),
        modality="text",
        mode="user_key",
    )
    assert result is None


@pytest.mark.parametrize(
    ("enable_user_override", "allow_all_users", "user_permission", "expected"),
    [
        (False, False, False, False),
        (False, True, True, False),
        (True, False, False, False),
        (True, False, True, True),
        (True, True, False, True),
    ],
)
def test_api_key_override_capability_combines_platform_and_user_permissions(
    monkeypatch,
    enable_user_override,
    allow_all_users,
    user_permission,
    expected,
):
    values = {
        "api.enable_user_override": enable_user_override,
        "api.allow_all_users_api_key_override": allow_all_users,
        "api.enable_user_url_override": True,
    }
    monkeypatch.setattr(
        main_mod,
        "_get_platform_setting",
        lambda key, db, default=None: values.get(key, default),
    )
    user = SimpleNamespace(
        allow_api_key_override=user_permission,
        allow_api_url_override=False,
    )

    capabilities = main_mod._user_api_override_capabilities(user, object())

    assert capabilities == {
        "can_override_api_key": expected,
        "can_override_api_url": False,
    }


def test_api_key_override_capability_never_allows_anonymous_user(monkeypatch):
    monkeypatch.setattr(
        main_mod,
        "_get_platform_setting",
        lambda key, db, default=None: {
            "api.enable_user_override": True,
            "api.allow_all_users_api_key_override": True,
            "api.enable_user_url_override": True,
        }.get(key, default),
    )

    assert main_mod._user_api_override_capabilities(None, object()) == {
        "can_override_api_key": False,
        "can_override_api_url": False,
    }


def test_video_api_key_override_capability_uses_main_policy(monkeypatch):
    expected = {"can_override_api_key": True, "can_override_api_url": False}
    monkeypatch.setattr(main_mod, "_user_api_override_capabilities", lambda user, db: expected)

    assert video_router._user_api_override_capabilities(object(), object()) is expected


def test_admin_points_settings_reads_and_updates_global_api_key_permission(monkeypatch):
    values = {
        "points.yuan_to_points": 10,
        "points.register_grant_enabled": False,
        "points.register_grant_amount": 0,
        "points.dual_track_enabled": True,
        "api.allow_all_users_api_key_override": False,
    }
    monkeypatch.setattr(points_ai, "_require_admin", lambda request, db: object())
    monkeypatch.setattr(
        points_ai,
        "_get_platform_setting",
        lambda key, db, default=None: values.get(key, default),
    )
    monkeypatch.setattr(
        points_ai,
        "_set_platform_setting",
        lambda key, value, db: values.__setitem__(key, value),
    )

    result = points_ai.admin_put_points_settings(
        points_ai.PointsSettingsIn(allow_all_users_api_key_override=True),
        object(),
        object(),
    )

    assert values["api.allow_all_users_api_key_override"] is True
    assert result["allow_all_users_api_key_override"] is True


def test_platform_settings_save_preserves_global_api_key_permission_when_field_is_omitted(monkeypatch):
    captured = {}
    db = SimpleNamespace(commit=lambda: None)
    monkeypatch.setattr(main_mod, "_require_admin", lambda request, db: object())
    monkeypatch.setattr(main_mod, "_get_platform_setting", lambda key, db, default=None: True if key == "api.allow_all_users_api_key_override" else default)
    monkeypatch.setattr(main_mod, "_set_platform_setting", lambda key, value, db, **kwargs: captured.setdefault(key, value))
    monkeypatch.setattr(main_mod, "_admin_platform_settings_snapshot", lambda db: {"api": {"allow_all_users_api_key_override": True}})

    main_mod.admin_save_platform_settings({"api": {}}, object(), db)

    assert captured["api.allow_all_users_api_key_override"] is True


def test_draft_credential_test_does_not_update_saved_status(monkeypatch):
    user = SimpleNamespace(id=7)
    saved_row = SimpleNamespace(status="invalid", last_validated_at=None)
    calls = []

    class Query:
        def filter(self, *_args, **_kwargs):
            return self

        def order_by(self, *_args, **_kwargs):
            return self

        def first(self):
            return SimpleNamespace(base_url="https://api.example.com/v1")

    class Db:
        def query(self, _model):
            return Query()

        def commit(self):
            calls.append("commit")

    class Response:
        status_code = 200

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, _url, *, headers):
            calls.append(headers["Authorization"])
            return Response()

    db = Db()
    monkeypatch.setattr(points_ai, "_require_user", lambda request, current_db: user)
    monkeypatch.setattr(
        points_ai,
        "_require_user_credential_permission",
        lambda current_user, current_db: {"can_override_api_key": True, "can_override_api_url": True},
    )
    monkeypatch.setattr(points_ai.ai_credentials, "load_user_api_key_plain", lambda *_args: pytest.fail("不应读取已保存 Key"))
    monkeypatch.setattr(points_ai.ai_credentials, "mark_credential_validated", lambda *_args: pytest.fail("草稿测试不应更新状态"))
    monkeypatch.setattr(points_ai.ai_bootstrap, "ensure_default_channels_and_models", lambda *_args: None)
    upstream_calls = []

    def resolve_upstream(*_args, **kwargs):
        upstream_calls.append(kwargs)
        return {"base_url": "https://api.example.com/v1", "model_key": "text-custom", "api_key": kwargs["api_key_override"]}

    monkeypatch.setattr(points_ai, "_main", lambda: SimpleNamespace(_resolve_user_upstream_override=resolve_upstream))
    monkeypatch.setattr(points_ai.httpx, "AsyncClient", lambda **_kwargs: Client())

    result = asyncio.run(
        points_ai.test_credential(
            SimpleNamespace(),
            points_ai.CredentialTestIn(api_key="draft-key"),
            db,
        )
    )

    assert result == {"ok": True, "status_code": 200}
    assert calls == ["Bearer draft-key", "commit"]
    assert upstream_calls[0]["api_key_override"] == "draft-key"
    assert saved_row.status == "invalid"
    assert saved_row.last_validated_at is None


def test_draft_credential_test_rejects_empty_key(monkeypatch):
    monkeypatch.setattr(points_ai, "_require_user", lambda request, db: SimpleNamespace(id=7))
    monkeypatch.setattr(
        points_ai,
        "_require_user_credential_permission",
        lambda user, db: {"can_override_api_key": True, "can_override_api_url": True},
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(points_ai.test_credential(SimpleNamespace(), points_ai.CredentialTestIn(api_key="  "), SimpleNamespace()))
    assert exc_info.value.status_code == 400


def test_saved_credential_test_updates_validation_status(monkeypatch):
    user = SimpleNamespace(id=7)
    calls = []

    class Query:
        def filter(self, *_args, **_kwargs):
            return self

        def order_by(self, *_args, **_kwargs):
            return self

        def first(self):
            return SimpleNamespace(base_url="https://api.example.com/v1")

    class Db:
        def query(self, _model):
            return Query()

        def commit(self):
            calls.append("commit")

    class Response:
        status_code = 200

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, _url, *, headers):
            calls.append(headers["Authorization"])
            return Response()

    db = Db()
    monkeypatch.setattr(points_ai, "_require_user", lambda request, current_db: user)
    monkeypatch.setattr(
        points_ai,
        "_require_user_credential_permission",
        lambda current_user, current_db: {"can_override_api_key": True, "can_override_api_url": True},
    )
    monkeypatch.setattr(points_ai.ai_credentials, "load_user_api_key_plain", lambda *_args: "saved-key")
    monkeypatch.setattr(points_ai.ai_credentials, "mark_credential_validated", lambda *_args: calls.append("marked"))
    monkeypatch.setattr(points_ai.ai_bootstrap, "ensure_default_channels_and_models", lambda *_args: None)
    monkeypatch.setattr(points_ai, "_main", lambda: SimpleNamespace(_resolve_user_upstream_override=lambda *_args, **_kwargs: None))
    monkeypatch.setattr(points_ai.httpx, "AsyncClient", lambda **_kwargs: Client())

    result = asyncio.run(points_ai.test_credential(SimpleNamespace(), None, db))

    assert result == {"ok": True, "status_code": 200}
    assert calls == ["Bearer saved-key", "marked", "commit"]


def test_user_upstream_override_rejects_platform_mode(monkeypatch):
    monkeypatch.setattr(main_mod, "_user_api_override_capabilities", lambda user, db: {"can_override_api_key": True, "can_override_api_url": True})
    request = SimpleNamespace(headers={"x-video-base-url": "https://video.example.com/v1"})

    with pytest.raises(HTTPException) as exc:
        main_mod._resolve_user_upstream_override(
            request,
            object(),
            user=SimpleNamespace(id=7),
            modality="video",
            mode="platform",
        )
    assert exc.value.status_code == 400


def test_spoofed_image_key_header_does_not_bypass_platform_billing(monkeypatch):
    class PreferenceQuery:
        def filter(self, *args, **kwargs):
            return self

        def first(self):
            return SimpleNamespace(credential_mode="platform")

    db = SimpleNamespace(query=lambda model: PreferenceQuery())
    request = SimpleNamespace(
        headers={"x-image-api-key": "invalid-placeholder"},
        state=SimpleNamespace(current_user=SimpleNamespace(id=7), db=db),
    )
    monkeypatch.setattr(
        main_mod,
        "_user_api_override_capabilities",
        lambda user, session: {"can_override_api_key": True, "can_override_api_url": True},
    )

    assert main_mod._custom_image_provider_active(request) is False


def test_user_upstream_override_uses_encrypted_user_key(monkeypatch):
    monkeypatch.setattr(main_mod, "_user_api_override_capabilities", lambda user, db: {"can_override_api_key": True, "can_override_api_url": True})
    monkeypatch.setattr(channels, "validate_user_base_url", lambda value: value.rstrip("/"))
    monkeypatch.setattr(credentials, "load_user_api_key_plain", lambda db, user_id: "user-secret")
    request = SimpleNamespace(
        headers={
            "x-image-base-url": "https://image.example.com/v1/",
            "x-image-model": "image-custom",
        }
    )

    result = main_mod._resolve_user_upstream_override(
        request,
        object(),
        user=SimpleNamespace(id=7),
        modality="image",
        mode="user_key",
    )

    assert result == {
        "base_url": "https://image.example.com/v1",
        "model_key": "image-custom",
        "api_key": "user-secret",
    }


def test_user_upstream_override_uses_draft_key_with_custom_upstream(monkeypatch):
    monkeypatch.setattr(
        main_mod,
        "_user_api_override_capabilities",
        lambda user, db: {"can_override_api_key": True, "can_override_api_url": True},
    )
    monkeypatch.setattr(channels, "validate_user_base_url", lambda value: value.rstrip("/"))
    monkeypatch.setattr(credentials, "load_user_api_key_plain", lambda *_args: pytest.fail("不应读取已保存 Key"))
    request = SimpleNamespace(
        headers={
            "x-deepseek-base-url": "https://text.example.com/v1",
            "x-deepseek-model": "text-custom",
        }
    )

    result = main_mod._resolve_user_upstream_override(
        request,
        object(),
        user=SimpleNamespace(id=7),
        modality="text",
        mode="user_key",
        api_key_override="draft-secret",
    )

    assert result == {
        "base_url": "https://text.example.com/v1",
        "model_key": "text-custom",
        "api_key": "draft-secret",
    }


def test_model_override_rejects_wrong_modality(monkeypatch):
    monkeypatch.setattr(ai_resolver, "get_visible_model", lambda db, model_id: SimpleNamespace(modality="image"))

    with pytest.raises(HTTPException) as exc:
        ai_resolver.resolve_model(object(), 7, modality="text", model_id=21)
    assert exc.value.status_code == 400


def test_credential_permission_requires_key_or_url_capability(monkeypatch):
    monkeypatch.setattr(
        points_ai,
        "_main",
        lambda: SimpleNamespace(
            _user_api_override_capabilities=lambda user, db: {
                "can_override_api_key": False,
                "can_override_api_url": False,
            }
        ),
    )

    with pytest.raises(HTTPException) as exc:
        points_ai._require_user_credential_permission(SimpleNamespace(id=7), object())
    assert exc.value.status_code == 403


def test_video_job_runtime_rejects_snapshot_after_permission_revoked(monkeypatch):
    monkeypatch.setattr(channels, "validate_user_base_url", lambda value: value.rstrip("/"))
    monkeypatch.setattr(
        main_mod,
        "_user_api_override_capabilities",
        lambda user, db: {"can_override_api_key": False, "can_override_api_url": False},
    )
    job = SimpleNamespace(
        model="old-model",
        provider_payload_json={
            "_runtime": {
                "credential_mode": "user_key",
                "base_url": "https://video.example.com/v1/",
                "model": "custom-video-model",
                "channel_id": None,
                "custom_upstream": True,
                "secret_ciphertext": encrypt_secret("saved-user-key"),
            }
        },
        shot=SimpleNamespace(
            scene=SimpleNamespace(
                chapter=SimpleNamespace(story=SimpleNamespace(owner_user_id=7))
            )
        ),
    )

    request = SimpleNamespace(state=SimpleNamespace(current_user=SimpleNamespace(id=7)))
    with pytest.raises(HTTPException) as exc:
        video_router._resolve_video_job_runtime(job, request, object())

    assert exc.value.status_code == 403


def test_custom_video_upstream_forces_lingdong_for_submit_snapshot_and_job_resolution():
    request = SimpleNamespace(
        state=SimpleNamespace(
            dual_track_video={
                "mode": "user_key",
                "channel_id": 12,
                "custom_upstream": True,
                "adapter_type": "openai_video",
                "api_key": "must-not-be-snapshotted",
            }
        ),
        headers={},
    )

    snapshot = video_router._build_video_runtime_snapshot(
        request,
        object(),
        api_key="must-not-be-snapshotted",
        base_url="https://video.example.com/v1",
        model="custom-video-model",
    )

    assert video_router._current_video_adapter_type(request) == "lingdong_video"
    assert snapshot == {
        "credential_mode": "user_key",
        "base_url": "https://video.example.com/v1",
        "model": "custom-video-model",
        "channel_id": 12,
        "custom_upstream": True,
        "adapter_type": "lingdong_video",
        "secret_ciphertext": snapshot["secret_ciphertext"],
    }
    job = SimpleNamespace(provider_payload_json={"_runtime": snapshot})
    assert video_router._video_job_adapter_type(job) == "lingdong_video"
    assert "must-not-be-snapshotted" not in repr(snapshot)


def test_video_job_runtime_keeps_original_key_after_user_rotates_key(monkeypatch):
    monkeypatch.setattr(channels, "validate_user_base_url", lambda value: value.rstrip("/"))
    monkeypatch.setattr(credentials, "load_user_api_key_plain", lambda db, user_id: "rotated-key")
    monkeypatch.setattr(
        main_mod,
        "_user_api_override_capabilities",
        lambda user, db: {"can_override_api_key": True, "can_override_api_url": True},
    )
    job = SimpleNamespace(
        model="custom-video-model",
        provider_payload_json={
            "_runtime": {
                "credential_mode": "user_key",
                "base_url": "https://old-video.example.com/v1",
                "model": "custom-video-model",
                "channel_id": None,
                "custom_upstream": True,
                "secret_ciphertext": encrypt_secret("original-key"),
            }
        },
    )

    request = SimpleNamespace(state=SimpleNamespace(current_user=SimpleNamespace(id=7)))
    result = video_router._resolve_video_job_runtime(job, request, object())

    assert result == ("original-key", "https://old-video.example.com/v1", "custom-video-model")


@pytest.mark.parametrize("model", ["sora_v2", "native-looking-model"])
def test_legacy_video_job_without_adapter_snapshot_defaults_to_lingdong(model):
    job = SimpleNamespace(
        model=model,
        provider_payload_json={"_runtime": {"model": model}},
    )

    assert video_router._video_job_adapter_type(job) == "lingdong_video"


def test_video_job_runtime_rejects_legacy_job_without_snapshot(monkeypatch):
    monkeypatch.setattr(video_router, "_user_video_api_key", lambda request: pytest.fail("不应回退到当前请求凭据"))
    job = SimpleNamespace(provider_payload_json=None)

    with pytest.raises(HTTPException) as exc:
        video_router._resolve_video_job_runtime(job, SimpleNamespace(), object())

    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_update_shot_checks_owner_and_only_updates_metadata(monkeypatch):
    shot = SimpleNamespace(
        id=12,
        scene_id=4,
        scene=SimpleNamespace(chapter_id=9),
        shot_number=1,
        title="旧标题",
        shot_type="",
        camera_angle="",
        camera_movement="",
        composition="",
        action_description="",
        dialogue="",
        sound_design="",
        duration_seconds=5,
        storyboard_prompt="",
        video_prompt="",
        negative_prompt="",
        first_frame_prompt="",
        last_frame_prompt="",
        character_prompts_json=[],
        continuity_notes="",
        character_involvement=None,
        scene_mood=None,
        status="draft",
        created_at=None,
        updated_at=None,
    )
    db = SimpleNamespace(get=lambda model, pk: shot, commit=lambda: None, refresh=lambda value: None)
    user = SimpleNamespace(id=7)
    ownership_checks = []
    monkeypatch.setattr(video_router, "_require_user", lambda request, session: user)
    monkeypatch.setattr(
        video_router,
        "_require_chapter_for_user",
        lambda chapter_id, current_user, session: ownership_checks.append((chapter_id, current_user.id)),
    )

    result = await video_router.update_shot(
        12,
        VideoShotUpdate(title="新标题", duration_seconds=999),
        SimpleNamespace(),
        db,
    )

    assert ownership_checks == [(9, 7)]
    assert result["title"] == "新标题"
    assert result["duration_seconds"] == video_router.SHOT_DURATION_SECONDS


def test_video_upstream_error_redacts_current_key():
    message = video_api._sanitize_upstream_error(
        '{"error":"Authorization: Bearer secret-key", "api_key":"secret-key"}',
        "secret-key",
    )

    assert "secret-key" not in message
    assert "***" in message


def test_video_upstream_payload_redacts_nested_success_fields():
    payload = video_api._sanitize_upstream_payload(
        {
            "status": "failed",
            "message": "Authorization: Bearer secret-key",
            "debug": [{"token": "secret-key"}],
        },
        "secret-key",
    )

    assert "secret-key" not in repr(payload)
    assert payload["message"].endswith("***")


def test_video_upstream_payload_preserves_long_signed_url():
    signed_url = "https://cdn.example.com/video.mp4?token=signed-download-token&padding=" + ("x" * 700)

    payload = video_api._sanitize_upstream_payload(
        {"result_url": signed_url},
        "different-api-key",
    )

    assert payload["result_url"] == signed_url


@pytest.mark.asyncio
async def test_provider_runtime_is_isolated_between_concurrent_tasks():
    async def resolve_runtime(suffix: str):
        deepseek.configure_runtime(base_url=f"https://text-{suffix}.example.com/v1", model=f"text-{suffix}")
        image2.configure_runtime(base_url=f"https://image-{suffix}.example.com/v1", model=f"image-{suffix}")
        video_api.configure(base_url=f"https://video-{suffix}.example.com/v1", api_key=f"key-{suffix}", model=f"video-{suffix}")
        await asyncio.sleep(0)
        return {
            "text": (deepseek.runtime_base_url(), deepseek.runtime_model()),
            "image": (image2.runtime_base_url(), image2.runtime_model()),
            "video": (video_api._resolved_base_url(), video_api._resolved_api_key(), video_api._resolved_model()),
        }

    first, second = await asyncio.gather(resolve_runtime("a"), resolve_runtime("b"))

    assert first["text"] == ("https://text-a.example.com/v1", "text-a")
    assert second["text"] == ("https://text-b.example.com/v1", "text-b")
    assert first["image"] == ("https://image-a.example.com/v1", "image-a")
    assert second["image"] == ("https://image-b.example.com/v1", "image-b")
    assert first["video"] == ("https://video-a.example.com/v1", "key-a", "video-a")
    assert second["video"] == ("https://video-b.example.com/v1", "key-b", "video-b")
