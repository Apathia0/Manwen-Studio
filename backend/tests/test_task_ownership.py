from types import SimpleNamespace

import asyncio
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import pytest

from database import Base
import main
from main import _background_task_belongs_to_user
from models import BackgroundTask, Chapter, Story, User
from services.errors import UpstreamServiceError


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


def test_external_generation_conflict_rejects_active_background_task():
    db = _session()
    db.add(BackgroundTask(
        task_id="chapter_gen_23_active",
        task_type="chapter_generation",
        chapter_id=23,
        status="running",
    ))
    db.commit()

    request = SimpleNamespace(headers={})
    with pytest.raises(main.HTTPException) as exc_info:
        main._reject_external_chapter_generation_conflict(request, 23, db)

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["task_id"] == "chapter_gen_23_active"


def test_external_generation_lease_rejects_same_chapter_agent_or_direct_run():
    async def scenario() -> None:
        lease = await main._acquire_external_chapter_generation_lease(12, 23)
        try:
            with pytest.raises(main.HTTPException) as exc_info:
                await main._acquire_external_chapter_generation_lease(12, 23)
            assert exc_info.value.status_code == 409
        finally:
            await lease.release()

    asyncio.run(scenario())


def test_internal_generation_signature_allows_background_task_call():
    db = _session()
    db.add(BackgroundTask(
        task_id="chapter_gen_23_active",
        task_type="chapter_generation",
        chapter_id=23,
        status="running",
    ))
    db.commit()

    request = SimpleNamespace(headers={
        main._CHAPTER_GENERATION_INTERNAL_HEADER: main._CHAPTER_GENERATION_INTERNAL_SECRET,
    })

    main._reject_external_chapter_generation_conflict(request, 23, db)


def test_generation_forward_headers_do_not_accept_external_internal_signature():
    request = SimpleNamespace(headers={
        "authorization": "Bearer user-token",
        main._CHAPTER_GENERATION_INTERNAL_HEADER: "forged-token",
    })

    headers = main._generation_forward_headers(request)

    assert headers == {"authorization": "Bearer user-token"}


def test_internal_asgi_generation_uses_dev_domain_and_private_signature(monkeypatch):
    captured = {}

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"id": 23, "chapter_number": 5}

    class FakeAsyncClient:
        def __init__(self, *, transport, base_url, timeout):
            captured["base_url"] = str(base_url)
            captured["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, path, json, headers):
            captured["path"] = path
            captured["headers"] = dict(headers)
            return FakeResponse()

    monkeypatch.setattr(main.httpx, "AsyncClient", FakeAsyncClient)

    result = asyncio.run(main._run_chapter_generation_request(
        23,
        "/api/chapters/23/generate-novel",
        None,
        {"authorization": "Bearer user-token"},
        task_id=None,
        story_id=12,
        chapter_id=23,
    ))

    assert result["status"] == "succeeded"
    assert captured["base_url"] == "http://localhost"
    assert captured["headers"]["authorization"] == "Bearer user-token"
    assert captured["headers"][main._CHAPTER_GENERATION_INTERNAL_HEADER] == main._CHAPTER_GENERATION_INTERNAL_SECRET


def test_internal_generation_preserves_structured_writer_error(monkeypatch):
    class FakeResponse:
        status_code = 502

        def json(self):
            return {
                "detail": {
                    "code": "writer_empty_content",
                    "message": "正文模型未返回可用正文，系统已停止保存",
                    "retryable": True,
                    "provider": "DeepSeek",
                    "status_code": 502,
                    "suggestion": "请重试生成",
                    "diagnostics": {"finish_reason": "length", "reasoning_tokens": 8192},
                }
            }

    class FakeAsyncClient:
        def __init__(self, *, transport, base_url, timeout):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, path, json, headers):
            return FakeResponse()

    monkeypatch.setattr(main.httpx, "AsyncClient", FakeAsyncClient)

    with pytest.raises(UpstreamServiceError) as exc_info:
        asyncio.run(main._run_chapter_generation_request(
            23,
            "/api/chapters/23/generate-novel",
            None,
            {"authorization": "Bearer user-token"},
            story_id=12,
        ))

    assert exc_info.value.code == "writer_empty_content"
    assert exc_info.value.retryable is True
    assert exc_info.value.diagnostics == {"finish_reason": "length", "reasoning_tokens": 8192}


def test_external_expand_chapter_rejects_active_background_task(monkeypatch):
    db = _session()
    user = User(email="expand-owner@example.com", password_hash="x", role="user", status="active")
    db.add(user)
    db.flush()
    story = Story(title="扩写冲突测试", owner_user_id=user.id)
    db.add(story)
    db.flush()
    chapter = Chapter(story_id=story.id, chapter_number=3, title="第三章", status="pending")
    db.add(chapter)
    db.flush()
    db.add(BackgroundTask(
        task_id="chapter_gen_expand_active",
        task_type="chapter_generation",
        story_id=story.id,
        chapter_id=chapter.id,
        status="running",
    ))
    db.commit()

    class FakeRequest:
        headers = {}

        async def json(self):
            return {"chapter_number": 3, "chapter_title": "第三章"}

    monkeypatch.setattr(main, "_require_user", lambda request, session: user)
    monkeypatch.setattr(main, "_require_story_for_user", lambda story_id, owner, session: story)

    with pytest.raises(main.HTTPException) as exc_info:
        asyncio.run(main.expand_chapter_endpoint(story.id, FakeRequest(), db))

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["task_id"] == "chapter_gen_expand_active"
