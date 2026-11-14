"""画布 Agent 改动预览、提案作废、自动模式强制预览与节点定位的回归测试。"""

import asyncio
import json
import copy
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models import BackgroundTask, CanvasAgentAction, VideoCanvas, VideoCanvasRun
from services import canvas_agent_actions as actions
from services.agent_service import _apply_canvas_ops_to_graph
from services.canvas_ops_preview import (
    build_ops_preview,
    describe_selected_nodes,
    diff_graphs,
    node_fingerprint,
    operations_overwrite_existing,
)


def _graph():
    return {
        "nodes": [
            {"id": "img-1", "type": "image", "position": {"x": 0, "y": 0}, "data": {"label": "分镜一", "config": {"prompt": "少女站在天台", "duration": 5}}},
            {"id": "img-2", "type": "image", "position": {"x": 300, "y": 0}, "data": {"label": "分镜一", "config": {"prompt": "夜晚的街道"}}},
        ],
        "edges": [{"id": "e1", "source": "img-1", "target": "img-2", "sourceHandle": None, "targetHandle": None}],
    }


def test_diff_graphs_reports_field_level_before_after():
    before = _graph()
    after = copy.deepcopy(before)
    after["nodes"][0]["data"]["config"]["prompt"] = "少女站在天台，赛璐璐厚涂风格"
    after["nodes"][0]["position"] = {"x": 99, "y": 99}  # 仅位置变化不应算内容变更
    diff = diff_graphs(before, after)
    assert diff["summary"]["updated_nodes"] == 1
    item = diff["nodes"][0]
    assert item["node_id"] == "img-1" and item["label"] == "分镜一"
    assert item["changes"] == [{
        "field": "data.config.prompt",
        "before": "少女站在天台",
        "after": "少女站在天台，赛璐璐厚涂风格",
    }]


def test_diff_graphs_detects_add_delete_nodes_and_edges():
    before = _graph()
    after = copy.deepcopy(before)
    after["nodes"] = [after["nodes"][0], {"id": "vid-1", "type": "video", "data": {"label": "视频", "config": {"prompt": "镜头推进"}}}]
    after["edges"] = [{"id": "e2", "source": "img-1", "target": "vid-1"}]
    diff = diff_graphs(before, after)
    assert diff["summary"] == {"added_nodes": 1, "updated_nodes": 0, "deleted_nodes": 1, "added_edges": 1, "deleted_edges": 1}
    assert {item["op"] for item in diff["nodes"]} == {"add_node", "delete_node"}


def test_build_ops_preview_applies_on_copy_and_reports_invalid_ops():
    base = _graph()
    snapshot = copy.deepcopy(base)
    preview = build_ops_preview(base, [{"op": "update_node", "node_id": "img-2", "config": {"prompt": "夜晚的街道，霓虹光影"}}])
    assert base == snapshot, "预览不能修改基图"
    assert preview["errors"] == []
    assert preview["nodes"][0]["changes"][0]["after"] == "夜晚的街道，霓虹光影"
    bad = build_ops_preview(base, [{"op": "update_node", "node_id": "missing", "config": {"prompt": "x"}}])
    assert bad["errors"]


def test_operations_overwrite_existing_only_flags_update_and_delete():
    assert operations_overwrite_existing([{"op": "update_node", "node_id": "a", "config": {"prompt": "x"}}])
    assert operations_overwrite_existing([{"op": "delete_node", "node_id": "a"}])
    assert not operations_overwrite_existing([{"op": "add_node", "node": {"type": "image"}}, {"op": "add_edge", "edge": {}}])
    assert not operations_overwrite_existing([{"op": "update_node", "node_id": "a"}])


def test_fingerprint_ignores_position_and_detects_content_change():
    graph = _graph()
    node = graph["nodes"][0]
    original = node_fingerprint(node)
    node["position"] = {"x": 5, "y": 5}
    assert node_fingerprint(node) == original
    node["data"]["config"]["prompt"] = "改过了"
    assert node_fingerprint(node) != original


def test_update_node_rejects_stale_fingerprint():
    from routers.video_canvas import NODE_CATALOG

    graph = _graph()
    stale = node_fingerprint(graph["nodes"][0])
    graph["nodes"][0]["data"]["config"]["prompt"] = "用户刚手动改过"
    _, errors = _apply_canvas_ops_to_graph(
        graph,
        [{"op": "update_node", "node_id": "img-1", "expected_fingerprint": stale, "config": {"prompt": "助手覆盖"}}],
        NODE_CATALOG,
    )
    assert errors and "已被改动" in errors[0]
    assert graph["nodes"][0]["data"]["config"]["prompt"] == "用户刚手动改过"
    # 指纹一致时正常应用
    fresh = node_fingerprint(graph["nodes"][0])
    _, errors = _apply_canvas_ops_to_graph(
        graph,
        [{"op": "update_node", "node_id": "img-1", "expected_fingerprint": fresh, "config": {"prompt": "助手覆盖"}}],
        NODE_CATALOG,
    )
    assert errors == [] and graph["nodes"][0]["data"]["config"]["prompt"] == "助手覆盖"


