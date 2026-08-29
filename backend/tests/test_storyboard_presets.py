import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import main
from database import Base, get_db
from models import Chapter, Story, StoryboardPromptPreset, User
from services import deepseek as deepseek_module
from services.deepseek import split_scenes


def _mock_async_client(response_content: str, captured_payloads: list[dict]) -> MagicMock:
    response = MagicMock()
    response.text = json.dumps(
        {"choices": [{"message": {"content": response_content}}]},
        ensure_ascii=False,
    )
    response.status_code = 200

    async def post(*_args, **kwargs):
        captured_payloads.append(kwargs["json"])
        return response

    client = MagicMock()
    client.post = AsyncMock(side_effect=post)
    client_class = MagicMock()
    client_class.return_value.__aenter__ = AsyncMock(return_value=client)
    client_class.return_value.__aexit__ = AsyncMock(return_value=False)
    return client_class


def _storyboard_seed_by_key() -> dict[str, dict]:
    seed_path = Path(__file__).resolve().parents[1] / "seed_data" / "storyboard_presets.json"
    presets = json.loads(seed_path.read_text(encoding="utf-8"))
    normalized = []
    for preset in presets:
        item = dict(preset)
        item["prompt_template"] = item.get("effective_prompt_template", item["prompt_template"])
        item["system_prompt"] = item.get("effective_system_prompt", item["system_prompt"])
        normalized.append(item)
    return {preset["preset_key"]: preset for preset in normalized}


def test_storyboard_runtime_has_no_embedded_layout_prompt_constants():
    assert not hasattr(deepseek_module, "_DEFAULT_STORYBOARD_PROMPT_TEMPLATE")
    assert not hasattr(deepseek_module, "_SINGLE_PANEL_STORYBOARD_PROMPT_TEMPLATE")
    assert not hasattr(deepseek_module, "_FOUR_PANEL_STORYBOARD_PROMPT_TEMPLATE")


@pytest.mark.asyncio
async def test_split_scenes_uses_custom_prompts_and_replaces_page_count(monkeypatch):
    captured_payloads = []
    monkeypatch.setattr("services.deepseek.DEEPSEEK_BASE_URL", "https://example.test")
    monkeypatch.setattr("services.deepseek.DEEPSEEK_MODEL", "test-model")

    with patch(
        "services.deepseek.httpx.AsyncClient",
        _mock_async_client(
            json.dumps({"scenes": ["第一页", "第二页"]}, ensure_ascii=False),
            captured_payloads,
        ),
    ):
        scenes = await split_scenes(
            [{"role": "user", "content": "原文"}],
            page_count=2,
            api_key="test-key",
            prompt_template="  自定义正文，共 {page_count} 页  ",
            system_prompt="  自定义系统，共 {page_count} 页  ",
        )

    assert scenes == ["第一页", "第二页"]
    payload = captured_payloads[0]
    assert payload["messages"][0]["content"] == "自定义系统，共 2 页"
    # v4.5.7 增强：末尾追加【强制页数要求】区块
    assert payload["messages"][-1]["content"].startswith("自定义正文，共 2 页")
    assert "【强制页数要求】" in payload["messages"][-1]["content"]
    assert "必须**恰好包含 2 个元素**" in payload["messages"][-1]["content"]


@pytest.mark.asyncio
async def test_split_scenes_compacts_default_manga_storyboard_output(monkeypatch):
    """默认漫画模板必须要求短旁白成片脚本，而非输出分析字段。"""
    captured_payloads = []
    default_seed = _storyboard_seed_by_key()["default"]
    monkeypatch.setattr("services.deepseek.DEEPSEEK_BASE_URL", "https://example.test")
    monkeypatch.setattr("services.deepseek.DEEPSEEK_MODEL", "test-model")

    with patch(
        "services.deepseek.httpx.AsyncClient",
        _mock_async_client(
            json.dumps({"scenes": ["第一页"]}, ensure_ascii=False),
            captured_payloads,
        ),
    ):
        await split_scenes(
            [{"role": "user", "content": "原文"}],
            page_count=1,
            api_key="test-key",
            prompt_template=default_seed["prompt_template"],
            system_prompt=default_seed["system_prompt"],
        )

    prompt = captured_payloads[0]["messages"][-1]["content"]
    assert "画面先行，读者一眼看懂" in prompt
    assert "每页4-5格" in prompt
    assert "不要出现“视觉焦点”“叙事作用”“环境分析”等元标签" in prompt


