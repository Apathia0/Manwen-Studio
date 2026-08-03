from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

import main
from database import Base, _migrate_storyboard_presets
from models import Story, StoryboardPromptPreset, User


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()


def _seed_users_and_stories(db):
    user_a = User(email="a@example.com", password_hash="x", name="A", role="user")
    user_b = User(email="b@example.com", password_hash="x", name="B", role="user")
    db.add_all([user_a, user_b])
    db.flush()
    story_a1 = Story(title="A1", owner_user_id=user_a.id)
    story_a2 = Story(title="A2", owner_user_id=user_a.id)
    story_b = Story(title="B", owner_user_id=user_b.id)
    db.add_all([story_a1, story_a2, story_b])
    db.commit()
    return user_a, user_b, story_a1, story_a2, story_b


def test_migration_upgrades_legacy_story_preset_to_user_scope():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY)"))
        conn.execute(text(
            "CREATE TABLE stories (id INTEGER PRIMARY KEY, owner_user_id INTEGER)"
        ))
        conn.execute(text("""
            CREATE TABLE storyboard_prompt_presets (
                id INTEGER PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                description TEXT,
                prompt_template TEXT NOT NULL,
                system_prompt TEXT,
                is_system BOOLEAN DEFAULT FALSE,
                story_id INTEGER,
                sort_order INTEGER DEFAULT 0,
                created_at TIMESTAMP,
                updated_at TIMESTAMP
            )
        """))
        conn.execute(text("INSERT INTO users (id) VALUES (7), (8)"))
        conn.execute(text(
            "INSERT INTO stories (id, owner_user_id) VALUES (12, 7)"
        ))
        conn.execute(
            text(
                "INSERT INTO storyboard_prompt_presets "
                "(id, name, prompt_template, is_system, story_id) "
                "VALUES (99, '旧模板', '提示词', FALSE, 12)"
            )
        )

    _migrate_storyboard_presets(engine)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO storyboard_prompt_presets "
                "(id, name, prompt_template, is_system, story_id, author_user_id) "
                "VALUES (200, '管理员旧模板', '旧提示词', FALSE, 12, 8)"
            )
        )
    _migrate_storyboard_presets(engine)

    with engine.connect() as conn:
        upgraded = conn.execute(text(
            "SELECT author_user_id, story_id FROM storyboard_prompt_presets WHERE id = 99"
        )).one()
        legacy_mismatch = conn.execute(text(
            "SELECT author_user_id, story_id FROM storyboard_prompt_presets WHERE id = 200"
        )).one()
    index_names = {
        index["name"] for index in inspect(engine).get_indexes("storyboard_prompt_presets")
    }

    assert upgraded == (7, None)
    assert legacy_mismatch == (7, None)
    assert "ix_storyboard_prompt_presets_user_order" in index_names


def test_created_user_preset_is_visible_across_owners_stories(db, monkeypatch):
    user_a, _user_b, story_a1, story_a2, _story_b = _seed_users_and_stories(db)
    monkeypatch.setattr(main, "_require_user", lambda *_args: user_a)

    created = main.create_storyboard_preset(
        {
            "story_id": story_a1.id,
            "name": "我的电影分镜",
            "prompt_template": "生成 {page_count} 页分镜",
        },
        SimpleNamespace(),
        db,
    )
    listed = main.list_storyboard_presets(SimpleNamespace(), story_a2.id, db)

    assert created["scope"] == "user"
    assert created["author_user_id"] == user_a.id
    assert created["story_id"] is None
    assert created["id"] in {preset["id"] for preset in listed["presets"]}


def test_other_users_preset_cannot_be_bound_or_duplicated(db, monkeypatch):
    user_a, user_b, story_a1, _story_a2, story_b = _seed_users_and_stories(db)
    foreign_preset = StoryboardPromptPreset(
        name="A 的模板",
        prompt_template="仅 A 可用",
        author_user_id=user_a.id,
        is_system=False,
    )
    db.add(foreign_preset)
    db.commit()
    monkeypatch.setattr(main, "_require_user", lambda *_args: user_b)

    with pytest.raises(main.HTTPException) as bind_error:
        main.bind_story_storyboard_preset(
            story_b.id,
            {"preset_id": foreign_preset.id},
            SimpleNamespace(),
            db,
        )
    with pytest.raises(main.HTTPException) as duplicate_error:
        main.duplicate_storyboard_preset(
            foreign_preset.id,
            {"story_id": story_b.id},
            SimpleNamespace(),
            db,
        )

    assert bind_error.value.status_code == 400
    assert duplicate_error.value.status_code == 403
    assert main._storyboard_preset_available_for_story(foreign_preset, story_a1)
    assert not main._storyboard_preset_available_for_story(foreign_preset, story_b)


def test_system_preset_is_read_only_and_legacy_story_preset_still_works(db, monkeypatch):
    user_a, _user_b, story_a1, story_a2, _story_b = _seed_users_and_stories(db)
    system_preset = StoryboardPromptPreset(
        name="系统模板",
        prompt_template="系统内容",
        is_system=True,
    )
    legacy_preset = StoryboardPromptPreset(
        name="旧版模板",
        prompt_template="旧版内容",
        story_id=story_a1.id,
        author_user_id=None,
        is_system=False,
    )
    db.add_all([system_preset, legacy_preset])
    db.commit()
    monkeypatch.setattr(main, "_require_user", lambda *_args: user_a)

    with pytest.raises(main.HTTPException) as update_error:
        main.update_storyboard_preset(
            system_preset.id,
            {"name": "被修改"},
            SimpleNamespace(),
            db,
        )

    assert update_error.value.status_code == 403
    assert main._storyboard_preset_available_for_story(legacy_preset, story_a1)
    assert not main._storyboard_preset_available_for_story(legacy_preset, story_a2)


def test_deleting_user_preset_unbinds_all_stories(db, monkeypatch):
    user_a, _user_b, story_a1, story_a2, _story_b = _seed_users_and_stories(db)
    preset = StoryboardPromptPreset(
        name="可删除模板",
        prompt_template="自定义内容",
        author_user_id=user_a.id,
        is_system=False,
    )
    db.add(preset)
    db.flush()
    story_a1.storyboard_preset_id = preset.id
    story_a2.storyboard_preset_id = preset.id
    db.commit()
    monkeypatch.setattr(main, "_require_user", lambda *_args: user_a)

    result = main.delete_storyboard_preset(preset.id, SimpleNamespace(), db)
    db.refresh(story_a1)
    db.refresh(story_a2)

    assert result == {"ok": True}
    assert story_a1.storyboard_preset_id is None
    assert story_a2.storyboard_preset_id is None
