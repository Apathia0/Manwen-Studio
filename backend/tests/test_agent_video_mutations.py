"""验证视频工作流 Agent 的分镜写入约束。"""

import asyncio
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, inspect, text

import database
import main  # noqa: F401 - 确保 Agent 路由可绑定主模块中的认证与计费依赖
from routers import agent_router
from services import agent_service as agent_service_module
from services import video_chapter_pipeline
from services.agent_service import _video_write_result_changed, has_video_mutation_intent, tool_registry
from models import Base


@pytest.mark.parametrize(
    "message",
    [
        "针对这个调整，重新优化故事版的分镜脚本内容",
        "请直接修改镜头 2 的故事版提示词",
        "把这些分镜重写后保存",
        "帮我调整 storyboard 并写入",
        "不要只给建议，直接优化分镜",
        "不用分析，直接修改故事版",
        "请帮我分析分镜，然后直接优化分镜",
        "帮我检查并优化分镜",
        "先分析分镜再直接修改故事版",
        "分析完分镜后直接优化分镜",
        "帮我检查分镜并优化",
        "先检查分镜，再优化一下",
    ],
)
def test_video_mutation_intent_accepts_explicit_commands(message: str):
    assert has_video_mutation_intent(message) is True


@pytest.mark.parametrize(
    "message",
    [
        "这个故事版有什么优化建议？",
        "请问如何优化故事版？",
        "请帮我分析分镜如何优化",
        "帮我看看故事版怎么调整",
        "帮我分析分镜，然后给我故事版优化建议",
        "先检查分镜，再给我故事版调整方案",
        "先分析分镜，然后给我故事版修改建议",
        "帮我分析分镜，然后给我故事版重写方案",
        "先分析分镜，暂时不要修改",
        "帮我检查故事版，优化建议先不要写入",
        "先分析分镜，优化方向有哪些",
        "先分析分镜，优化重点是什么",
        "分镜能优化吗",
        "故事版可以调整吗",
        "这个分镜需要修改吗",
        "先分析分镜，不要修改",
        "只给我分镜调整方案",
        "当前视频工作流怎么样",
    ],
)
def test_video_mutation_intent_rejects_advice_and_negation(message: str):
    assert has_video_mutation_intent(message) is False


def _video_tool_specs(mode: str = "agent") -> dict[str, dict]:
    return {
        spec["function"]["name"]: spec["function"]
        for spec in tool_registry.get_tool_specs(mode=mode, workflow_type="video")
    }


def test_video_write_tools_are_available_to_single_agent():
    agent_specs = _video_tool_specs()

    assert "update_shot_prompts" in agent_specs
    assert "batch_update_shot_fields" in agent_specs


def test_video_shot_field_whitelist_contains_business_fields_only():
    properties = _video_tool_specs()["update_shot_fields"]["parameters"]["properties"]

    expected = {
        "dialogue_or_narration",
        "continuity_notes",
        "narrative_purpose",
        "beat_density",
        "transition_to_next",
    }
    forbidden = {"workflow_id", "shot_index", "status", "storyboard_image_url", "video_url"}

    assert expected <= properties.keys()
    assert forbidden.isdisjoint(properties.keys())


def test_video_prompt_json_fields_use_array_schema():
    properties = _video_tool_specs()["update_shot_prompts"]["parameters"]["properties"]

    for field in ("character_prompts_json", "prop_prompts_json"):
        assert properties[field]["type"] == "array"
        assert properties[field]["items"]["type"] == "object"


def test_agent_cannot_write_protected_storyboard_prompt():
    specs = _video_tool_specs()
    single_properties = specs["update_shot_prompts"]["parameters"]["properties"]
    batch_item_properties = specs["batch_update_shot_prompts"]["parameters"]["properties"]["shots"]["items"]["properties"]

    assert "storyboard_prompt" not in single_properties
    assert "storyboard_prompt" not in batch_item_properties