@pytest.mark.asyncio
async def test_split_scenes_rejects_calls_without_database_prompts(monkeypatch):
    captured_payloads = []
    monkeypatch.setattr("services.deepseek.DEEPSEEK_BASE_URL", "https://example.test")
    monkeypatch.setattr("services.deepseek.DEEPSEEK_MODEL", "test-model")

    with patch(
        "services.deepseek.httpx.AsyncClient",
        _mock_async_client(
            json.dumps({"scenes": ["第一页"]}, ensure_ascii=False),
            captured_payloads,
        ),
    ):
        with pytest.raises(ValueError, match="必须先从数据库解析模板"):
            await split_scenes(
                [{"role": "user", "content": "原文"}],
                page_count=1,
                api_key="test-key",
            )

    assert captured_payloads == []


@pytest.mark.asyncio
async def test_split_scenes_retries_on_timeout_then_succeeds(monkeypatch):
    """DeepSeek 超时后应退避重试，最终成功返回分镜。"""
    captured_payloads = []
    monkeypatch.setattr("services.deepseek.DEEPSEEK_BASE_URL", "https://example.test")
    monkeypatch.setattr("services.deepseek.DEEPSEEK_MODEL", "test-model")
    monkeypatch.setattr("services.deepseek.asyncio.sleep", AsyncMock())  # 避免真实等待退避

    responses = [
        httpx.ReadTimeout("first timeout"),
        httpx.ReadTimeout("second timeout"),
        json.dumps(
            {
                "choices": [
                    {"message": {"content": json.dumps({"scenes": ["第一页", "第二页"]}, ensure_ascii=False)}}
                ]
            },
            ensure_ascii=False,
        ),
    ]
    call_count = 0

    async def post(*_args, **kwargs):
        nonlocal call_count
        captured_payloads.append(kwargs["json"])
        result = responses[call_count]
        call_count += 1
        if isinstance(result, Exception):
            raise result
        response = MagicMock()
        response.text = result
        response.status_code = 200
        return response

    client = MagicMock()
    client.post = AsyncMock(side_effect=post)
    client_class = MagicMock()
    client_class.return_value.__aenter__ = AsyncMock(return_value=client)
    client_class.return_value.__aexit__ = AsyncMock(return_value=False)

    with patch("services.deepseek.httpx.AsyncClient", client_class):
        scenes = await split_scenes(
            [{"role": "user", "content": "原文"}],
            page_count=2,
            api_key="test-key",
            prompt_template="正文 {page_count} 页",
            system_prompt="系统 {page_count} 页",
        )

    assert scenes == ["第一页", "第二页"]
    assert call_count == 3  # 2 次超时重试 + 1 次成功


@pytest.mark.asyncio
async def test_split_scenes_raises_timeout_after_retries_exhausted(monkeypatch):
    """超时重试耗尽后应抛出 httpx.TimeoutException（而非 ValueError），由上层转 502 友好错误。"""
    monkeypatch.setattr("services.deepseek.DEEPSEEK_BASE_URL", "https://example.test")
    monkeypatch.setattr("services.deepseek.DEEPSEEK_MODEL", "test-model")
    monkeypatch.setattr("services.deepseek.asyncio.sleep", AsyncMock())

    async def post(*_args, **_kwargs):
        raise httpx.ReadTimeout("always timeout")

    client = MagicMock()
    client.post = AsyncMock(side_effect=post)
    client_class = MagicMock()
    client_class.return_value.__aenter__ = AsyncMock(return_value=client)
    client_class.return_value.__aexit__ = AsyncMock(return_value=False)

    with patch("services.deepseek.httpx.AsyncClient", client_class):
        with pytest.raises(httpx.TimeoutException):
            await split_scenes(
                [{"role": "user", "content": "原文"}],
                page_count=2,
                api_key="test-key",
                prompt_template="正文 {page_count} 页",
                system_prompt="系统 {page_count} 页",
            )


