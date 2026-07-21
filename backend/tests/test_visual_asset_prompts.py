import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from models import MangaAsset, MangaAssetBinding
from routers import video
from services.visual_asset_prompts import (
    VISUAL_ASSET_ANALYSIS_SYSTEM_PROMPT,
    _build_visual_asset_analysis_system_prompt,
    _parse_visual_asset_json,
    normalize_visual_asset_suggestions,
)


def test_shared_visual_asset_prompt_reuses_video_workflow_standards():
    assert "Character Design Director" in VISUAL_ASSET_ANALYSIS_SYSTEM_PROMPT
    assert "Production Design Director" in VISUAL_ASSET_ANALYSIS_SYSTEM_PROMPT
    assert '"characters"' in VISUAL_ASSET_ANALYSIS_SYSTEM_PROMPT
    assert '"scenes"' in VISUAL_ASSET_ANALYSIS_SYSTEM_PROMPT
    assert '"props"' in VISUAL_ASSET_ANALYSIS_SYSTEM_PROMPT


def test_visual_asset_prompt_only_contains_selected_asset_groups():
    prompt = _build_visual_asset_analysis_system_prompt({"characters"}, max_items=4)

    assert "本次只分析以下资产类型：角色" in prompt
    assert '"characters"' in prompt
    assert '"scenes"' not in prompt
    assert '"props"' not in prompt
    assert "Production Design Director" not in prompt


def test_visual_asset_prompt_separates_scene_and_prop_rules_for_single_selection():
    scene_prompt = _build_visual_asset_analysis_system_prompt({"scenes"})
    prop_prompt = _build_visual_asset_analysis_system_prompt({"props"})

    assert '"scenes"' in scene_prompt
    assert '"props"' not in scene_prompt
    assert "Location Name" in scene_prompt
    assert "Prop Name" not in scene_prompt
    assert '"props"' in prop_prompt
    assert '"scenes"' not in prop_prompt
    assert "Prop Name" in prop_prompt
    assert "Location Name" not in prop_prompt


def test_normalize_visual_asset_suggestions_filters_duplicates_and_empty_prompts():
    result = normalize_visual_asset_suggestions({
        "characters": [
            {"name": "陈玄", "description": "描述", "evidence": "依据", "prompt": "完整提示词"},
            {"name": " 陈玄 ", "prompt": "重复项"},
            {"name": "无提示词角色", "prompt": ""},
        ],
        "scenes": "invalid",
        "props": [{"name": f"道具{i}", "prompt": f"提示词{i}"} for i in range(8)],
    }, max_items=6)

    assert result["characters"] == [{
        "name": "陈玄",
        "description": "描述",
        "evidence": "依据",
        "prompt": "完整提示词",
    }]
    assert result["scenes"] == []
    assert len(result["props"]) == 6


def test_parse_visual_asset_json_repairs_unescaped_quotes_and_missing_commas():
    broken = '''{
      "characters": [{
        "name": "陈玄",
        "description": "角色描述",
        "evidence": "正文依据",
        "prompt": "Character sheet with "front view", "side view", and "detail callouts""
      }],
      "scenes": [
        {"name": "出租屋", "description": "场景", "evidence": "正文", "prompt": "Scene board"}
        {"name": "擂台", "description": "场景", "evidence": "正文", "prompt": "Arena board"}
      ],
      "props": []
    }'''

    result = _parse_visual_asset_json(broken)

    assert result["characters"][0]["prompt"] == 'Character sheet with "front view", "side view", and "detail callouts"'
    assert [scene["name"] for scene in result["scenes"]] == ["出租屋", "擂台"]


class _Request:
    async def json(self):
        return {
            "asset_type": "character_reference",
            "name": "陈玄",
            "prompt": "完整角色设定图提示词",
        }


class _AnalysisRequest:
    async def json(self):
        return {
            "suggestions": [{
                "asset_type": "character_reference",
                "name": "陈玄",
                "description": "角色描述",
                "evidence": "正文依据",
                "prompt": "编辑后的提示词",
                "candidates": [],
            }],
        }


class _RedrawRequest:
    async def json(self):
        return {
            "prompt": "保留角色特征，调整服装纹样",
            "mode": "full",
        }


class _Query:
    def join(self, *_args):
        return self

    def filter(self, *_args):
        return self

    def order_by(self, *_args):
        return self

    def first(self):
        return None

    def all(self):
        return []


class _Db:
    def __init__(self):
        self.added = []

    def query(self, *_args):
        return _Query()

    def add(self, value):
        self.added.append(value)

    def flush(self):
        for value in self.added:
            if isinstance(value, MangaAsset) and value.id is None:
                value.id = 101

    def commit(self):
        return None

    def rollback(self):
        return None

    def refresh(self, _value):
        return None


