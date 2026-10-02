"""视频无限画布图协议的纯函数测试。"""

from types import SimpleNamespace

from routers.video_canvas import NODE_CATALOG, _apply_legacy_edge_marks, _import_graph, _legacy_edge_keys, _matches_creation_scope, _merge_import_graph, _run_scope_node_ids, _validate_graph
from services.video_canvas_runtime import _node_inputs, _reference_urls, _reusable_image_asset


def _node(node_id, node_type, config=None, origin=None):
    data = {"label": node_id, "config": config or {}}
    if origin is not None:
        data["origin"] = origin
    return {"id": node_id, "type": node_type, "position": {"x": 0, "y": 0}, "data": data}


def _origin(source_type, source_id, workflow_id, baseline, source_missing=False):
    return {
        "source_type": source_type,
        "source_id": source_id,
        "source_workflow_id": workflow_id,
        "baseline_config": baseline,
        "source_missing": source_missing,
    }


def test_validate_graph_accepts_asset_reference_to_shot():
    graph = {
        "nodes": [_node("asset-1", "asset"), _node("shot-1", "shot")],
        "edges": [{
            "id": "edge-1", "source": "asset-1", "sourceHandle": "asset",
            "target": "shot-1", "targetHandle": "references",
        }],
    }

    result = _validate_graph(graph)

    assert result["valid"] is True
    assert result["errors"] == []


def test_validate_graph_accepts_video_asset_to_concat():
    graph = {
        "nodes": [_node("video-asset", "video_asset"), _node("concat-1", "concat")],
        "edges": [{
            "id": "edge-1", "source": "video-asset", "sourceHandle": "video",
            "target": "concat-1", "targetHandle": "videos",
        }],
    }

    assert _validate_graph(graph)["valid"] is True


def test_validate_graph_rejects_type_mismatch_and_cycle():
    type_mismatch = {
        "nodes": [_node("style-1", "style"), _node("shot-1", "shot")],
        "edges": [{
            "id": "edge-1", "source": "style-1", "sourceHandle": "style",
            "target": "shot-1", "targetHandle": "references",
        }],
    }
    cycle = {
        "nodes": [_node("first", "screenplay"), _node("second", "shot")],
        "edges": [
            {"id": "edge-1", "source": "first", "sourceHandle": "screenplay", "target": "second", "targetHandle": "screenplay"},
            {"id": "edge-2", "source": "second", "sourceHandle": "shot", "target": "first", "targetHandle": "source"},
        ],
    }

    assert "edge_type" in {error["code"] for error in _validate_graph(type_mismatch)["errors"]}
    assert "cycle" in {error["code"] for error in _validate_graph(cycle)["errors"]}


def test_validate_graph_rejects_unsafe_node_id():
    graph = {"nodes": [_node("../escape", "text")], "edges": []}

    result = _validate_graph(graph)

    assert result["valid"] is False
    assert "node_id" in {error["code"] for error in result["errors"]}


def test_validate_graph_accepts_image_reference_to_video_chain():
    graph = {
        "nodes": [_node("asset-1", "image"), _node("board-1", "image"), _node("video-1", "video"), _node("concat-1", "concat")],
        "edges": [
            {"id": "e1", "source": "asset-1", "sourceHandle": "image", "target": "board-1", "targetHandle": "references"},
            {"id": "e2", "source": "asset-1", "sourceHandle": "image", "target": "video-1", "targetHandle": "image"},
            {"id": "e3", "source": "board-1", "sourceHandle": "image", "target": "video-1", "targetHandle": "image"},
            {"id": "e4", "source": "video-1", "sourceHandle": "video", "target": "concat-1", "targetHandle": "videos"},
            {"id": "e5", "source": "board-1", "sourceHandle": "image", "target": "concat-1", "targetHandle": "videos"},
        ],
    }

    result = _validate_graph(graph)

    assert result["valid"] is True
    assert result["errors"] == []


def test_validate_graph_rejects_video_output_to_image_ports():
    to_references = {
        "nodes": [_node("video-src", "video"), _node("board-1", "image")],
        "edges": [{"id": "e1", "source": "video-src", "sourceHandle": "video", "target": "board-1", "targetHandle": "references"}],
    }
    to_image_input = {
        "nodes": [_node("video-a", "video"), _node("video-b", "video")],
        "edges": [{"id": "e2", "source": "video-a", "sourceHandle": "video", "target": "video-b", "targetHandle": "image"}],
    }

    assert "edge_type" in {error["code"] for error in _validate_graph(to_references)["errors"]}
    assert "edge_type" in {error["code"] for error in _validate_graph(to_image_input)["errors"]}


