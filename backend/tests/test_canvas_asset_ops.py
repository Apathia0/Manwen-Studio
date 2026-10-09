import copy

from routers.video_canvas import NODE_CATALOG, _validate_graph
from services.agent_service import _apply_canvas_ops_to_graph, _describe_applied_ops
from services.canvas_agent_digest import describe_canvas_digest
from services.canvas_asset_ops import build_asset_operations


def _graph():
    scene = {
        "id": "scene-1", "type": "scene", "position": {"x": 0, "y": 0},
        "data": {"label": "剧本场景", "ui": {"width": 1280, "height": 800}, "config": {
            "approved": True, "scenes": [],
            "asset_candidates": [
                {"name": "剑", "role": "prop", "desc": "三尺青锋，剑身有符文", "scene_ids": ["3"]},
                {"name": "书", "role": "prop", "desc": "线装书", "scene_ids": ["1"]},
                {"name": "金", "role": "prop", "desc": "金锭", "scene_ids": ["2"]},
            ],
        }},
    }
    ning = {
        "id": "image-ning", "type": "image", "position": {"x": 1700, "y": 0},
        "data": {"label": "宁采臣", "config": {"node_role": "asset", "asset_role": "character", "asset_name": "宁采臣", "asset_scene_node": "scene-1"}},
    }
    gold = {
        "id": "image-gold", "type": "image", "position": {"x": 2200, "y": 0},
        "data": {"label": "道具·金", "config": {"node_role": "asset", "asset_role": "prop", "asset_name": "金", "asset_scene_node": "scene-1"}},
    }
    board = {
        "id": "board-4", "type": "image", "position": {"x": 3000, "y": 0},
        "data": {"label": "分镜4", "config": {"node_role": "storyboard", "prompt": "燕赤霞横剑挡门，剑光破夜，宁采臣后退", "source_scene_ids": ["3"]}},
    }
    movie = {
        "id": "video-4", "type": "video", "position": {"x": 3500, "y": 0},
        "data": {"label": "视频4", "config": {"unit_id": "u4", "video_prompt": "剑斩黑雾", "source_scene_ids": ["3"]}},
    }
    return {"nodes": [scene, ning, gold, board, movie], "edges": [], "metadata": {"production_settings": {"aspect_ratio": "16:9"}}}


def test_adds_candidate_asset_with_node_and_bindings():
    built = build_asset_operations(_graph(), [{"name": "剑"}])

    assert [item["name"] for item in built["added"]] == ["剑"]
    node_ops = [op for op in built["operations"] if op["op"] == "add_node"]
    assert len(node_ops) == 1
    config = node_ops[0]["node"]["data"]["config"]
    assert config["asset_role"] == "prop" and config["asset_scene_node"] == "scene-1"
    assert config["scene_ids"] == ["3"]
    assert "三尺青锋" in config["prompt"]
    # 分镜 4 与视频 4 的文字都提到「剑」，应各连一条
    edges = [op["edge"] for op in built["operations"] if op["op"] == "add_edge"]
    targets = {(edge["target"], edge["targetHandle"]) for edge in edges}
    assert targets == {("board-4", "references"), ("video-4", "image")}
    assert all(edge["data"]["agent_asset_binding"] for edge in edges)
    assert built["added"][0]["linked_shots"] == 2


def test_skips_existing_unknown_and_roleless_assets():
    built = build_asset_operations(_graph(), [{"name": "金"}, {"name": "老妖"}, {"name": "宁采臣", "role": "character"}])

    assert built["added"] == []
    assert built["operations"] == []
    reasons = {item["name"]: item["reason"] for item in built["skipped"]}
    assert "已有" in reasons["金"]
    assert "role" in reasons["老妖"]
    assert "已有" in reasons["宁采臣"]


def test_adds_new_character_with_explicit_role_and_places_below_same_column():
    graph = _graph()
    built = build_asset_operations(graph, [{"name": "燕赤霞", "role": "角色", "description": "中年道士，青衫，背负长剑"}])

    node = next(op["node"] for op in built["operations"] if op["op"] == "add_node")
    assert node["data"]["config"]["asset_role"] == "character"
    assert "中年道士" in node["data"]["config"]["prompt"]
    existing = next(n for n in graph["nodes"] if n["id"] == "image-ning")
    # 与同类已有角色同一列，且排在其下方
    assert node["position"]["x"] == existing["position"]["x"]
    assert node["position"]["y"] > existing["position"]["y"]


