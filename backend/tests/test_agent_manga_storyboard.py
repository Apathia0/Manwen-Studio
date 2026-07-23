import asyncio
from types import SimpleNamespace

import pytest

from services import agent_service as agent_service_module


class FakeQuery:
    def __init__(self, images=None):
        self.images = list(images or [])

    def filter(self, *_args):
        return self

    def order_by(self, *_args):
        return self

    def all(self):
        return list(self.images)


class FakeDb:
    def __init__(self, images=None):
        self.images = images or []

    def query(self, _model):
        return FakeQuery(self.images)

    def close(self):
        return None

    def commit(self):
        return None


@pytest.fixture
def manga_workspace(tmp_path, monkeypatch):
    chapter = SimpleNamespace(id=7, story_id=1, chapter_number=2, title="雨夜追踪")
    images = [SimpleNamespace(image_number=1), SimpleNamespace(image_number=3)]
    monkeypatch.setattr(agent_service_module, "BACKEND_DIR", tmp_path)
    monkeypatch.setattr(agent_service_module, "SessionLocal", lambda: FakeDb(images))
    monkeypatch.setattr(
        agent_service_module,
        "_validate_chapter_ownership",
        lambda _db, chapter_id, _story_id: chapter if chapter_id == chapter.id else None,
    )
    agent_service_module._write_scenes_text_atomic(
        chapter.id,
        agent_service_module._render_scenes_text(["第一格旧脚本", "第二格旧脚本", "第三格旧脚本"]),
    )
    return chapter


def _set_manga_context():
    tracker = agent_service_module.PendingChangesTracker()
    context = agent_service_module.AgentRunContext(
        story_id=1,
        api_key=None,
        mode="execute",
        pending_changes=tracker,
        workflow_type="manga",
        chapter_id=7,
    )
    token = agent_service_module._AGENT_RUN_CONTEXT.set(context)
    return tracker, token


def test_manga_workflow_only_exposes_safe_storyboard_writes():
    execute_names = {
        spec["function"]["name"]
        for spec in agent_service_module.tool_registry.get_tool_specs(
            mode="execute",
            workflow_type="manga",
        )
    }
    analyze_names = {
        spec["function"]["name"]
        for spec in agent_service_module.tool_registry.get_tool_specs(
            mode="analyze",
            workflow_type="manga",
        )
    }

    assert {
        "get_manga_storyboard",
        "update_manga_storyboard_scene",
        "batch_update_manga_storyboard_scenes",
        "replace_manga_storyboard",
    } <= execute_names
    assert "get_manga_storyboard" in analyze_names
    assert "update_manga_storyboard_scene" not in analyze_names
    assert "update_chapter_content" not in execute_names
    assert "update_shot_fields" not in execute_names


def test_get_manga_storyboard_returns_scripts_and_image_state(manga_workspace):
    result = asyncio.run(agent_service_module.get_manga_storyboard(manga_workspace.id))

    assert result["chapter_title"] == "雨夜追踪"
    assert result["scene_count"] == 3
    assert len(result["revision"]) == 64
    assert [scene["script"] for scene in result["scenes"]] == [
        "第一格旧脚本",
        "第二格旧脚本",
        "第三格旧脚本",
    ]
    assert [scene["has_generated_image"] for scene in result["scenes"]] == [True, False, True]


def test_single_scene_update_is_persisted_and_can_be_rolled_back(manga_workspace):
    tracker, context_token = _set_manga_context()
    try:
        result = asyncio.run(agent_service_module.update_manga_storyboard_scene(
            manga_workspace.id,
            2,
            "第二格新脚本：角色转身看向门口",
        ))
    finally:
        agent_service_module._AGENT_RUN_CONTEXT.reset(context_token)

    assert result["ok"] is True
    assert result["updated_scene_indices"] == [2]
    assert result["images_preserved"] is True
    assert agent_service_module._parse_scenes_text(
        agent_service_module._scenes_path(manga_workspace.id).read_text(encoding="utf-8")
    )[1] == "第二格新脚本：角色转身看向门口"
    assert [change.type for change in tracker._changes] == ["scenes_file"]

    rollback_db = SimpleNamespace(commit=lambda: None)
    rollback_result = tracker.rollback(rollback_db)

    assert rollback_result[0]["ok"] is True
    assert agent_service_module._parse_scenes_text(
        agent_service_module._scenes_path(manga_workspace.id).read_text(encoding="utf-8")
    ) == ["第一格旧脚本", "第二格旧脚本", "第三格旧脚本"]


def test_batch_scene_update_writes_all_changes_once(manga_workspace):
    tracker, context_token = _set_manga_context()
    try:
        result = asyncio.run(agent_service_module.batch_update_manga_storyboard_scenes(
            manga_workspace.id,
            [
                {"scene_index": 1, "script": "第一格新脚本"},
                {"scene_index": 3, "script": "第三格新脚本"},
            ],
        ))
    finally:
        agent_service_module._AGENT_RUN_CONTEXT.reset(context_token)

    assert result["updated_scene_indices"] == [1, 3]
    assert agent_service_module._parse_scenes_text(
        agent_service_module._scenes_path(manga_workspace.id).read_text(encoding="utf-8")
    ) == ["第一格新脚本", "第二格旧脚本", "第三格新脚本"]
    assert len(tracker._changes) == 1