def test_marked_legacy_mismatch_edge_degrades_to_warning():
    graph = {
        "nodes": [_node("video-src", "video"), _node("board-1", "image")],
        "edges": [{"id": "e1", "source": "video-src", "sourceHandle": "video", "target": "board-1", "targetHandle": "references"}],
    }

    assert _validate_graph(graph)["valid"] is False

    _apply_legacy_edge_marks(graph)
    result = _validate_graph(graph)

    marked_data = graph["edges"][0].get("data")
    assert isinstance(marked_data, dict) and marked_data["legacy_type_edge"] is True
    assert result["valid"] is True
    assert result["errors"] == []
    assert "edge_type" in {warning["code"] for warning in result["warnings"]}


def test_save_baseline_exempts_existing_edge_but_rejects_new_mismatch():
    nodes = [_node("video-src", "video"), _node("board-1", "image"), _node("board-2", "image")]
    legacy_edge = {"id": "e1", "source": "video-src", "sourceHandle": "video", "target": "board-1", "targetHandle": "references"}
    new_illegal_edge = {"id": "e2", "source": "video-src", "sourceHandle": "video", "target": "board-2", "targetHandle": "references"}
    db_graph = {"nodes": nodes, "edges": [dict(legacy_edge)]}

    baseline_keys = _legacy_edge_keys(db_graph)
    incoming = {"nodes": nodes, "edges": [legacy_edge, new_illegal_edge]}
    _apply_legacy_edge_marks(incoming, baseline_keys)
    result = _validate_graph(incoming)

    legacy_data = incoming["edges"][0].get("data")
    new_data = incoming["edges"][1].get("data")
    assert isinstance(legacy_data, dict) and legacy_data["legacy_type_edge"] is True
    assert not (isinstance(new_data, dict) and new_data.get("legacy_type_edge"))
    assert "edge_type" in {warning["code"] for warning in result["warnings"]}
    assert "edge_type" in {error["code"] for error in result["errors"]}
    assert result["valid"] is False


def test_merge_import_graph_preserves_local_edit_and_reports_conflict():
    baseline = {"video_prompt": "旧提示词", "duration_seconds": 15}
    current = {
        "nodes": [_node(
            "existing-shot", "shot",
            {"video_prompt": "画布本地提示词", "duration_seconds": 15},
            _origin("chapter_video_shot", 8, 3, baseline),
        )],
        "edges": [],
    }
    source = {
        "nodes": [_node(
            "source-shot", "shot",
            {"video_prompt": "列表最新提示词", "duration_seconds": 20},
            _origin("chapter_video_shot", 8, 3, {"video_prompt": "列表最新提示词", "duration_seconds": 20}),
        )],
        "edges": [],
    }

    merged, result = _merge_import_graph(current, source, 3)
    config = merged["nodes"][0]["data"]["config"]

    assert config["video_prompt"] == "画布本地提示词"
    assert config["duration_seconds"] == 20
    assert result["updated_node_ids"] == ["existing-shot"]
    assert result["conflicts"] == [{
        "node_id": "existing-shot", "field": "video_prompt",
        "source_value": "列表最新提示词", "local_value": "画布本地提示词",
    }]


def test_merge_import_graph_marks_removed_source_as_orphaned():
    current = {
        "nodes": [_node(
            "old-shot", "shot", {"story_summary": "旧镜头"},
            _origin("chapter_video_shot", 9, 3, {"story_summary": "旧镜头"}),
        )],
        "edges": [],
    }

    merged, result = _merge_import_graph(current, {"nodes": [], "edges": []}, 3)

    assert result["source_orphaned_node_ids"] == ["old-shot"]
    assert merged["nodes"][0]["data"]["origin"]["source_missing"] is True


def test_merge_import_graph_upgrades_matching_legacy_node_type():
    current = {
        "nodes": [_node("legacy-shot", "shot", {"video_prompt": "旧"}, _origin("chapter_video_shot", 8, 3, {"video_prompt": "旧"}))],
        "edges": [],
    }
    source = {
        "nodes": [_node("source-shot", "text", {"video_prompt": "新"}, _origin("chapter_video_shot", 8, 3, {"video_prompt": "新"}))],
        "edges": [],
    }

    merged, result = _merge_import_graph(current, source, 3)

    assert merged["nodes"][0]["type"] == "text"
    assert result["migrated_node_ids"] == ["legacy-shot"]


def test_run_scope_includes_all_upstream_dependencies():
    graph = {
        "nodes": [_node("source", "text"), _node("image", "image_generation"), _node("video", "video_generation")],
        "edges": [
            {"id": "one", "source": "source", "sourceHandle": "text", "target": "image", "targetHandle": "prompt"},
            {"id": "two", "source": "image", "sourceHandle": "image", "target": "video", "targetHandle": "image"},
        ],
    }

    assert _run_scope_node_ids(graph, {"video"}) == {"source", "image", "video"}


