from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from routers import video
from models import VideoAsset, VideoShot
from schemas import (
    CompileProjectRequest,
    CreateVideoAssetRequest,
    PromoteAssetRequest,
    RetryJobRequest,
    ShotStylePresetUpdate,
    StoryboardActionRequest,
    UpdateAssetScopeRequest,
    VideoRenderRequest,
)
from services import image2, media_locator
from services.ai import crypto_secrets


class _SingleRowQuery:
    def __init__(self, row):
        self.row = row

    def filter(self, *_args, **_kwargs):
        return self

    def first(self):
        return self.row


def test_platform_setting_reader_supports_encrypted_payload(monkeypatch):
    payload = {"ciphertext": "encrypted-value"}
    db = SimpleNamespace(query=lambda _model: _SingleRowQuery(SimpleNamespace(value_json=payload)))
    calls = []

    def fake_reader(value, default=None):
        calls.append((value, default))
        return "decrypted-value"

    monkeypatch.setattr(crypto_secrets, "read_platform_setting_payload", fake_reader)

    assert video._get_platform_setting("api.video.api_key", db, "fallback") == "decrypted-value"
    assert calls == [(payload, "fallback")]


def test_image2_oss_auto_configure_supports_encrypted_payload(monkeypatch):
    values = {
        "oss.enabled": {"value": True},
        "oss.access_key_id": {"ciphertext": "encrypted-id"},
        "oss.access_key_secret": {"ciphertext": "encrypted-secret"},
        "oss.endpoint": {"value": "oss.example.com"},
        "oss.bucket": {"value": "bucket"},
        "oss.public_url_base": {"value": "https://cdn.example.com"},
    }

    class Query:
        def __init__(self):
            self.key = None

        def filter(self, expression):
            self.key = expression.right.value
            return self

        def first(self):
            payload = values.get(self.key)
            return SimpleNamespace(value_json=payload) if payload is not None else None

    class Db:
        def query(self, _model):
            return Query()

        def close(self):
            return None

    configured = {}

    def fake_reader(payload, default=None):
        if "ciphertext" in payload:
            return {"encrypted-id": "access-id", "encrypted-secret": "access-secret"}[payload["ciphertext"]]
        return payload.get("value", default)

    monkeypatch.setattr("database.SessionLocal", lambda: Db())
    monkeypatch.setattr(crypto_secrets, "read_platform_setting_payload", fake_reader)
    monkeypatch.setattr("services.oss.configure", lambda **kwargs: configured.update(kwargs))

    image2._auto_configure_oss()

    assert configured["access_key_id"] == "access-id"
    assert configured["access_key_secret"] == "access-secret"
    assert configured["endpoint"] == "oss.example.com"


def test_shot_guard_delegates_to_chapter_owner_check(monkeypatch):
    user = SimpleNamespace(id=7)
    shot = SimpleNamespace(scene=SimpleNamespace(chapter_id=42))
    db = SimpleNamespace(get=lambda model, object_id: shot)
    calls = []

    monkeypatch.setattr(
        video,
        "_require_chapter_for_user",
        lambda chapter_id, current_user, current_db: calls.append((chapter_id, current_user, current_db)),
    )

    assert video._require_shot_for_user(9, user, db) is shot
    assert calls == [(42, user, db)]


def test_asset_guard_delegates_to_chapter_owner_check(monkeypatch):
    user = SimpleNamespace(id=7)
    asset = SimpleNamespace(chapter_id=43, scene_id=None, shot_id=None, story_id=None)
    chapter = SimpleNamespace(id=43, story_id=5)

    def get(model, object_id):
        return asset if model is VideoAsset else chapter

    db = SimpleNamespace(get=get)
    calls = []

    monkeypatch.setattr(
        video,
        "_require_chapter_for_user",
        lambda chapter_id, current_user, current_db: calls.append((chapter_id, current_user, current_db)),
    )

    assert video._require_video_asset_for_user(10, user, db) is asset
    assert calls == [(43, user, db)]