def test_operations_apply_cleanly_and_graph_stays_valid():
    graph = _graph()
    built = build_asset_operations(graph, [{"name": "剑"}, {"name": "书"}])

    merged, errors = _apply_canvas_ops_to_graph(copy.deepcopy(graph), built["operations"], NODE_CATALOG)

    assert errors == []
    assert _validate_graph(merged)["errors"] == []
    assert len(merged["nodes"]) == len(graph["nodes"]) + 2
    # 连线上的 agent_asset_binding 标记得以保留，之后资产阶段才能识别并重建
    bound = [e for e in merged["edges"] if (e.get("data") or {}).get("agent_asset_binding")]
    assert bound and all(e["source"].startswith("ast-scene-1-prop-") for e in bound)
    # 再来一次不会重复新增
    again = build_asset_operations(merged, [{"name": "剑"}, {"name": "书"}])
    assert again["operations"] == []


def test_requires_a_scene_node_and_non_empty_assets():
    assert "assets" in build_asset_operations(_graph(), [])["error"]
    assert "场景" in build_asset_operations({"nodes": [], "edges": []}, [{"name": "剑", "role": "prop"}])["error"]


def test_multiple_scene_nodes_pick_the_one_with_candidates_or_ask_for_id():
    only_one_has_candidates = _graph()
    only_one_has_candidates["nodes"].append({"id": "scene-2", "type": "scene", "position": {"x": 0, "y": 900}, "data": {"config": {}}})
    assert build_asset_operations(only_one_has_candidates, [{"name": "剑"}])["scene_node_id"] == "scene-1"

    both = copy.deepcopy(only_one_has_candidates)
    both["nodes"][-1]["data"]["config"]["asset_candidates"] = [{"name": "灯", "role": "prop"}]
    assert "scene_node_id" in build_asset_operations(both, [{"name": "剑"}])["error"]
    assert build_asset_operations(both, [{"name": "灯"}], "scene-2")["scene_node_id"] == "scene-2"


def test_digest_lists_progress_assets_and_missing_candidates():
    text = describe_canvas_digest(_graph())

    assert "阶段进度" in text
    assert "资产 2（已出图 0）" in text
    assert "宁采臣" in text and "image-ning" in text
    assert "「剑」" in text and "「书」" in text
    assert "「金」" not in text.split("候选资产：")[-1]
    assert "add_canvas_assets" in text
    assert describe_canvas_digest(None) == ""
    assert describe_canvas_digest({"nodes": [], "edges": []}) == ""


def test_describe_applied_ops_summarises_what_was_written():
    graph = _graph()
    built = build_asset_operations(graph, [{"name": "剑"}])
    args = {"operations": built["operations"] + [{"op": "update_node", "node_id": "x"}]}

    text = _describe_applied_ops("apply_canvas_ops", args)

    assert "新增节点 1 个" in text and "道具·剑" in text
    assert "新增连线 2 条" in text and "更新节点 1 个" in text
    assert _describe_applied_ops("canvas_stage", args) == ""


# ── 贯穿真实派发链路：ask 模式提案 → 批准 → 落库 ─────────────────────────────