def test_replace_storyboard_rejects_structural_change_when_images_exist(manga_workspace):
    tracker, context_token = _set_manga_context()
    try:
        current = asyncio.run(agent_service_module.get_manga_storyboard(manga_workspace.id))
        result = asyncio.run(agent_service_module.replace_manga_storyboard(
            manga_workspace.id,
            ["重排后的第一格", "新增的第二格"],
            current["revision"],
        ))
    finally:
        agent_service_module._AGENT_RUN_CONTEXT.reset(context_token)

    assert result["structural_change_denied"] is True
    assert result["generated_image_indices"] == [1, 3]
    assert tracker.get_summary() == []


def test_replace_storyboard_supports_structural_change_without_images(manga_workspace, monkeypatch):
    monkeypatch.setattr(agent_service_module, "SessionLocal", lambda: FakeDb([]))
    tracker, context_token = _set_manga_context()
    try:
        current = asyncio.run(agent_service_module.get_manga_storyboard(manga_workspace.id))
        result = asyncio.run(agent_service_module.replace_manga_storyboard(
            manga_workspace.id,
            ["重排后的第一格", "新增的第二格"],
            current["revision"],
        ))
    finally:
        agent_service_module._AGENT_RUN_CONTEXT.reset(context_token)

    assert result["ok"] is True
    assert result["scene_count"] == 2
    assert len(tracker.get_summary()) == 1


def test_replace_storyboard_rejects_stale_revision(manga_workspace, monkeypatch):
    monkeypatch.setattr(agent_service_module, "SessionLocal", lambda: FakeDb([]))
    current = asyncio.run(agent_service_module.get_manga_storyboard(manga_workspace.id))
    agent_service_module._write_scenes_text_atomic(
        manga_workspace.id,
        agent_service_module._render_scenes_text(["其他会话的新脚本"]),
    )

    result = asyncio.run(agent_service_module.replace_manga_storyboard(
        manga_workspace.id,
        ["过期会话准备覆盖的脚本"],
        current["revision"],
    ))

    assert result["conflict"] is True
    assert agent_service_module._parse_scenes_text(
        agent_service_module._scenes_path(manga_workspace.id).read_text(encoding="utf-8")
    ) == ["其他会话的新脚本"]


def test_manga_write_rejects_unowned_chapter(manga_workspace):
    result = asyncio.run(agent_service_module.update_manga_storyboard_scene(
        999,
        1,
        "无权写入",
    ))

    assert result == {"error": "章节不存在或无权访问"}


def test_manga_context_rejects_sibling_chapter():
    sibling = SimpleNamespace(id=8, story_id=1)
    db = SimpleNamespace(get=lambda _model, _record_id: sibling)
    tracker, context_token = _set_manga_context()
    try:
        result = agent_service_module._validate_chapter_ownership(db, sibling.id, 1)
    finally:
        agent_service_module._AGENT_RUN_CONTEXT.reset(context_token)

    assert result is None


@pytest.mark.parametrize(
    "message",
    [
        "直接修改漫画分镜第2格",
        "把第三格脚本重写后保存",
        "批量优化这些画格并写入",
        "把第2格改成角色回头看门口",
        "删除第2格并保存",
        "在第3格后新增一格",
        "我已经修改了第1格，现在请删除第2格",
        "已经优化后的分镜，现在把第2格改成夜景",
    ],
)
def test_manga_mutation_intent_accepts_explicit_commands(message):
    assert agent_service_module.has_manga_storyboard_mutation_intent(message) is True


@pytest.mark.parametrize(
    "message",
    [
        "这个漫画分镜有什么优化建议？",
        "先分析画格，不要修改",
        "当前漫画效果怎么样",
        "我已经修改了漫画分镜第2格",
        "优化后的漫画分镜第2格很好",
        "不要删除第2格",
        "先不要新增画格",
        "不要对漫画分镜第2格进行删除",
        "请不要对第2格做任何形式的修改",
    ],
)
def test_manga_mutation_intent_rejects_advice(message):
    assert agent_service_module.has_manga_storyboard_mutation_intent(message) is False


def test_manga_write_result_requires_real_change():
    assert agent_service_module._manga_write_result_changed(
        '{"ok": true, "changed": true, "updated_scene_indices": [2]}'
    ) is True


@pytest.mark.parametrize("revision", [None, "", "not-a-revision", "A" * 64])
def test_replace_storyboard_rejects_invalid_revision(manga_workspace, revision):
    result = asyncio.run(agent_service_module.replace_manga_storyboard(
        manga_workspace.id,
        ["不会被写入"],
        revision,
    ))

    assert "expected_revision" in result["error"]
    assert agent_service_module._manga_write_result_changed(
        '{"ok": true, "changed": false, "updated_scene_indices": []}'
    ) is True


def test_manga_execute_blocks_non_manga_write_tool():
    tracker, context_token = _set_manga_context()
    try:
        result = asyncio.run(agent_service_module.tool_registry.execute(
            "update_scenes",
            {"chapter_id": 7, "scenes": ["绕过写入"]},
        ))
    finally:
        agent_service_module._AGENT_RUN_CONTEXT.reset(context_token)

    assert '"workflow_tool_denied": true' in result
    assert tracker.get_summary() == []


def test_manga_analyze_prompt_does_not_require_writes():
    prompt = agent_service_module.agent_service._build_system_prompt(
        "测试上下文",
        story_id=1,
        workflow_type="manga",
        mode="analyze",
    )

    assert "当前是只读分析模式" in prompt
    assert "禁止调用或声称调用任何写入工具" in prompt