def test_storyboard_preset_migration_creates_table_column_and_default_seed():
    from database import _migrate_storyboard_presets

    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY)"))
        conn.execute(text("CREATE TABLE stories (id INTEGER PRIMARY KEY)"))

    _migrate_storyboard_presets(engine)
    _migrate_storyboard_presets(engine)

    inspector = inspect(engine)
    assert "storyboard_prompt_presets" in inspector.get_table_names()
    assert "storyboard_preset_id" in {
        column["name"] for column in inspector.get_columns("stories")
    }
    with engine.connect() as conn:
        presets = conn.execute(
            text(
                "SELECT preset_key, name, description, prompt_template, system_prompt, "
                "is_system, sort_order FROM storyboard_prompt_presets "
                "ORDER BY sort_order"
            )
        ).mappings().all()
    assert len(presets) == 3
    default_preset = presets[0]
    assert default_preset["preset_key"] == "default"
    assert default_preset["name"] == "默认分镜模板"
    default_seed = _storyboard_seed_by_key()["default"]
    assert default_preset["prompt_template"] == default_seed["prompt_template"]
    assert default_preset["system_prompt"] == default_seed["system_prompt"]
    assert bool(default_preset["is_system"]) is True
    assert default_preset["sort_order"] == 1


def test_storyboard_preset_migration_seeds_system_layout_presets_idempotently():
    from database import _migrate_storyboard_presets
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY)"))
        conn.execute(text("CREATE TABLE stories (id INTEGER PRIMARY KEY)"))

    _migrate_storyboard_presets(engine)
    # 已补种过一次后再次迁移，不应重复插入（幂等性）
    _migrate_storyboard_presets(engine)
    _migrate_storyboard_presets(engine)

    with engine.connect() as conn:
        presets = {
            row["name"]: row
            for row in conn.execute(
                text(
                    "SELECT name, prompt_template, system_prompt, is_system, "
                    "sort_order FROM storyboard_prompt_presets"
                )
            ).mappings().all()
        }

    seeds = _storyboard_seed_by_key()
    assert presets["单格大图"]["prompt_template"] == seeds["single_panel"]["prompt_template"]
    assert presets["单格大图"]["system_prompt"] == seeds["single_panel"]["system_prompt"]
    assert bool(presets["单格大图"]["is_system"]) is True
    assert presets["单格大图"]["sort_order"] == 2
    assert "{page_count}" in presets["单格大图"]["prompt_template"]
    assert "{page_count}" in presets["单格大图"]["system_prompt"]

    assert presets["四宫格无气泡"]["prompt_template"] == seeds["four_panel_no_bubble"]["prompt_template"]
    assert presets["四宫格无气泡"]["system_prompt"] == seeds["four_panel_no_bubble"]["system_prompt"]
    assert bool(presets["四宫格无气泡"]["is_system"]) is True
    assert presets["四宫格无气泡"]["sort_order"] == 3
    assert "{page_count}" in presets["四宫格无气泡"]["prompt_template"]
    assert "{page_count}" in presets["四宫格无气泡"]["system_prompt"]


def test_storyboard_preset_migration_preserves_existing_custom_presets():
    """已有数据库再次迁移时同步系统预设，但不改动自定义数据。"""
    from database import _migrate_storyboard_presets

    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY)"))
        conn.execute(text("CREATE TABLE stories (id INTEGER PRIMARY KEY)"))

    _migrate_storyboard_presets(engine)
    # 模拟用户创建的自定义预设
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO storyboard_prompt_presets "
                "(name, prompt_template, is_system, sort_order) "
                "VALUES (:name, :prompt, FALSE, 99)"
            ),
            {"name": "我的模板", "prompt": "自定义正文 {page_count}"},
        )

    _migrate_storyboard_presets(engine)

    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT name, is_system, sort_order FROM storyboard_prompt_presets "
                "ORDER BY sort_order"
            )
        ).fetchall()
    names = [row[0] for row in rows]
    assert names == ["默认分镜模板", "单格大图", "四宫格无气泡", "我的模板"]
    custom_row = [row for row in rows if row[0] == "我的模板"][0]
    assert bool(custom_row[1]) is False
    assert custom_row[2] == 99


