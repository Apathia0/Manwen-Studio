import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import database
from models import VideoStylePreset
from routers import video as video_router
from schemas import VideoStylePresetCreate, VideoStylePresetUpdate


@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:")
    VideoStylePreset.__table__.create(eng)
    yield eng
    eng.dispose()


def _insert(eng, name, sort_order):
    with eng.begin() as conn:
        conn.execute(text("INSERT INTO video_style_presets (name, category, sort_order) VALUES (:n, 'realistic', :s)"), {"n": name, "s": sort_order})


def _names(eng):
    with eng.connect() as conn:
        return [row[0] for row in conn.execute(text("SELECT name FROM video_style_presets ORDER BY id"))]


def test_migration_never_renames_custom_preset_by_sort_order(engine):
    """管理员新增的风格排序号可能与内置风格相同（内置 1~8）：每次启动的迁移不能把它改回内置名。"""
    _insert(engine, "科技赛博风", 8)
    _insert(engine, "聊斋", 8)
    _insert(engine, "我的写实", 1)

    database._normalize_video_style_names(engine)
    database._normalize_video_style_names(engine)  # 迁移每次启动都会跑，必须幂等且不改用户命名

    assert _names(engine) == ["科技赛博风", "聊斋", "我的写实"]


def test_migration_still_fixes_known_typos(engine):
    _insert(engine, "科技赛模风", 8)
    _insert(engine, "日式动漏风", 2)

    database._normalize_video_style_names(engine)

    assert _names(engine) == ["科技赛博风", "日式动漫风"]


@pytest.fixture
def db(engine, monkeypatch):
    monkeypatch.setattr(video_router, "_require_user", lambda *_a, **_k: SimpleNamespace(id=1))
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _create(db, name, **extra):
    return asyncio.run(video_router.create_video_style_preset(VideoStylePresetCreate(name=name, **extra), SimpleNamespace(), db))


def test_create_rejects_duplicate_and_blank_names(db):
    first = _create(db, "聊斋", sort_order=9)
    assert first["name"] == "聊斋"
    with pytest.raises(HTTPException) as dup:
        _create(db, " 聊斋 ")
    assert dup.value.status_code == 409
    with pytest.raises(HTTPException) as blank:
        _create(db, "   ")
    assert blank.value.status_code == 422


def test_update_checks_name_against_other_presets_only(db):
    a = _create(db, "聊斋", sort_order=9)
    b = _create(db, "水墨", sort_order=10)

    # 保存自己（名字没变）不算重名
    asyncio.run(video_router.update_video_style_preset(a["id"], VideoStylePresetUpdate(name="聊斋", sort_order=11), SimpleNamespace(), db))
    # 改成别人的名字要拒绝
    with pytest.raises(HTTPException) as dup:
        asyncio.run(video_router.update_video_style_preset(b["id"], VideoStylePresetUpdate(name="聊斋"), SimpleNamespace(), db))
    assert dup.value.status_code == 409
    # 不改名只改其它字段也应放行（历史重名数据不被卡住）
    asyncio.run(video_router.update_video_style_preset(b["id"], VideoStylePresetUpdate(prompt_template="ink"), SimpleNamespace(), db))


def test_list_order_is_stable_when_sort_orders_tie(db):
    _create(db, "A", sort_order=5)
    _create(db, "B", sort_order=5)
    _create(db, "C", sort_order=5)

    names = [p["name"] for p in asyncio.run(video_router.list_video_style_presets(SimpleNamespace(), db))["presets"]]

    assert names == ["A", "B", "C"]
