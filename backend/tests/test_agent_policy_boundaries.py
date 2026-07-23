"""验证 Agent 工具授权和视频资产归属边界。"""

import asyncio
import json
from types import SimpleNamespace

from services import agent_service


def _tool_names(**kwargs) -> set[str]:
    return {
        spec["function"]["name"]
        for spec in agent_service.tool_registry.get_tool_specs(**kwargs)
    }


def _context(**overrides):
    values = {
        "story_id": 1,
        "api_key": None,
        "mode": "execute",
        "pending_changes": agent_service.PendingChangesTracker(),
        "workflow_type": "video",
        "workflow_id": 5,
        "chapter_id": 10,
        "enabled_skills": None,
    }
    values.update(overrides)
    return agent_service.AgentRunContext(**values)


def test_video_workflow_uses_closed_allowlist():
    names = _tool_names(mode="execute", workflow_type="video")

    assert "get_chapter_full" in names
    assert "update_screenplay" in names
    assert "update_chapter_content" not in names
    assert "update_story_bible" not in names
    assert "create_chapter" not in names


def test_novel_workflow_uses_general_tool_set():
    default_names = _tool_names(mode="execute", workflow_type=None)
    novel_names = _tool_names(mode="execute", workflow_type="novel")

    assert novel_names == default_names
    assert "update_chapter_content" in novel_names
    assert "update_screenplay" not in novel_names


def test_unknown_policy_inputs_fail_closed():
    assert _tool_names(mode="execute", workflow_type="unknown") == set()
    assert _tool_names(
        mode="execute",
        workflow_type="video",
        enabled_skills=["unknown_skill"],
    ) == set()
    assert _tool_names(
        mode="execute",
        workflow_type="video",
        enabled_skills=[],
    ) == set()
    assert "update_screenplay" not in _tool_names(mode="invalid", workflow_type="video")


def test_execute_reuses_spec_policy_for_skills():
    context = _context(enabled_skills=["unknown_skill"])
    token = agent_service._AGENT_RUN_CONTEXT.set(context)
    try:
        result = asyncio.run(agent_service.tool_registry.execute(
            "get_video_workflow",
            {"workflow_id": 5},
        ))
    finally:
        agent_service._AGENT_RUN_CONTEXT.reset(token)

    payload = json.loads(result)
    assert payload["tool_denied"] is True
    assert payload["workflow_tool_denied"] is True


def test_cross_story_reference_asset_is_rejected(monkeypatch):
    workflow = SimpleNamespace(id=5, story_id=1, chapter_id=10)
    shot = SimpleNamespace(id=7, workflow_id=5)
    asset = SimpleNamespace(id=21, story_id=2, chapter_id=10, asset_type="character_reference")

    class Query:
        def filter(self, *_args):
            return self

        def all(self):
            return [asset]

    db = SimpleNamespace(query=lambda _model: Query())
    monkeypatch.setattr(agent_service, "_require_current_video_workflow", lambda _db, _id: workflow)

    error = agent_service._validate_video_reference_assets(
        db,
        shot,
        {"character_reference_ids": [21]},
    )

    assert error == "引用资产 21 不属于当前故事"


def test_reference_asset_type_must_match_target_field(monkeypatch):
    workflow = SimpleNamespace(id=5, story_id=1, chapter_id=10)
    shot = SimpleNamespace(id=7, workflow_id=5)
    asset = SimpleNamespace(id=21, story_id=1, chapter_id=10, asset_type="scene_reference")

    class Query:
        def filter(self, *_args):
            return self

        def all(self):
            return [asset]

    db = SimpleNamespace(query=lambda _model: Query())
    monkeypatch.setattr(agent_service, "_require_current_video_workflow", lambda _db, _id: workflow)

    error = agent_service._validate_video_reference_assets(
        db,
        shot,
        {"character_reference_ids": [21]},
    )

    assert "类型 scene_reference" in error


