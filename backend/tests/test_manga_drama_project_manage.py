"""漫剧项目的编辑 / 删除：只允许操作自己的 story_type='video' 作品，删除要先清掉画布数据。"""

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import main
from database import Base
from models import (
    CanvasAgentAction,
    Story,
    User,
    VideoCanvas,
    VideoCanvasLayout,
    VideoCanvasRun,
    VideoCanvasRunNode,
    VideoCanvasVersion,
)
from routers import video_canvas as router


@pytest.fixture
def env(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        owner = User(email="owner@example.com", password_hash="x", name="作者")
        other = User(email="other@example.com", password_hash="x", name="别人")
        db.add_all([owner, other])
        db.flush()
        drama = Story(title="我的漫剧", owner_user_id=owner.id, story_type="video")
        another_drama = Story(title="另一个漫剧", owner_user_id=owner.id, story_type="video")
        novel = Story(title="一部小说", owner_user_id=owner.id, story_type="novel")
        foreign = Story(title="别人的漫剧", owner_user_id=other.id, story_type="video")
        db.add_all([drama, another_drama, novel, foreign])
        db.flush()
        for story in (drama, another_drama):
            canvas = VideoCanvas(owner_user_id=owner.id, story_id=story.id, name="画布", definition_revision=1)
            db.add(canvas)
            db.flush()
            db.add(VideoCanvasVersion(canvas_id=canvas.id, version_no=1, graph_json={"nodes": [], "edges": []}, source="manual"))
            db.add(VideoCanvasLayout(canvas_id=canvas.id, layout_json={}))
            run = VideoCanvasRun(canvas_id=canvas.id, canvas_version_id=1, status="succeeded", plan_json={})
            db.add(run)
            db.flush()
            db.add(VideoCanvasRunNode(run_id=run.id, node_id="n1", node_type="image", status="succeeded"))
            db.add(CanvasAgentAction(canvas_id=canvas.id, owner_user_id=owner.id, conversation_id=1, permission_mode="ask", stage="node_edit",
                                     tool_name="apply_canvas_ops", summary="x", arguments_json={}, expected_definition_revision=1, status="completed"))
        db.commit()
        ids = SimpleNamespace(owner=owner.id, drama=drama.id, another=another_drama.id, novel=novel.id, foreign=foreign.id)
        user = SimpleNamespace(id=owner.id)
    monkeypatch.setattr(router, "_require_user", lambda request, db: user)
    monkeypatch.setattr(main, "_require_user", lambda request, db: user)
    yield factory, ids
    engine.dispose()


def _count(factory, model, **filters):
    with factory() as db:
        return db.query(model).filter_by(**filters).count()


def test_update_renames_and_sets_description(env):
    factory, ids = env
    result = asyncio.run(router.update_manga_drama_project(ids.drama, router.MangaDramaProjectUpdate(title="  新名字  ", description="一句简介"), None, factory()))
    assert result["title"] == "新名字" and result["description"] == "一句简介"
    with factory() as db:
        assert db.get(Story, ids.drama).title == "新名字"


def test_update_rejects_blank_title_and_foreign_or_non_video_stories(env):
    factory, ids = env
    with pytest.raises(HTTPException) as blank:
        asyncio.run(router.update_manga_drama_project(ids.drama, router.MangaDramaProjectUpdate(title="   "), None, factory()))
    assert blank.value.status_code == 422
    for story_id in (ids.novel, ids.foreign, 99999):
        with pytest.raises(HTTPException) as denied:
            asyncio.run(router.update_manga_drama_project(story_id, router.MangaDramaProjectUpdate(title="改名"), None, factory()))
        assert denied.value.status_code == 404


def test_delete_removes_project_and_all_canvas_data_but_keeps_other_projects(env):
    factory, ids = env
    with factory() as db:
        canvas_id = db.query(VideoCanvas).filter_by(story_id=ids.drama).one().id
    result = asyncio.run(router.delete_manga_drama_project(ids.drama, None, factory()))
    assert result == {"ok": True}
    with factory() as db:
        assert db.get(Story, ids.drama) is None
        assert db.query(VideoCanvas).filter_by(story_id=ids.drama).count() == 0
        assert db.query(VideoCanvasVersion).filter_by(canvas_id=canvas_id).count() == 0
        assert db.query(VideoCanvasRun).filter_by(canvas_id=canvas_id).count() == 0
        assert db.query(CanvasAgentAction).filter_by(canvas_id=canvas_id).count() == 0
        # 其它项目与小说不受影响
        assert db.get(Story, ids.another) is not None and db.get(Story, ids.novel) is not None
        assert db.query(VideoCanvas).filter_by(story_id=ids.another).count() == 1
        assert db.query(VideoCanvasVersion).count() == 1 and db.query(VideoCanvasRunNode).count() == 1


def test_delete_is_refused_while_a_generation_is_running(env):
    factory, ids = env
    with factory() as db:
        canvas_id = db.query(VideoCanvas).filter_by(story_id=ids.drama).one().id
        db.add(VideoCanvasRun(canvas_id=canvas_id, canvas_version_id=1, status="running", plan_json={}))
        db.commit()
    with pytest.raises(HTTPException) as refused:
        asyncio.run(router.delete_manga_drama_project(ids.drama, None, factory()))
    assert refused.value.status_code == 409 and "停止" in str(refused.value.detail)
    assert _count(factory, Story, id=ids.drama) == 1 and _count(factory, VideoCanvas, story_id=ids.drama) == 1


def test_delete_never_touches_novels_or_other_users_projects(env):
    factory, ids = env
    for story_id in (ids.novel, ids.foreign, 99999):
        with pytest.raises(HTTPException) as denied:
            asyncio.run(router.delete_manga_drama_project(story_id, None, factory()))
        assert denied.value.status_code == 404
    assert _count(factory, Story, id=ids.novel) == 1 and _count(factory, Story, id=ids.foreign) == 1
