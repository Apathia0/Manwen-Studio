"""视频无限画布运行时的安全与提示词组装测试。"""

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from services.video_canvas_runtime import _apply_style_prompt, _asset_static_url, _configured_reference_inputs, _external_video_reference_urls, _local_reference_paths, _node_inputs, _node_output_path, _reference_urls, _reusable_image_asset, _resolved_video_model, _trusted_import_media
from services.agent_service import _resolve_canvas_source_snapshot
from services import oss
from routers.video_canvas import _compile_plan_graph, _plan_ready_errors, _plan_shots, _plan_source_stale_error, _resolve_plan_source_snapshot, _run_scope_node_ids, _run_target_chapter_id, _validate_graph


def test_node_output_path_rejects_path_traversal(tmp_path: Path):
    with pytest.raises(RuntimeError, match="节点 id 不合法"):
        _node_output_path(tmp_path, 1, 2, "../escape", ".png")


def test_style_snapshot_is_appended_once_to_prompt():
    prompt = _apply_style_prompt(
        "雨夜街道",
        {"style_snapshot": {"prompt_template": "电影感，冷色调"}},
        [{"style_snapshot": {"prompt_template": "电影感，冷色调"}}],
    )

    assert prompt == "雨夜街道\n\n风格要求：电影感，冷色调"


def test_legacy_uploaded_image_is_reused_and_passed_to_downstream_video():
    asset = SimpleNamespace(id=17, story_id=3, status="active", file_path="uploads/reference.png", asset_type="image")
    canvas = SimpleNamespace(story_id=3)
    db = SimpleNamespace(get=lambda model, asset_id: asset if model.__name__ == "VideoAsset" and asset_id == 17 else None)
    image_config = {"reference_asset_ids": [17]}
    graph = {"edges": [{"source": "image", "target": "video"}]}

    reused = _reusable_image_asset(image_config, canvas, db)
    image_output = {"asset_id": reused.id, "file_path": reused.file_path, "url": reused.file_path, "reused": True}
    video_inputs = _node_inputs(graph, "video", {"image": image_output})

    assert reused is asset
    assert _reference_urls(video_inputs, canvas, db) == ["/static/video/uploads/reference.png"]


def test_trusted_imported_storyboard_requires_exact_workflow_and_shot_match():
    workflow = SimpleNamespace(id=6, story_id=3)
    shot = SimpleNamespace(id=8, workflow_id=6, storyboard_image_url="/static/manga/storyboard.png", video_url="/static/video/shot.mp4")
    canvas = SimpleNamespace(story_id=3)
    db = SimpleNamespace(get=lambda model, record_id: {"ChapterVideoWorkflow": workflow, "ChapterVideoShot": shot}.get(model.__name__) if record_id in {6, 8} else None)
    node = {
        "data": {
            "config": {"trusted_import_media_url": "/static/manga/storyboard.png", "existing_url": "https://untrusted.invalid/file.png"},
            "origin": {"source_type": "chapter_video_shot_storyboard", "source_id": 8, "source_workflow_id": 6},
        },
    }

    assert _trusted_import_media(node, canvas, db, "image") == "/static/manga/storyboard.png"
    node["data"]["config"]["trusted_import_media_url"] = "https://untrusted.invalid/file.png"
    assert _trusted_import_media(node, canvas, db, "image") is None


def test_video_reference_rejects_non_image_asset_before_submission():
    asset = SimpleNamespace(id=21, story_id=3, status="active", file_path="uploads/reference.mp4", asset_type="video")
    canvas = SimpleNamespace(story_id=3)
    db = SimpleNamespace(get=lambda model, asset_id: asset if model.__name__ == "VideoAsset" and asset_id == 21 else None)

    with pytest.raises(RuntimeError, match="仅支持图片参考素材"):
        _configured_reference_inputs({"reference_asset_ids": [21]}, canvas, db)


def test_canvas_style_reference_is_included_in_image_generation_inputs():
    asset = SimpleNamespace(id=22, story_id=3, status="active", file_path="style.png", asset_type="style_reference")
    canvas = SimpleNamespace(story_id=3)
    db = SimpleNamespace(get=lambda model, asset_id: asset if model.__name__ == "VideoAsset" and asset_id == 22 else None)

    inputs = _configured_reference_inputs({"style_reference_asset_id": 22}, canvas, db)

    assert [item["asset_id"] for item in inputs] == [22]