def _env(monkeypatch, mode="ask"):
    import pytest as _pytest  # noqa: F401
    from types import SimpleNamespace
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from models import BackgroundTask, CanvasAgentAction, VideoCanvas, VideoCanvasRun, VideoCanvasVersion
    from services import agent_service
    from services import canvas_agent_actions as actions

    engine = create_engine("sqlite:///:memory:")
    for model in (VideoCanvas, VideoCanvasVersion, VideoCanvasRun, CanvasAgentAction, BackgroundTask):
        model.__table__.create(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(agent_service, "SessionLocal", factory)
    monkeypatch.setattr(actions, "SessionLocal", factory)
    with factory() as db:
        db.add(VideoCanvas(id=1, owner_user_id=2, story_id=3, name="测试画布", definition_revision=4))
        db.add(VideoCanvasVersion(canvas_id=1, version_no=4, graph_json=_graph(), source="manual"))
        db.commit()
    context = SimpleNamespace(
        workflow_type="video_canvas", workflow_id=1, story_id=3, enabled_skills=["video_canvas_workflow"],
        pending_change_key=SimpleNamespace(user_id=2, conversation_id=5), canvas_permission_mode=mode,
        canvas_executing_action_id=None, canvas_graph_snapshot=None, canvas_snapshot_consumed=False,
        canvas_graph_write_mode="server", pending_changes=None, canvas_expected_definition_revision=None,
    )
    monkeypatch.setattr(agent_service, "_current_run_context", lambda: context)
    return agent_service, actions, context, factory, engine


def test_ask_mode_single_proposal_then_approval_writes_nodes_and_edges(monkeypatch):
    import asyncio
    import json

    from models import VideoCanvas, VideoCanvasVersion

    agent_service, actions, context, factory, engine = _env(monkeypatch, "ask")
    try:
        first = json.loads(asyncio.run(agent_service.tool_registry.execute("add_canvas_assets", {"canvas_id": 1, "assets": [{"name": "剑"}]})))
        assert first["awaiting_approval"] is True
        assert [item["name"] for item in first["assets_report"]["added"]] == ["剑"]
        # 提案阶段不写画布
        with factory() as db:
            assert db.get(VideoCanvas, 1).definition_revision == 4
        # 同样的请求再来一次复用同一张卡片，不会堆出第二张
        again = json.loads(asyncio.run(agent_service.tool_registry.execute("add_canvas_assets", {"canvas_id": 1, "assets": [{"name": "剑"}]})))
        assert again["approval"]["id"] == first["approval"]["id"]

        action_id = first["approval"]["id"]
        tool, arguments = actions.claim_approval(context, action_id)
        assert tool == "apply_canvas_ops"
        context.canvas_executing_action_id = action_id
        done = json.loads(asyncio.run(agent_service.tool_registry.execute(tool, arguments)))
        assert done["ok"] is True and done["definition_revision"] == 5
        assert "新增节点 1 个" in _describe_applied_ops(tool, arguments)

        with factory() as db:
            latest = db.query(VideoCanvasVersion).filter(VideoCanvasVersion.canvas_id == 1).order_by(VideoCanvasVersion.version_no.desc()).first()
        labels = {n["data"].get("label") for n in latest.graph_json["nodes"]}
        assert "道具·剑" in labels
        assert len([e for e in latest.graph_json["edges"] if (e.get("data") or {}).get("agent_asset_binding")]) == 2
    finally:
        engine.dispose()


def test_auto_mode_executes_immediately_and_reports_noop_for_existing_assets(monkeypatch):
    import asyncio
    import json

    agent_service, actions, context, factory, engine = _env(monkeypatch, "auto")
    try:
        done = json.loads(asyncio.run(agent_service.tool_registry.execute("add_canvas_assets", {"canvas_id": 1, "assets": [{"name": "剑"}, {"name": "书"}]})))
        assert done["ok"] is True and done["definition_revision"] == 5
        assert len(done["assets_report"]["added"]) == 2
        # 已经建好：不再出卡片也不再写入，并如实说明跳过原因
        noop = json.loads(asyncio.run(agent_service.tool_registry.execute("add_canvas_assets", {"canvas_id": 1, "assets": [{"name": "剑"}]})))
        assert noop["no_change"] is True
        assert "已有" in noop["assets_report"]["skipped"][0]["reason"]
    finally:
        engine.dispose()


def test_tool_is_not_exposed_outside_canvas_workflow(monkeypatch):
    import asyncio
    import json

    agent_service, actions, context, factory, engine = _env(monkeypatch, "ask")
    try:
        context.workflow_type = "novel"
        denied = json.loads(asyncio.run(agent_service.tool_registry.execute("add_canvas_assets", {"canvas_id": 1, "assets": [{"name": "剑"}]})))
        assert denied.get("tool_denied") is True
    finally:
        engine.dispose()


# ── 角色资产分级：有名有姓且有台词的角色必须有资产 ───────────────────────────────

_TEXT = (
    "宁采臣：小倩，别怕。\n聂小倩：公子，我没有恶意。\n宁采臣：我信你。\n聂小倩：多谢公子。\n宁采臣：夜深了。\n"
    "燕赤霞：妖孽，休走！\n路人甲：那边怎么了？\n书生在门口站了一会儿，没有说话，只提到过陈老板一次。\n"
)


def test_named_character_with_a_single_line_is_a_main_character():
    from services.canvas_asset_analysis import split_characters

    names = ["宁采臣", "聂小倩", "燕赤霞", "路人甲", "陈老板"]
    main, minor, extras = split_characters(names, _TEXT)

    assert "燕赤霞" in main, "只有一句台词的有名角色也要建资产（后续集数还会出现）"
    assert extras == ["路人甲"]
    assert minor == ["陈老板"], "有名字但没台词、几乎没出场：进可选资产而不是丢弃"
    assert {"宁采臣", "聂小倩"} <= set(main)


def test_overflow_beyond_the_cap_goes_to_minor_not_lost():
    from services import canvas_asset_analysis as analysis

    names = [f"角色{chr(0x4e00 + i)}" for i in range(analysis.MAX_MAIN_CHARACTERS + 3)]
    text = "\n".join(f"{name}：台词。" for name in names)

    main, minor, extras = analysis.split_characters(names, text)

    assert len(main) == analysis.MAX_MAIN_CHARACTERS
    assert len(minor) == 3 and extras == []
    assert set(main) | set(minor) == set(names)


def test_analysis_builds_asset_for_speaking_character_and_lists_minor_as_candidate(monkeypatch):
    import asyncio

    from services import canvas_asset_analysis as analysis
    from services import video_canvas_director as director

    async def fake_triage(**kwargs):
        return {"characters": [{"name": "燕赤霞", "profile": "中年道士，青衫，背负长剑"}], "scenes": [], "props": [], "optional": []}

    async def fake_prompts(shot_data, profiles, api_key):
        return [{"name": name, "prompt": f"{name}的外貌"} for name in shot_data["characters"]]

    monkeypatch.setattr(director, "_call_deepseek_json", fake_triage)
    monkeypatch.setattr(analysis, "generate_character_prompts", fake_prompts)
    scenes = [
        {"scene_id": "1", "location": "兰若寺", "characters": ["宁采臣", "聂小倩", "陈老板"], "beats": []},
        {"scene_id": "3", "location": "西厢房", "characters": ["燕赤霞", "宁采臣", "路人甲"], "beats": []},
    ]

    result = asyncio.run(analysis.analyze_scene_assets(scenes=scenes, screenplay_text=_TEXT))

    built = {(a["role"], a["name"]) for a in result["assets"]}
    assert ("character", "燕赤霞") in built and ("character", "宁采臣") in built
    assert ("character", "路人甲") not in built
    candidates = {(c["role"], c["name"]): c for c in result["candidates"]}
    assert ("character", "陈老板") in candidates and candidates[("character", "陈老板")]["scene_ids"] == ["1"]
    assert any("路人甲" in w for w in result["warnings"]) and any("陈老板" in w for w in result["warnings"])


def test_manually_added_assets_are_flagged_so_reanalysis_keeps_them():
    built = build_asset_operations(_graph(), [{"name": "剑"}])
    config = next(op["node"]["data"]["config"] for op in built["operations"] if op["op"] == "add_node")
    assert config["manual_added"] is True


def test_named_character_in_several_scenes_is_main_even_without_lines():
    from services.canvas_asset_analysis import split_characters

    text = "顾沉捡起工牌。陈磊把工牌摔在地上。"
    main, minor, _ = split_characters(["顾沉", "陈磊"], text, {"顾沉": 3, "陈磊": 2})
    assert "陈磊" in main and minor == []
    # 只在一个分场露脸、没台词、只提到一次：进可选资产
    main, minor, _ = split_characters(["顾沉", "陈磊"], text, {"顾沉": 3, "陈磊": 1})
    assert minor == ["陈磊"]
