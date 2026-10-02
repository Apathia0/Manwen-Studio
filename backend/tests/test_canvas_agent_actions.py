"""三种画布权限与阶段审批的数据库回归测试，不调用真实生成服务。"""

import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from models import BackgroundTask, CanvasAgentAction, VideoCanvas, VideoCanvasRun
from services import canvas_agent_actions as actions


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
    )
    yield context, factory
    engine.dispose()


def _args(content="第一版剧本"):
    return {"canvas_id": 1, "stage": "screenplay", "summary": "改编首集剧本", "parameters": {"content": content}}


@pytest.mark.parametrize("mode", ["ask", "plan"])
def test_review_modes_do_not_execute_until_exact_structured_approval(state, mode):
    context, factory = state
    context.canvas_permission_mode = mode
    calls = []

    async def perform():
        calls.append("executed")
        return {"ok": True}

    result = asyncio.run(actions.execute_action(context, "canvas_stage", _args(), perform))
    assert result["awaiting_approval"] is True and calls == []
    action_id = result["approval"]["id"]
    tool, arguments = actions.claim_approval(context, action_id)
    context.canvas_executing_action_id = action_id
    assert asyncio.run(actions.execute_action(context, tool, arguments, perform)) == {"ok": True}
    assert calls == ["executed"]
    with pytest.raises(HTTPException, match="已处理"):
        actions.claim_approval(context, action_id)


def test_auto_executes_and_persists_waiting_task(state):
    context, factory = state
    context.canvas_permission_mode = "auto"

    async def perform():
        assert context.canvas_executing_action_id
        return {"ok": True, "pending_task": {"canvas_id": 1, "run_id": 9, "status": "queued"}}

    result = asyncio.run(actions.execute_action(context, "canvas_stage", _args(), perform))
    with factory() as db:
        saved = db.query(CanvasAgentAction).one()
        assert saved.status == "waiting" and saved.result_json == result


def test_same_stage_and_target_reuses_pending_proposal_despite_summary_change(state):
    context, factory = state
    context.canvas_permission_mode = "ask"

    async def forbidden():
        pytest.fail("等待审阅的提案不应执行")

    first = asyncio.run(actions.execute_action(context, "canvas_stage", _args(), forbidden))
    second = asyncio.run(actions.execute_action(
        context, "canvas_stage", {**_args(), "summary": "换个说法的阶段摘要"}, forbidden,
    ))
    first_approval = first.get("approval")
    second_approval = second.get("approval")
    assert isinstance(first_approval, dict) and isinstance(second_approval, dict)
    assert second_approval["id"] == first_approval["id"]
    with factory() as db:
        assert db.query(CanvasAgentAction).count() == 1


def test_same_stage_with_different_target_creates_separate_proposal(state):
    context, factory = state
    context.canvas_permission_mode = "ask"

    async def forbidden():
        pytest.fail("等待审阅的提案不应执行")

    first = asyncio.run(actions.execute_action(context, "canvas_stage", _args(), forbidden))
    second = asyncio.run(actions.execute_action(
        context, "canvas_stage",
        {**_args(), "parameters": {"content": "第一版剧本", "node_id": "script-two"}}, forbidden,
    ))
    first_approval = first.get("approval")
    second_approval = second.get("approval")
    assert isinstance(first_approval, dict) and isinstance(second_approval, dict)
    assert second_approval["id"] != first_approval["id"]
    with factory() as db:
        assert db.query(CanvasAgentAction).count() == 2


@pytest.mark.parametrize("change", ["owner", "conversation", "canvas", "mode", "revision"])
def test_approval_rejects_changed_owner_scope_mode_or_graph_version(state, change):
    context, factory = state

    async def forbidden():
        pytest.fail("未授权操作不应执行")

    result = asyncio.run(actions.execute_action(context, "canvas_stage", _args(), forbidden))
    if change == "owner":
        context.pending_change_key.user_id = 7
    elif change == "conversation":
        context.pending_change_key.conversation_id = 7
    elif change == "canvas":
        context.workflow_id = 7
    elif change == "mode":
        context.canvas_permission_mode = "auto"
    else:
        with factory() as db:
            db.get(VideoCanvas, 1).definition_revision += 1
            db.commit()
    with pytest.raises(HTTPException):
        actions.claim_approval(context, result["approval"]["id"])


