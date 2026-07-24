"""验证 Agent 工具授权和视频资产归属边界。"""

import asyncio
import json
from contextlib import nullcontext
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


def test_chapter_pipeline_tools_use_extended_timeout(monkeypatch):
    monkeypatch.delenv("AGENT_TOOL_EXECUTION_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("AGENT_LONG_TOOL_EXECUTION_TIMEOUT_SECONDS", raising=False)

    for tool_name in (
        "adjust_chapter_by_instruction",
        "generate_chapter_content",
        "batch_adjust_chapters",
    ):
        assert agent_service._agent_tool_execution_timeout_seconds(tool_name) == 1200


def test_regular_agent_tool_keeps_default_timeout(monkeypatch):
    monkeypatch.delenv("AGENT_TOOL_EXECUTION_TIMEOUT_SECONDS", raising=False)

    assert agent_service._agent_tool_execution_timeout_seconds("get_chapter_full") == 300


def test_agent_timeout_environment_variables_override_each_tier(monkeypatch):
    monkeypatch.setenv("AGENT_TOOL_EXECUTION_TIMEOUT_SECONDS", "450")
    monkeypatch.setenv("AGENT_LONG_TOOL_EXECUTION_TIMEOUT_SECONDS", "1500")

    assert agent_service._agent_tool_execution_timeout_seconds("get_chapter_full") == 450
    assert agent_service._agent_tool_execution_timeout_seconds("adjust_chapter_by_instruction") == 1500


def test_invalid_agent_timeout_configuration_falls_back_to_default(monkeypatch):
    monkeypatch.delenv("AGENT_TOOL_EXECUTION_TIMEOUT_SECONDS", raising=False)
    for invalid_value in ("", "abc", "0", "-1"):
        monkeypatch.setenv("AGENT_LONG_TOOL_EXECUTION_TIMEOUT_SECONDS", invalid_value)
        assert (
            agent_service._agent_tool_execution_timeout_seconds("generate_chapter_content")
            == agent_service.DEFAULT_AGENT_LONG_TOOL_EXECUTION_TIMEOUT_SECONDS
        )


def test_long_tool_timeout_is_never_shorter_than_regular_timeout(monkeypatch):
    monkeypatch.setenv("AGENT_TOOL_EXECUTION_TIMEOUT_SECONDS", "1800")
    monkeypatch.delenv("AGENT_LONG_TOOL_EXECUTION_TIMEOUT_SECONDS", raising=False)

    regular_timeout = agent_service._agent_tool_execution_timeout_seconds("get_story_info")
    long_timeout = agent_service._agent_tool_execution_timeout_seconds("batch_adjust_chapters")

    assert regular_timeout == 1800
    assert long_timeout == regular_timeout


def test_reusable_creation_pack_replaces_previous_instruction_without_mutating_source():
    quality_score = {
        "creation_pack_fingerprint": "fingerprint",
        "creation_pack": {
            "chapter_task": {"user_instruction": "旧调整要求"},
            "hard_requirements": ["旧调整要求", "保留核心冲突"],
        },
    }

    reusable = agent_service._reusable_chapter_creation_pack(
        quality_score,
        expected_fingerprint="fingerprint",
        instruction="新的去AI味要求",
    )

    assert reusable is not None
    assert reusable["chapter_task"]["user_instruction"] == "新的去AI味要求"
    assert reusable["hard_requirements"] == ["新的去AI味要求", "保留核心冲突"]
    assert quality_score["creation_pack"]["chapter_task"]["user_instruction"] == "旧调整要求"


def test_reusable_creation_pack_rejects_explicitly_stale_fingerprint():
    quality_score = {
        "creation_pack_fingerprint": "old",
        "creation_pack": {"chapter_task": {}},
    }

    reusable = agent_service._reusable_chapter_creation_pack(
        quality_score,
        expected_fingerprint="new",
        instruction="调整节奏",
    )

    assert reusable is None


def test_reusable_creation_pack_rejects_legacy_cache_without_fingerprint():
    quality_score = {"creation_pack": {"chapter_task": {}}}

    reusable = agent_service._reusable_chapter_creation_pack(
        quality_score,
        expected_fingerprint="new",
        instruction="调整节奏",
    )

    assert reusable is None


def test_creation_pack_fingerprint_tracks_structural_source_changes():
    base_context = {
        "outline": {"chapters": [{"chapter_number": 1}]},
        "story_bible": {"world": "测试世界"},
        "characters": {"主角": {"name": "林墨"}},
        "story_memory": {"summary": "旧记忆"},
    }
    chapter_info = {"chapter_number": 1, "title": "开端", "act": "第一幕", "key_events": []}

    first = agent_service._chapter_creation_pack_fingerprint(base_context, chapter_info, "规则")
    memory_changed = agent_service._chapter_creation_pack_fingerprint(
        {**base_context, "story_memory": {"summary": "新记忆"}},
        chapter_info,
        "规则",
    )
    outline_changed = agent_service._chapter_creation_pack_fingerprint(
        {**base_context, "outline": {"chapters": [{"chapter_number": 1, "goal": "新目标"}]}},
        chapter_info,
        "规则",
    )
    description_changed = agent_service._chapter_creation_pack_fingerprint(
        {**base_context, "description": "新的作品简介", "tags": {"genre": "悬疑"}},
        chapter_info,
        "规则",
    )

    assert first == memory_changed
    assert first != outline_changed
    assert first != description_changed


def test_background_memory_refresh_skips_stale_chapter_content(monkeypatch):
    class FakeDb:
        def __init__(self):
            self.chapter = SimpleNamespace(id=7, story_id=3, novel_content="新正文")
            self.closed = False
            self.committed = False

        def get(self, model, record_id):
            return self.chapter

        def commit(self):
            self.committed = True

        def rollback(self):
            pass

        def close(self):
            self.closed = True

    fake_db = FakeDb()
    monkeypatch.setattr(agent_service, "SessionLocal", lambda: fake_db)
    agent_service._AGENT_MEMORY_REFRESH_LOCKS.clear()

    asyncio.run(agent_service._refresh_agent_memory_background(
        chapter_id=7,
        story_id=3,
        api_key="sk-test",
        expected_content_fingerprint=agent_service._chapter_content_fingerprint("旧正文"),
    ))

    assert fake_db.closed is True
    assert fake_db.committed is False


def test_memory_refresh_final_check_locks_story_and_chapter_rows():
    lock_count = 0
    scalar_values = iter([3, "最新正文"])

    class FakeQuery:
        def filter(self, *args):
            return self

        def with_for_update(self):
            nonlocal lock_count
            lock_count += 1
            return self

        def scalar(self):
            return next(scalar_values)

    class FakeDb:
        no_autoflush = nullcontext()

        def query(self, *args):
            return FakeQuery()

    content = agent_service._lock_agent_memory_rows(FakeDb(), story_id=3, chapter_id=7)

    assert content == "最新正文"
    assert lock_count == 2