def test_story_only_asset_uses_story_owner_check(monkeypatch):
    user = SimpleNamespace(id=7)
    asset = SimpleNamespace(chapter_id=None, scene_id=None, shot_id=None, story_id=5)
    db = SimpleNamespace(get=lambda model, object_id: asset)
    calls = []

    monkeypatch.setattr(
        video,
        "_require_story_for_user",
        lambda story_id, current_user, current_db: calls.append((story_id, current_user, current_db)),
    )

    assert video._require_video_asset_for_user(10, user, db) is asset
    assert calls == [(5, user, db)]


def test_reference_assets_must_belong_to_same_story():
    asset = SimpleNamespace(id=8, story_id=99, chapter_id=None, scene_id=None, shot_id=None)
    db = SimpleNamespace(query=lambda _model: _SingleRowQuery([asset]))
    db.query = lambda _model: SimpleNamespace(
        filter=lambda *_args: SimpleNamespace(all=lambda: [asset])
    )

    with pytest.raises(HTTPException) as exc_info:
        video._require_reference_assets_for_story([8], 5, db)
    assert exc_info.value.status_code == 403


@pytest.mark.parametrize(
    "file_path",
    [
        "C:/Windows/System32/drivers/etc/hosts",
        "../../backend/.env",
        "http://127.0.0.1/internal.png",
    ],
)
def test_video_asset_storage_path_rejects_untrusted_inputs(file_path):
    with pytest.raises(HTTPException):
        video._validate_video_asset_storage_path(file_path)


def test_video_asset_storage_path_accepts_managed_relative_path():
    assert video._validate_video_asset_storage_path("character_refs/chapter_1/a.png") == "character_refs/chapter_1/a.png"


def test_media_locator_rejects_absolute_path_outside_media_roots(tmp_path):
    outside_file = tmp_path / "secret.txt"
    outside_file.write_text("secret", encoding="utf-8")

    assert media_locator.resolve_local_media_path(str(outside_file), "video") is None
    assert media_locator.resolve_local_media_path(str(outside_file), "manga") is None


def test_visual_asset_references_keep_paths_labels_and_roles_aligned(monkeypatch):
    assets = [
        SimpleNamespace(id=1, asset_type="character_reference", name="林秋", file_path="https://cdn.example.com/lin.png"),
        SimpleNamespace(id=2, asset_type="storyboard_frame", name="旧故事板", file_path="/static/video/storyboard.png"),
        SimpleNamespace(id=3, asset_type="prop_reference", name="木簪", file_path="/static/video/prop.png"),
        SimpleNamespace(id=4, asset_type="style_reference", name="写实风格", file_path="/static/video/style.png"),
    ]
    path_map = {
        "https://cdn.example.com/lin.png": "C:/cache/lin.png",
        "/static/video/storyboard.png": "C:/video/storyboard.png",
        "/static/video/prop.png": "C:/video/prop.png",
        "/static/video/style.png": "C:/video/style.png",
    }
    monkeypatch.setattr(video, "ensure_local_media_path", lambda value, kind: path_map.get(value))

    resolved = video._resolve_visual_asset_references(assets)

    assert [(asset.id, path, label, role) for asset, path, label, role in resolved] == [
        (1, "C:/cache/lin.png", "林秋", "character"),
        (3, "C:/video/prop.png", "木簪", "prop"),
        (4, "C:/video/style.png", "写实风格", "style"),
    ]


def test_frame_reference_inputs_append_style_with_aligned_metadata(monkeypatch):
    assets = [
        SimpleNamespace(asset_type="character_reference", name="林秋", file_path="character.png"),
        SimpleNamespace(asset_type="prop_reference", name="木簪", file_path="prop.png"),
    ]
    monkeypatch.setattr(video, "_resolve_asset_file_paths", lambda rows: [f"C:/refs/{rows[0].file_path}"])

    paths, labels, roles = video._resolve_frame_reference_inputs(assets, "C:/refs/style.png")

    assert paths == ["C:/refs/character.png", "C:/refs/prop.png", "C:/refs/style.png"]
    assert labels == ["林秋", "木簪", "画面风格参考锚点"]
    assert roles == ["character", "prop", "style"]


def test_frame_prompt_uses_image_as_only_style_source():
    prompt = video._merge_style_prompt_for_reference_image(
        "雨夜追逐",
        "C:/refs/style.png",
        "写实电影感",
        "写实",
    )

    assert prompt == "雨夜追逐"