def test_natural_language_revision_invalidates_old_proposal(state):
    context, factory = state

    async def forbidden():
        pytest.fail("修改提案不能触发制作")

    original = asyncio.run(actions.execute_action(context, "canvas_stage", _args(), forbidden))["approval"]
    revised = actions.revise_proposal(context, original["id"])
    assert revised["parameters"]["parameters"]["content"] == "第一版剧本"
    with pytest.raises(HTTPException):
        actions.claim_approval(context, original["id"])
    replacement = asyncio.run(actions.execute_action(context, "canvas_stage", _args("用户要求的第二版"), forbidden))["approval"]
    assert replacement["id"] != original["id"]


def test_model_cannot_change_parameters_after_approval(state):
    context, factory = state

    async def forbidden():
        pytest.fail("不能执行不同于审批的正文")

    original = asyncio.run(actions.execute_action(context, "canvas_stage", _args(), forbidden))["approval"]
    actions.claim_approval(context, original["id"])
    context.canvas_executing_action_id = original["id"]
    with pytest.raises(HTTPException, match="不一致"):
        asyncio.run(actions.execute_action(context, "canvas_stage", _args("偷偷替换正文"), forbidden))


def test_completed_background_stage_can_resume_only_once(state):
    context, factory = state
    context.canvas_permission_mode = "auto"
    with factory() as db:
        db.add(VideoCanvasRun(id=9, canvas_id=1, canvas_version_id=1, status="succeeded", plan_json={}))
        db.add(CanvasAgentAction(canvas_id=1, owner_user_id=2, conversation_id=5, permission_mode="auto", stage="images", tool_name="canvas_stage", summary="出图", arguments_json={}, expected_definition_revision=4, status="waiting", result_json={"pending_task": {"run_id": 9}}))
        db.commit()
    assert actions.consume_resume(context, 9)["stage"] == "images"
    with pytest.raises(HTTPException):
        actions.consume_resume(context, 9)


def test_success_callback_creates_one_next_action_and_is_idempotent(state):
    context, factory = state
    with factory() as db:
        db.add(BackgroundTask(task_id="canvas-task", task_type="video_canvas_run", status="succeeded", metadata_json={"canvas_id": 1, "run_id": 9, "agent_action_id": 10}))
        db.add(VideoCanvasRun(id=9, canvas_id=1, canvas_version_id=1, status="succeeded", plan_json={}))
        db.add(CanvasAgentAction(
            id=10, canvas_id=1, owner_user_id=2, conversation_id=5, permission_mode="auto",
            stage="images", tool_name="canvas_stage", summary="出图", arguments_json={},
            expected_definition_revision=4, status="waiting",
            result_json={"pending_task": {"run_id": 9}, "next_stage": "videos", "node_ids": ["video-1"]},
        ))
        db.commit()
    first = actions.continue_canvas_stage_after_run("canvas-task", {"run_id": 9, "status": "succeeded"})
    second = actions.continue_canvas_stage_after_run("canvas-task", {"run_id": 9, "status": "succeeded"})
    assert first and first["idempotent"] is False
    assert second and second["idempotent"] is True
    with factory() as db:
        rows = db.query(CanvasAgentAction).order_by(CanvasAgentAction.id).all()
        assert len(rows) == 2
        assert rows[0].status == "completed"
        assert rows[1].stage == "videos"
        assert rows[1].status == "queued"


def test_waiting_task_serializer_returns_all_tasks(state):
    _context, factory = state
    with factory() as db:
        db.add_all([
            CanvasAgentAction(canvas_id=1, owner_user_id=2, conversation_id=5, permission_mode="ask", stage="images", tool_name="canvas_stage", summary="图", arguments_json={}, expected_definition_revision=4, status="waiting", result_json={"pending_task": {"run_id": 1}}),
            CanvasAgentAction(canvas_id=1, owner_user_id=2, conversation_id=5, permission_mode="auto", stage="videos", tool_name="canvas_stage", summary="视频", arguments_json={}, expected_definition_revision=4, status="waiting", result_json={"pending_task": {"run_id": 2}}),
        ])
        db.commit()
        rows = db.query(CanvasAgentAction).order_by(CanvasAgentAction.id).all()
        waiting = actions.serialize_waiting_tasks(rows)
    assert [item["run_id"] for item in waiting] == [1, 2]
    assert [item["action_id"] for item in waiting] == [1, 2]