def test_storyboard_script_edits_use_business_fields():
    specs = _video_tool_specs()
    single_properties = specs["update_shot_fields"]["parameters"]["properties"]
    batch_item_properties = specs["batch_update_shot_fields"]["parameters"]["properties"]["shots"]["items"]["properties"]
    expected = {
        "story_summary",
        "dialogue_or_narration",
        "camera_plan",
        "motion_plan",
        "emotion_plan",
        "continuity_notes",
        "narrative_purpose",
        "beat_density",
        "transition_to_next",
    }

    assert expected <= single_properties.keys()
    assert expected <= batch_item_properties.keys()


@pytest.mark.asyncio
async def test_business_field_change_invalidates_protected_storyboard_prompt(monkeypatch):
    shot = SimpleNamespace(
        id=7,
        shot_index=1,
        story_summary="旧剧情",
        storyboard_prompt="完整五区故事板提示词",
        storyboard_prompt_stale=False,
    )
    db = SimpleNamespace(commit=lambda: None, close=lambda: None)
    monkeypatch.setattr(agent_service_module, "SessionLocal", lambda: db)
    monkeypatch.setattr(agent_service_module, "_require_current_video_shot", lambda _db, _shot_id: shot)
    tracker = agent_service_module.PendingChangesTracker()
    context = agent_service_module.AgentRunContext(
        story_id=1,
        api_key=None,
        pending_changes=tracker,
        workflow_type="video",
        workflow_id=1,
        shot_id=7,
    )
    context_token = agent_service_module._AGENT_RUN_CONTEXT.set(context)

    try:
        result = await agent_service_module.update_shot_fields(7, story_summary="新剧情")
    finally:
        agent_service_module._AGENT_RUN_CONTEXT.reset(context_token)

    assert shot.story_summary == "新剧情"
    assert shot.storyboard_prompt == "完整五区故事板提示词"
    assert shot.storyboard_prompt_stale is True
    assert "storyboard_prompt_stale" in result["updated_fields"]
    assert [change.field for change in tracker._changes] == ["story_summary", "storyboard_prompt_stale"]

    rollback_db = SimpleNamespace(get=lambda _model, _record_id, **_kwargs: shot, commit=lambda: None)
    rollback_result = tracker.rollback(rollback_db)

    assert shot.story_summary == "旧剧情"
    assert shot.storyboard_prompt == "完整五区故事板提示词"
    assert shot.storyboard_prompt_stale is False
    assert all(item["ok"] for item in rollback_result)


@pytest.mark.asyncio
async def test_storyboard_regeneration_conflict_skips_entire_shot_rollback(monkeypatch):
    shot = SimpleNamespace(
        id=9,
        shot_index=3,
        story_summary="旧剧情",
        storyboard_prompt="旧五区故事板提示词",
        storyboard_prompt_stale=False,
    )
    db = SimpleNamespace(commit=lambda: None, close=lambda: None)
    monkeypatch.setattr(agent_service_module, "SessionLocal", lambda: db)
    monkeypatch.setattr(agent_service_module, "_require_current_video_shot", lambda _db, _shot_id: shot)
    tracker = agent_service_module.PendingChangesTracker()
    context = agent_service_module.AgentRunContext(
        story_id=1,
        api_key=None,
        pending_changes=tracker,
        workflow_type="video",
        workflow_id=1,
        shot_id=9,
    )
    context_token = agent_service_module._AGENT_RUN_CONTEXT.set(context)

    try:
        await agent_service_module.update_shot_fields(9, story_summary="新剧情")
    finally:
        agent_service_module._AGENT_RUN_CONTEXT.reset(context_token)

    shot.storyboard_prompt = "重新生成的新五区提示词"
    shot.storyboard_prompt_stale = False
    rollback_db = SimpleNamespace(get=lambda _model, _record_id, **_kwargs: shot, commit=lambda: None)
    rollback_result = tracker.rollback(rollback_db)

    assert shot.story_summary == "新剧情"
    assert shot.storyboard_prompt == "重新生成的新五区提示词"
    assert rollback_result == [{
        "ok": False,
        "conflict": True,
        "type": "video_shot",
        "id": 9,
        "field": "storyboard_prompt_stale",
        "error": "故事板已重新生成，为避免覆盖新结果，未撤回该镜头的修改",
    }]


