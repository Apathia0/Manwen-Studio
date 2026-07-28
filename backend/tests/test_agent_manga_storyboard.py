import asyncio
from types import SimpleNamespace

import pytest

import main
from schemas import MangaStoryboardImportCommitIn, MangaStoryboardImportPreviewIn
from services import agent_service as agent_service_module
from services.manga_storyboard_import import END_MARKER, START_MARKER, parse_import_text
from services.manga_storyboard_storage import canonical_scenes_hash, content_revision


def test_single_image_regeneration_uses_module_media_locator():
    assert "ensure_local_media_path" not in main.regenerate_single_image.__code__.co_varnames


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
