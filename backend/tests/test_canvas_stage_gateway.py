"""画布阶段入口的授权版本、执行范围和资产失效回归。"""

import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from services import canvas_stage_gateway as gateway
from routers import video_canvas as api
from models import VideoCanvasRun, VideoCanvasRunNode
from schemas import VideoCanvasRunRequest


@pytest.fixture(autouse=True)
def _skip_script_review(monkeypatch):
    """剧本逻辑审稿要调文本模型；网关测试只关心阶段编排，默认视为审稿通过。"""
    async def passed(*_args, **_kwargs):
        return []

    monkeypatch.setattr("services.canvas_script_review.review_screenplay", passed)


def node(identifier, kind="image", **config):
    return {"id": identifier, "type": kind, "position": {"x": 0, "y": 0}, "data": {"config": config}}


class EmptyQuery:
    def filter(self, *args):
        return self

    def first(self):
        return None


@pytest.fixture
def stage_state(monkeypatch):
    state = SimpleNamespace(
        canvas=SimpleNamespace(id=1, definition_revision=3),
        graph={"nodes": [node("first", prompt="镜头一"), node("second", prompt="镜头二")], "edges": []},
        saved=[], planned=[],
    )
    db = SimpleNamespace(query=lambda *args: EmptyQuery())
    state.db = db
    monkeypatch.setattr(api, "_require_user", lambda *args: SimpleNamespace(id=9))
    monkeypatch.setattr(api, "_require_canvas", lambda *args: state.canvas)
    monkeypatch.setattr(api, "_latest_version", lambda *args: SimpleNamespace(graph_json=state.graph))
    monkeypatch.setattr(gateway, "_reusable_outputs", lambda *args: None)

    def save(graph, canvas, user, db, expected, summary):
        assert expected == state.canvas.definition_revision
        state.saved.append(deepcopy(graph))
        state.canvas.definition_revision += 1
        return state.canvas.definition_revision

    async def create(canvas_id, body, request, db):
        state.planned.append(body)
        return {"run": {"id": 21, "status": "queued"}}

    monkeypatch.setattr(gateway, "_save", save)
    monkeypatch.setattr(api, "create_video_canvas_run", create)
    return state


def execute(state, stage="images", **parameters):
    return asyncio.run(gateway.execute_agent_canvas_stage(
        1, stage, {"agent_action_id": 7, "expected_definition_revision": 3, **parameters},
        SimpleNamespace(), state.db,
    ))


def test_authorized_target_node_ids_never_expand_to_all_nodes(stage_state):
    execute(stage_state, target_node_ids=["second"])
    assert stage_state.planned[0].target_node_ids == ["second"]


def test_legacy_node_ids_keep_precise_scope(stage_state):
    execute(stage_state, node_ids=["first"])
    assert stage_state.planned[0].target_node_ids == ["first"]


def test_revision_change_between_approval_and_gateway_is_rejected(stage_state):
    with pytest.raises(HTTPException) as failure:
        execute(stage_state, expected_definition_revision=2)
    assert failure.value.status_code == 409
    assert stage_state.saved == []
    assert stage_state.planned == []


def test_missing_server_action_does_not_write(stage_state):
    with pytest.raises(HTTPException) as failure:
        execute(stage_state, agent_action_id=None)
    assert failure.value.status_code == 403
    assert stage_state.saved == []


def test_unknown_requested_node_is_rejected_before_any_generation(stage_state):
    with pytest.raises(HTTPException) as failure:
        execute(stage_state, target_node_ids=["missing"])
    assert failure.value.status_code == 422
    assert stage_state.saved == []
    assert stage_state.planned == []