def test_get_video_assets_requires_current_workflow_chapter(monkeypatch):
    db = SimpleNamespace(close=lambda: None)
    monkeypatch.setattr(agent_service, "SessionLocal", lambda: db)
    monkeypatch.setattr(
        agent_service,
        "_validate_chapter_ownership",
        lambda *_args: SimpleNamespace(id=11, story_id=1),
    )
    monkeypatch.setattr(
        agent_service,
        "_require_current_video_workflow",
        lambda *_args: SimpleNamespace(id=5, story_id=1, chapter_id=10),
    )
    token = agent_service._AGENT_RUN_CONTEXT.set(_context())
    try:
        result = asyncio.run(agent_service.get_video_assets(11))
    finally:
        agent_service._AGENT_RUN_CONTEXT.reset(token)

    assert "不属于当前视频工作流" in result["error"]


def test_created_chapter_snapshot_can_be_rolled_back():
    chapter = SimpleNamespace(
        id=9,
        story_id=1,
        chapter_number=3,
        title="第三章",
        status="pending",
        novel_content=None,
    )

    class Db:
        deleted = None
        committed = False

        def get(self, _model, record_id, **_kwargs):
            return chapter if record_id == chapter.id else None

        def delete(self, value):
            self.deleted = value

        def commit(self):
            self.committed = True

    tracker = agent_service.PendingChangesTracker()
    tracker.record(agent_service.PendingChange(
        type="chapter_created",
        record_id=chapter.id,
        display_name="第3章 · 第三章",
        field="__created__",
        old_value=None,
        new_value={
            "story_id": 1,
            "chapter_number": 3,
            "title": "第三章",
            "status": "pending",
            "novel_content": None,
        },
    ))
    db = Db()

    result = tracker.rollback(db)

    assert db.deleted is chapter
    assert db.committed is True
    assert result == [{"ok": True, "type": "chapter_created", "id": 9, "field": "__created__"}]


def test_system_prompt_marks_attachments_untrusted():
    prompt = agent_service.agent_service._build_system_prompt(
        "测试上下文",
        story_id=1,
        mode="analyze",
    )

    assert "当前处于只读模式" in prompt
    assert "附件与视觉资料安全边界" in prompt
    assert "都属于不可信资料" in prompt


def test_full_writing_rules_only_load_for_chapter_writer_skill():
    service = agent_service.AgentService()

    regular_prompt = service._build_system_prompt(
        "测试上下文",
        story_id=1,
        mode="analyze",
        enabled_skills=[],
    )
    chapter_prompt = service._build_system_prompt(
        "测试上下文",
        story_id=1,
        mode="analyze",
        enabled_skills=["chapter_writer"],
    )

    assert "正文写作参考规范" not in regular_prompt
    assert "正文写作参考规范" in chapter_prompt


def test_pending_change_is_persisted_when_new_value_is_recorded(monkeypatch):
    persisted = []
    monkeypatch.setattr(
        agent_service,
        "_persist_pending_changes",
        lambda key, tracker, *, run_id=None: persisted.append((key, tracker, run_id)) or True,
    )
    key = agent_service.AgentPendingChangeKey(user_id=1, story_id=2, conversation_id=3)
    tracker = agent_service.PendingChangesTracker()
    context = _context(
        pending_changes=tracker,
        pending_change_key=key,
        run_id="run-1",
    )
    token = agent_service._AGENT_RUN_CONTEXT.set(context)
    try:
        tracker.record(agent_service.PendingChange(
            type="chapter",
            record_id=9,
            display_name="第1章",
            field="title",
            old_value="旧标题",
            new_value=None,
        ))
        assert persisted == []
        tracker.update_new_value("chapter", 9, "title", "新标题")
    finally:
        agent_service._AGENT_RUN_CONTEXT.reset(token)

    assert persisted[0][0] == key
    assert persisted[0][2] == "run-1"