def test_auto_dispatcher_executes_sync_stage_and_queues_next_action(state, monkeypatch):
    _context, factory = state
    with factory() as db:
        db.add(CanvasAgentAction(
            id=20, canvas_id=1, owner_user_id=2, conversation_id=5, permission_mode="auto",
            stage="screenplay", tool_name="canvas_stage", summary="剧本", arguments_json={
                "canvas_id": 1, "stage": "screenplay", "parameters": {"content": "测试剧本"}
            }, expected_definition_revision=4, status="queued", result_json={"continuation": {"source_action_id": 19}},
        ))
        db.commit()

    async def gateway(canvas_id, stage, parameters, request, db):
        assert request.state.trusted_agent_dispatch is True
        if stage == "screenplay":
            assert parameters["agent_action_id"] == 20
            return {"ok": True, "next_stage": "split", "node_id": "screenplay-1", "definition_revision": 4}
        assert stage == "split"
        assert parameters["agent_action_id"] != 20
        return {"ok": True, "definition_revision": 4}

    from services import canvas_stage_gateway
    monkeypatch.setattr(canvas_stage_gateway, "execute_agent_canvas_stage", gateway)
    result = asyncio.run(actions.dispatch_queued_canvas_action(20))
    assert result["status"] == "completed"
    with factory() as db:
        rows = db.query(CanvasAgentAction).order_by(CanvasAgentAction.id).all()
        assert rows[0].status == "completed"
        assert rows[1].stage == "split"
        assert rows[1].status == "completed"
        assert len(rows) == 2
    # A duplicate consumer cannot claim the already completed action, but gets
    # a stable idempotent receipt.
    duplicate = asyncio.run(actions.dispatch_queued_canvas_action(20))
    assert duplicate and duplicate["idempotent"] is True


def test_auto_dispatcher_marks_generation_stage_waiting(state, monkeypatch):
    _context, factory = state
    with factory() as db:
        db.add(CanvasAgentAction(
            id=21, canvas_id=1, owner_user_id=2, conversation_id=5, permission_mode="auto",
            stage="images", tool_name="canvas_stage", summary="出图", arguments_json={
                "canvas_id": 1, "stage": "images", "parameters": {"node_ids": ["image-1"]}
            }, expected_definition_revision=4, status="queued", result_json={"continuation": {"source_action_id": 20}},
        ))
        db.commit()

    async def gateway(canvas_id, stage, parameters, request, db):
        return {"ok": True, "pending_task": {"canvas_id": 1, "run_id": 99, "status": "queued"}, "next_stage": "videos"}

    from services import canvas_stage_gateway
    monkeypatch.setattr(canvas_stage_gateway, "execute_agent_canvas_stage", gateway)
    result = asyncio.run(actions.dispatch_queued_canvas_action(21))
    assert result["status"] == "waiting"
    with factory() as db:
        action = db.get(CanvasAgentAction, 21)
        assert action.status == "waiting"
        assert action.result_json["pending_task"]["run_id"] == 99
        assert db.query(CanvasAgentAction).count() == 1


def test_failed_or_cancelled_callback_does_not_create_continuation(state):
    _context, factory = state
    with factory() as db:
        db.add(BackgroundTask(task_id="canvas-failed", task_type="video_canvas_run", status="failed", metadata_json={"canvas_id": 1, "run_id": 11, "agent_action_id": 10}))
        db.add(VideoCanvasRun(id=11, canvas_id=1, canvas_version_id=1, status="failed", plan_json={}))
        db.add(CanvasAgentAction(
            id=10, canvas_id=1, owner_user_id=2, conversation_id=5, permission_mode="auto",
            stage="images", tool_name="canvas_stage", summary="出图", arguments_json={},
            expected_definition_revision=4, status="waiting", result_json={"pending_task": {"run_id": 11}, "next_stage": "videos"},
        ))
        db.commit()
    assert actions.continue_canvas_stage_after_run("canvas-failed", {"run_id": 11, "status": "failed"}) is None
    with factory() as db:
        assert db.query(CanvasAgentAction).count() == 1