def test_storyboard_preset_migration_refreshes_existing_system_presets():
    """已有系统分镜模板应同步到最新种子，用户自定义模板必须保持原样。"""
    from database import _migrate_storyboard_presets

    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY)"))
        conn.execute(text("CREATE TABLE stories (id INTEGER PRIMARY KEY)"))

    _migrate_storyboard_presets(engine)
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE storyboard_prompt_presets SET prompt_template = :prompt, "
                "system_prompt = :system_prompt, description = :description, sort_order = :sort_order "
                "WHERE is_system = TRUE AND preset_key = 'default'"
            ),
            {
                "prompt": "旧版系统提示词",
                "system_prompt": "旧版系统规则",
                "description": "旧版说明",
                "sort_order": 99,
            },
        )
        conn.execute(
            text(
                "INSERT INTO storyboard_prompt_presets "
                "(name, prompt_template, is_system, sort_order) "
                "VALUES (:name, :prompt, FALSE, 99)"
            ),
            {"name": "用户保留模板", "prompt": "用户自定义提示词"},
        )

    _migrate_storyboard_presets(engine)

    with engine.connect() as conn:
        default_preset = conn.execute(
            text(
                "SELECT prompt_template, system_prompt, description, sort_order "
                "FROM storyboard_prompt_presets "
                "WHERE is_system = TRUE AND preset_key = 'default'"
            )
        ).mappings().one()
        custom_prompt = conn.execute(
            text(
                "SELECT prompt_template FROM storyboard_prompt_presets "
                "WHERE name = '用户保留模板'"
            )
        ).scalar()

    default_seed = _storyboard_seed_by_key()["default"]
    assert default_preset["prompt_template"] == default_seed["prompt_template"]
    assert default_preset["system_prompt"] == default_seed["system_prompt"]
    assert default_preset["description"] == default_seed["description"]
    assert default_preset["sort_order"] == default_seed["sort_order"]
    assert custom_prompt == "用户自定义提示词"


def test_storyboard_preset_migration_refreshes_legacy_default_preset():
    """旧版无 preset_key 的默认系统模板应升级并同步最新种子。"""
    from database import _migrate_storyboard_presets

    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY)"))
        conn.execute(text("CREATE TABLE stories (id INTEGER PRIMARY KEY)"))

    _migrate_storyboard_presets(engine)
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE storyboard_prompt_presets SET preset_key = NULL, "
                "prompt_template = :prompt WHERE is_system = TRUE AND preset_key = 'default'"
            ),
            {"prompt": "旧版默认模板"},
        )

    _migrate_storyboard_presets(engine)

    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT preset_key, prompt_template FROM storyboard_prompt_presets "
                "WHERE is_system = TRUE AND name = '默认分镜模板'"
            )
        ).mappings().one()

    assert row["preset_key"] == "default"
    assert row["prompt_template"] == _storyboard_seed_by_key()["default"]["prompt_template"]


@pytest.fixture
def api_context(monkeypatch):
    monkeypatch.setattr(main, "SYSTEM_READY", True)
    monkeypatch.setattr(
        main,
        "INSTALL_STATUS",
        {"installed": True, "requires_restart": False},
    )
    monkeypatch.setattr(main.license_checker, "check_domain", lambda _hostname: True)
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, expire_on_commit=False)
    db = TestSession()
    user = User(
        email="author@example.com",
        password_hash="test",
        name="author",
        role="user",
        status="active",
        email_verified=True,
    )
    other_user = User(
        email="other@example.com",
        password_hash="test",
        name="other",
        role="user",
        status="active",
        email_verified=True,
    )
    db.add_all([user, other_user])
    db.flush()
    story = Story(owner_user_id=user.id, title="测试作品")
    other_story = Story(owner_user_id=other_user.id, title="其他作品")
    db.add_all([story, other_story])
    db.flush()
    system_preset = StoryboardPromptPreset(
        preset_key="default",
        name="系统模板",
        prompt_template="系统正文 {page_count}",
        system_prompt="系统角色 {page_count}",
        is_system=True,
        sort_order=1,
    )
    custom_preset = StoryboardPromptPreset(
        name="已有模板",
        prompt_template="已有正文 {page_count}",
        is_system=False,
        story_id=story.id,
        author_user_id=user.id,
        sort_order=2,
    )
    hidden_preset = StoryboardPromptPreset(
        name="不可见模板",
        prompt_template="其他作品正文 {page_count}",
        is_system=False,
        story_id=other_story.id,
        author_user_id=other_user.id,
        sort_order=3,
    )
    db.add_all([system_preset, custom_preset, hidden_preset])
    db.commit()

    def override_get_db():
        yield db

    current_user = SimpleNamespace(id=user.id, role="user")
    monkeypatch.setattr(main, "_require_user", lambda _request, _db: current_user)
    main.app.dependency_overrides[get_db] = override_get_db
    client = TestClient(main.app)
    try:
        yield SimpleNamespace(
            client=client,
            db=db,
            user=user,
            other_user=other_user,
            story=story,
            other_story=other_story,
            system_preset=system_preset,
            custom_preset=custom_preset,
            current_user=current_user,
        )
    finally:
        main.app.dependency_overrides.clear()
        client.close()
        db.close()
        engine.dispose()