def test_screenplay_alias_selects_one_of_multiple_scripts(stage_state, monkeypatch):
    stage_state.graph["nodes"] = [node("script-one", "screenplay", content="甲"), node("script-two", "screenplay", content="乙")]
    selected = []

    async def split(canvas_id, body, request, db):
        selected.append(body.node_id)
        return {"units": [{"scene_id": "scene-a"}], "content_hash": "hash", "truncated": False}

    monkeypatch.setattr(api, "screenplay_split", split)
    execute(stage_state, stage="split", screenplay_node_id="script-two")
    assert selected == ["script-two"]
    assert stage_state.saved[0]["edges"][0]["source"] == "script-two"


def test_screenplay_stage_reuses_existing_node_without_node_id(stage_state):
    stage_state.graph["nodes"] = [node("script", "screenplay", content="旧剧本")]
    execute(stage_state, stage="screenplay", content="确认后的新剧本正文")
    screens = [item for item in stage_state.saved[0]["nodes"] if item["type"] == "screenplay"]
    assert len(screens) == 1
    assert screens[0]["id"] == "script"
    assert screens[0]["data"]["config"]["content"] == "确认后的新剧本正文"


def test_screenplay_stage_ignores_stale_node_and_creates_fresh_one(stage_state):
    stage_state.graph["nodes"] = [node("old-script", "screenplay", content="过期剧本", stale=True)]
    execute(stage_state, stage="screenplay", content="确认后的新剧本正文")
    screens = [item for item in stage_state.saved[0]["nodes"] if item["type"] == "screenplay"]
    assert len(screens) == 2
    fresh = next(item for item in screens if item["id"] != "old-script")
    assert fresh["data"]["config"]["content"] == "确认后的新剧本正文"
    assert not fresh["data"]["config"].get("stale")


def test_browser_snapshot_takes_priority_over_database_graph(stage_state):
    snapshot = {"nodes": [node("snap-only", prompt="快照镜头")], "edges": []}
    asyncio.run(gateway.execute_agent_canvas_stage(
        1, "images", {"agent_action_id": 7, "expected_definition_revision": 3, "target_node_ids": ["snap-only"]},
        SimpleNamespace(), stage_state.db, graph_snapshot=snapshot,
    ))
    assert [item["id"] for item in stage_state.saved[0]["nodes"]] == ["snap-only"]


def test_invalid_snapshot_falls_back_to_database_graph(stage_state):
    asyncio.run(gateway.execute_agent_canvas_stage(
        1, "images", {"agent_action_id": 7, "expected_definition_revision": 3, "target_node_ids": ["second"]},
        SimpleNamespace(), stage_state.db, graph_snapshot={"nodes": "bad", "edges": []},
    ))
    assert stage_state.planned[0].target_node_ids == ["second"]


def test_truncated_scene_response_is_never_saved(stage_state, monkeypatch):
    stage_state.graph["nodes"] = [node("script", "screenplay", content="剧本")]

    async def split(*args):
        return {"units": [{"scene_id": "scene-a"}], "truncated": True}

    monkeypatch.setattr(api, "screenplay_split", split)
    with pytest.raises(HTTPException) as failure:
        execute(stage_state, stage="split", screenplay_node_id="script")
    assert failure.value.status_code == 422
    assert stage_state.saved == []


def test_definition_hash_tracks_all_upstream_configuration():
    graph = {"nodes": [node("asset", prompt="红衣"), node("shot", prompt="站立")], "edges": [
        {"id": "edge", "source": "asset", "target": "shot", "sourceHandle": "image", "targetHandle": "references"},
    ]}
    original = gateway._definition_hash(graph, "shot")
    graph["nodes"][0]["data"]["config"]["prompt"] = "蓝衣"
    assert gateway._definition_hash(graph, "shot") != original


def test_reuse_marker_does_not_change_definition_fingerprint():
    graph = {"nodes": [node("shot", prompt="站立")], "edges": []}
    original = gateway._definition_hash(graph, "shot")
    graph["nodes"][0]["data"]["config"].update(asset_id=12, _reused_definition_hash=original)
    assert gateway._definition_hash(graph, "shot") == original