def test_real_tool_registry_gate_saves_proposal_without_calling_gateway(state, monkeypatch):
    from services import agent_service as agent
    from services import canvas_stage_gateway
    context, factory = state
    monkeypatch.setattr(agent, "SessionLocal", factory)

    async def forbidden(*args):
        pytest.fail("询问模式不能调用制作网关")

    monkeypatch.setattr(canvas_stage_gateway, "execute_agent_canvas_stage", forbidden)
    run_context = agent.AgentRunContext(
        story_id=3, api_key="test", pending_changes=agent.PendingChangesTracker(),
        pending_change_key=agent.AgentPendingChangeKey(user_id=2, story_id=3, conversation_id=5),
        workflow_type="video_canvas", workflow_id=1, canvas_permission_mode="ask", canvas_request=object(),
    )
    token = agent._AGENT_RUN_CONTEXT.set(run_context)
    try:
        result = json.loads(asyncio.run(agent.tool_registry.execute("canvas_stage", _args())))
        assert result["awaiting_approval"] is True
    finally:
        agent._AGENT_RUN_CONTEXT.reset(token)


def test_approved_stage_emits_waiting_and_done_without_model_request(state, monkeypatch):
    from services import agent_service as agent
    from services import canvas_stage_gateway
    context, factory = state
    monkeypatch.setattr(agent, "SessionLocal", factory)

    async def unused():
        pytest.fail("提案阶段不能执行")

    proposal = asyncio.run(actions.execute_action(context, "canvas_stage", _args(), unused))["approval"]

    async def gateway(canvas_id, stage, parameters, request, db):
        assert parameters["agent_action_id"] == proposal["id"]
        assert parameters["expected_definition_revision"] == 4
        return {"ok": True, "pending_task": {"canvas_id": 1, "run_id": 9, "status": "queued"}}

    monkeypatch.setattr(canvas_stage_gateway, "execute_agent_canvas_stage", gateway)

    async def collect():
        return [event async for event in agent.agent_service.run_stream(
            messages=[{"role": "user", "content": "确认阶段"}], story_context="测试", api_key="test", story_id=3,
            pending_change_key=agent.AgentPendingChangeKey(user_id=2, story_id=3, conversation_id=5),
            workflow_type="video_canvas", workflow_id=1, canvas_permission_mode="ask",
            canvas_approval_id=proposal["id"], canvas_request=object(),
        )]

    events = asyncio.run(collect())
    assert [event["event"] for event in events] == ["tool_result", "canvas_updated", "waiting", "done"]
    assert json.loads(events[-1]["data"])["pending_task"]["run_id"] == 9