@pytest.mark.asyncio
async def test_initial_empty_storyboard_prompt_still_creates_regeneration_guard(monkeypatch):
    shot = SimpleNamespace(
        id=10,
        shot_index=4,
        story_summary="旧剧情",
        storyboard_prompt="",
        storyboard_prompt_stale=False,
    )
    db = SimpleNamespace(commit=lambda: None, close=lambda: None)
    monkeypatch.setattr(agent_service_module, "SessionLocal", lambda: db)
    monkeypatch.setattr(agent_service_module, "_require_current_video_shot", lambda _db, _shot_id: shot)
    tracker = agent_service_module.PendingChangesTracker()
    context = agent_service_module.AgentRunContext(
        story_id=1,
        api_key=None,
        pending_changes=tracker,
        workflow_type="video",
        workflow_id=1,
        shot_id=10,
    )
    context_token = agent_service_module._AGENT_RUN_CONTEXT.set(context)

    try:
        await agent_service_module.update_shot_fields(10, story_summary="新剧情")
    finally:
        agent_service_module._AGENT_RUN_CONTEXT.reset(context_token)

    assert [change.field for change in tracker._changes] == ["story_summary", "storyboard_prompt_stale"]
    shot.storyboard_prompt = "首次生成的新五区提示词"
    shot.storyboard_prompt_stale = False
    rollback_db = SimpleNamespace(get=lambda _model, _record_id, **_kwargs: shot, commit=lambda: None)
    rollback_result = tracker.rollback(rollback_db)

    assert shot.story_summary == "新剧情"
    assert shot.storyboard_prompt == "首次生成的新五区提示词"
    assert rollback_result[0]["conflict"] is True


@pytest.mark.asyncio
async def test_unchanged_business_field_keeps_storyboard_prompt(monkeypatch):
    shot = SimpleNamespace(
        id=8,
        shot_index=2,
        story_summary="相同剧情",
        storyboard_prompt="完整五区故事板提示词",
        storyboard_prompt_stale=False,
    )
    db = SimpleNamespace(commit=lambda: None, close=lambda: None)
    monkeypatch.setattr(agent_service_module, "SessionLocal", lambda: db)
    monkeypatch.setattr(agent_service_module, "_require_current_video_shot", lambda _db, _shot_id: shot)

    result = await agent_service_module.update_shot_fields(8, story_summary="相同剧情")

    assert shot.storyboard_prompt == "完整五区故事板提示词"
    assert shot.storyboard_prompt_stale is False
    assert result == {"ok": True, "message": "没有提供任何需要更新的字段"}


@pytest.mark.asyncio
async def test_batch_business_field_change_keeps_prompt_and_marks_stale(monkeypatch):
    shot = SimpleNamespace(
        id=11,
        shot_index=5,
        story_summary="旧剧情",
        storyboard_prompt="应继续保留的五区故事板提示词",
        storyboard_prompt_stale=False,
    )
    db = SimpleNamespace(commit=lambda: None, close=lambda: None)
    monkeypatch.setattr(agent_service_module, "SessionLocal", lambda: db)
    monkeypatch.setattr(agent_service_module, "_require_current_video_shot", lambda _db, _shot_id: shot)
    tracker = agent_service_module.PendingChangesTracker()
    context = agent_service_module.AgentRunContext(
        story_id=1,
        api_key=None,
        pending_changes=tracker,
        workflow_type="video",
        workflow_id=1,
        shot_id=11,
    )
    context_token = agent_service_module._AGENT_RUN_CONTEXT.set(context)

    try:
        result = await agent_service_module.batch_update_shot_fields([
            {"shot_id": 11, "story_summary": "新剧情"},
        ])
    finally:
        agent_service_module._AGENT_RUN_CONTEXT.reset(context_token)

    assert result["results"][0]["updated_fields"] == ["story_summary", "storyboard_prompt_stale"]
    assert shot.storyboard_prompt == "应继续保留的五区故事板提示词"
    assert shot.storyboard_prompt_stale is True
    assert [change.field for change in tracker._changes] == ["story_summary", "storyboard_prompt_stale"]