@pytest.mark.parametrize("parameters", [
    {"node_ids": ["first"], "target_node_ids": ["second"]},
    {"node_id": "first", "screenplay_node_id": "second"},
])
def test_conflicting_scope_aliases_are_rejected(stage_state, parameters):
    with pytest.raises(HTTPException) as failure:
        execute(stage_state, **parameters)
    assert failure.value.status_code == 422
    assert stage_state.planned == []


def test_resplit_marks_old_storyboard_and_video_stale(stage_state, monkeypatch):
    stage_state.graph["nodes"] = [
        node("script", "screenplay", content="当前剧本"),
        node("scene", "scene", source_screenplay_node="script", director_plan={"old": True}, director_plan_hash="old"),
        node("image", source_scene_node="scene"),
        node("video", "video", source_scene_node="scene"),
    ]

    async def split(*args):
        return {"units": [{"scene_id": "new"}], "content_hash": "current", "truncated": False}

    monkeypatch.setattr(api, "screenplay_split", split)
    execute(stage_state, stage="split", screenplay_node_id="script")
    nodes = {item["id"]: item["data"]["config"] for item in stage_state.saved[0]["nodes"]}
    assert nodes["image"]["stale"] is True
    assert nodes["video"]["stale"] is True
    assert "director_plan" not in nodes["scene"]


@pytest.mark.parametrize("stage", ["images", "videos", "concat"])
def test_changed_screenplay_blocks_old_generated_nodes(stage_state, stage):
    stage_state.graph["nodes"] = [
        node("script", "screenplay", content="新版剧本"),
        node("scene", "scene", source_screenplay_node="script", source_content="旧版剧本", director_plan_hash="same"),
        node("result", "image" if stage == "images" else "video", source_scene_node="scene", director_plan_hash="same", asset_id=10),
    ]
    with pytest.raises(HTTPException) as failure:
        execute(stage_state, stage=stage, target_node_ids=["result"])
    assert failure.value.status_code == 409
    assert stage_state.planned == []


def _scene_graph(approved):
    return {"nodes": [
        node("script", "screenplay", content="剧本"),
        node("scene-1", "scene", approved=approved, scenes=[{"scene_id": "a"}], source_screenplay_node="script"),
    ], "edges": []}


def _fake_director(monkeypatch):
    async def director(canvas_id, body, request, db):
        return {"plan": {"units": []}, "plan_hash": "h", "unit_count": 0}

    monkeypatch.setattr(api, "create_director_plan", director)


def test_auto_mode_approves_unapproved_scene_and_persists_before_director(stage_state, monkeypatch):
    stage_state.graph = _scene_graph(False)
    _fake_director(monkeypatch)
    result = execute(stage_state, stage="director", scene_node_id="scene-1", auto_approve_scenes=True)
    assert result["next_stage"] == "assets"
    scene = next(n for n in stage_state.saved[0]["nodes"] if n["id"] == "scene-1")
    assert scene["data"]["config"]["approved"] is True
    assert scene["data"]["config"]["approved_by"] == "agent_auto"


@pytest.mark.parametrize("stage", ["images", "videos", "concat"])
def test_auto_mode_never_submits_generation_stages(stage_state, stage):
    with pytest.raises(HTTPException) as failure:
        execute(stage_state, stage=stage, auto_approve_scenes=True)
    assert failure.value.status_code == 409
    assert stage_state.planned == []
    assert stage_state.saved == []


def test_non_auto_mode_still_requires_manual_scene_approval(stage_state, monkeypatch):
    stage_state.graph = _scene_graph(False)
    _fake_director(monkeypatch)
    with pytest.raises(HTTPException) as failure:
        execute(stage_state, stage="director", scene_node_id="scene-1")
    assert failure.value.status_code == 409
    assert stage_state.saved == []


