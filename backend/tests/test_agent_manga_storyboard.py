import asyncio
import json
from types import SimpleNamespace

import pytest

import main
from schemas import MangaStoryboardImportCommitIn, MangaStoryboardImportPreviewIn
from services import agent_service as agent_service_module
from services.manga_storyboard_import import END_MARKER, START_MARKER, parse_import_text
from services.manga_storyboard_storage import canonical_scenes_hash, content_revision


def test_single_image_regeneration_uses_module_media_locator():
    assert "ensure_local_media_path" not in main.regenerate_single_image.__code__.co_varnames


def test_manga_aspect_ratio_is_persisted_on_chapter(monkeypatch):
    class AspectRatioDb:
        def __init__(self):
            self.commit_count = 0

        def commit(self):
            self.commit_count += 1

    chapter = SimpleNamespace(id=7, manga_aspect_ratio="9:16")
    db = AspectRatioDb()
    monkeypatch.setattr(main, "_require_user", lambda *_args: SimpleNamespace(id=1))
    monkeypatch.setattr(main, "_require_chapter_for_user", lambda *_args: chapter)

    saved = asyncio.run(main.set_manga_aspect_ratio(
        chapter.id,
        {"aspect_ratio": "16:9"},
        SimpleNamespace(),
        db,
    ))
    loaded = asyncio.run(main.get_manga_aspect_ratio(chapter.id, SimpleNamespace(), db))

    assert saved == {"ok": True, "aspect_ratio": "16:9"}
    assert loaded == {"aspect_ratio": "16:9"}
    assert chapter.manga_aspect_ratio == "16:9"
    assert db.commit_count == 1


def test_manga_aspect_ratio_defaults_and_rejects_unknown_values(monkeypatch):
    class AspectRatioDb:
        def commit(self):
            raise AssertionError("非法比例不应提交数据库")

    chapter = SimpleNamespace(id=8, manga_aspect_ratio=None)
    monkeypatch.setattr(main, "_require_user", lambda *_args: SimpleNamespace(id=1))
    monkeypatch.setattr(main, "_require_chapter_for_user", lambda *_args: chapter)

    loaded = asyncio.run(main.get_manga_aspect_ratio(chapter.id, SimpleNamespace(), AspectRatioDb()))

    with pytest.raises(main.HTTPException, match="漫画比例不受支持"):
        asyncio.run(main.set_manga_aspect_ratio(
            chapter.id,
            {"aspect_ratio": "5:7"},
            SimpleNamespace(),
            AspectRatioDb(),
        ))

    assert loaded == {"aspect_ratio": "9:16"}


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

    def rollback(self):
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
        pending_changes=tracker,
        workflow_type="manga",
        chapter_id=7,
    )
    token = agent_service_module._AGENT_RUN_CONTEXT.set(context)
    return tracker, token


def test_manga_workflow_exposes_safe_storyboard_tools_to_single_agent():
    agent_names = {
        spec["function"]["name"]
        for spec in agent_service_module.tool_registry.get_tool_specs(
            mode="agent",
            workflow_type="manga",
        )
    }

    assert {
        "get_manga_storyboard",
        "get_manga_asset_prompts",
        "update_manga_storyboard_scene",
        "batch_update_manga_storyboard_scenes",
        "replace_manga_storyboard",
        "update_manga_asset_prompts",
    } <= agent_names
    assert "update_chapter_content" not in agent_names
    assert "update_shot_fields" not in agent_names


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


class AssetPromptDb:
    def __init__(self, chapter, *, fail_commit=False):
        self.chapter = chapter
        self.fail_commit = fail_commit
        self.commit_count = 0
        self.rollback_count = 0
        self.get_calls = []
        self.ownership_calls = []
        self._committed_payload = agent_service_module.copy.deepcopy(chapter.manga_asset_analysis_json)

    def get(self, model, record_id, **_kwargs):
        self.get_calls.append((model.__name__, record_id, _kwargs))
        if model.__name__ == "Chapter" and self.chapter.id == record_id:
            return self.chapter
        return None

    def commit(self):
        self.commit_count += 1
        if self.fail_commit:
            raise RuntimeError("模拟提交失败")
        self._committed_payload = agent_service_module.copy.deepcopy(self.chapter.manga_asset_analysis_json)

    def rollback(self):
        self.rollback_count += 1
        self.chapter.manga_asset_analysis_json = agent_service_module.copy.deepcopy(self._committed_payload)

    def close(self):
        return None