@pytest.mark.parametrize("deleted_table", ["video_canvases", "agent_conversations"])
def test_deleting_parent_cascades_new_action_records(deleted_table):
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("PRAGMA foreign_keys=ON"))
        for table in ("users", "video_canvases", "agent_conversations"):
            connection.execute(text(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY)"))
            connection.execute(text(f"INSERT INTO {table} (id) VALUES (1)"))
        CanvasAgentAction.__table__.create(connection)
        connection.execute(CanvasAgentAction.__table__.insert().values(
            canvas_id=1, conversation_id=1, owner_user_id=1, permission_mode="ask", stage="split",
            tool_name="canvas_stage", summary="测试", arguments_json={}, expected_definition_revision=1,
        ))
        connection.execute(text(f"DELETE FROM {deleted_table} WHERE id=1"))
        assert connection.execute(text("SELECT COUNT(*) FROM canvas_agent_actions")).scalar() == 0
    engine.dispose()


def test_request_error_cleans_temporary_media_before_response(tmp_path):
    import main  # noqa: F401
    from routers.agent_router import _cleanup_media_on_request_error

    temporary = tmp_path / "temporary-frames"
    temporary.mkdir()
    request = SimpleNamespace(state=SimpleNamespace(agent_media_temporary_paths=[temporary]))

    @_cleanup_media_on_request_error
    async def fails(*, request):
        raise HTTPException(403, "额度不足")

    with pytest.raises(HTTPException):
        asyncio.run(fails(request=request))
    assert not temporary.exists()


def test_approved_sync_stage_rewrites_confirmation_so_model_does_not_redo_it(state, monkeypatch):
    """点确认卡片后，“已在阶段卡片确认，执行此阶段”不能原样交给模型，否则它会把确认当新指令再提一次方案。"""
    from services import agent_service as agent
    from services import canvas_stage_gateway
    from test_agent_media import _agent_sse_response, _install_agent_stream_client
    context, factory = state
    monkeypatch.setattr(agent, "SessionLocal", factory)

    async def unused():
        pytest.fail("提案阶段不能执行")

    proposal = asyncio.run(actions.execute_action(context, "canvas_stage", _args(), unused))["approval"]

    async def gateway(canvas_id, stage, parameters, request, db, **_kwargs):
        return {"ok": True, "canvas_id": 1, "stage": "screenplay", "node_id": "script-1", "definition_revision": 5, "graph": {"nodes": ["很大的整图"] * 50}}

    monkeypatch.setattr(canvas_stage_gateway, "execute_agent_canvas_stage", gateway)
    payloads = _install_agent_stream_client(monkeypatch, [_agent_sse_response("剧本已写入画布。", "stop")])
    monkeypatch.setattr(agent.agent_service, "_build_system_prompt", lambda *_a, **_k: "系统提示")

    async def collect():
        return [event async for event in agent.agent_service.run_stream(
            messages=[{"role": "user", "content": "已在阶段卡片确认，执行此阶段。"}], story_context="测试", api_key="test", story_id=3,
            pending_change_key=agent.AgentPendingChangeKey(user_id=2, story_id=3, conversation_id=5),
            workflow_type="video_canvas", workflow_id=1, canvas_permission_mode="ask",
            canvas_approval_id=proposal["id"], canvas_request=object(),
        )]

    asyncio.run(collect())
    sent = payloads[0]["messages"]
    assert "已在阶段卡片确认" not in sent[-1]["content"]
    assert "系统代述" in sent[-1]["content"] and "不要重复提交" in sent[-1]["content"]
    assert "很大的整图" not in json.dumps(sent, ensure_ascii=False), "执行结果里的整图不能注入上下文"


def test_canvas_tools_use_session_canvas_even_if_model_passes_story_id(state, monkeypatch):
    """模型常把作品 ID 当画布 ID 传入，导致“画布不存在或无权访问”；执行层按会话画布纠正。"""
    from services import agent_service as agent
    context, factory = state
    monkeypatch.setattr(agent, "SessionLocal", factory)
    run_context = agent.AgentRunContext(
        story_id=3, api_key="test", pending_changes=agent.PendingChangesTracker(),
        pending_change_key=agent.AgentPendingChangeKey(user_id=2, story_id=3, conversation_id=5),
        workflow_type="video_canvas", workflow_id=1, canvas_permission_mode="ask", canvas_request=object(),
    )
    token = agent._AGENT_RUN_CONTEXT.set(run_context)
    try:
        result = json.loads(asyncio.run(agent.tool_registry.execute("canvas_stage", {**_args(), "canvas_id": 35})))
        assert result["awaiting_approval"] is True and result["approval"]["canvas_id"] == 1
    finally:
        agent._AGENT_RUN_CONTEXT.reset(token)


def test_get_canvas_nodes_is_available_to_canvas_agent():
    from services import agent_service as agent
    for skills in (None, ["video_canvas_workflow"], ["canvas_graph_compiler"]):
        allowed = agent.tool_registry._effective_tool_names("video_canvas", skills)
        assert "get_canvas_nodes" in allowed and "get_canvas_graph" in allowed, skills