def test_legacy_uploaded_image_is_reused_and_passed_to_downstream_video():
    asset = SimpleNamespace(id=17, story_id=3, status="active", file_path="uploads/reference.png", asset_type="image")
    canvas = SimpleNamespace(story_id=3)
    db = SimpleNamespace(get=lambda model, asset_id: asset if model.__name__ == "VideoAsset" and asset_id == 17 else None)
    graph = {"edges": [{"source": "image", "target": "video"}]}

    reused = _reusable_image_asset({"reference_asset_ids": [17]}, canvas, db)
    image_output = {"asset_id": reused.id, "file_path": reused.file_path, "url": reused.file_path, "reused": True}
    video_inputs = _node_inputs(graph, "video", {"image": image_output})

    assert reused is asset
    assert _reference_urls(video_inputs, canvas, db) == ["/static/video/uploads/reference.png"]


def test_creation_idempotency_key_cannot_cross_story_or_chapter_scope():
    canvas = SimpleNamespace(story_id=3, default_chapter_id=7)

    assert _matches_creation_scope(canvas, 3, 7) is True
    assert _matches_creation_scope(canvas, 3, 8) is False
    assert _matches_creation_scope(canvas, 4, 7) is False


def test_public_catalog_includes_review_and_media_container_nodes():
    assert set(NODE_CATALOG) == {"text", "screenplay", "scene", "image", "video", "audio", "container", "concat"}


class _Query:
    def __init__(self, rows):
        self.rows = rows

    def filter(self, *_args, **_kwargs):
        return self

    def order_by(self, *_args, **_kwargs):
        return self

    def all(self):
        return self.rows


class _ImportDb:
    def __init__(self, shots, assets):
        self.shots = shots
        self.assets = assets

    def query(self, model):
        name = getattr(model, "__name__", "")
        return _Query(self.shots if name == "ChapterVideoShot" else self.assets)


def test_import_graph_uses_text_image_video_and_keeps_shot_details():
    workflow = type("Workflow", (), {
        "id": 3,
        "screenplay_text": "场景剧本",
        "screenplay_json": {"scenes": [{"id": "s1"}]},
        "source_text": "原文",
        "screenplay_status": "approved",
        "screenplay_version": 2,
    })()
    shot = type("Shot", (), {
        "id": 8, "shot_index": 1, "source_text_span": "原文片段", "scene_location": "客厅", "time_of_day": "夜",
        "characters": ["甲"], "story_summary": "冲突", "dialogue_or_narration": "快走", "camera_plan": "近景",
        "motion_plan": "推镜", "emotion_plan": "紧张", "continuity_notes": "接上集", "screenplay_scene_id": "s1",
        "screenplay_beat_id": "b1", "narrative_purpose": "转折", "beat_density": "high", "transition_to_next": "cut",
        "continuity_json": {"next": "b2"}, "storyboard_prompt": "画面", "video_prompt": "视频",
        "character_prompts_json": {"甲": "黑衣"}, "scene_prompt": "客厅", "prop_prompts_json": {"刀": "银色"},
        "key_props_json": ["刀"], "scene_asset_candidates_json": [], "negative_prompt": "模糊",
        "duration_seconds": 15, "character_reference_ids": [11], "scene_reference_ids": [], "prop_reference_ids": [],
        "storyboard_image_url": "/static/manga/storyboard.png", "storyboard_json": {"panels": 1},
        "video_url": "/static/video/shot.mp4",
    })()
    asset = type("Asset", (), {"id": 11, "name": "角色甲", "revision": 4, "asset_type": "character_reference", "file_path": "character.png"})()

    graph = _import_graph(workflow, _ImportDb([shot], [asset]))
    assert {node["type"] for node in graph["nodes"]} == {"text", "image", "video"}
    shot_node = next(node for node in graph["nodes"] if node["data"]["origin"]["source_type"] == "chapter_video_shot")
    assert shot_node["data"]["config"]["continuity"] == {"next": "b2"}
    assert shot_node["data"]["config"]["camera_plan"] == "近景"
    image_nodes = [node for node in graph["nodes"] if node["type"] == "image"]
    assert any(node["data"]["config"].get("roles") == ["character"] for node in image_nodes)
    assert any(node["data"]["origin"]["source_type"] == "chapter_video_shot_storyboard" for node in image_nodes)
    assert any(node["type"] == "video" and node["data"]["origin"]["source_type"] == "chapter_video_shot_video" for node in graph["nodes"])
    assert _validate_graph(graph)["valid"] is True


def test_target_duration_parsing_ignores_pacing_requirements():
    from services.video_duration import estimate_screenplay_seconds, parse_target_duration_seconds, screenplay_char_budget

    assert parse_target_duration_seconds("日式动漫风。时长约60秒，16:9横屏。开场3秒内出现悬念；每10到15秒一个反转") == 60
    assert parse_target_duration_seconds("总时长1分钟") == 60
    assert parse_target_duration_seconds("做一个90秒短剧") == 90
    assert parse_target_duration_seconds("开场3秒内出现冲突，每10到15秒一次反转") is None
    assert parse_target_duration_seconds(None) is None
    assert screenplay_char_budget(60) == 336
    assert 150 < estimate_screenplay_seconds("字" * 852) < 154  # 与本地真实画布 151 秒的实测吻合