@pytest.mark.asyncio
async def test_generate_chapter_manga_asset_creates_asset_and_binding(monkeypatch, tmp_path):
    user = SimpleNamespace(id=7)
    chapter = SimpleNamespace(id=12, story_id=3)
    db = _Db()
    quota_deductions = []

    monkeypatch.setattr(video, "_MANGA_OUTPUTS_DIR", tmp_path)
    monkeypatch.setattr(video, "_require_user", lambda request, current_db: user)
    monkeypatch.setattr(video, "_require_chapter_for_user", lambda *_args: chapter)
    monkeypatch.setattr(video, "_user_image_api_key", lambda request: "image-key")
    monkeypatch.setattr(video, "_configure_image_service_from_db", lambda *_args: None)
    monkeypatch.setattr(
        video,
        "_check_and_consume_quota_wrapper",
        lambda *_args, **kwargs: quota_deductions.append(kwargs["deduct"]),
    )

    async def fake_generate_reference_image(*, output_path, **_kwargs):
        output_path.write_bytes(b"png")
        return str(output_path)

    monkeypatch.setattr(video.image2_service, "generate_reference_image", fake_generate_reference_image)

    result = await video.generate_chapter_manga_asset(12, _Request(), db)

    asset = next(value for value in db.added if isinstance(value, MangaAsset))
    binding = next(value for value in db.added if isinstance(value, MangaAssetBinding))
    assert result["id"] == 101
    assert result["storage_path"].startswith("manga_outputs/story_3/assets/asset_")
    assert asset.metadata_json == {"prompt": "完整角色设定图提示词", "provider": "image2"}
    assert binding.asset_id == 101
    assert binding.chapter_id == 12
    assert quota_deductions == [False, True]


@pytest.mark.asyncio
async def test_redraw_managed_manga_asset_replaces_image_after_success(monkeypatch, tmp_path):
    user = SimpleNamespace(id=7)
    source_dir = tmp_path / "story_3" / "assets"
    source_dir.mkdir(parents=True)
    source_path = source_dir / "original.png"
    source_path.write_bytes(b"original")
    asset = MangaAsset(
        id=21,
        owner_user_id=7,
        story_id=3,
        chapter_id=12,
        asset_type="character_reference",
        name="陈玄",
        storage_path="manga_outputs/story_3/assets/original.png",
        source_type="generated",
        status="active",
        metadata_json={"prompt": "旧提示词", "revision": 2},
    )

    class _RedrawDb(_Db):
        def get(self, model, asset_id):
            return asset if model is MangaAsset and asset_id == asset.id else None

    db = _RedrawDb()
    quota_deductions = []
    monkeypatch.setattr(video, "_MANGA_OUTPUTS_DIR", tmp_path)
    monkeypatch.setattr(video, "_require_user", lambda request, current_db: user)
    monkeypatch.setattr(video, "_user_image_api_key", lambda request: "image-key")
    monkeypatch.setattr(video, "_configure_image_service_from_db", lambda *_args: None)
    monkeypatch.setattr(
        video,
        "_check_and_consume_quota_wrapper",
        lambda *_args, **kwargs: quota_deductions.append(kwargs["deduct"]),
    )

    async def fake_edit_existing_image(*, source_image_path, output_path, **_kwargs):
        assert source_image_path == source_path
        output_path.write_bytes(b"redrawn")
        return str(output_path)

    monkeypatch.setattr(video.image2_service, "edit_existing_image", fake_edit_existing_image)

    result = await video.redraw_managed_manga_asset(21, _RedrawRequest(), db)

    assert result["storage_path"].startswith("manga_outputs/story_3/assets/asset_redraw_")
    assert result["metadata"]["prompt"] == "保留角色特征，调整服装纹样"
    assert result["metadata"]["revision"] == 3
    assert result["metadata"]["redraw_mode"] == "full"
    assert quota_deductions == [False, True]
    assert not source_path.exists()
    assert (tmp_path / result["storage_path"].removeprefix("manga_outputs/")).read_bytes() == b"redrawn"


@pytest.mark.asyncio
async def test_save_and_get_chapter_manga_asset_analysis(monkeypatch):
    user = SimpleNamespace(id=7)
    chapter = SimpleNamespace(id=12, story_id=3, manga_asset_analysis_json=None)
    db = _Db()
    monkeypatch.setattr(video, "_require_user", lambda request, current_db: user)
    monkeypatch.setattr(video, "_require_chapter_for_user", lambda *_args: chapter)

    saved = await video.save_chapter_manga_asset_analysis(12, _AnalysisRequest(), db)
    loaded = await video.get_chapter_manga_asset_analysis(12, SimpleNamespace(), db)

    assert saved["suggestions"][0]["prompt"] == "编辑后的提示词"
    assert chapter.manga_asset_analysis_json == {"version": 1, "suggestions": saved["suggestions"]}
    assert loaded == saved


