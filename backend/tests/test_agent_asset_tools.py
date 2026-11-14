"""验证 Agent 助手新增/修改资产工具的授权边界与回滚语义。"""

from types import SimpleNamespace

import pytest

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
        "pending_changes": agent_service.PendingChangesTracker(),
        "workflow_type": "manga",
        "workflow_id": None,
        "chapter_id": 10,
        "pending_change_key": agent_service.AgentPendingChangeKey(
            user_id=1, story_id=1, conversation_id="conv-1"
        ),
        "enabled_skills": None,
    }
    values.update(overrides)
    return agent_service.AgentRunContext(**values)


def _chapter(**overrides):
    values = {
        "id": 10,
        "story_id": 1,
        "chapter_number": 3,
        "title": "测试章节",
        "story": SimpleNamespace(owner_user_id=1),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _workflow(**overrides):
    values = {"id": 5, "story_id": 1, "chapter_id": 10}
    values.update(overrides)
    return SimpleNamespace(**values)


class FakeQuery:
    """支持 filter / order_by / with_for_update 链式调用与 all / delete 的假查询。"""

    def __init__(self, rows=None):
        self.rows = rows or []
        self.deleted_count = 0

    def filter(self, *_args, **_kwargs):
        return self

    def order_by(self, *_args, **_kwargs):
        return self

    def with_for_update(self, *_args, **_kwargs):
        return self

    def all(self):
        return self.rows

    def delete(self, synchronize_session=False):
        count = len(self.rows)
        self.rows = []
        self.deleted_count = count
        return count


class FakeDb:
    """模拟 SessionLocal 会话：记录新增/删除并支持 get/query。"""

    def __init__(self, objects=None):
        self.objects = dict(objects or {})
        self.added = []
        self.deleted = []
        self.query_result = []
        self.committed = 0
        self.flushed = 0
        self.refreshed = []

    def add(self, obj):
        self.added.append(obj)

    def flush(self):
        self.flushed += 1

    def commit(self):
        self.committed += 1

    def refresh(self, obj):
        self.refreshed.append(obj)

    def rollback(self):
        pass

    def close(self):
        pass

    def get(self, _model, record_id, **_kwargs):
        return self.objects.get(record_id)

    def delete(self, obj):
        self.deleted.append(obj)

    def query(self, _model):
        return FakeQuery(self.query_result)


# ── 1. 授权白名单 ──

def test_manga_workflow_allowlist_includes_create_manga_asset():
    assert "create_manga_asset" in _tool_names(mode="agent", workflow_type="manga")
    assert "create_video_asset" not in _tool_names(mode="agent", workflow_type="manga")


def test_video_workflow_allowlist_includes_asset_tools():
    names = _tool_names(mode="agent", workflow_type="video")
    assert "create_video_asset" in names
    assert "update_video_asset_prompts" in names
    assert "create_manga_asset" not in names


# ── 2. create_manga_asset ──

@pytest.mark.asyncio
async def test_create_manga_asset_creates_blank_asset_and_binding(monkeypatch):
    db = FakeDb()
    tracker = agent_service.PendingChangesTracker()
    context = _context(workflow_type="manga", pending_changes=tracker)
    monkeypatch.setattr(agent_service, "SessionLocal", lambda: db)
    monkeypatch.setattr(
        agent_service,
        "_validate_chapter_ownership",
        lambda _db, _cid, _sid, with_for_update=False: _chapter(),
    )
    token = agent_service._AGENT_RUN_CONTEXT.set(context)
    try:
        result = await agent_service.create_manga_asset(
            chapter_id=10, name="林晚秋正面设定图", asset_type="character_reference"
        )
    finally:
        agent_service._AGENT_RUN_CONTEXT.reset(token)

    assert result["ok"] is True
    assert result["storage_path"] == ""
    assert result["name"] == "林晚秋正面设定图"

    asset = next(obj for obj in db.added if isinstance(obj, agent_service.MangaAsset))
    assert asset.owner_user_id == 1
    assert asset.story_id == 1
    assert asset.chapter_id == 10
    assert asset.asset_type == "character_reference"
    assert asset.storage_path == ""
    assert asset.source_type == "agent"
    assert asset.status == "active"

    binding = next(obj for obj in db.added if isinstance(obj, agent_service.MangaAssetBinding))
    assert binding.binding_role == "character"
    assert binding.label == "林晚秋正面设定图"
    assert binding.priority == 0
    assert binding.is_required is False

    assert [change.type for change in tracker._changes] == ["manga_asset"]
    change = tracker._changes[0]
    assert change.field == "__created__"
    assert change.record_id == asset.id
    assert change.new_value["asset_type"] == "character_reference"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("name", "asset_type", "chapter_id"),
    [
        ("   ", "character_reference", 10),
        ("a" * 256, "character_reference", 10),
        ("合法名称", "bogus_type", 10),
        ("合法名称", "character_reference", 999),
    ],
)
async def test_create_manga_asset_validation_errors(monkeypatch, name, asset_type, chapter_id):
    db = FakeDb()
    monkeypatch.setattr(agent_service, "SessionLocal", lambda: db)
    monkeypatch.setattr(
        agent_service,
        "_validate_chapter_ownership",
        lambda _db, _cid, _sid, with_for_update=False: _chapter() if _cid == 10 else None,
    )
    context = _context(workflow_type="manga")
    token = agent_service._AGENT_RUN_CONTEXT.set(context)
    try:
        result = await agent_service.create_manga_asset(
            chapter_id=chapter_id, name=name, asset_type=asset_type
        )
    finally:
        agent_service._AGENT_RUN_CONTEXT.reset(token)

    assert "error" in result
    assert result.get("ok") is not True
    assert db.added == []