def test_describe_selected_nodes_includes_full_config_and_neighbors():
    text = describe_selected_nodes(_graph(), ["img-2", "ghost"])
    assert "img-2" in text and "夜晚的街道" in text
    assert "分镜一（image，img-1）" in text  # 上游邻居
    assert "ghost" not in text
    assert describe_selected_nodes(_graph(), []) == ""


# ── 提案流程 ──────────────────────────────────────────────

@pytest.fixture
def state(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    for model in (VideoCanvas, VideoCanvasRun, CanvasAgentAction, BackgroundTask):
        model.__table__.create(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(actions, "SessionLocal", factory)
    with factory() as db:
        db.add(VideoCanvas(id=1, owner_user_id=2, story_id=3, name="测试画布", definition_revision=4))
        db.commit()
    context = SimpleNamespace(
        pending_change_key=SimpleNamespace(user_id=2, conversation_id=5),
        workflow_id=1, story_id=3, canvas_permission_mode="ask",
        canvas_executing_action_id=None,
        canvas_graph_snapshot=_graph(), canvas_snapshot_consumed=False,
    )
    yield context, factory
    engine.dispose()


def _ops_args(prompt):
    return {
        "canvas_id": 1,
        "operations": [{"op": "update_node", "node_id": "img-1", "config": {"prompt": prompt}}],
        "expected_definition_revision": 4,
    }


def _forbidden():
    async def inner():
        pytest.fail("待审阅的提案不应执行")
    return inner


def test_ask_proposal_carries_field_level_preview(state):
    context, _ = state
    result = asyncio.run(actions.execute_action(context, "apply_canvas_ops", _ops_args("新提示词"), _forbidden()))
    preview = result["approval"]["preview"]
    assert preview["summary"]["updated_nodes"] == 1
    assert preview["nodes"][0]["changes"][0] == {"field": "data.config.prompt", "before": "少女站在天台", "after": "新提示词"}


def test_changed_operations_supersede_old_pending_proposal(state):
    context, factory = state
    first = asyncio.run(actions.execute_action(context, "apply_canvas_ops", _ops_args("第一版"), _forbidden()))
    second = asyncio.run(actions.execute_action(context, "apply_canvas_ops", _ops_args("用户追加要求后的第二版"), _forbidden()))
    assert first["approval"]["id"] != second["approval"]["id"]
    assert second["approval"]["preview"]["nodes"][0]["changes"][0]["after"] == "用户追加要求后的第二版"
    with factory() as db:
        statuses = {row.id: row.status for row in db.query(CanvasAgentAction).all()}
    assert statuses[first["approval"]["id"]] == "superseded"
    assert statuses[second["approval"]["id"]] == "pending"


def test_identical_operations_still_reuse_pending_proposal(state):
    context, factory = state
    first = asyncio.run(actions.execute_action(context, "apply_canvas_ops", _ops_args("同一版"), _forbidden()))
    second = asyncio.run(actions.execute_action(context, "apply_canvas_ops", _ops_args("同一版"), _forbidden()))
    assert first["approval"]["id"] == second["approval"]["id"]
    with factory() as db:
        assert db.query(CanvasAgentAction).count() == 1


def test_auto_mode_forces_preview_when_overwriting_existing_node(state):
    context, _ = state
    context.canvas_permission_mode = "auto"
    result = asyncio.run(actions.execute_action(context, "apply_canvas_ops", _ops_args("自动模式也要先预览"), _forbidden()))
    assert result["awaiting_approval"] is True
    assert result["approval"]["permission_mode"] == "auto"


def test_auto_mode_executes_pure_additions_without_review(state):
    context, _ = state
    context.canvas_permission_mode = "auto"
    calls = []

    async def perform():
        calls.append(1)
        return {"ok": True}

    args = {
        "canvas_id": 1,
        "operations": [{"op": "add_node", "node": {"type": "image", "data": {"label": "新增", "config": {"prompt": "x"}}}}],
        "expected_definition_revision": 4,
    }
    result = asyncio.run(actions.execute_action(context, "apply_canvas_ops", args, perform))
    assert result == {"ok": True} and calls == [1]


def test_invalid_operations_are_rejected_before_creating_proposal(state):
    context, factory = state
    args = {"canvas_id": 1, "operations": [{"op": "update_node", "node_id": "ghost", "config": {"prompt": "x"}}], "expected_definition_revision": 4}
    result = asyncio.run(actions.execute_action(context, "apply_canvas_ops", args, _forbidden()))
    assert "error" in result and "ghost" in result["error"]
    with factory() as db:
        assert db.query(CanvasAgentAction).count() == 0


# ── 审批时画布版本号漂移（发送前 flush 保存导致 +1） ─────────

@pytest.fixture
def drift_state(monkeypatch):
    from models import VideoCanvasVersion

    engine = create_engine("sqlite:///:memory:")
    for model in (VideoCanvas, VideoCanvasRun, CanvasAgentAction, BackgroundTask, VideoCanvasVersion):
        model.__table__.create(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(actions, "SessionLocal", factory)
    with factory() as db:
        db.add(VideoCanvas(id=1, owner_user_id=2, story_id=3, name="画布", definition_revision=4))
        db.add(VideoCanvasVersion(canvas_id=1, version_no=4, graph_json=_graph(), source="agent"))
        db.commit()
    context = SimpleNamespace(
        pending_change_key=SimpleNamespace(user_id=2, conversation_id=5),
        workflow_id=1, story_id=3, canvas_permission_mode="ask",
        canvas_executing_action_id=None, canvas_graph_snapshot=_graph(), canvas_snapshot_consumed=False,
    )
    yield context, factory
    engine.dispose()


def _propose(context, tool, args):
    async def forbidden():
        pytest.fail("不应执行")
    return asyncio.run(actions.execute_action(context, tool, args, forbidden))["approval"]["id"]


def _bump(factory, source, mutate=None):
    from models import VideoCanvasVersion

    with factory() as db:
        canvas = db.get(VideoCanvas, 1)
        graph = copy.deepcopy(_graph())
        if mutate:
            mutate(graph)
        canvas.definition_revision += 1
        db.add(VideoCanvasVersion(canvas_id=1, version_no=canvas.definition_revision, graph_json=graph, source=source))
        db.commit()


def test_stage_approval_survives_users_own_save_and_rebases_revision(drift_state):
    context, factory = drift_state
    stage_args = {"canvas_id": 1, "stage": "split", "summary": "拆分", "parameters": {"node_id": "img-1"}}
    action_id = _propose(context, "canvas_stage", stage_args)
    _bump(factory, "manual")  # 点击“同意”前 flush 保存产生的新版本
    tool, _ = actions.claim_approval(context, action_id)
    assert tool == "canvas_stage"
    with factory() as db:
        saved = db.get(CanvasAgentAction, action_id)
        assert saved.status == "executing" and saved.expected_definition_revision == 5


def test_stage_approval_rejected_and_superseded_when_agent_or_other_source_changed_canvas(drift_state):
    from fastapi import HTTPException

    context, factory = drift_state
    action_id = _propose(context, "canvas_stage", {"canvas_id": 1, "stage": "split", "summary": "拆分", "parameters": {"node_id": "img-1"}})
    _bump(factory, "agent")
    with pytest.raises(HTTPException, match="提案之后被修改"):
        actions.claim_approval(context, action_id)
    with factory() as db:
        assert db.get(CanvasAgentAction, action_id).status == "superseded"


def test_ops_approval_allowed_only_if_target_node_unchanged(drift_state):
    from fastapi import HTTPException

    context, factory = drift_state
    first = _propose(context, "apply_canvas_ops", _ops_args("新提示词"))
    _bump(factory, "manual")  # 目标节点内容没变
    assert actions.claim_approval(context, first)[0] == "apply_canvas_ops"

    context2, factory2 = drift_state
    with factory2() as db:
        db.query(CanvasAgentAction).delete()
        db.commit()
    second = _propose(context2, "apply_canvas_ops", {**_ops_args("再改一次"), "expected_definition_revision": 5})

    def edit_target(graph):
        graph["nodes"][0]["data"]["config"]["prompt"] = "用户手动改过目标节点"

    _bump(factory2, "manual", edit_target)
    with pytest.raises(HTTPException):
        actions.claim_approval(context2, second)


def test_graph_snapshot_keeps_canvas_level_settings():
    """快照是阶段写库的基图：画风/比例（metadata）和分组不能被清洗掉，否则助手每写一次就抹掉画风。"""
    from routers.agent_router import _sanitize_canvas_graph_snapshot

    payload = {
        "schema_version": 1,
        "nodes": [{"id": "a", "type": "image", "data": {}}],
        "edges": [],
        "groups": [{"id": "g1"}],
        "metadata": {"canvas_style": {"enabled": True, "style_snapshot": {"name": "写实电影感"}}, "production_settings": {"aspect_ratio": "9:16"}},
        "junk": "ignored",
    }
    result = _sanitize_canvas_graph_snapshot(payload)
    assert result["metadata"]["canvas_style"]["style_snapshot"]["name"] == "写实电影感"
    assert result["metadata"]["production_settings"]["aspect_ratio"] == "9:16"
    assert result["groups"] == [{"id": "g1"}] and result["schema_version"] == 1
    assert "junk" not in result
    # 类型不对的可选字段被丢弃而不是让整个快照失效
    assert "metadata" not in _sanitize_canvas_graph_snapshot({"nodes": [], "edges": [], "metadata": "bad"})


def test_resubmitting_already_executed_ops_returns_no_change_instead_of_new_card(state):
    """批准执行后模型又提交同样的改动：画布上已是目标内容，不能再弹确认卡片。"""
    context, factory = state
    applied = _graph()
    applied["nodes"][0]["data"]["config"]["prompt"] = "萧炎的手按在魔石碑上"
    context.canvas_graph_snapshot = applied
    result = asyncio.run(actions.execute_action(context, "apply_canvas_ops", _ops_args("萧炎的手按在魔石碑上"), _forbidden()))
    assert result["ok"] is True and result["no_change"] is True
    with factory() as db:
        assert db.query(CanvasAgentAction).count() == 0


def test_resubmitting_completed_stage_with_unchanged_canvas_is_reported_as_already_applied(state):
    context, factory = state
    stage_args = {"canvas_id": 1, "stage": "split", "summary": "拆分", "parameters": {"node_id": "script"}}
    with factory() as db:
        db.add(CanvasAgentAction(
            canvas_id=1, owner_user_id=2, conversation_id=5, permission_mode="ask", stage="split", tool_name="canvas_stage",
            summary="拆分", arguments_json={**stage_args, "summary": "换个说法"}, expected_definition_revision=3,
            status="completed", result_json={"ok": True, "definition_revision": 4},
        ))
        db.commit()
    result = asyncio.run(actions.execute_action(context, "canvas_stage", stage_args, _forbidden()))
    assert result["already_applied"] is True
    # 画布之后有变化（版本号前进）则视为新请求，正常出提案
    with factory() as db:
        db.get(VideoCanvas, 1).definition_revision = 6
        db.commit()
    again = asyncio.run(actions.execute_action(context, "canvas_stage", stage_args, _forbidden()))
    assert again["awaiting_approval"] is True


def test_large_canvas_graph_is_returned_as_overview_with_hint():
    from services.agent_service import _CANVAS_GRAPH_FULL_MAX_CHARS, _compact_canvas_graph

    graph = {"nodes": [{"id": f"n{i}", "type": "image", "data": {"label": f"分镜{i}", "config": {"prompt": "长提示词" * 200, "storyboard_json": {"segments": [1, 2]}}}} for i in range(20)], "edges": [{"id": "e", "source": "n0", "target": "n1"}]}
    assert len(json.dumps(graph, ensure_ascii=False)) > _CANVAS_GRAPH_FULL_MAX_CHARS
    compact = _compact_canvas_graph(graph)
    assert len(json.dumps(compact, ensure_ascii=False)) < _CANVAS_GRAPH_FULL_MAX_CHARS
    first = compact["nodes"][0]
    assert first["label"] == "分镜0" and first["config_preview"]["prompt"].endswith("…")
    assert "get_canvas_nodes" in first["config_preview"]["storyboard_json"]
    assert compact["edges"] == graph["edges"]


def test_internal_media_attachment_lines_are_hidden_from_history_and_api():
    """助手自动调取的画布媒体属于内部查看：历史里早期写入的记录行不展示、不再发给模型；用户自己上传的附件保留。"""
    import datetime

    from schemas import AgentConversationMessageOut, strip_internal_attachment_notes

    stored = (
        "剧本改写有问题，分镜1应该是萧炎的手\n\n"
        "[附件] 画布媒体观察[node=image-5357877cd7df4778 run=78 version=471 asset=309]（image）\n"
        "[附件] 画布媒体观察[node=image-8f5a3a160ae64993 run=75 version=470 asset=312]（image）\n"
        "[附件] 第2张漫画图（image）\n"
        "[附件] 参考图.png（image）"
    )
    cleaned = strip_internal_attachment_notes(stored)
    assert "画布媒体观察" not in cleaned and "第2张漫画图" not in cleaned
    assert cleaned.startswith("剧本改写有问题") and cleaned.endswith("[附件] 参考图.png（image）")
    assert strip_internal_attachment_notes("普通消息") == "普通消息"
    out = AgentConversationMessageOut(id=1, conversation_id=2, role="user", content=stored, created_at=datetime.datetime.now())
    assert "画布媒体观察" not in out.content
