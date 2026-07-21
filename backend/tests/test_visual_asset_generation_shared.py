import asyncio
from pathlib import Path

import pytest

import main
from services import visual_asset_generation as service


def test_select_visual_references_matches_roles_and_required_assets(tmp_path: Path):
    character = tmp_path / "character.png"
    scene = tmp_path / "scene.png"
    prop = tmp_path / "prop.png"
    for path in (character, scene, prop):
        path.write_bytes(b"image")

    selected = service.select_visual_references(
        "林秋走进走廊",
        [
            {"path": character, "label": "林秋", "kind": "character_reference"},
            {"path": scene, "label": "旧宅走廊", "kind": "scene_reference"},
            {"path": prop, "label": "银色怀表", "kind": "prop_reference", "is_required": True},
        ],
    )

    assert [(item.path.name, item.role) for item in selected] == [
        ("prop.png", "prop"),
        ("character.png", "character"),
    ]


def test_style_visual_role_is_preserved():
    assert service.normalize_visual_role("style") == "style"
    assert service.normalize_visual_role("style_reference") == "style"


def test_manga_page_prioritizes_character_before_scene_and_prop(tmp_path: Path):
    character = tmp_path / "character.png"
    scene = tmp_path / "scene.png"
    prop = tmp_path / "prop.png"
    for path in (character, scene, prop):
        path.write_bytes(b"image")

    selected = main._select_ref_image_paths_for_scene(
        "陈玄在出租屋查看手机",
        [
            {"path": scene, "label": "出租屋", "kind": "scene"},
            {"path": prop, "label": "手机", "kind": "prop"},
            {"path": character, "label": "陈玄", "kind": "character"},
        ],
    )

    assert [(path.name, role) for path, _, role in selected] == [
        ("character.png", "character"),
        ("scene.png", "scene"),
        ("prop.png", "prop"),
    ]


@pytest.mark.asyncio
async def test_generate_visual_asset_image_delegates_without_style_prompt(monkeypatch, tmp_path: Path):
    captured = {}

    async def fake_generate_reference_image(**kwargs):
        captured.update(kwargs)
        return str(kwargs["output_path"])

    monkeypatch.setattr(service.image2, "generate_reference_image", fake_generate_reference_image)
    output_path = tmp_path / "scene.png"

    result = await service.generate_visual_asset_image(
        prompt="  雨夜旧宅走廊  ",
        output_path=output_path,
        asset_type="scene_reference",
        api_key="image-key",
    )

    assert result == str(output_path)
    assert captured["prompt"] == "雨夜旧宅走廊"
    assert captured["ref_type"] == "scene"
    assert captured["ref_image_paths"] is None


def test_implicit_style_reference_uses_only_highest_priority(tmp_path: Path):
    low = tmp_path / "low.png"
    high = tmp_path / "high.png"
    low.write_bytes(b"low")
    high.write_bytes(b"high")

    selected = main._select_ref_image_paths_for_scene(
        "无角色的空镜",
        [
            {"path": low, "kind": "style", "label": "低优先级", "priority": 1},
            {"path": high, "kind": "style_reference", "label": "高优先级", "priority": 10},
        ],
    )
    assert selected == [(high, "高优先级", "style")]


def test_multi_character_page_keeps_profiles_when_one_reference_is_missing():
    profiles = "角色名：林秋\n外貌：黑发\n角色名：顾川\n外貌：银发"
    result = main._character_profiles_for_page(
        profiles, "林秋与顾川在走廊会面", ["林秋"], ["character"],
    )
    assert result == profiles


def test_character_profiles_are_omitted_when_all_page_characters_have_references():
    profiles = "角色名：林秋\n外貌：黑发\n角色名：顾川\n外貌：银发"
    result = main._character_profiles_for_page(
        profiles,
        "林秋与顾川在走廊会面",
        ["林秋角色卡", "顾川角色卡"],
        ["character", "character"],
    )
    assert result == ""


def test_unknown_page_characters_keep_multi_character_profiles():
    profiles = "角色名：林秋\n外貌：黑发\n角色名：顾川\n外貌：银发"
    result = main._character_profiles_for_page(
        profiles, "两人在走廊会面", ["林秋", "顾川"], ["character", "character"],
    )
    assert result == profiles


def test_unknown_page_character_omits_single_matching_profile():
    profiles = "角色名：林秋\n外貌：黑发"
    result = main._character_profiles_for_page(
        profiles, "她独自走进房间", ["林秋角色卡"], ["character"],
    )
    assert result == ""


@pytest.mark.asyncio
async def test_auto_asset_cancellation_settles_completed_children_and_cancels_pending(monkeypatch):
    accounted = asyncio.Event()
    pending_cancelled = asyncio.Event()
    metadata_updates = []
    settlements = []

    async def fake_generate_auto_manga_asset(**kwargs):
        if kwargs["item"]["name"] == "已完成":
            return {"status": "generated", "asset_id": 101, "resolved_path": "done.png"}
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            pending_cancelled.set()
            raise

    def fake_update_metadata(task_id, **kwargs):
        metadata_updates.append(kwargs)
        if kwargs.get("asset_generated") == 1 and kwargs.get("asset_completed") == 1:
            accounted.set()

    monkeypatch.setattr(main, "_generate_auto_manga_asset", fake_generate_auto_manga_asset)
    monkeypatch.setattr(main, "AUTO_MANGA_ASSET_START_INTERVAL_SECONDS", 0)
    monkeypatch.setattr(main.task_manager, "is_cancellation_requested", lambda task_id: False)
    monkeypatch.setattr(main.task_manager, "update_task_metadata", fake_update_metadata)
    monkeypatch.setattr(
        main,
        "_finish_streaming_platform_points",
        lambda ctx, **kwargs: settlements.append(kwargs),
    )

    task = asyncio.create_task(main._ensure_auto_manga_assets(
        chapter_id=1,
        story_id=2,
        user_id=3,
        items=[
            {"name": "已完成", "asset_type": "character_reference", "prompt": "完成"},
            {"name": "未完成", "asset_type": "scene_reference", "prompt": "等待"},
        ],
        image_api_key=None,
        style_ref_path="style.png",
        fallback_anchor_path=None,
        billing_ctx=object(),
        task_id="task-1",
    ))
    await asyncio.wait_for(accounted.wait(), timeout=1)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert pending_cancelled.is_set()
    assert settlements == [{"success": True, "image_count": 1}]
    assert metadata_updates[-1]["asset_generated_ids"] == [101]
    assert metadata_updates[-1]["asset_generated"] == 1
    assert metadata_updates[-1]["asset_completed"] == 1