def test_storyboard_preset_api_lists_creates_updates_and_deletes(api_context):
    ctx = api_context
    response = ctx.client.get(
        "/api/storyboard-presets", params={"story_id": ctx.story.id}
    )
    assert response.status_code == 200
    assert [item["name"] for item in response.json()["presets"]] == [
        "系统模板",
        "已有模板",
    ]

    response = ctx.client.post(
        "/api/storyboard-presets",
        json={
            "name": "新模板",
            "description": "测试描述",
            "prompt_template": "新正文 {page_count}",
            "system_prompt": "新系统 {page_count}",
            "story_id": ctx.story.id,
        },
    )
    assert response.status_code == 200
    created = response.json()
    assert created["is_system"] is False
    assert created["story_id"] is None
    assert created["author_user_id"] == ctx.user.id
    assert created["scope"] == "user"

    response = ctx.client.put(
        f"/api/storyboard-presets/{created['id']}",
        json={"name": "已更新", "system_prompt": None},
    )
    assert response.status_code == 200
    assert response.json()["name"] == "已更新"
    assert response.json()["system_prompt"] is None

    response = ctx.client.put(
        f"/api/stories/{ctx.story.id}/storyboard-preset",
        json={"preset_id": created["id"]},
    )
    assert response.status_code == 200
    assert response.json()["preset_id"] == created["id"]

    response = ctx.client.delete(f"/api/storyboard-presets/{created['id']}")
    assert response.status_code == 200
    assert response.json() == {"ok": True}
    ctx.db.refresh(ctx.story)
    assert ctx.story.storyboard_preset_id is None


def test_storyboard_preset_api_duplicates_and_binds_system_preset(api_context):
    ctx = api_context
    response = ctx.client.post(
        f"/api/storyboard-presets/{ctx.system_preset.id}/duplicate",
        json={"story_id": ctx.story.id},
    )
    assert response.status_code == 200
    duplicate = response.json()
    assert duplicate["name"] == "系统模板（副本）"
    assert duplicate["is_system"] is False
    assert duplicate["story_id"] is None
    assert duplicate["author_user_id"] == ctx.user.id

    response = ctx.client.put(
        f"/api/stories/{ctx.story.id}/storyboard-preset",
        json={"preset_id": ctx.system_preset.id},
    )
    assert response.status_code == 200
    response = ctx.client.get(
        f"/api/stories/{ctx.story.id}/storyboard-preset"
    )
    assert response.status_code == 200
    assert response.json()["preset"]["id"] == ctx.system_preset.id

    response = ctx.client.put(
        f"/api/stories/{ctx.story.id}/storyboard-preset",
        json={"preset_id": None},
    )
    assert response.status_code == 200
    assert response.json() == {"preset_id": None, "preset": None}