@pytest.mark.asyncio
async def test_business_change_records_regeneration_guard_when_prompt_already_stale(monkeypatch):
    shot = SimpleNamespace(
        id=13,
        shot_index=6,
        story_summary="旧剧情",
        storyboard_prompt="保留的旧提示词",
        storyboard_prompt_stale=True,
    )
    db = SimpleNamespace(commit=lambda: None, close=lambda: None)
    monkeypatch.setattr(agent_service_module, "SessionLocal", lambda: db)
    monkeypatch.setattr(agent_service_module, "_require_current_video_shot", lambda _db, _shot_id: shot)
    tracker = agent_service_module.PendingChangesTracker()
    context = agent_service_module.AgentRunContext(
        story_id=1,
        api_key=None,
        pending_changes=tracker,
        workflow_type="video",
        workflow_id=1,
        shot_id=13,
    )
    context_token = agent_service_module._AGENT_RUN_CONTEXT.set(context)

    try:
        result = await agent_service_module.update_shot_fields(13, story_summary="新剧情")
    finally:
        agent_service_module._AGENT_RUN_CONTEXT.reset(context_token)

    assert result["updated_fields"] == ["story_summary"]
    assert [(change.field, change.old_value, change.new_value) for change in tracker._changes] == [
        ("story_summary", "旧剧情", "新剧情"),
        ("storyboard_prompt_stale", True, True),
    ]

    shot.storyboard_prompt_stale = False
    rollback_db = SimpleNamespace(get=lambda _model, _record_id, **_kwargs: shot, commit=lambda: None)
    rollback_result = tracker.rollback(rollback_db)

    assert shot.story_summary == "新剧情"
    assert rollback_result[0]["conflict"] is True


@pytest.mark.asyncio
async def test_business_change_marks_neighbor_storyboard_prompts_stale(monkeypatch):
    shots = [
        SimpleNamespace(id=31, workflow_id=4, shot_index=1, story_summary="前镜", storyboard_prompt_stale=False),
        SimpleNamespace(id=32, workflow_id=4, shot_index=2, story_summary="当前", storyboard_prompt_stale=False),
        SimpleNamespace(id=33, workflow_id=4, shot_index=3, story_summary="后镜", storyboard_prompt_stale=False),
    ]
    db = SimpleNamespace(commit=lambda: None, close=lambda: None)
    monkeypatch.setattr(agent_service_module, "SessionLocal", lambda: db)
    monkeypatch.setattr(agent_service_module, "_require_current_video_shot", lambda _db, _shot_id: shots[1])
    monkeypatch.setattr(agent_service_module, "_locked_workflow_shots", lambda _db, _workflow_id: shots)
    tracker = agent_service_module.PendingChangesTracker()
    context = agent_service_module.AgentRunContext(
        story_id=1,
        api_key=None,
        pending_changes=tracker,
        workflow_type="video",
        workflow_id=4,
        shot_id=32,
    )
    context_token = agent_service_module._AGENT_RUN_CONTEXT.set(context)

    try:
        await agent_service_module.update_shot_fields(32, story_summary="当前镜头新剧情")
    finally:
        agent_service_module._AGENT_RUN_CONTEXT.reset(context_token)

    assert [shot.storyboard_prompt_stale for shot in shots] == [True, True, True]
    stale_ids = [change.record_id for change in tracker._changes if change.field == "storyboard_prompt_stale"]
    assert stale_ids == [31, 32, 33]