def test_browser_snapshot_with_unsaved_approval_is_synced_before_director(stage_state, monkeypatch):
    stage_state.graph = _scene_graph(False)
    _fake_director(monkeypatch)
    asyncio.run(gateway.execute_agent_canvas_stage(
        1, "director", {"agent_action_id": 7, "expected_definition_revision": 3, "scene_node_id": "scene-1"},
        SimpleNamespace(), stage_state.db, graph_snapshot=_scene_graph(True),
    ))
    synced = next(n for n in stage_state.saved[0]["nodes"] if n["id"] == "scene-1")
    assert synced["data"]["config"]["approved"] is True
    assert "approved_by" not in synced["data"]["config"]


def _assets_state(stage_state, monkeypatch, *, locked, profile_edited=False):
    stage_state.graph = _scene_graph(True)
    stage_state.graph["nodes"].append(node("hero", "image", asset_role="character", asset_name="林晚", asset_scene_node="scene-1", prompt="旧提示词", asset_id=42, locked=locked, profile="旧档案", profile_edited=profile_edited))

    async def analyze(canvas_id, body, request, db):
        return {"assets": [{"role": "character", "name": "林晚", "prompt": "新提示词", "scene_ids": ["a"], "profile": "新档案"}], "warnings": [], "failed_calls": 0}

    monkeypatch.setattr(api, "analyze_canvas_assets", analyze)
    execute(stage_state, stage="assets", scene_node_id="scene-1")
    return next(n for n in stage_state.saved[0]["nodes"] if n["id"] == "hero")["data"]["config"]


def test_locked_character_keeps_asset_and_prompt_on_reanalysis(stage_state, monkeypatch):
    config = _assets_state(stage_state, monkeypatch, locked=True)
    assert config["asset_id"] == 42 and config["prompt"] == "旧提示词"


def test_unlocked_character_is_refreshed_and_profile_stored(stage_state, monkeypatch):
    config = _assets_state(stage_state, monkeypatch, locked=False)
    assert "asset_id" not in config and config["prompt"] == "新提示词" and config["profile"] == "新档案"


def test_user_edited_profile_is_not_overwritten(stage_state, monkeypatch):
    config = _assets_state(stage_state, monkeypatch, locked=False, profile_edited=True)
    assert config["profile"] == "旧档案"


def test_locked_node_ignores_explicit_regenerate(stage_state):
    stage_state.graph["nodes"] = [node("hero", "image", asset_id=5, locked=True), node("free", "image", asset_id=6)]
    execute(stage_state, stage="images", regenerate=True)
    saved = {n["id"]: n["data"]["config"] for n in stage_state.saved[0]["nodes"]}
    assert saved["hero"].get("asset_id") == 5 and "asset_id" not in saved["free"]


def test_assets_are_laid_out_in_columns_by_kind_below_the_scene(stage_state, monkeypatch):
    stage_state.graph = _scene_graph(True)
    stage_state.graph["nodes"][1]["position"] = {"x": 1000, "y": 200}

    async def analyze(canvas_id, body, request, db):
        assets = [{"role": "character", "name": f"角色{i}", "prompt": "p", "scene_ids": ["a"]} for i in range(5)]
        assets += [{"role": "scene", "name": "宴会厅", "prompt": "p", "scene_ids": ["a"]}, {"role": "prop", "name": "工牌", "prompt": "p", "scene_ids": ["a"]}]
        return {"assets": assets, "candidates": [{"role": "prop", "name": "售货机", "scene_ids": ["a"], "desc": "d"}], "warnings": [], "failed_calls": 0}

    monkeypatch.setattr(api, "analyze_canvas_assets", analyze)
    result = execute(stage_state, stage="assets", scene_node_id="scene-1")
    nodes = {n["data"]["config"].get("asset_name"): n for n in stage_state.saved[0]["nodes"] if n["data"]["config"].get("asset_role")}
    top = 200 + gateway.ASSET_BLOCK_GAP + 640
    # 资产只占两列：角色 5 个从左到右、从上到下排（2+2+1 共 3 行）
    assert nodes["角色0"]["position"] == {"x": 1000, "y": top}
    assert nodes["角色1"]["position"] == {"x": 1000 + gateway.ASSET_CELL_W, "y": top}
    assert nodes["角色4"]["position"] == {"x": 1000, "y": top + 2 * gateway.ASSET_CELL_H}
    # 场景段、道具段依次排在角色段下方（不再并排占第三、第四列）
    scene_y = top + 3 * gateway.ASSET_CELL_H + gateway.ASSET_KIND_GAP
    assert nodes["宴会厅"]["position"] == {"x": 1000, "y": scene_y}
    assert nodes["工牌"]["position"] == {"x": 1000, "y": scene_y + gateway.ASSET_CELL_H + gateway.ASSET_KIND_GAP}
    assert max(n["position"]["x"] for n in nodes.values()) + gateway.NODE_W <= 1000 + gateway.ASSET_COLUMNS * gateway.ASSET_CELL_W
    # 可选候选保存在场景节点上
    scene_config = next(n for n in stage_state.saved[0]["nodes"] if n["id"] == "scene-1")["data"]["config"]
    assert scene_config["asset_candidates"][0]["name"] == "售货机"
    assert result["candidate_count"] == 1