def test_canvas_style_preset_image_is_included_in_video_reference_urls():
    canvas = SimpleNamespace(story_id=3)
    db = SimpleNamespace(get=lambda *_args: None)

    inputs = _configured_reference_inputs(
        {"style_snapshot": {"name": "电影感", "image_url": "https://cdn.example.com/style.png"}},
        canvas,
        db,
    )

    assert _reference_urls(inputs, canvas, db) == ["https://cdn.example.com/style.png"]


def test_canvas_style_preset_image_is_localized_for_image_generation(monkeypatch, tmp_path: Path):
    cached_reference = tmp_path / "cached-style-reference.png"
    cached_reference.write_bytes(b"image")
    canvas = SimpleNamespace(story_id=3)
    db = SimpleNamespace(get=lambda *_args: None)
    received: list[tuple[str, str]] = []

    def localize(value: str, kind: str) -> str:
        received.append((value, kind))
        return str(cached_reference)

    monkeypatch.setattr("services.video_canvas_runtime.ensure_local_media_path", localize)
    inputs = _configured_reference_inputs(
        {"style_snapshot": {"name": "电影感", "image_url": "https://cdn.example.com/style.png"}},
        canvas,
        db,
    )

    assert _local_reference_paths(inputs, canvas, db) == [str(cached_reference)]
    assert received == [("https://cdn.example.com/style.png", "manga")]


def test_canvas_image_reference_resolves_static_manga_path(monkeypatch, tmp_path: Path):
    manga_dir = tmp_path / "manga_outputs"
    video_dir = tmp_path / "video_outputs"
    manga_dir.mkdir()
    video_dir.mkdir()
    reference = manga_dir / "asset_1" / "reference.png"
    reference.parent.mkdir()
    reference.write_bytes(b"image")
    monkeypatch.setattr("services.video_canvas_runtime.MANGA_OUTPUTS", manga_dir)
    monkeypatch.setattr("services.video_canvas_runtime.VIDEO_OUTPUTS", video_dir)
    asset = SimpleNamespace(id=23, story_id=3, status="active", file_path="/static/manga/asset_1/reference.png", asset_type="image")
    canvas = SimpleNamespace(story_id=3)
    db = SimpleNamespace(get=lambda model, asset_id: asset if model.__name__ == "VideoAsset" and asset_id == 23 else None)

    paths = _local_reference_paths([{"asset_id": 23}], canvas, db)

    assert paths == [str(reference.resolve())]


def test_canvas_image_reference_downloads_oss_url_before_image_submission(monkeypatch, tmp_path: Path):
    cached_reference = tmp_path / "cached-reference.png"
    cached_reference.write_bytes(b"image")
    asset = SimpleNamespace(id=26, story_id=3, status="active", file_path="https://canvas.example.com/video_outputs/reference.png", asset_type="image")
    canvas = SimpleNamespace(story_id=3)
    db = SimpleNamespace(get=lambda model, asset_id: asset if model.__name__ == "VideoAsset" and asset_id == 26 else None)
    received: list[tuple[str, str]] = []

    def localize(value: str, kind: str) -> str:
        received.append((value, kind))
        return str(cached_reference)

    monkeypatch.setattr("services.video_canvas_runtime.ensure_local_media_path", localize)

    paths = _local_reference_paths([{"asset_id": 26}], canvas, db)

    assert received == [("https://canvas.example.com/video_outputs/reference.png", "manga")]
    assert paths == [str(cached_reference)]


def test_canvas_video_reference_urls_include_style_and_manga_assets(monkeypatch, tmp_path: Path):
    manga_dir = tmp_path / "manga_outputs"
    video_dir = tmp_path / "video_outputs"
    manga_dir.mkdir()
    video_dir.mkdir()
    reference = manga_dir / "style.png"
    reference.write_bytes(b"image")
    monkeypatch.setattr("services.video_canvas_runtime.MANGA_OUTPUTS", manga_dir)
    monkeypatch.setattr("services.video_canvas_runtime.VIDEO_OUTPUTS", video_dir)
    asset = SimpleNamespace(id=24, story_id=3, status="active", file_path="manga_outputs/style.png", asset_type="style_reference")
    canvas = SimpleNamespace(story_id=3)
    db = SimpleNamespace(get=lambda model, asset_id: asset if model.__name__ == "VideoAsset" and asset_id == 24 else None)

    inputs = _configured_reference_inputs({"style_reference_asset_id": 24}, canvas, db)

    assert _reference_urls(inputs, canvas, db) == ["/static/manga/style.png"]
    assert _asset_static_url("manga_outputs/style.png") == "/static/manga/style.png"