@pytest.mark.asyncio
async def test_compile_video_project_rejects_clip_from_other_chapter(monkeypatch):
    user = SimpleNamespace(id=7)
    project = SimpleNamespace(
        id=1,
        chapter_id=42,
        story_id=5,
        timeline_json=[{"clip_id": 8, "enabled": True, "order": 0}],
        subtitle_json=[],
        bgm_path="",
    )
    clip = SimpleNamespace(id=8, shot_id=9, is_active=True, video_path="/static/video/clip.mp4")
    shot = SimpleNamespace(id=9, scene_id=10)
    scene = SimpleNamespace(id=10, chapter_id=99)
    foreign_chapter = SimpleNamespace(id=99, story_id=5)

    def get(model, object_id):
        rows = {
            "VideoProject": project,
            "RenderedClip": clip,
            "VideoShot": shot,
            "ScriptScene": scene,
            "Chapter": foreign_chapter,
        }
        return rows.get(getattr(model, "__name__", ""))

    db = SimpleNamespace(get=get)
    monkeypatch.setattr(video, "_require_user", lambda request, current_db: user)
    monkeypatch.setattr(video, "_require_chapter_for_user", lambda *_args: SimpleNamespace(id=42, story_id=5))

    with pytest.raises(HTTPException) as exc_info:
        await video.compile_video_project(1, CompileProjectRequest(), SimpleNamespace(), db)
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_create_video_asset_rejects_cross_story_injection(monkeypatch):
    user = SimpleNamespace(id=7)
    chapter = SimpleNamespace(id=42, story_id=5)
    monkeypatch.setattr(video, "_require_user", lambda request, db: user)
    monkeypatch.setattr(video, "_require_chapter_for_user", lambda chapter_id, current_user, db: chapter)
    body = CreateVideoAssetRequest(
        story_id=99,
        asset_type="scene_reference",
        name="invalid",
        file_path="invalid.png",
    )

    with pytest.raises(HTTPException) as exc_info:
        await video.create_video_asset(42, body, SimpleNamespace(), SimpleNamespace())
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("scene_id", "shot_id"),
    [(8, None), (None, 9)],
)
async def test_create_video_asset_rejects_cross_chapter_links(monkeypatch, scene_id, shot_id):
    user = SimpleNamespace(id=7)
    chapter = SimpleNamespace(id=42, story_id=5)
    foreign_scene = SimpleNamespace(id=8, chapter_id=99)
    foreign_shot = SimpleNamespace(id=9, scene=foreign_scene, scene_id=8)

    def get(model, object_id):
        if model is VideoShot:
            return foreign_shot
        return foreign_scene

    db = SimpleNamespace(get=get)
    monkeypatch.setattr(video, "_require_user", lambda request, current_db: user)
    monkeypatch.setattr(video, "_require_chapter_for_user", lambda *_args: chapter)
    body = CreateVideoAssetRequest(
        scene_id=scene_id,
        shot_id=shot_id,
        asset_type="scene_reference",
        name="invalid",
        file_path="invalid.png",
    )

    with pytest.raises(HTTPException) as exc_info:
        await video.create_video_asset(42, body, SimpleNamespace(), db)
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_set_master_storyboard_rejects_asset_from_another_shot(monkeypatch):
    user = SimpleNamespace(id=7)
    chapter = SimpleNamespace(id=42, story_id=5)
    scene = SimpleNamespace(chapter_id=42, chapter=chapter)
    shot = SimpleNamespace(id=11, scene=scene)
    asset = SimpleNamespace(id=8, shot_id=12, asset_type="storyboard_frame")

    def get(model, object_id):
        if model is VideoShot:
            return shot
        if model is VideoAsset:
            return asset
        return None

    db = SimpleNamespace(get=get)
    monkeypatch.setattr(video, "_require_user", lambda request, current_db: user)
    monkeypatch.setattr(video, "_require_chapter_for_user", lambda *_args: chapter)

    with pytest.raises(HTTPException) as exc_info:
        await video.set_master_storyboard(
            11,
            StoryboardActionRequest(action="set_master", asset_id=8),
            SimpleNamespace(),
            db,
        )
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("endpoint", "body"),
    [
        (video.set_shot_video_style_preset, ShotStylePresetUpdate(style_preset="cinematic")),
        (video.delete_shot_video_style_preset, None),
        (video.get_shot_asset_bundle, None),
    ],
)
async def test_shot_resource_routes_reject_unowned_shots(monkeypatch, endpoint, body):
    user = SimpleNamespace(id=7)
    monkeypatch.setattr(video, "_require_user", lambda request, db: user)

    def reject(*_args, **_kwargs):
        raise HTTPException(403, "章节访问被拒绝")

    monkeypatch.setattr(video, "_require_shot_for_user", reject)
    kwargs = {"shot_id": 9, "request": SimpleNamespace(), "db": SimpleNamespace()}
    if body is not None:
        kwargs["body"] = body
    with pytest.raises(HTTPException) as exc_info:
        await endpoint(**kwargs)
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("endpoint", "body"),
    [
        (video.update_asset_scope, UpdateAssetScopeRequest()),
        (video.promote_asset, PromoteAssetRequest()),
    ],
)
async def test_asset_resource_routes_reject_unowned_assets(monkeypatch, endpoint, body):
    user = SimpleNamespace(id=7)
    monkeypatch.setattr(video, "_require_user", lambda request, db: user)

    def reject(*_args, **_kwargs):
        raise HTTPException(403, "章节访问被拒绝")

    monkeypatch.setattr(video, "_require_video_asset_for_user", reject)
    with pytest.raises(HTTPException) as exc_info:
        await endpoint(asset_id=10, body=body, request=SimpleNamespace(), db=SimpleNamespace())
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_latest_video_job_route_rejects_unowned_shot(monkeypatch):
    user = SimpleNamespace(id=7)
    monkeypatch.setattr(video, "_require_user", lambda request, db: user)

    def reject(*_args, **_kwargs):
        raise HTTPException(403, "章节访问被拒绝")

    monkeypatch.setattr(video, "_require_shot_for_user", reject)
    with pytest.raises(HTTPException) as exc_info:
        await video.get_latest_video_job_for_shot(11, SimpleNamespace(), SimpleNamespace())
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_retry_video_job_uses_current_runtime_credentials(monkeypatch, tmp_path):
    user = SimpleNamespace(id=7)
    shot = SimpleNamespace(
        id=11,
        scene=SimpleNamespace(chapter_id=42, chapter=SimpleNamespace(story_id=88)),
    )
    old_job = SimpleNamespace(
        id=3,
        shot=shot,
        shot_id=11,
        duration_seconds=15,
        request_payload_json={"prompt": "retry prompt"},
        provider="old-provider",
        model="old-model",
        aspect_ratio="16:9",
        input_mode="text_to_video",
        provider_payload_json={"_runtime": {"secret_ciphertext": "old-secret"}},
        reference_asset_ids_json=[31, 32],
        source_storyboard_asset_id=None,
    )

    class Db:
        def __init__(self):
            self.added = None

        def get(self, model, object_id):
            return old_job

        def add(self, value):
            self.added = value

        def commit(self):
            return None

        def refresh(self, value):
            if value.id is None:
                value.id = 99

    db = Db()
    submitted = {}
    snapshot_args = {}
    resolved_reference_ids = []
    local_reference = tmp_path / "31.png"
    local_reference.write_bytes(b"local-reference")

    async def fake_submit_task(**kwargs):
        submitted.update(kwargs)

    def build_snapshot(_request, _db, **kwargs):
        snapshot_args.update(kwargs)
        return {"current": True, "model": kwargs["model"]}

    monkeypatch.setattr(video, "_require_user", lambda request, current_db: user)
    monkeypatch.setattr(video, "_require_chapter_for_user", lambda *_args: None)
    monkeypatch.setattr(video, "_user_video_api_key", lambda request: ("current-key", "https://current.example", "current-model"))
    monkeypatch.setattr(
        video,
        "_resolve_video_job_runtime",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("不应读取旧任务凭据快照")),
    )
    monkeypatch.setattr(video, "_reserve_video_billing", lambda *_args, **_kwargs: {"usage_event_id": 55})
    monkeypatch.setattr(video, "_detach_video_billing", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(video, "_resolve_video_provider", lambda provider, current_db: "current-provider")
    monkeypatch.setattr(video, "_build_video_runtime_snapshot", build_snapshot)
    monkeypatch.setattr(video, "_require_reference_assets_for_story", lambda *_args: None)
    monkeypatch.setattr(
        video,
        "_resolve_asset_reference_urls",
        lambda asset_ids, *_args: resolved_reference_ids.extend(asset_ids)
        or [
            str(local_reference),
            "https://cdn.example.com/32.png?token=TRANSIENT",
        ],
    )
    monkeypatch.setattr(video.task_manager, "submit_task", fake_submit_task)

    result = await video.retry_video_job(3, RetryJobRequest(), SimpleNamespace(), db)

    assert submitted["api_key"] == "current-key"
    assert submitted["base_url"] == "https://current.example"
    assert submitted["model"] == "current-model"
    assert submitted["provider"] == "current-provider"
    assert submitted["adapter_type"] == "lingdong_video"
    assert snapshot_args == {
        "api_key": "current-key",
        "base_url": "https://current.example",
        "model": "current-model",
    }
    assert db.added.provider_payload_json["_runtime"] == {"current": True, "model": "current-model"}
    assert resolved_reference_ids == [31, 32]
    assert submitted["reference_images"][0].startswith("data:image/png;base64,")
    assert submitted["reference_images"][1] == "https://cdn.example.com/32.png?token=TRANSIENT"
    lingdong_reference = "|".join(submitted["reference_images"])
    assert lingdong_reference.startswith("data:image/png;base64,")
    assert lingdong_reference.endswith("|https://cdn.example.com/32.png?token=TRANSIENT")
    assert db.added.request_payload_json["reference_asset_ids"] == [31, 32]
    assert "TRANSIENT" not in str(db.added.request_payload_json)
    assert result["job"]["id"] == 99


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("budget_name", "file_sizes", "limit_name", "limit_value", "error_text"),
    [
        ("single", [5], "MAX_VIDEO_REFERENCE_FILE_BYTES", 4, "单个参考文件"),
        ("cumulative", [4, 4], "MAX_VIDEO_REFERENCE_TOTAL_BYTES", 7, "累计大小"),
        ("base64", [4], "MAX_VIDEO_REFERENCE_BASE64_BYTES", 4, "Base64"),
    ],
)
async def test_retry_video_job_preflights_reference_budgets_before_side_effects(
    monkeypatch,
    tmp_path,
    budget_name,
    file_sizes,
    limit_name,
    limit_value,
    error_text,
):
    user = SimpleNamespace(id=7)
    shot = SimpleNamespace(
        id=11,
        scene=SimpleNamespace(chapter_id=42, chapter=SimpleNamespace(story_id=88)),
    )
    reference_ids = list(range(31, 31 + len(file_sizes)))
    old_job = SimpleNamespace(
        id=3,
        shot=shot,
        shot_id=11,
        duration_seconds=15,
        request_payload_json={"prompt": "retry prompt"},
        aspect_ratio="16:9",
        input_mode="image_to_video",
        reference_asset_ids_json=reference_ids,
    )
    db = SimpleNamespace(get=lambda _model, _object_id: old_job)
    reference_paths = []
    for index, size in enumerate(file_sizes):
        path = tmp_path / f"{budget_name}-{index}.png"
        path.write_bytes(b"x" * size)
        reference_paths.append(str(path))

    read_calls = []
    original_open = open

    def tracking_open(file, mode="r", *args, **kwargs):
        if "b" in mode:
            read_calls.append(str(file))
        return original_open(file, mode, *args, **kwargs)

    async def reject_submit(**_kwargs):
        pytest.fail("引用预算失败时不应提交上游任务")

    monkeypatch.setattr("builtins.open", tracking_open)
    monkeypatch.setattr(video, "MAX_VIDEO_REFERENCE_FILE_BYTES", 100)
    monkeypatch.setattr(video, "MAX_VIDEO_REFERENCE_TOTAL_BYTES", 100)
    monkeypatch.setattr(video, "MAX_VIDEO_REFERENCE_BASE64_BYTES", 200)
    monkeypatch.setattr(video, limit_name, limit_value)
    monkeypatch.setattr(video, "_require_user", lambda *_args: user)
    monkeypatch.setattr(video, "_require_chapter_for_user", lambda *_args: None)
    monkeypatch.setattr(video, "_user_video_api_key", lambda _request: ("key", "https://api.example.com", "model"))
    monkeypatch.setattr(video, "_resolve_video_provider", lambda *_args: "provider")
    monkeypatch.setattr(video, "_require_reference_assets_for_story", lambda *_args: None)
    monkeypatch.setattr(video, "_resolve_asset_reference_urls", lambda *_args: reference_paths)
    monkeypatch.setattr(
        video,
        "_reserve_video_billing",
        lambda *_args, **_kwargs: pytest.fail("引用预算失败时不应预扣积分"),
    )
    monkeypatch.setattr(video.task_manager, "submit_task", reject_submit)

    with pytest.raises(ValueError, match=error_text):
        await video.retry_video_job(3, RetryJobRequest(), SimpleNamespace(), db)

    assert read_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", [video.render_shot_video_stream, video.render_shot_video])