@pytest.mark.asyncio
async def test_screenplay_change_marks_all_workflow_storyboards_stale(monkeypatch):
    workflow = SimpleNamespace(id=8, screenplay_text="旧文本", screenplay_json={"scenes": []})
    shots = [
        SimpleNamespace(id=41, shot_index=1, storyboard_prompt_stale=False),
        SimpleNamespace(id=42, shot_index=2, storyboard_prompt_stale=True),
    ]
    db = SimpleNamespace(commit=lambda: None, close=lambda: None)
    monkeypatch.setattr(agent_service_module, "SessionLocal", lambda: db)
    monkeypatch.setattr(agent_service_module, "_require_current_video_workflow", lambda _db, _workflow_id: workflow)
    monkeypatch.setattr(agent_service_module, "_locked_workflow_shots", lambda _db, _workflow_id: shots)
    tracker = agent_service_module.PendingChangesTracker()
    context = agent_service_module.AgentRunContext(
        story_id=1,
        api_key=None,
        pending_changes=tracker,
        workflow_type="video",
        workflow_id=8,
    )
    context_token = agent_service_module._AGENT_RUN_CONTEXT.set(context)

    try:
        await agent_service_module.update_screenplay(8, screenplay_json={"scenes": [{"scene_id": "1"}]})
    finally:
        agent_service_module._AGENT_RUN_CONTEXT.reset(context_token)

    assert [shot.storyboard_prompt_stale for shot in shots] == [True, True]
    stale_changes = [change for change in tracker._changes if change.field == "storyboard_prompt_stale"]
    assert [(change.record_id, change.old_value, change.new_value) for change in stale_changes] == [
        (41, False, True),
        (42, True, True),
    ]


@pytest.mark.parametrize(
    "result",
    [
        '{"ok": true, "updated_fields": ["storyboard_prompt"]}',
        '{"ok": true, "results": [{"ok": true, "updated_fields": ["camera_plan"]}]}',
    ],
)
def test_video_write_result_requires_real_updates(result: str):
    assert _video_write_result_changed(result) is True


@pytest.mark.parametrize(
    "result",
    [
        '{"ok": true, "message": "没有提供任何需要更新的字段"}',
        '{"ok": true, "results": []}',
        '{"ok": true, "results": [{"error": "镜头不存在"}]}',
        '{"error": "执行失败"}',
        'not-json',
    ],
)
def test_video_write_result_rejects_empty_or_failed_updates(result: str):
    assert _video_write_result_changed(result) is False


def test_video_migration_adds_and_backfills_storyboard_prompt_stale():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE chapter_video_shots DROP COLUMN storyboard_prompt_stale"))
        conn.execute(text("ALTER TABLE chapter_video_shots DROP COLUMN storyboard_generation_token"))
        conn.execute(text(
            "INSERT INTO chapter_video_shots (workflow_id, shot_index, duration_seconds, status) "
            "VALUES (1, 1, 15, 'pending')"
        ))

    database._migrate_video_tables(engine)

    columns = {column["name"] for column in inspect(engine).get_columns("chapter_video_shots")}
    assert "storyboard_prompt_stale" in columns
    assert "storyboard_generation_token" in columns
    with engine.begin() as conn:
        value = conn.execute(text(
            "SELECT storyboard_prompt_stale FROM chapter_video_shots LIMIT 1"
        )).scalar_one()
    assert value in (False, 0)