def test_storyboard_preset_api_enforces_ownership_and_system_read_only(api_context):
    ctx = api_context
    response = ctx.client.put(
        f"/api/storyboard-presets/{ctx.system_preset.id}",
        json={"name": "不允许"},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "系统预设不允许编辑"

    response = ctx.client.delete(
        f"/api/storyboard-presets/{ctx.system_preset.id}"
    )
    assert response.status_code == 403

    response = ctx.client.post(
        "/api/storyboard-presets",
        json={
            "name": "越权模板",
            "prompt_template": "正文",
            "story_id": ctx.other_story.id,
        },
    )
    assert response.status_code == 403

    response = ctx.client.put(
        f"/api/stories/{ctx.story.id}/storyboard-preset",
        json={"preset_id": ctx.db.query(StoryboardPromptPreset).filter_by(name="不可见模板").one().id},
    )
    assert response.status_code == 400


def test_storyboard_prompt_snapshot_reads_unbound_default_from_database(api_context):
    ctx = api_context
    ctx.story.storyboard_preset_id = None
    ctx.db.commit()

    prompt_template, system_prompt = main._storyboard_prompt_snapshot_for_generation(
        ctx.db,
        ctx.story,
        None,
        preset_id_provided=False,
    )

    assert prompt_template == ctx.system_preset.prompt_template
    assert system_prompt == ctx.system_preset.system_prompt


def test_storyboard_prompt_snapshot_rejects_missing_database_default(api_context):
    ctx = api_context
    ctx.db.delete(ctx.system_preset)
    ctx.db.commit()

    with pytest.raises(main.HTTPException) as missing_error:
        main._storyboard_prompt_snapshot_for_generation(
            ctx.db,
            ctx.story,
            None,
            preset_id_provided=False,
        )

    assert missing_error.value.status_code == 503


class _JsonRequest:
    def __init__(self, body: dict):
        self._body = body

    async def json(self):
        return self._body

    async def is_disconnected(self):
        return False


@pytest.mark.asyncio
async def test_generate_scenes_uses_story_bound_preset(api_context, monkeypatch):
    ctx = api_context
    ctx.story.storyboard_preset_id = ctx.custom_preset.id
    chapter = Chapter(
        story_id=ctx.story.id,
        chapter_number=1,
        novel_content="测试正文",
    )
    ctx.db.add(chapter)
    ctx.db.commit()
    captured = {}

    async def fake_split_scenes(*_args, **kwargs):
        captured.update(kwargs)
        return ["第一页"]

    monkeypatch.setattr(main, "_require_user", lambda _request, _db: ctx.current_user)
    monkeypatch.setattr(
        main,
        "_require_chapter_for_user",
        lambda _chapter_id, _user, _db: chapter,
    )
    monkeypatch.setattr(main, "_effective_image_count", lambda *_args: 1)
    monkeypatch.setattr(main, "_load_characters_async", AsyncMock(return_value=""))
    monkeypatch.setattr(main, "_user_deepseek_api_key", lambda _request: "test-key")
    monkeypatch.setattr(main, "_check_and_consume_feature_quota", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main, "_release_db_transaction", lambda _db: None)
    monkeypatch.setattr(main, "_write_scenes_file", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main, "split_scenes", fake_split_scenes)

    result = await main.generate_scenes_endpoint(
        chapter.id,
        _JsonRequest({}),
        ctx.db,
    )

    assert result == {"scenes": ["第一页"], "sanitized_indices": []}
    assert captured["prompt_template"] == ctx.custom_preset.prompt_template
    assert captured["system_prompt"] == ctx.system_preset.system_prompt


@pytest.mark.asyncio
async def test_scenes_from_selection_uses_explicit_preset_and_rejects_cross_story(
    api_context,
    monkeypatch,
):
    ctx = api_context
    chapter = Chapter(
        story_id=ctx.story.id,
        chapter_number=1,
        novel_content="测试正文",
    )
    ctx.db.add(chapter)
    ctx.db.commit()
    calls = []

    async def fake_scenes_from_selection(*_args, **kwargs):
        calls.append(kwargs)
        return ["第一页"]

    monkeypatch.setattr(main, "_require_user", lambda _request, _db: ctx.current_user)
    monkeypatch.setattr(
        main,
        "_require_chapter_for_user",
        lambda _chapter_id, _user, _db: chapter,
    )
    monkeypatch.setattr(main, "_user_deepseek_api_key", lambda _request: "test-key")
    monkeypatch.setattr(main, "_check_and_consume_feature_quota", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main, "_release_db_transaction", lambda _db: None)
    monkeypatch.setattr(main, "scenes_from_selection", fake_scenes_from_selection)

    await main.scenes_from_selection_endpoint(
        chapter.id,
        _JsonRequest(
            {
                "selected_text": "选中文本",
                "page_count": 1,
                "preset_id": ctx.system_preset.id,
            }
        ),
        ctx.db,
    )
    hidden_id = (
        ctx.db.query(StoryboardPromptPreset)
        .filter_by(name="不可见模板")
        .one()
        .id
    )
    with pytest.raises(main.HTTPException) as forbidden_error:
        await main.scenes_from_selection_endpoint(
            chapter.id,
            _JsonRequest(
                {
                    "selected_text": "选中文本",
                    "page_count": 1,
                    "preset_id": hidden_id,
                }
            ),
            ctx.db,
        )

    assert calls[0]["prompt_template"] == ctx.system_preset.prompt_template
    assert calls[0]["system_prompt"] == ctx.system_preset.system_prompt
    assert forbidden_error.value.status_code == 403
    assert len(calls) == 1