# ── 3. create_video_asset ──

@pytest.mark.asyncio
async def test_create_video_asset_creates_blank_asset(monkeypatch):
    db = FakeDb()
    tracker = agent_service.PendingChangesTracker()
    context = _context(
        workflow_type="video",
        workflow_id=5,
        pending_changes=tracker,
    )
    monkeypatch.setattr(agent_service, "SessionLocal", lambda: db)
    monkeypatch.setattr(
        agent_service,
        "_validate_chapter_ownership",
        lambda _db, _cid, _sid, with_for_update=False: _chapter(),
    )
    monkeypatch.setattr(
        agent_service,
        "_require_current_video_workflow",
        lambda _db, _wid: _workflow(),
    )
    token = agent_service._AGENT_RUN_CONTEXT.set(context)
    try:
        result = await agent_service.create_video_asset(
            chapter_id=10, name="林晚秋角色参考图", asset_type="character_reference"
        )
    finally:
        agent_service._AGENT_RUN_CONTEXT.reset(token)

    assert result["ok"] is True
    assert result["file_path"] == ""
    assert result["name"] == "林晚秋角色参考图"

    asset = next(obj for obj in db.added if isinstance(obj, agent_service.VideoAsset))
    assert asset.story_id == 1
    assert asset.chapter_id == 10
    assert asset.asset_type == "character_reference"
    assert asset.file_path == ""
    assert asset.source_type == "agent"
    assert asset.usage_scope == "shot_only"
    assert asset.status == "active"

    assert [change.type for change in tracker._changes] == ["video_asset"]
    change = tracker._changes[0]
    assert change.field == "__created__"
    assert change.record_id == asset.id