def test_stale_storyboard_regeneration_forces_new_prompt_and_clears_stale(monkeypatch):
    old_prompt = "旧故事板提示词，不能被复用"
    new_prompt = "新生成的完整五区故事板提示词"
    shot = SimpleNamespace(
        id=99,
        workflow_id=55,
        shot_index=2,
        scene_location="旧宅走廊",
        time_of_day="夜",
        characters=["林秋"],
        story_summary="林秋停在走廊中央",
        dialogue_or_narration="她没有继续向前。",
        source_text_span="原文",
        camera_plan="中景缓慢推近",
        motion_plan="停步，抬眼",
        emotion_plan="迟疑转为警觉",
        continuity_notes="承接上一镜",
        screenplay_scene_id=None,
        screenplay_beat_id=None,
        narrative_purpose=None,
        beat_density=None,
        transition_to_next=None,
        continuity_json=None,
        storyboard_json=None,
        storyboard_prompt=old_prompt,
        storyboard_prompt_stale=True,
        character_reference_ids=[],
        scene_reference_ids=[],
        prop_reference_ids=[],
    )
    workflow = SimpleNamespace(
        id=55,
        chapter_id=440,
        story_id=901,
        screenplay_json=None,
        shots=[shot],
    )
    updates: list[dict] = []
    completed_results: list[dict] = []
    generated_payloads: list[dict] = []

    monkeypatch.setattr(video_chapter_pipeline, "get_shot", lambda _shot_id: shot)
    monkeypatch.setattr(video_chapter_pipeline, "get_workflow", lambda _workflow_id: workflow)
    monkeypatch.setattr(video_chapter_pipeline, "update_shot", lambda _shot_id, **kwargs: updates.append(kwargs))
    monkeypatch.setattr(
        video_chapter_pipeline,
        "_begin_storyboard_generation_if_current",
        lambda _shot_id, _expected_source: "generation-token",
    )
    monkeypatch.setattr(
        video_chapter_pipeline,
        "_complete_storyboard_generation_if_current",
        lambda _shot_id, _expected_source, **kwargs: completed_results.append(kwargs) or True,
    )
    monkeypatch.setattr(video_chapter_pipeline, "_resolve_video_asset_references", lambda *_args: [])
    monkeypatch.setattr(video_chapter_pipeline, "_persist_chapter_storyboard_asset", lambda **_kwargs: None)

    async def fake_generate_prompt(payload, api_key=None):
        generated_payloads.append(payload)
        return new_prompt

    async def fake_generate_image(**kwargs):
        assert kwargs["prompt"] == new_prompt
        return SimpleNamespace(image_path="chapter_440_storyboard.png")

    monkeypatch.setattr(
        video_chapter_pipeline.deepseek_service,
        "generate_shot_storyboard_prompt",
        fake_generate_prompt,
    )
    monkeypatch.setattr(
        video_chapter_pipeline.image_service,
        "generate_manga_image",
        fake_generate_image,
    )

    result = asyncio.run(video_chapter_pipeline.regenerate_shot_storyboard(99, api_key="image-key"))

    assert result is shot
    assert len(generated_payloads) == 1
    assert all(update.get("storyboard_prompt") != old_prompt for update in updates)
    assert completed_results == [{
        "generation_token": "generation-token",
        "director_prompt": new_prompt,
        "storyboard_url": "/static/manga/chapter_440_storyboard.png",
    }]


def test_storyboard_completion_discards_result_when_agent_changes_source(monkeypatch):
    shot = SimpleNamespace(
        id=101,
        shot_index=1,
        story_summary="旧剧情",
        storyboard_prompt="旧提示词",
        storyboard_prompt_stale=True,
        storyboard_generation_token="generation-token",
        status="storyboard_generating",
        error_message=None,
        storyboard_image_url="旧图片.png",
        **{
            field: None
            for field in video_chapter_pipeline._STORYBOARD_SOURCE_FIELDS
            if field not in {"story_summary", "storyboard_prompt", "storyboard_prompt_stale"}
        },
    )
    workflow = SimpleNamespace(id=88, screenplay_json=None, shots=[shot])
    shot.workflow_id = workflow.id
    expected_source = video_chapter_pipeline._storyboard_workflow_snapshot(workflow, shot)
    shot.story_summary = "Agent 生成期间写入的新剧情"

    class FakeDb:
        def commit(self):
            return None

        def close(self):
            return None

    monkeypatch.setattr(video_chapter_pipeline, "SessionLocal", FakeDb)
    monkeypatch.setattr(
        video_chapter_pipeline,
        "_locked_storyboard_context",
        lambda _db, _shot_id: (workflow, shot, [shot]),
    )

    saved = video_chapter_pipeline._complete_storyboard_generation_if_current(
        shot.id,
        expected_source,
        generation_token="generation-token",
        director_prompt="过期提示词",
        storyboard_url="过期图片.png",
    )

    assert saved is False
    assert shot.storyboard_prompt == "旧提示词"
    assert shot.storyboard_prompt_stale is True
    assert shot.storyboard_image_url == "旧图片.png"
    assert shot.status == "pending"