def test_existing_asset_nodes_keep_their_position_on_reanalysis(stage_state, monkeypatch):
    stage_state.graph = _scene_graph(True)
    hero = node("hero", "image", asset_role="character", asset_name="林晚", asset_scene_node="scene-1", prompt="p")
    hero["position"] = {"x": 7, "y": 9}
    stage_state.graph["nodes"].append(hero)

    async def analyze(canvas_id, body, request, db):
        return {"assets": [{"role": "character", "name": "林晚", "prompt": "p", "scene_ids": ["a"]}], "candidates": [], "warnings": [], "failed_calls": 0}

    monkeypatch.setattr(api, "analyze_canvas_assets", analyze)
    execute(stage_state, stage="assets", scene_node_id="scene-1")
    assert next(n for n in stage_state.saved[0]["nodes"] if n["id"] == "hero")["position"] == {"x": 7, "y": 9}


def test_changed_director_plan_blocks_old_video(stage_state):
    stage_state.graph["nodes"] = [
        node("scene", "scene", director_plan_hash="new"),
        node("result", "video", source_scene_node="scene", director_plan_hash="old"),
    ]
    with pytest.raises(HTTPException) as failure:
        execute(stage_state, stage="videos")
    assert failure.value.status_code == 409
    assert stage_state.planned == []


def test_video_stage_does_not_silently_generate_missing_image(stage_state):
    stage_state.graph = {"nodes": [node("image", prompt="未生成分镜"), node("video", "video", prompt="动作")], "edges": [
        {"id": "edge", "source": "image", "target": "video", "sourceHandle": "image", "targetHandle": "image"},
    ]}
    with pytest.raises(HTTPException) as failure:
        execute(stage_state, stage="videos", target_node_ids=["video"])
    assert failure.value.status_code == 422
    assert stage_state.planned == []


def test_same_definition_reuses_assets_but_upstream_edit_invalidates_cache():
    original = {"nodes": [node("character", prompt="红衣"), node("shot", prompt="站立")], "edges": [
        {"id": "edge", "source": "character", "target": "shot", "sourceHandle": "image", "targetHandle": "references"},
    ]}

    class Query:
        def __init__(self, values):
            self.values = values

        def filter(self, *args):
            return self

        def order_by(self, *args):
            return self

        def limit(self, *args):
            return self

        def all(self):
            return self.values

    run = SimpleNamespace(id=5, canvas_version_id=8)
    outputs = [SimpleNamespace(node_id="character", output_snapshot_json={"asset_id": 10}),
               SimpleNamespace(node_id="shot", output_snapshot_json={"asset_id": 11})]
    db = SimpleNamespace(
        query=lambda model: Query([run] if model is gateway.VideoCanvasRun else outputs),
        get=lambda model, identifier: SimpleNamespace(graph_json=original),
    )
    graph = deepcopy(original)
    gateway._reusable_outputs(graph, 1, db, set())
    assert graph["nodes"][1]["data"]["config"]["asset_id"] == 11
    graph["nodes"][0]["data"]["config"]["prompt"] = "蓝衣"
    gateway._reusable_outputs(graph, 1, db, set())
    assert all("asset_id" not in item["data"]["config"] for item in graph["nodes"])
    assert all("_reused_definition_hash" not in item["data"]["config"] for item in graph["nodes"])

    graph = deepcopy(original)
    gateway._reusable_outputs(graph, 1, db, set())
    gateway._reusable_outputs(graph, 1, db, {"character"})
    assert all("asset_id" not in item["data"]["config"] for item in graph["nodes"])


