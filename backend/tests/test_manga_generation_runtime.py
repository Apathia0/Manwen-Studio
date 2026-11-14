import asyncio
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import main
from models import BackgroundTask, Base
from services import image2


@pytest.mark.asyncio
async def test_image_count_can_change_after_images_exist(monkeypatch, tmp_path):
    chapter = SimpleNamespace(images=[SimpleNamespace(id=1)])
    monkeypatch.setattr(main, "_require_user", lambda _request, _db: SimpleNamespace(id=7))
    monkeypatch.setattr(main, "_require_chapter_for_user", lambda *_args: chapter)
    count_path = tmp_path / "chapter_49" / "image_count.txt"
    monkeypatch.setattr(main, "_image_count_path", lambda _chapter_id: count_path)

    result = await main.set_image_count(49, {"image_count": 8}, object(), object())

    assert result == {"ok": True, "image_count": 8}
    assert count_path.read_text(encoding="utf-8") == "8"


def test_manga_image_concurrency_defaults_to_two_and_caps_at_two(monkeypatch):
    monkeypatch.delenv("MANGA_IMAGE_CONCURRENCY", raising=False)
    assert main._load_manga_image_concurrency() == 2

    monkeypatch.setenv("MANGA_IMAGE_CONCURRENCY", "8")
    assert main._load_manga_image_concurrency() == 2


def test_manga_generation_timeout_per_page_is_bounded(monkeypatch):
    monkeypatch.setenv("MANGA_IMAGE_TIMEOUT_PER_PAGE", "30")
    assert main._load_manga_generation_timeout_per_image() == 180

    monkeypatch.setenv("MANGA_IMAGE_TIMEOUT_PER_PAGE", "1200")
    assert main._load_manga_generation_timeout_per_image() == 900


def test_manga_image_start_interval_defaults_to_five_and_is_bounded(monkeypatch):
    monkeypatch.delenv("MANGA_IMAGE_START_INTERVAL_SECONDS", raising=False)
    assert main._load_manga_image_start_interval() == 5

    monkeypatch.setenv("MANGA_IMAGE_START_INTERVAL_SECONDS", "90")
    assert main._load_manga_image_start_interval() == 60


def test_only_one_active_manga_task_is_allowed_per_chapter():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    first = BackgroundTask(
        task_id="manga-first",
        task_type="manga_generation",
        chapter_id=49,
        status="running",
    )
    db.add(first)
    db.commit()

    db.add(BackgroundTask(
        task_id="manga-duplicate",
        task_type="manga_generation",
        chapter_id=49,
        status="pending",
    ))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()

    first.status = "succeeded"
    db.commit()
    db.add(BackgroundTask(
        task_id="manga-retry",
        task_type="manga_generation",
        chapter_id=49,
        status="pending",
    ))
    db.commit()
    db.close()


def test_gateway_524_is_not_retried():
    request = httpx.Request("POST", "https://images.example.com/v1/images/edits")
    response = httpx.Response(524, request=request, text="openai_error")

    error = image2._classify_response_error(response, "1/1", "测试提示词", False)

    assert error.code == "upstream_gateway_timeout"
    assert error.retryable is False
    assert error.status_code == 524


class _EmptyQuery:
    def filter(self, *_args):
        return self

    def first(self):
        return None


class _EmptySession:
    def query(self, *_args):
        return _EmptyQuery()

    def close(self):
        return None


@pytest.mark.asyncio
async def test_parent_cancellation_stops_all_page_tasks(monkeypatch):
    started = 0
    all_started = asyncio.Event()
    cancelled_pages: list[int] = []

    async def blocking_generate(*_args, **kwargs):
        nonlocal started
        page = int(kwargs.get("image_number") or _args[2])
        started += 1
        if started == 2:
            all_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled_pages.append(page)
            raise

    monkeypatch.setattr(main, "SessionLocal", _EmptySession)
    monkeypatch.setattr(main, "MANGA_IMAGE_CONCURRENCY", 2)
    monkeypatch.setattr(main, "MANGA_IMAGE_START_INTERVAL_SECONDS", 0)
    monkeypatch.setattr(main, "generate_manga_image", blocking_generate)
    monkeypatch.setattr(main.task_manager, "update_task_metadata", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main.task_manager, "is_cancellation_requested", lambda *_args: False)

    parent = asyncio.create_task(main._background_manga_generation_concurrent(
        chapter_id=9,
        scenes=["第一页", "第二页"],
        image_count=2,
        character_profiles="",
        ref_entries=[],
        color_mode="color",
        image_api_key="test-key",
        task_id="cancel-test",
    ))
    await asyncio.wait_for(all_started.wait(), timeout=1)
    parent.cancel()

    with pytest.raises(asyncio.CancelledError):
        await parent

    assert sorted(cancelled_pages) == [1, 2]
