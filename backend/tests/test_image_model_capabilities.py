from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import main
from routers import creation_studio, points_ai
from services import image2


@pytest.fixture(autouse=True)
def image_runtime_isolated():
    image2._IMAGE_RUNTIME.set(None)
    yield
    image2._IMAGE_RUNTIME.set(None)


def test_image_model_capabilities_accepts_controlled_quality_config():
    points_ai._validate_model_capabilities(
        {
            "schema_version": 1,
            "image": {
                "defaults": {"quality": "high"},
                "limits": {
                    "qualities": ["low", "medium", "high"],
                },
            },
        },
        "image",
        "openai_compatible",
    )


@pytest.mark.parametrize(
    "capabilities",
    [
        None,
        {},
        {"legacy": True},
    ],
)
def test_image_model_capabilities_keeps_legacy_records_compatible(capabilities):
    points_ai._validate_model_capabilities(capabilities, "image", "openai_compatible")


@pytest.mark.parametrize(
    "capabilities",
    [
        {"schema_version": 2, "image": {}},
        {"image": {"defaults": {"quality": "ultra"}}},
        {"image": "bad"},
        {"image": {"limits": {"qualities": ["high", "high"]}}},
        {"image": {"defaults": {"quality": "high"}, "limits": {"qualities": ["low"]}}},
    ],
)
def test_image_model_capabilities_rejects_invalid_quality_config(capabilities):
    with pytest.raises(HTTPException):
        points_ai._validate_model_capabilities(capabilities, "image", "openai_compatible")


def test_dual_track_image_model_quality_overrides_platform_default(monkeypatch):
    image2._IMAGE_RUNTIME.set(None)
    monkeypatch.setattr(
        main,
        "_resolve_dual_track_runtime",
        lambda *_args, **_kwargs: {
            "base_url": "https://image.example.com/v1",
            "model_key": "image-model",
            "api_key": "image-key",
            "capabilities_json": {"image": {"defaults": {"quality": "high"}}},
        },
    )
    monkeypatch.setattr(main, "_get_platform_setting", lambda key, _db, default=None: "low" if key == "api.image.quality" else default)
    request = SimpleNamespace(state=SimpleNamespace(db=object()), headers={})

    assert main._user_image_api_key(request) == "image-key"
    assert image2._runtime_settings().quality == "high"


def test_dual_track_legacy_quality_only_profile_keeps_unconstrained_edit_size(monkeypatch):
    monkeypatch.setattr(
        main,
        "_resolve_dual_track_runtime",
        lambda *_args, **_kwargs: {
            "base_url": "https://image.example.com/v1",
            "model_key": "image-model",
            "api_key": "image-key",
            "capabilities_json": {"image": {"defaults": {"quality": "high"}}},
        },
    )
    monkeypatch.setattr(main, "_get_platform_setting", lambda *_args, **_kwargs: "1920x1080")
    request = SimpleNamespace(state=SimpleNamespace(db=object()), headers={})

    assert main._user_image_api_key(request) == "image-key"
    payload = image2._manga_edit_payload("旧配置尺寸诊断", "1920x1080", ["character"])
    assert image2._runtime_settings().size == "1920x1080"  # 配置值不变
    assert payload["size"] == "1920x1088"  # 实际发出的尺寸对齐到 16 的倍数，避免被上游 400 拒绝


def test_creation_studio_image_quality_uses_default_and_enforces_limits():
    capabilities = {
        "defaults": {"quality": "high"},
        "limits": {"qualities": ["medium", "high"]},
    }

    assert creation_studio._resolve_image_quality(capabilities, "auto") == "high"
    assert creation_studio._resolve_image_quality(capabilities, "medium") == "medium"
    with pytest.raises(HTTPException):
        creation_studio._resolve_image_quality(capabilities, "low")