def test_concat_does_not_regenerate_images_behind_explicit_video_asset(stage_state):
    stage_state.graph = {"nodes": [node("image", prompt="尚未生成"), node("video", "video", asset_id=12)], "edges": [
        {"id": "edge", "source": "image", "target": "video", "sourceHandle": "image", "targetHandle": "image"},
    ]}
    with pytest.raises(HTTPException) as failure:
        execute(stage_state, stage="concat", target_node_ids=["video"])
    assert failure.value.status_code == 422
    assert stage_state.planned == []


def test_deleted_source_scene_is_not_treated_as_standalone_video(stage_state):
    stage_state.graph["nodes"] = [node("video", "video", source_scene_node="deleted")]
    with pytest.raises(HTTPException) as failure:
        execute(stage_state, stage="videos")
    assert failure.value.status_code == 409
    assert stage_state.planned == []


def test_editing_scene_beats_invalidates_unchanged_plan_hash(stage_state):
    script = node("script", "screenplay", content="当前剧本")
    scene = node("scene", "scene", source_screenplay_node="script", source_content="当前剧本",
                 approved=True, scenes=[{"scene_id": "a", "beats": ["原动作"]}], director_plan_hash="unchanged")
    movie = node("video", "video", source_scene_node="scene", director_plan_hash="unchanged")
    graph = {"nodes": [script, scene, movie], "edges": []}
    _, screenplay_hash, scene_hash = api._scene_screenplay_hashes(graph, scene["data"]["config"], "scene")
    scene["data"]["config"]["director_plan"] = {"meta": {
        "source_screenplay_hash": screenplay_hash, "source_scene_revision": scene_hash,
    }}
    scene["data"]["config"]["scenes"][0]["beats"] = ["用户修改的动作"]
    stage_state.graph = graph
    with pytest.raises(HTTPException) as failure:
        execute(stage_state, stage="videos")
    assert failure.value.status_code == 409
    assert stage_state.planned == []


def test_asset_binding_rebuild_removes_obsolete_automatic_refs_but_keeps_manual():
    graph = {"nodes": [
        node("asset", asset_role="scene", asset_name="房间", scene_ids=["a"]),
        node("manual", asset_role="scene", asset_name="参考", scene_ids=[]),
        node("shot", node_role="storyboard", source_scene_ids=["a"]),
    ], "edges": [{"id": "manual-edge", "source": "manual", "target": "shot", "sourceHandle": "image", "targetHandle": "references"}]}
    gateway._bind_assets(graph)
    assert len(graph["edges"]) == 2
    graph["nodes"][0]["data"]["config"]["scene_ids"] = ["other-scene"]
    gateway._bind_assets(graph)
    assert [edge["id"] for edge in graph["edges"]] == ["manual-edge"]


def test_rebinding_identical_assets_keeps_output_cache_valid():
    graph = {"nodes": [
        node("asset", asset_role="scene", asset_name="房间", scene_ids=["a"]),
        node("shot", node_role="storyboard", source_scene_ids=["a"]),
    ], "edges": []}
    gateway._bind_assets(graph)
    fingerprint = gateway._definition_hash(graph, "shot")
    gateway._bind_assets(graph)
    assert gateway._definition_hash(graph, "shot") == fingerprint