@pytest.mark.asyncio
async def test_create_video_asset_rejects_workflow_mismatch(monkeypatch):
    db = FakeDb()
    monkeypatch.setattr(agent_service, "SessionLocal", lambda: db)
    monkeypatch.setattr(
        agent_service,
        "_validate_chapter_ownership",
        lambda _db, _cid, _sid, with_for_update=False: _chapter(),
    )
    monkeypatch.setattr(
        agent_service,
        "_require_current_video_workflow",
        lambda _db, _wid: _workflow(chapter_id=99),
    )
    context = _context(workflow_type="video", workflow_id=5)
    token = agent_service._AGENT_RUN_CONTEXT.set(context)
    try:
        result = await agent_service.create_video_asset(
            chapter_id=10, name="林晚秋角色参考图", asset_type="character_reference"
        )
    finally:
        agent_service._AGENT_RUN_CONTEXT.reset(token)

    assert "error" in result
    assert db.added == []


# ── 4. update_video_asset_prompts ──

@pytest.mark.asyncio
async def test_update_video_asset_prompts_records_rollback_restore(monkeypatch):
    asset = SimpleNamespace(
        id=101,
        asset_type="character_reference",
        name="林晚秋角色参考图",
        prompt="旧提示词",
    )
    db = FakeDb(objects={101: asset})
    db.query_result = [asset]
    tracker = agent_service.PendingChangesTracker()
    context = _context(
        workflow_type="video",
        workflow_id=5,
        pending_changes=tracker,
    )
    monkeypatch.setattr(agent_service, "SessionLocal", lambda: db)
    monkeypatch.setattr(
        agent_service,
        "_validate_chapter_ownership",
        lambda _db, _cid, _sid, with_for_update=False: _chapter(),
    )
    monkeypatch.setattr(
        agent_service,
        "_require_current_video_workflow",
        lambda _db, _wid: _workflow(),
    )
    token = agent_service._AGENT_RUN_CONTEXT.set(context)
    try:
        result = await agent_service.update_video_asset_prompts(
            chapter_id=10,
            updates=[{"asset_id": 101, "prompt": "新提示词"}],
        )
    finally:
        agent_service._AGENT_RUN_CONTEXT.reset(token)

    assert result["ok"] is True
    assert result["changed"] is True
    assert asset.prompt == "新提示词"
    assert [change.type for change in tracker._changes] == ["video_asset"]
    change = tracker._changes[0]
    assert change.field == "prompt"
    assert change.old_value == "旧提示词"
    assert change.new_value == "新提示词"

    rollback_db = FakeDb(objects={101: asset})
    rollback_result = tracker.rollback(rollback_db)
    assert all(item["ok"] for item in rollback_result)
    assert asset.prompt == "旧提示词"


@pytest.mark.asyncio
async def test_update_video_asset_prompts_rejects_unknown_asset(monkeypatch):
    db = FakeDb()
    monkeypatch.setattr(agent_service, "SessionLocal", lambda: db)
    monkeypatch.setattr(
        agent_service,
        "_validate_chapter_ownership",
        lambda _db, _cid, _sid, with_for_update=False: _chapter(),
    )
    monkeypatch.setattr(
        agent_service,
        "_require_current_video_workflow",
        lambda _db, _wid: _workflow(),
    )
    context = _context(workflow_type="video", workflow_id=5)
    token = agent_service._AGENT_RUN_CONTEXT.set(context)
    try:
        result = await agent_service.update_video_asset_prompts(
            chapter_id=10,
            updates=[{"asset_id": 999, "prompt": "新提示词"}],
        )
    finally:
        agent_service._AGENT_RUN_CONTEXT.reset(token)

    assert "error" in result


@pytest.mark.asyncio
async def test_update_video_asset_prompts_validation_errors(monkeypatch):
    db = FakeDb()
    monkeypatch.setattr(agent_service, "SessionLocal", lambda: db)
    context = _context(workflow_type="video", workflow_id=5)
    token = agent_service._AGENT_RUN_CONTEXT.set(context)
    try:
        result = await agent_service.update_video_asset_prompts(
            chapter_id=10,
            updates=[{"asset_id": 101, "prompt": "   "}],
        )
    finally:
        agent_service._AGENT_RUN_CONTEXT.reset(token)

    assert "error" in result