@pytest.fixture
def manga_asset_workspace(monkeypatch):
    chapter = SimpleNamespace(
        id=7,
        story_id=1,
        chapter_number=2,
        title="雨夜追踪",
        manga_asset_analysis_json={
            "version": 3,
            "status": "ready",
            "input_hash": "输入版本",
            "suggestions": [
                {
                    "asset_type": "character_reference",
                    "name": "陈玄",
                    "description": "黑衣青年",
                    "evidence": "第二段出现",
                    "prompt": "旧角色提示词",
                    "candidates": [{"id": 11, "url": "/static/character.png"}],
                },
                {
                    "asset_type": "scene_reference",
                    "name": "雨巷",
                    "description": "石板路与昏黄路灯",
                    "evidence": "开场地点",
                    "prompt": "旧场景提示词",
                    "candidates": [],
                },
                {
                    "asset_type": "prop_reference",
                    "name": "铜钥匙",
                    "description": "磨损的旧钥匙",
                    "evidence": "角色手中",
                    "prompt": "旧道具提示词",
                    "candidates": [{"id": 12}],
                },
            ],
            "extra": {"保留字段": True},
        },
    )
    db = AssetPromptDb(chapter)
    monkeypatch.setattr(agent_service_module, "SessionLocal", lambda: db)
    def validate_ownership(_db, chapter_id, _story_id, **kwargs):
        _db.ownership_calls.append(kwargs)
        return chapter if chapter_id == chapter.id else None

    monkeypatch.setattr(agent_service_module, "_validate_chapter_ownership", validate_ownership)
    return chapter, db


def test_get_manga_asset_prompts_returns_stable_indices_and_revision(manga_asset_workspace):
    chapter, _db = manga_asset_workspace

    result = asyncio.run(agent_service_module.get_manga_asset_prompts(chapter.id))

    assert len(result["revision"]) == 64
    assert result["revision"] == agent_service_module._manga_asset_analysis_revision(
        chapter.manga_asset_analysis_json
    )
    assert result["suggestions"] == [
        {
            "suggestion_index": 1,
            "asset_type": "character_reference",
            "name": "陈玄",
            "description": "黑衣青年",
            "prompt": "旧角色提示词",
        },
        {
            "suggestion_index": 2,
            "asset_type": "scene_reference",
            "name": "雨巷",
            "description": "石板路与昏黄路灯",
            "prompt": "旧场景提示词",
        },
        {
            "suggestion_index": 3,
            "asset_type": "prop_reference",
            "name": "铜钥匙",
            "description": "磨损的旧钥匙",
            "prompt": "旧道具提示词",
        },
    ]


def test_get_manga_asset_prompts_returns_readable_empty_result(manga_asset_workspace):
    chapter, _db = manga_asset_workspace
    chapter.manga_asset_analysis_json = None

    result = asyncio.run(agent_service_module.get_manga_asset_prompts(chapter.id))

    assert result["suggestions"] == []
    assert len(result["revision"]) == 64
    assert "尚无资产分析提示词" in result["message"]