@pytest.mark.parametrize("stage,model_key,kind", [("images", "image_model_id", "image"), ("videos", "video_model_id", "video")])
def test_explicit_generation_settings_update_only_selected_node(stage_state, stage, model_key, kind):
    stage_state.graph["nodes"] = [
        node("first", kind, model_id=1, aspect_ratio="16:9", asset_id=10),
        node("second", kind, model_id=1, aspect_ratio="16:9", asset_id=11),
    ]
    execute(stage_state, stage=stage, target_node_ids=["second"], aspect_ratio="9:16", **{model_key: 2})
    first, second = [item["data"]["config"] for item in stage_state.saved[0]["nodes"]]
    assert first == {"model_id": 1, "aspect_ratio": "16:9", "asset_id": 10}
    assert second["model_id"] == 2
    assert second["aspect_ratio"] == "9:16"
    assert "asset_id" not in second


@pytest.mark.parametrize("parameters", [{"image_model_id": 2}, {"aspect_ratio": "9:16"}])
def test_changing_either_model_or_aspect_invalidates_old_asset(stage_state, parameters):
    stage_state.graph["nodes"] = [node("first", model_id=1, aspect_ratio="16:9", asset_id=10)]
    execute(stage_state, target_node_ids=["first"], **parameters)
    assert "asset_id" not in stage_state.saved[0]["nodes"][0]["data"]["config"]


def test_reaffirming_identical_generation_settings_keeps_asset(stage_state):
    stage_state.graph["nodes"] = [node("first", model_id=1, aspect_ratio="16:9", asset_id=10)]
    execute(stage_state, image_model_id=1, aspect_ratio="16:9")
    assert stage_state.saved[0]["nodes"][0]["data"]["config"]["asset_id"] == 10