def test_storyboard_workflow_snapshot_tracks_neighbors_and_screenplay():
    previous = SimpleNamespace(
        id=1,
        shot_index=1,
        scene_location="走廊",
        time_of_day="夜",
        characters=["林秋"],
        story_summary="林秋停步",
    )
    current = SimpleNamespace(
        id=2,
        shot_index=2,
        **{field: None for field in video_chapter_pipeline._STORYBOARD_SOURCE_FIELDS},
    )
    workflow = SimpleNamespace(
        id=3,
        screenplay_json={"scenes": [{"scene_id": "1"}]},
        shots=[previous, current],
    )
    initial = video_chapter_pipeline._storyboard_workflow_snapshot(workflow, current)

    previous.story_summary = "相邻镜头已被 Agent 修改"
    assert video_chapter_pipeline._storyboard_workflow_snapshot(workflow, current) != initial

    previous.story_summary = "林秋停步"
    workflow.screenplay_json = {"scenes": [{"scene_id": "2"}]}
    assert video_chapter_pipeline._storyboard_workflow_snapshot(workflow, current) != initial


def test_older_generation_token_cannot_downgrade_newer_ready_result(monkeypatch):
    shot = SimpleNamespace(
        id=21,
        workflow_id=22,
        shot_index=1,
        storyboard_generation_token="new-token",
        status="storyboard_ready",
        error_message=None,
        **{field: None for field in video_chapter_pipeline._STORYBOARD_SOURCE_FIELDS},
    )
    workflow = SimpleNamespace(id=22, screenplay_json=None, shots=[shot])
    expected = video_chapter_pipeline._storyboard_workflow_snapshot(workflow, shot)

    class FakeDb:
        def close(self):
            return None

    monkeypatch.setattr(video_chapter_pipeline, "SessionLocal", FakeDb)
    monkeypatch.setattr(
        video_chapter_pipeline,
        "_locked_storyboard_context",
        lambda _db, _shot_id: (workflow, shot, [shot]),
    )

    saved = video_chapter_pipeline._complete_storyboard_generation_if_current(
        shot.id,
        expected,
        generation_token="old-token",
        director_prompt="旧任务提示词",
        storyboard_url="旧任务图片.png",
    )

    assert saved is False
    assert shot.status == "storyboard_ready"
    assert shot.storyboard_generation_token == "new-token"


def test_rollback_does_not_overwrite_newer_novel_edit():
    chapter = SimpleNamespace(id=5, chapter_number=1, title="第一章", novel_content="手工保存的新正文")
    tracker = agent_service_module.PendingChangesTracker()
    tracker.record(agent_service_module.PendingChange(
        type="chapter",
        record_id=5,
        display_name="第1章",
        field="novel_content",
        old_value="原正文",
        new_value="Agent 写入正文",
    ))
    db = SimpleNamespace(get=lambda _model, _record_id, **_kwargs: chapter, commit=lambda: None)

    result = tracker.rollback(db)

    assert chapter.novel_content == "手工保存的新正文"
    assert result == [{
        "ok": False,
        "conflict": True,
        "type": "chapter",
        "id": 5,
        "field": "novel_content",
        "error": "内容已被再次修改，为避免覆盖新结果，本次未撤回",
    }]


def test_regenerated_neighbor_blocks_entire_workflow_shot_rollback():
    regenerated_neighbor = SimpleNamespace(id=51, workflow_id=9, storyboard_prompt_stale=False)
    edited_shot = SimpleNamespace(
        id=52,
        workflow_id=9,
        story_summary="Agent 写入的新剧情",
        storyboard_prompt_stale=True,
    )
    tracker = agent_service_module.PendingChangesTracker()
    tracker.record(agent_service_module.PendingChange(
        type="video_shot",
        record_id=52,
        display_name="镜头 2",
        field="story_summary",
        old_value="旧剧情",
        new_value="Agent 写入的新剧情",
    ))
    for target in (regenerated_neighbor, edited_shot):
        tracker.record(agent_service_module.PendingChange(
            type="video_shot",
            record_id=target.id,
            display_name="镜头",
            field="storyboard_prompt_stale",
            old_value=False,
            new_value=True,
        ))
    db = SimpleNamespace(
        get=lambda _model, record_id, **_kwargs: regenerated_neighbor if record_id == 51 else edited_shot,
        commit=lambda: None,
    )

    result = tracker.rollback(db)

    assert edited_shot.story_summary == "Agent 写入的新剧情"
    assert edited_shot.storyboard_prompt_stale is True
    assert result == [{
        "ok": False,
        "conflict": True,
        "type": "video_shot",
        "id": 51,
        "field": "storyboard_prompt_stale",
        "error": "故事板已重新生成，为避免覆盖新结果，未撤回该镜头的修改",
    }]