def test_update_manga_asset_prompts_batches_and_preserves_metadata(manga_asset_workspace):
    chapter, db = manga_asset_workspace
    current = asyncio.run(agent_service_module.get_manga_asset_prompts(chapter.id))
    tracker, context_token = _set_manga_context()
    try:
        result = asyncio.run(agent_service_module.update_manga_asset_prompts(
            chapter.id,
            [
                {"suggestion_index": 1, "prompt": "  新角色提示词  "},
                {"suggestion_index": 3, "prompt": "新道具提示词"},
            ],
            current["revision"],
        ))
    finally:
        agent_service_module._AGENT_RUN_CONTEXT.reset(context_token)

    assert result["ok"] is True
    assert result["changed"] is True
    assert result["updated_suggestion_indices"] == [1, 3]
    assert [item["name"] for item in result["updated_assets"]] == ["陈玄", "铜钥匙"]
    assert db.commit_count == 1
    assert {"with_for_update": True} in db.ownership_calls
    suggestions = chapter.manga_asset_analysis_json["suggestions"]
    assert [item["prompt"] for item in suggestions] == [
        "新角色提示词",
        "旧场景提示词",
        "新道具提示词",
    ]
    assert suggestions[0]["evidence"] == "第二段出现"
    assert suggestions[0]["candidates"] == [{"id": 11, "url": "/static/character.png"}]
    assert chapter.manga_asset_analysis_json["extra"] == {"保留字段": True}
    assert len(tracker._changes) == 1
    change = tracker._changes[0]
    assert change.field == "manga_asset_analysis_json"
    assert change.old_value["suggestions"][0]["prompt"] == "旧角色提示词"
    assert change.new_value["suggestions"][0]["prompt"] == "新角色提示词"


def test_manga_asset_prompt_update_can_be_rolled_back(manga_asset_workspace):
    chapter, db = manga_asset_workspace
    original = agent_service_module.copy.deepcopy(chapter.manga_asset_analysis_json)
    revision = agent_service_module._manga_asset_analysis_revision(original)
    tracker, context_token = _set_manga_context()
    try:
        result = asyncio.run(agent_service_module.update_manga_asset_prompts(
            chapter.id,
            [{"suggestion_index": 2, "prompt": "修改后的雨巷提示词"}],
            revision,
        ))
    finally:
        agent_service_module._AGENT_RUN_CONTEXT.reset(context_token)

    rollback_result = tracker.rollback(db)

    assert result["changed"] is True
    assert rollback_result == [{
        "ok": True,
        "type": "chapter",
        "id": chapter.id,
        "field": "manga_asset_analysis_json",
    }]
    assert chapter.manga_asset_analysis_json == original


def test_manga_asset_prompt_noop_does_not_commit_or_record_pending(manga_asset_workspace):
    chapter, db = manga_asset_workspace
    revision = agent_service_module._manga_asset_analysis_revision(chapter.manga_asset_analysis_json)
    tracker, context_token = _set_manga_context()
    try:
        result = asyncio.run(agent_service_module.update_manga_asset_prompts(
            chapter.id,
            [{"suggestion_index": 1, "prompt": "  旧角色提示词  "}],
            revision,
        ))
    finally:
        agent_service_module._AGENT_RUN_CONTEXT.reset(context_token)

    assert result["ok"] is True
    assert result["changed"] is False
    assert result["updated_suggestion_indices"] == []
    assert db.commit_count == 0
    assert tracker.get_summary() == []


def test_update_manga_asset_prompts_rejects_revision_conflict_without_writing(manga_asset_workspace):
    chapter, db = manga_asset_workspace
    original = agent_service_module.copy.deepcopy(chapter.manga_asset_analysis_json)

    result = asyncio.run(agent_service_module.update_manga_asset_prompts(
        chapter.id,
        [{"suggestion_index": 1, "prompt": "不应写入"}],
        "0" * 64,
    ))

    assert result["conflict"] is True
    assert result["current_revision"] == agent_service_module._manga_asset_analysis_revision(original)
    assert chapter.manga_asset_analysis_json == original
    assert db.commit_count == 0


def test_update_manga_asset_prompts_rejects_out_of_range_index(manga_asset_workspace):
    chapter, db = manga_asset_workspace
    revision = agent_service_module._manga_asset_analysis_revision(chapter.manga_asset_analysis_json)

    result = asyncio.run(agent_service_module.update_manga_asset_prompts(
        chapter.id,
        [{"suggestion_index": 4, "prompt": "不存在的资产"}],
        revision,
    ))

    assert "超出范围" in result["error"]
    assert db.commit_count == 0