@pytest.mark.parametrize(
    ("duration_seconds", "reference_urls", "error_text"),
    [
        (15, [], "不支持该时长"),
        (5, ["https://cdn.example.com/a.png", "https://cdn.example.com/b.png"], "最多一张参考图"),
    ],
)
async def test_traditional_render_rejects_openai_limits_before_reserve(
    monkeypatch, endpoint, duration_seconds, reference_urls, error_text
):
    chapter = SimpleNamespace(id=42, story=SimpleNamespace())
    scene = SimpleNamespace(chapter_id=42, chapter=chapter)
    shot = SimpleNamespace(
        id=11,
        scene=scene,
        duration_seconds=5,
        storyboard_asset_id=None,
        storyboard_locked=False,
        storyboard_prompt="",
        negative_prompt="",
    )

    class Query:
        def filter(self, *_args, **_kwargs):
            return self

        def all(self):
            return []

    db = SimpleNamespace(get=lambda _model, _pk: shot, query=lambda _model: Query())
    request = SimpleNamespace(
        headers={},
        state=SimpleNamespace(
            dual_track_video={
                "adapter_type": "openai_video",
                "model_key": "openai-model",
                "model_id": 4,
                "custom_upstream": False,
            }
        ),
    )
    capabilities = {
        "limits": {"duration_seconds": {"allowed": [5]}, "max_reference_images": 1},
        "input_modes": ["text_to_video", "image_to_video"],
        "wire": {"size_by_resolution_aspect": {"720P|16:9": "1280x720"}},
    }
    monkeypatch.setattr(video, "_require_user", lambda *_args: SimpleNamespace(id=7))
    monkeypatch.setattr(video, "_require_chapter_for_user", lambda *_args: None)
    monkeypatch.setattr(video, "_resolve_video_provider", lambda *_args: "provider")
    monkeypatch.setattr(video, "_collect_shot_reference_asset_ids", lambda *_args, **_kwargs: [1, 2])
    monkeypatch.setattr(video, "_resolve_asset_reference_urls", lambda *_args, **_kwargs: reference_urls)
    monkeypatch.setattr(
        video,
        "_split_frame_assets",
        lambda _assets: (
            None,
            None,
            [SimpleNamespace(id=index) for index in range(1, len(reference_urls) + 1)],
        ),
    )
    monkeypatch.setattr(video, "_get_previous_shot_last_frame", lambda *_args: None)
    monkeypatch.setattr(video, "_resolve_effective_style_for_shot", lambda *_args, **_kwargs: {
        "name": "", "video_style_params": {}, "prompt_template": ""
    })
    monkeypatch.setattr(video, "_resolve_workflow_style_ref_path", lambda *_args: None)
    monkeypatch.setattr(video, "_user_video_api_key", lambda *_args: ("key", "https://example.com", "openai-model"))
    monkeypatch.setattr(video, "_current_video_capabilities", lambda *_args: capabilities)
    monkeypatch.setattr(
        video,
        "_reserve_video_billing",
        lambda *_args, **_kwargs: pytest.fail("协议能力校验失败时不应预扣积分"),
    )

    with pytest.raises(ValueError, match=error_text):
        await endpoint(
            11,
            VideoRenderRequest(duration_seconds=duration_seconds, reference_asset_ids=[1, 2]),
            request,
            db,
        )