def test_canvas_video_reference_urls_are_converted_to_oss_urls(monkeypatch):
    asset = SimpleNamespace(id=25, story_id=3, status="active", file_path="/static/manga/reference.png", asset_type="image")
    canvas = SimpleNamespace(story_id=3)
    db = SimpleNamespace(get=lambda model, asset_id: asset if model.__name__ == "VideoAsset" and asset_id == 25 else None)
    received: list[str] = []

    async def prepare_urls(urls: list[str]) -> list[str]:
        received.extend(urls)
        return ["https://canvas.example.com/video_outputs/reference.png"]

    monkeypatch.setattr("services.video_canvas_runtime.video_api_service.prepare_video_reference_urls", prepare_urls)

    urls = asyncio.run(_external_video_reference_urls([{"asset_id": 25}], canvas, db))

    assert received == ["/static/manga/reference.png"]
    assert urls == ["https://canvas.example.com/video_outputs/reference.png"]


def test_video_submission_model_comes_from_model_catalog():
    model = SimpleNamespace(id=4, model_key="catalog-video-model", modality="video", enabled=True)
    db = SimpleNamespace(get=lambda model_class, model_id: model if model_class.__name__ == "AiModel" and model_id == 4 else None)

    assert _resolved_video_model({"model_id": 4, "model": "forged-model"}, db, "default-model") == "catalog-video-model"


def test_browser_upload_signature_rejects_unsafe_object_key(monkeypatch):
    monkeypatch.setattr(oss, "is_enabled", lambda: True)

    assert oss.create_browser_upload_signature("../escape.png") is None
    assert oss.create_browser_upload_signature("/absolute/escape.png") is None


def test_canvas_plan_requires_all_review_sections():
    plan = SimpleNamespace(
        source_snapshot_json={"source_type": "chapter"},
        screenplay_json={"scenes": []},
        shot_json=None,
        asset_json={},
        canvas_json={"operations": []},
        execution_json=None,
    )

    assert set(_plan_ready_errors(plan)) == {
        "缺少镜头计划",
        "缺少资产计划",
        "缺少执行计划",
        "来源快照缺少 source_hash",
    }


def test_complete_canvas_plan_is_ready_for_user_confirmation():
    plan = SimpleNamespace(
        source_snapshot_json={"source_type": "text_node", "source_hash": "a"},
        screenplay_json={"scenes": [{"scene_id": "s1"}]},
        shot_json={"shots": [{"shot_index": 1}]},
        asset_json={"assets": []},
        canvas_json={"graph": {"nodes": [], "edges": []}},
        execution_json={"batches": []},
    )

    assert _plan_ready_errors(plan) == []


def test_complete_plan_compiles_to_reviewable_canvas_graph():
    plan = SimpleNamespace(
        id=9,
        source_snapshot_json={"source_type": "chapter", "source_hash": "a", "content": "雨夜相遇"},
        screenplay_json={"text": "第一场", "scenes": [{"scene_id": "s1"}]},
        shot_json={"shots": [{
            "shot_index": 1,
            "story_summary": "主角走入雨巷",
            "storyboard_prompt": "雨巷中的主角",
            "video_prompt": "镜头跟随主角前进",
            "duration_seconds": 15,
            "character_reference_ids": [17],
        }]},
        asset_json={"assets": [{"name": "雨伞", "prompt": "黑色长柄伞", "used_by_shot_indexes": [1]}]},
        story_id=1,
        chapter_id=2,
    )

    graph = _compile_plan_graph(plan)

    assert {node["id"] for node in graph["nodes"]} >= {"source", "screenplay", "shot-1", "board-1", "video-1"}
    assert _validate_graph(graph)["errors"] == []


def test_compiled_plan_run_uses_plan_chapter_instead_of_canvas_default():
    canvas = SimpleNamespace(id=8, story_id=1, default_chapter_id=2)
    version = SimpleNamespace(graph_json={"metadata": {"compiled_from_plan_id": 9}})
    plan = SimpleNamespace(id=9, canvas_id=8, story_id=1, chapter_id=7)
    db = SimpleNamespace(get=lambda model, record_id: plan if model.__name__ == "VideoCanvasPlan" and record_id == 9 else None)

    assert _run_target_chapter_id(canvas, version, db) == 7