@pytest.fixture
def run_creation_state(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    VideoCanvasRun.__table__.create(engine)
    VideoCanvasRunNode.__table__.create(engine)
    graph = {"nodes": [node("first", prompt="镜头一"), node("second", prompt="镜头二")], "edges": []}
    state = SimpleNamespace(
        graph=graph, locks=[], canvas=SimpleNamespace(id=1, story_id=1, definition_revision=3, default_chapter_id=None),
    )

    def lock(canvas_id, user, db):
        state.locks.append(canvas_id)
        return state.canvas

    monkeypatch.setattr(api, "_require_user", lambda *args: SimpleNamespace(id=9))
    monkeypatch.setattr(api, "_lock_canvas", lock)
    monkeypatch.setattr(api, "_latest_version", lambda *args: SimpleNamespace(id=8, graph_json=state.graph))
    monkeypatch.setattr(api, "_run_target_chapter_id", lambda *args: None)
    with Session(engine) as db:
        state.db = db
        yield state
    engine.dispose()


def existing_run(state, status, resolved_ids, key="canvas-agent-action:old"):
    run = VideoCanvasRun(
        canvas_id=1, canvas_version_id=8, status=status, requested_by_user_id=9,
        idempotency_key=key, scope_json={"resolved_node_ids": resolved_ids}, plan_json={"topological_order": resolved_ids},
    )
    state.db.add(run)
    state.db.commit()
    return run


def create_run(state, targets, key="canvas-agent-action:new"):
    return asyncio.run(api.create_video_canvas_run(
        1, VideoCanvasRunRequest(target_node_ids=targets, expected_definition_revision=3, idempotency_key=key),
        SimpleNamespace(), state.db,
    ))


@pytest.mark.parametrize("status", ["queued", "running", "awaiting_approval"])
def test_new_action_cannot_duplicate_active_generation_node(run_creation_state, status):
    state = run_creation_state
    original = existing_run(state, status, ["first"])
    with pytest.raises(HTTPException) as failure:
        create_run(state, ["first"])
    assert failure.value.status_code == 409
    assert failure.value.detail["run_id"] == original.id
    assert state.db.query(VideoCanvasRun).count() == 1
    assert state.locks == [1]


def test_overlap_guard_checks_generated_ancestors_not_only_targets(run_creation_state):
    state = run_creation_state
    state.graph["nodes"][1]["type"] = "video"
    state.graph["edges"] = [{"id": "reference", "source": "first", "target": "second", "sourceHandle": "image", "targetHandle": "image"}]
    existing_run(state, "running", ["first"])
    with pytest.raises(HTTPException) as failure:
        create_run(state, ["second"])
    assert failure.value.status_code == 409
    assert state.db.query(VideoCanvasRun).count() == 1


@pytest.mark.parametrize("status", ["succeeded", "failed", "cancelled"])
def test_terminal_run_does_not_block_new_authorized_action(run_creation_state, status):
    state = run_creation_state
    existing_run(state, status, ["first"])
    result = create_run(state, ["first"])
    assert result["run"]["status"] == "awaiting_approval"
    assert state.db.query(VideoCanvasRun).count() == 2
    assert state.locks == [1]


def test_same_action_returns_existing_run_without_duplicate(run_creation_state):
    state = run_creation_state
    original = existing_run(state, "running", ["first"], key="canvas-agent-action:same")
    result = create_run(state, ["first"], key="canvas-agent-action:same")
    assert result["idempotent"] is True
    assert result["run"]["id"] == original.id
    assert state.db.query(VideoCanvasRun).count() == 1


def test_independent_nodes_can_generate_with_shared_static_context(run_creation_state):
    state = run_creation_state
    state.graph["nodes"].append(node("text", "text", content="公共上下文"))
    state.graph["edges"] = [
        {"id": identifier, "source": "text", "target": target, "sourceHandle": "text", "targetHandle": "prompt"}
        for identifier, target in [("a", "first"), ("b", "second")]
    ]
    existing_run(state, "running", ["text", "first"])
    result = create_run(state, ["second"])
    assert result["run"]["status"] == "awaiting_approval"
    assert state.db.query(VideoCanvasRun).count() == 2


# ── 目标总时长预算 ────────────────────────────────────────

def test_screenplay_stage_rejects_script_far_longer_than_target_duration(stage_state):
    """60 秒只是参考，合理上限 120 秒；852 字的剧本约 150 秒，超过上限必须在剧本阶段拦下并告知字数预算。"""
    long_script = "林夏把煎蛋翻面，蛋边焦卷。" * 70
    with pytest.raises(HTTPException) as error:
        execute(stage_state, stage="screenplay", content=long_script, user_constraints="日式动漫风。时长约60秒，16:9横屏。开场3秒内出现悬念。")
    assert error.value.status_code == 422
    assert "合理时长上限 120 秒" in str(error.value.detail) and "672 字" in str(error.value.detail)
    assert stage_state.saved == [], "被拒绝的剧本不能落库"


def test_screenplay_stage_allows_script_longer_than_reference_within_ceiling(stage_state):
    """参考 60 秒、剧本约 90 秒（在 2 倍上限内）：故事讲完整优先，不拦。"""
    script = "林夏把煎蛋翻面，蛋边焦卷。" * 40
    execute(stage_state, stage="screenplay", content=script, user_constraints="时长约60秒")
    assert stage_state.saved[0]["metadata"]["production_settings"]["target_duration_seconds"] == 60


def test_screenplay_stage_accepts_script_within_budget_and_records_target(stage_state):
    short_script = "场景1：厨房\n林夏翻动煎蛋。\n林夏：又是双黄的。\n" * 8
    execute(stage_state, stage="screenplay", content=short_script, user_constraints="时长约60秒")
    settings = stage_state.saved[0]["metadata"]["production_settings"]
    assert settings["target_duration_seconds"] == 60


def test_screenplay_stage_without_target_duration_keeps_old_behaviour(stage_state):
    execute(stage_state, stage="screenplay", content="很长的剧本" * 300, user_constraints="日式动漫风，开场3秒内出现冲突，每10到15秒一次反转")
    assert "target_duration_seconds" not in stage_state.saved[0]["metadata"]["production_settings"]