# ── 5. rollback 删除已创建资产 ──

@pytest.mark.asyncio
async def test_rollback_deletes_created_manga_asset(monkeypatch):
    asset = SimpleNamespace(
        id=201,
        story_id=1,
        storage_path="",
        asset_type="character_reference",
    )
    db = FakeDb()
    tracker = agent_service.PendingChangesTracker()
    tracker.record(agent_service.PendingChange(
        type="manga_asset",
        record_id=201,
        display_name="第3章 · 资产「测试」",
        field="__created__",
        old_value=None,
        new_value={"asset_id": 201, "story_id": 1},
    ))
    rollback_db = FakeDb(objects={201: asset})
    result = tracker.rollback(rollback_db)

    assert all(item["ok"] for item in result)
    assert asset in rollback_db.deleted


@pytest.mark.asyncio
async def test_rollback_keeps_created_manga_asset_with_image(monkeypatch):
    asset = SimpleNamespace(
        id=202,
        story_id=1,
        storage_path="/static/manga/users/1/cover.png",
        asset_type="character_reference",
    )
    tracker = agent_service.PendingChangesTracker()
    tracker.record(agent_service.PendingChange(
        type="manga_asset",
        record_id=202,
        display_name="第3章 · 资产「测试」",
        field="__created__",
        old_value=None,
        new_value={"asset_id": 202, "story_id": 1},
    ))
    rollback_db = FakeDb(objects={202: asset})
    result = tracker.rollback(rollback_db)

    assert all(item["ok"] is False and item["conflict"] for item in result)
    assert rollback_db.deleted == []


@pytest.mark.asyncio
async def test_rollback_deletes_created_video_asset():
    asset = SimpleNamespace(
        id=203,
        story_id=1,
        file_path="",
        asset_type="character_reference",
    )
    tracker = agent_service.PendingChangesTracker()
    tracker.record(agent_service.PendingChange(
        type="video_asset",
        record_id=203,
        display_name="第3章 · 资产「测试」",
        field="__created__",
        old_value=None,
        new_value={"asset_id": 203, "story_id": 1},
    ))
    rollback_db = FakeDb(objects={203: asset})
    result = tracker.rollback(rollback_db)

    assert all(item["ok"] for item in result)
    assert asset in rollback_db.deleted


@pytest.mark.asyncio
async def test_rollback_keeps_created_video_asset_with_video():
    asset = SimpleNamespace(
        id=204,
        story_id=1,
        file_path="/static/video/users/1/clip.mp4",
        asset_type="video_asset",
    )
    tracker = agent_service.PendingChangesTracker()
    tracker.record(agent_service.PendingChange(
        type="video_asset",
        record_id=204,
        display_name="第3章 · 资产「测试」",
        field="__created__",
        old_value=None,
        new_value={"asset_id": 204, "story_id": 1},
    ))
    rollback_db = FakeDb(objects={204: asset})
    result = tracker.rollback(rollback_db)

    assert all(item["ok"] is False and item["conflict"] for item in result)
    assert rollback_db.deleted == []


# ── 6. agent_router 归属复核 ──

def test_agent_router_loads_owned_pending_target_supports_asset_types():
    import main  # noqa: F401 - 确保 Agent 路由可绑定主模块依赖
    from routers import agent_router

    manga_asset = SimpleNamespace(id=301, story_id=1)
    video_asset = SimpleNamespace(id=302, story_id=1)
    db = FakeDb(objects={301: manga_asset, 302: video_asset})

    assert agent_router._load_owned_pending_target(db, "manga_asset", 301, 1) is manga_asset
    assert agent_router._load_owned_pending_target(db, "video_asset", 302, 1) is video_asset
    assert agent_router._load_owned_pending_target(db, "manga_asset", 301, 2) is None
    assert agent_router._load_owned_pending_target(db, "video_asset", 302, 2) is None