def test_manga_asset_prompt_tools_only_expose_supported_asset_types(manga_asset_workspace):
    chapter, db = manga_asset_workspace
    chapter.manga_asset_analysis_json["suggestions"].append({
        "asset_type": "style_reference",
        "name": "不应暴露的风格图",
        "prompt": "不应修改",
    })
    revision = agent_service_module._manga_asset_analysis_revision(chapter.manga_asset_analysis_json)

    read_result = asyncio.run(agent_service_module.get_manga_asset_prompts(chapter.id))
    write_result = asyncio.run(agent_service_module.update_manga_asset_prompts(
        chapter.id,
        [{"suggestion_index": 4, "prompt": "不应写入"}],
        revision,
    ))

    assert [item["name"] for item in read_result["suggestions"]] == ["陈玄", "雨巷", "铜钥匙"]
    assert "不是可修改的角色、场景或道具资产" in write_result["error"]
    assert db.commit_count == 0


def test_manga_asset_prompt_write_tool_uses_its_own_revision_guard(manga_asset_workspace):
    chapter, _db = manga_asset_workspace
    revision = agent_service_module._manga_asset_analysis_revision(chapter.manga_asset_analysis_json)
    tracker = agent_service_module.PendingChangesTracker()
    context = agent_service_module.AgentRunContext(
        story_id=1,
        api_key=None,
        pending_changes=tracker,
        workflow_type="manga",
        chapter_id=chapter.id,
        enabled_skills=["manga_workflow"],
        run_id="asset-prompt-run",
    )
    context_token = agent_service_module._AGENT_RUN_CONTEXT.set(context)
    try:
        result = json.loads(asyncio.run(agent_service_module.tool_registry.execute(
            "update_manga_asset_prompts",
            {
                "chapter_id": chapter.id,
                "updates": [{"suggestion_index": 2, "prompt": "新场景提示词"}],
                "expected_revision": revision,
            },
        )))
    finally:
        agent_service_module._AGENT_RUN_CONTEXT.reset(context_token)

    assert result["ok"] is True
    assert result["updated_suggestion_indices"] == [2]
    assert chapter.manga_asset_analysis_json["suggestions"][1]["prompt"] == "新场景提示词"


@pytest.mark.parametrize(
    ("updates", "revision", "error_fragment"),
    [
        ([], "0" * 64, "非空数组"),
        ([{"suggestion_index": 1, "prompt": "a"}, {"suggestion_index": 1, "prompt": "b"}], "0" * 64, "重复"),
        ([{"suggestion_index": 1, "prompt": "   "}], "0" * 64, "不能为空"),
        ([{"suggestion_index": 1, "prompt": "x" * 24001}], "0" * 64, "24000"),
        ([{"suggestion_index": 1, "prompt": "有效"}], "非法版本", "expected_revision"),
    ],
)
def test_update_manga_asset_prompts_rejects_invalid_input(
    manga_asset_workspace,
    updates,
    revision,
    error_fragment,
):
    _chapter, db = manga_asset_workspace

    result = asyncio.run(agent_service_module.update_manga_asset_prompts(7, updates, revision))

    assert error_fragment in result["error"]
    assert db.commit_count == 0


def test_manga_asset_prompt_tools_reject_sibling_chapter(manga_asset_workspace):
    _chapter, db = manga_asset_workspace

    read_result = asyncio.run(agent_service_module.get_manga_asset_prompts(8))
    write_result = asyncio.run(agent_service_module.update_manga_asset_prompts(
        8,
        [{"suggestion_index": 1, "prompt": "越权修改"}],
        "0" * 64,
    ))

    assert read_result == {"error": "章节不存在或无权访问"}
    assert write_result == {"error": "章节不存在或无权访问"}
    assert db.commit_count == 0


