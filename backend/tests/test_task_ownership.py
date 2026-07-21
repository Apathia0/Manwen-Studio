from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from main import _background_task_belongs_to_user
from models import BackgroundTask, Story, User


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def test_background_task_uses_billing_owner_as_authoritative_owner():
    db = _session()
    owner = User(email="owner@example.com", password_hash="x", role="user", status="active")
    other = User(email="other@example.com", password_hash="x", role="user", status="active")
    db.add_all([owner, other])
    db.flush()
    task = BackgroundTask(task_id="owned", task_type="video_render", quota_user_id=owner.id)

    assert _background_task_belongs_to_user(task, owner, db) is True
    assert _background_task_belongs_to_user(task, other, db) is False


def test_background_task_falls_back_to_story_owner_and_allows_admin():
    db = _session()
    owner = User(email="story-owner@example.com", password_hash="x", role="user", status="active")
    other = User(email="story-other@example.com", password_hash="x", role="user", status="active")
    db.add_all([owner, other])
    db.flush()
    story = Story(title="归属测试", owner_user_id=owner.id)
    db.add(story)
    db.flush()
    task = BackgroundTask(task_id="story-owned", task_type="novel_crawl", story_id=story.id)

    assert _background_task_belongs_to_user(task, owner, db) is True
    assert _background_task_belongs_to_user(task, other, db) is False
    assert _background_task_belongs_to_user(task, SimpleNamespace(id=999, role="admin"), db) is True