@pytest.mark.asyncio
async def test_analyze_chapter_manga_assets_persists_completed_result(monkeypatch):
    user = SimpleNamespace(id=7)
    story = SimpleNamespace(character_profiles="角色资料", characters=[])
    chapter = SimpleNamespace(
        id=12,
        story_id=3,
        story=story,
        novel_content="陈玄走进出租屋。",
        manga_asset_analysis_json=None,
    )
    db = _Db()
    quota_deductions = []
    monkeypatch.setattr(video, "_require_user", lambda request, current_db: user)
    monkeypatch.setattr(video, "_require_chapter_for_user", lambda *_args: chapter)
    monkeypatch.setattr(video, "_user_deepseek_api_key", lambda *_args: "text-key")
    monkeypatch.setattr(
        video,
        "_check_and_consume_quota_wrapper",
        lambda *_args, **kwargs: quota_deductions.append(kwargs["deduct"]),
    )

    async def fake_analyze_visual_assets(**_kwargs):
        return {
            "characters": [{
                "name": "陈玄",
                "description": "角色描述",
                "evidence": "正文依据",
                "prompt": "完整角色提示词",
            }],
            "scenes": [],
            "props": [],
        }

    monkeypatch.setattr(video, "analyze_visual_assets", fake_analyze_visual_assets)

    result = await video.analyze_chapter_manga_assets(12, SimpleNamespace(), db)

    assert result["suggestions"][0]["name"] == "陈玄"
    assert chapter.manga_asset_analysis_json == {"version": 1, "suggestions": result["suggestions"]}
    assert quota_deductions == [False, True]


def test_manga_asset_analysis_normalization_rejects_invalid_entries():
    suggestions = video._normalize_manga_asset_analysis_suggestions([
        {"asset_type": "style_reference", "name": "风格", "prompt": "提示词"},
        {"asset_type": "scene_reference", "name": "出租屋", "prompt": "场景提示词", "candidates": []},
    ])

    assert suggestions == [{
        "asset_type": "scene_reference",
        "name": "出租屋",
        "description": "",
        "evidence": "",
        "prompt": "场景提示词",
        "candidates": [],
    }]


class _BatchDb:
    def __init__(self):
        self.closed = False
        self.rolled_back = False

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


def test_validate_manga_asset_generation_item_rejects_invalid_payload():
    with pytest.raises(HTTPException) as exc_info:
        video._validate_manga_asset_generation_item({
            "asset_type": "style_reference",
            "name": "水墨风",
            "prompt": "风格图",
        })

    assert getattr(exc_info.value, "status_code", None) == 422


@pytest.mark.asyncio
async def test_manga_asset_batch_limits_concurrency_and_keeps_partial_success(monkeypatch):
    sessions = []
    active = 0
    max_active = 0
    metadata_updates = []

    def session_factory():
        session = _BatchDb()
        sessions.append(session)
        return session

    async def fake_generate(*, db, item, **_kwargs):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.01)
        active -= 1
        if item["name"] == "失败道具":
            raise RuntimeError("上游拒绝生成")
        return {"id": len(sessions), "name": item["name"]}

    monkeypatch.setattr(video, "SessionLocal", session_factory)
    monkeypatch.setattr(video, "MANGA_ASSET_GENERATION_CONCURRENCY", 3)
    monkeypatch.setattr(video, "_generate_and_bind_manga_asset", fake_generate)
    monkeypatch.setattr(
        video.task_manager,
        "update_task_metadata",
        lambda task_id, **metadata: metadata_updates.append((task_id, metadata)),
    )
    items = [
        {"asset_type": "character_reference", "name": "角色甲", "prompt": "角色甲设定"},
        {"asset_type": "character_reference", "name": "角色乙", "prompt": "角色乙设定"},
        {"asset_type": "scene_reference", "name": "场景甲", "prompt": "场景甲设定"},
        {"asset_type": "prop_reference", "name": "失败道具", "prompt": "失败道具设定"},
        {"asset_type": "prop_reference", "name": "成功道具", "prompt": "成功道具设定"},
    ]

    result = await video._run_manga_asset_batch(
        items=items,
        user_id=7,
        api_key="image-key",
        style_ref_paths=[],
        billing_usage_event_id=None,
        task_id="batch-test",
        story_id=3,
        chapter_id=12,
    )

    assert result["status"] == "completed"
    assert result["completed"] == 4
    assert result["failed"] == 1
    assert max_active == 3
    assert all(session.closed for session in sessions)
    assert any(session.rolled_back for session in sessions)
    assert metadata_updates[-1][1]["stage"] == "succeeded"
    assert metadata_updates[-1][1]["completed"] == 4