def test_manga_asset_prompt_commit_failure_restores_pending_snapshot(
    manga_asset_workspace,
    monkeypatch,
):
    chapter, _db = manga_asset_workspace
    failing_db = AssetPromptDb(chapter, fail_commit=True)
    monkeypatch.setattr(agent_service_module, "SessionLocal", lambda: failing_db)
    revision = agent_service_module._manga_asset_analysis_revision(chapter.manga_asset_analysis_json)
    original = agent_service_module.copy.deepcopy(chapter.manga_asset_analysis_json)
    tracker, context_token = _set_manga_context()
    try:
        result = asyncio.run(agent_service_module.update_manga_asset_prompts(
            chapter.id,
            [{"suggestion_index": 2, "prompt": "提交失败的新提示词"}],
            revision,
        ))
    finally:
        agent_service_module._AGENT_RUN_CONTEXT.reset(context_token)

    assert "模拟提交失败" in result["error"]
    assert failing_db.rollback_count == 1
    assert chapter.manga_asset_analysis_json == original
    assert tracker.get_summary() == []
    assert tracker._changes == []


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

    # 兼容文件即使丢失，撤回也必须依据数据库中的当前版本判断冲突。
    agent_service_module._scenes_path(manga_workspace.id).unlink()

    rollback_db = SimpleNamespace(
        get=lambda model, record_id: manga_workspace
        if model.__name__ == "Chapter" and record_id == manga_workspace.id
        else None,
        commit=lambda: None,
    )
    rollback_result = tracker.rollback(rollback_db)

    assert rollback_result[0]["ok"] is True
    assert agent_service_module._parse_scenes_text(
        agent_service_module._scenes_path(manga_workspace.id).read_text(encoding="utf-8")
    ) == ["第一格旧脚本", "第二格旧脚本", "第三格旧脚本"]
    assert manga_workspace.manga_storyboard_json["scenes"] == [
        "第一格旧脚本",
        "第二格旧脚本",
        "第三格旧脚本",
    ]


def test_agent_scene_update_prefers_database_when_file_is_stale(manga_workspace):
    manga_workspace.manga_storyboard_json = {
        "schema_version": 1,
        "scenes": ["数据库第一格", "数据库第二格", "数据库第三格"],
        "sanitized_indices": [],
    }
    tracker, context_token = _set_manga_context()
    try:
        result = asyncio.run(agent_service_module.update_manga_storyboard_scene(
            manga_workspace.id,
            2,
            "数据库第二格已更新",
        ))
    finally:
        agent_service_module._AGENT_RUN_CONTEXT.reset(context_token)

    assert result["ok"] is True
    assert manga_workspace.manga_storyboard_json["scenes"] == [
        "数据库第一格",
        "数据库第二格已更新",
        "数据库第三格",
    ]
    assert agent_service_module._parse_scenes_text(
        agent_service_module._scenes_path(manga_workspace.id).read_text(encoding="utf-8")
    ) == manga_workspace.manga_storyboard_json["scenes"]
    assert tracker._changes[0].old_value == agent_service_module._render_scenes_text([
        "数据库第一格",
        "数据库第二格",
        "数据库第三格",
    ])


def test_agent_database_failure_does_not_replace_compatibility_file(manga_workspace, monkeypatch):
    class FailingCommitDb(FakeDb):
        def commit(self):
            raise RuntimeError("数据库提交失败")

    original_text = agent_service_module._scenes_path(manga_workspace.id).read_text(encoding="utf-8")
    monkeypatch.setattr(agent_service_module, "SessionLocal", lambda: FailingCommitDb([]))

    result = agent_service_module._save_manga_storyboard_scenes(
        manga_workspace.id,
        ["失败后的第一格", "失败后的第二格", "失败后的第三格"],
        expected_old_text=original_text,
    )

    assert "error" in result
    assert agent_service_module._scenes_path(manga_workspace.id).read_text(encoding="utf-8") == original_text


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


class ImportQuery:
    def __init__(self, rows=None, active_task=None):
        self.rows = list(rows or [])
        self.active_task = active_task

    def filter(self, *_args):
        return self

    def all(self):
        return list(self.rows)

    def first(self):
        return self.active_task