def test_persisted_video_rollback_detects_regenerated_storyboard(monkeypatch):
    shot = SimpleNamespace(
        id=12,
        story_summary="Agent 写入的新剧情",
        storyboard_prompt_stale=False,
    )
    records = [
        SimpleNamespace(
            change_type="video_shot",
            record_id=12,
            field="story_summary",
            old_value="旧剧情",
            new_value="Agent 写入的新剧情",
        ),
        SimpleNamespace(
            change_type="video_shot",
            record_id=12,
            field="storyboard_prompt_stale",
            old_value=False,
            new_value=True,
        ),
    ]

    class FakeQuery:
        def filter(self, *_args):
            return self

        def all(self):
            return list(records)

        def delete(self):
            records.clear()

    class FakeDb:
        def query(self, _model):
            return FakeQuery()

        def get(self, _model, _record_id, **_kwargs):
            if _model is agent_router.AgentConversation:
                return SimpleNamespace(
                    story_id=2,
                    owner_user_id=1,
                    active_run_id=None,
                    active_run_started_at=None,
                )
            return shot

        def commit(self):
            return None

    class FakeRequest:
        async def json(self):
            return {"conversation_id": 3}

    key = agent_service_module.AgentPendingChangeKey(user_id=1, story_id=2, conversation_id=3)
    monkeypatch.setattr(agent_router, "_require_user", lambda *_args: SimpleNamespace(id=1))
    monkeypatch.setattr(agent_router, "_require_story_for_user", lambda *_args: None)
    monkeypatch.setattr(agent_router, "_pending_change_key_from_request", lambda **_kwargs: key)

    result = asyncio.run(agent_router.rollback_changes(2, FakeRequest(), FakeDb()))

    assert shot.story_summary == "Agent 写入的新剧情"
    assert shot.storyboard_prompt_stale is False
    assert len(records) == 2
    assert result["pending_retained"] is True
    assert result["results"] == [{
        "ok": False,
        "conflict": True,
        "type": "video_shot",
        "id": 12,
        "field": "storyboard_prompt_stale",
        "error": "故事板已重新生成，为避免覆盖新结果，未撤回该镜头的修改",
    }]


def test_confirm_only_clears_pending_records_and_keeps_saved_content(monkeypatch):
    shot = SimpleNamespace(story_summary="确认后必须保留的剧情", storyboard_prompt="完整五区提示词")
    records = [SimpleNamespace(id=1)]

    class FakeQuery:
        def filter(self, *_args):
            return self

        def delete(self):
            records.clear()

    class FakeDb:
        def query(self, _model):
            return FakeQuery()

        def get(self, _model, _record_id, **_kwargs):
            return SimpleNamespace(
                story_id=2,
                owner_user_id=1,
                active_run_id=None,
                active_run_started_at=None,
            )

        def commit(self):
            return None

    class FakeRequest:
        async def json(self):
            return {"conversation_id": 3}

    key = agent_service_module.AgentPendingChangeKey(user_id=1, story_id=2, conversation_id=3)
    monkeypatch.setattr(agent_router, "_require_user", lambda *_args: SimpleNamespace(id=1))
    monkeypatch.setattr(agent_router, "_require_story_for_user", lambda *_args: None)
    monkeypatch.setattr(agent_router, "_pending_change_key_from_request", lambda **_kwargs: key)

    result = asyncio.run(agent_router.confirm_changes(2, FakeRequest(), FakeDb()))

    assert result["ok"] is True
    assert records == []
    assert shot.story_summary == "确认后必须保留的剧情"
    assert shot.storyboard_prompt == "完整五区提示词"