def test_manual_canvas_run_falls_back_to_default_chapter():
    canvas = SimpleNamespace(id=8, story_id=1, default_chapter_id=2)
    version = SimpleNamespace(graph_json={"metadata": {}})

    assert _run_target_chapter_id(canvas, version, SimpleNamespace()) == 2


def test_plan_shots_rejects_invalid_duration_before_workflow_sync():
    plan = SimpleNamespace(
        shot_json={"shots": [{"shot_index": 1, "story_summary": "相遇", "duration_seconds": 61}]},
        story_id=1,
        chapter_id=2,
    )

    with pytest.raises(Exception, match="duration_seconds"):
        _plan_shots(plan, SimpleNamespace())


def test_run_scope_ignores_disabled_edges():
    graph = {
        "nodes": [],
        "edges": [
            {"source": "stale", "target": "target"},
            {"source": "active", "target": "target", "data": {"disabled": True}},
        ],
    }

    assert _run_scope_node_ids(graph, {"target"}) == {"stale", "target"}


def test_canvas_source_snapshot_reloads_chapter_content_on_server():
    chapter = SimpleNamespace(id=2, story_id=1, title="雨巷", novel_content="服务器保存的章节正文")
    canvas = SimpleNamespace(id=8, story_id=1, default_chapter_id=2)
    db = SimpleNamespace(get=lambda model, record_id: chapter if model.__name__ == "Chapter" and record_id == 2 else None)

    source = _resolve_canvas_source_snapshot(db, canvas, "chapter", 2)

    assert source["content"] == "服务器保存的章节正文"
    assert source["source_type"] == "chapter"
    assert len(source["source_hash"]) == 64


def test_rest_plan_source_snapshot_ignores_client_supplied_chapter_content():
    chapter = SimpleNamespace(id=2, story_id=1, title="雨巷", novel_content="服务端保存的章节正文")
    canvas = SimpleNamespace(id=8, story_id=1)
    db = SimpleNamespace(get=lambda model, record_id: chapter if model.__name__ == "Chapter" and record_id == 2 else None)

    source = _resolve_plan_source_snapshot(canvas, {"source_type": "chapter", "source_id": 2, "content": "伪造正文", "source_hash": "forged"}, db)

    assert source["content"] == "服务端保存的章节正文"
    assert source["source_hash"] != "forged"


def test_canvas_source_snapshot_rejects_unsupported_source_type():
    canvas = SimpleNamespace(id=8, story_id=1, default_chapter_id=None)

    with pytest.raises(ValueError, match="source_type"):
        _resolve_canvas_source_snapshot(SimpleNamespace(), canvas, "external_url")


def test_canvas_plan_detects_changed_chapter_source_before_confirmation():
    chapter = SimpleNamespace(id=2, story_id=1, novel_content="已经被编辑的新正文")
    plan = SimpleNamespace(
        story_id=1,
        source_snapshot_json={"source_type": "chapter", "source_id": 2, "source_hash": "old"},
    )
    db = SimpleNamespace(get=lambda model, record_id: chapter if model.__name__ == "Chapter" and record_id == 2 else None)

    assert _plan_source_stale_error(plan, db) == "章节正文已更新，请重新生成创作计划"


def test_plan_shots_rejects_unknown_fields_before_workflow_sync():
    plan = SimpleNamespace(
        shot_json={"shots": [{"shot_index": 1, "story_summary": "相遇", "unsafe_field": "x"}]},
        story_id=1,
        chapter_id=2,
    )
    db = SimpleNamespace()

    with pytest.raises(Exception, match="不支持字段"):
        _plan_shots(plan, db)


def test_plan_shots_rejects_video_asset_as_image_reference():
    plan = SimpleNamespace(
        shot_json={"shots": [{"shot_index": 1, "story_summary": "相遇", "character_reference_ids": [22]}]},
        story_id=1,
        chapter_id=2,
    )
    video_asset = SimpleNamespace(id=22, story_id=1, chapter_id=2, asset_type="video_clip", file_path="clips/shot.mp4")
    db = SimpleNamespace(query=lambda _model: SimpleNamespace(filter=lambda *_args: SimpleNamespace(all=lambda: [video_asset])))

    with pytest.raises(Exception, match="非图片"):
        _plan_shots(plan, db)