class ImportDb:
    def __init__(self, image_indices=None, chapter=None):
        self.image_indices = list(image_indices or [])
        self.chapter = chapter
        self.commit_count = 0

    def query(self, entity):
        if getattr(entity, "key", None) == "image_number":
            rows = [SimpleNamespace(image_number=index) for index in self.image_indices]
            return ImportQuery(rows)
        return ImportQuery()

    def get(self, model, record_id):
        if model.__name__ == "Chapter" and self.chapter and self.chapter.id == record_id:
            return self.chapter
        return None

    def add(self, _record):
        return None

    def commit(self):
        self.commit_count += 1

    def rollback(self):
        return None


def test_import_parser_requires_markers_for_plain_content():
    unmarked = parse_import_text("这是普通章节正文。", require_markers_for_prose=True)
    marked = parse_import_text(
        f"{START_MARKER}\n第一格正文\n\n第二格正文\n{END_MARKER}",
        require_markers_for_prose=True,
    )

    assert unmarked["errors"]
    assert marked["scenes"] == ["第一格正文", "第二格正文"]


def test_import_parser_rejects_empty_heading_scene():
    result = parse_import_text(
        f"{START_MARKER}\n=== 第1格 ===\n\n=== 第2格 ===\n第二格正文\n{END_MARKER}",
        require_markers_for_prose=True,
    )

    assert result["scenes"] == []
    assert result["errors"] == ["第 1 格脚本为空"]


def test_import_parser_accepts_simple_episode_headings():
    result = parse_import_text(
        "第一话\n画面：雨夜推门\n对白：还有人在吗？\n\n"
        "第二话\n画面：男人抬头\n对白：等你很久了。\n\n"
        "第三话：\n画面：两人对视",
        require_markers_for_prose=True,
    )

    assert result["errors"] == []
    assert result["scenes"] == [
        "画面：雨夜推门\n对白：还有人在吗？",
        "画面：男人抬头\n对白：等你很久了。",
        "画面：两人对视",
    ]


def test_import_parser_accepts_episode_headings_up_to_twenty():
    headings = [
        "第一话",
        "第二话",
        "第三话",
        "第四话",
        "第五话",
        "第六话",
        "第七话",
        "第八话",
        "第九话",
        "第十话",
        "第十一话",
        "第十二话",
        "第十三话",
        "第十四话",
        "第十五话",
        "第十六话",
        "第十七话",
        "第十八话",
        "第十九话",
        "第二十话",
    ]
    text = "\n\n".join(f"{heading}\n画面：第 {index} 格" for index, heading in enumerate(headings, start=1))

    result = parse_import_text(text, require_markers_for_prose=True)

    assert result["errors"] == []
    assert len(result["scenes"]) == 20


def test_import_preview_and_same_count_commit_report_stale_images(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "__file__", str(tmp_path / "main.py"))
    monkeypatch.setattr(main, "_require_user", lambda *_args: SimpleNamespace(id=5))
    chapter = SimpleNamespace(id=7, story_id=3, novel_content=(
        f"{START_MARKER}\n旧第一格\n\n旧第二格\n{END_MARKER}"
    ))
    monkeypatch.setattr(main, "_require_chapter_for_user", lambda *_args: chapter)
    chapter.manga_storyboard_json = None
    db = ImportDb([1], chapter)
    preview = asyncio.run(main.preview_manga_storyboard(
        chapter.id,
        MangaStoryboardImportPreviewIn(source_kind="chapter_content"),
        SimpleNamespace(),
        db,
    ))
    main._write_scenes_file(chapter.id, preview["scenes"], [], db=db, chapter=chapter)
    raw = (tmp_path / "manga_outputs" / "chapter_7" / "scenes.txt").read_text(encoding="utf-8")
    scenes = ["尸体位于走廊", "旧第二格"]

    result = asyncio.run(main.commit_manga_storyboard_import(
        chapter.id,
        MangaStoryboardImportCommitIn(
            scenes=scenes,
            expected_revision=content_revision(raw),
            canonical_hash=canonical_scenes_hash(scenes),
        ),
        SimpleNamespace(),
        db,
    ))

    assert preview["scene_count"] == 2
    assert result["stale_image_indices"] == [1]
    assert "尸体" not in result["scenes"][0]
    assert chapter.manga_storyboard_json["scenes"] == result["scenes"]
    assert db.commit_count == 2

    scenes_file = tmp_path / "manga_outputs" / "chapter_7" / "scenes.txt"
    scenes_file.unlink()
    loaded = asyncio.run(main.get_scenes_endpoint(chapter.id, SimpleNamespace(), db))

    assert loaded["scenes"] == result["scenes"]
    assert scenes_file.exists()


def test_get_scenes_lazily_backfills_legacy_file_into_database(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "__file__", str(tmp_path / "main.py"))
    monkeypatch.setattr(main, "_require_user", lambda *_args: SimpleNamespace(id=5))
    chapter = SimpleNamespace(id=8, manga_storyboard_json=None)
    monkeypatch.setattr(main, "_require_chapter_for_user", lambda *_args: chapter)
    db = ImportDb([], chapter)
    main.write_scenes_text_atomic(
        tmp_path,
        chapter.id,
        main.render_scenes_text(["历史第一格", "历史第二格"]),
    )

    loaded = asyncio.run(main.get_scenes_endpoint(chapter.id, SimpleNamespace(), db))

    assert loaded["scenes"] == ["历史第一格", "历史第二格"]
    assert chapter.manga_storyboard_json["scenes"] == loaded["scenes"]
    assert db.commit_count == 1


def test_get_scenes_rejects_legacy_file_over_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "__file__", str(tmp_path / "main.py"))
    monkeypatch.setattr(main, "_require_user", lambda *_args: SimpleNamespace(id=5))
    chapter = SimpleNamespace(id=10, manga_storyboard_json=None)
    monkeypatch.setattr(main, "_require_chapter_for_user", lambda *_args: chapter)
    db = ImportDb([], chapter)
    main.write_scenes_text_atomic(
        tmp_path,
        chapter.id,
        main.render_scenes_text([f"第 {index} 格" for index in range(1, 22)]),
    )

    with pytest.raises(main.HTTPException, match="历史分镜数量必须"):
        asyncio.run(main.get_scenes_endpoint(chapter.id, SimpleNamespace(), db))

    assert chapter.manga_storyboard_json is None
    assert db.commit_count == 0


def test_get_scenes_prefers_database_over_stale_file(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "__file__", str(tmp_path / "main.py"))
    monkeypatch.setattr(main, "_require_user", lambda *_args: SimpleNamespace(id=5))
    chapter = SimpleNamespace(
        id=9,
        manga_storyboard_json={
            "schema_version": 1,
            "scenes": ["数据库第一格", "数据库第二格"],
            "sanitized_indices": [],
        },
    )
    monkeypatch.setattr(main, "_require_chapter_for_user", lambda *_args: chapter)
    db = ImportDb([], chapter)
    main.write_scenes_text_atomic(tmp_path, chapter.id, main.render_scenes_text(["旧文件内容"]))

    loaded = asyncio.run(main.get_scenes_endpoint(chapter.id, SimpleNamespace(), db))
    mirrored = (tmp_path / "manga_outputs" / "chapter_9" / "scenes.txt").read_text(encoding="utf-8")

    assert loaded["scenes"] == ["数据库第一格", "数据库第二格"]
    assert main._parse_scenes_text(mirrored) == loaded["scenes"]


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
        "把角色提示词改成黑色长风衣并保存",
        "请优化当前章节的场景提示词并保持与角色画风一致",
        "直接修改道具提示词中的材质描述",
        "更新资产提示词并写入",
        "把设定图提示词改得更适合正面全身立绘",
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
        "请优化当前章节的场景提示词",
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
    ) is False


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


def test_manga_prompt_describes_single_agent_write_boundary():
    prompt = agent_service_module.agent_service._build_system_prompt(
        "测试上下文",
        story_id=1,
        workflow_type="manga",
        mode="agent",
    )

    assert "系统采用单一 Agent" in prompt
    assert "用户明确要求修改时才允许调用对应写入工具" in prompt
    assert "get_manga_asset_prompts" in prompt
    assert "update_manga_asset_prompts" in prompt
    assert "必须先读取当前资产提示词" in prompt
