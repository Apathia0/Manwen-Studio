import asyncio
import io
import os
import tempfile
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import main
from database import Base, get_db
from models import Chapter, MangaImage, PlatformSetting, Story, User


@pytest.fixture
def manga_zip_context(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setattr(main, "SYSTEM_READY", True)
    monkeypatch.setattr(
        main,
        "INSTALL_STATUS",
        {"installed": True, "requires_restart": False},
    )
    monkeypatch.setattr(main.license_checker, "check_domain", lambda _hostname: True)
    monkeypatch.setenv("STORYCANVAS_DOWNLOAD_SECRET", "manga-zip-test-secret-at-least-32-characters")

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    test_session = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(main, "SessionLocal", test_session)
    db = test_session()
    user = User(
        email="manga@example.com",
        password_hash="test",
        name="漫画作者",
        role="user",
        status="active",
        email_verified=True,
    )
    db.add(user)
    db.flush()
    story = Story(owner_user_id=user.id, title="测试漫画")
    db.add(story)
    db.flush()
    chapter = Chapter(story_id=story.id, chapter_number=12, title="导出测试")
    empty_chapter = Chapter(story_id=story.id, chapter_number=13, title="暂无图片")
    db.add_all([chapter, empty_chapter])
    db.flush()

    second_image = tmp_path / "second.jpg"
    first_image = tmp_path / "first.png"
    second_image.write_bytes(b"second-image")
    first_image.write_bytes(b"first-image")
    db.add_all(
        [
            MangaImage(chapter_id=chapter.id, image_number=2, image_path="stored/second.jpg"),
            MangaImage(chapter_id=chapter.id, image_number=1, image_path="stored/first.png"),
        ]
    )
    db.commit()

    resolved_paths = {
        "stored/first.png": str(first_image),
        "stored/second.jpg": str(second_image),
    }
    monkeypatch.setattr(
        main,
        "ensure_local_media_path",
        lambda value, _kind: resolved_paths.get(value),
    )
    current_user = SimpleNamespace(id=user.id, role="user")
    monkeypatch.setattr(main, "_require_user", lambda _request, _db: current_user)

    def override_get_db():
        yield db

    main.app.dependency_overrides[get_db] = override_get_db
    client = TestClient(main.app)
    try:
        yield SimpleNamespace(
            client=client,
            db=db,
            user=user,
            story=story,
            chapter=chapter,
            empty_chapter=empty_chapter,
            session_factory=test_session,
        )
    finally:
        main.app.dependency_overrides.clear()
        client.close()
        db.close()
        engine.dispose()


def test_manga_zip_ticket_rejects_expired_tampered_and_cross_chapter_tokens(
    manga_zip_context,
    monkeypatch,
):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("STORYCANVAS_DOWNLOAD_SECRET", "manga-zip-test-secret-at-least-32-characters")
    token = main._issue_manga_zip_ticket(12, 7, now=100)

    assert main._verify_manga_zip_ticket(12, token, now=160) is True
    assert main._verify_manga_zip_ticket(12, token, user_id=7, now=100) is True
    assert main._verify_manga_zip_ticket(12, token, user_id=8, now=100) is False
    assert main._verify_manga_zip_ticket(12, token, now=161) is False
    assert main._verify_manga_zip_ticket(13, token, now=100) is False
    assert main._verify_manga_zip_ticket(12, f"{token[:-1]}0", now=100) is False


def test_manga_zip_ticket_persists_database_secret_when_environment_is_missing(
    manga_zip_context,
    monkeypatch,
):
    ctx = manga_zip_context
    for name in (
        "STORYCANVAS_DOWNLOAD_SECRET",
        "AI_CREDENTIAL_SECRET",
        "SECRET_KEY",
        "JWT_SECRET",
    ):
        monkeypatch.delenv(name, raising=False)

    monkeypatch.setattr(main, "SessionLocal", ctx.session_factory)
    first_secret = main._manga_zip_ticket_secret()
    monkeypatch.setenv(
        "STORYCANVAS_DOWNLOAD_SECRET",
        "later-environment-secret-must-not-split-existing-database-key",
    )
    second_secret = main._manga_zip_ticket_secret()
    ctx.db.expire_all()
    rows = ctx.db.query(PlatformSetting).filter(
        PlatformSetting.setting_key == main._MANGA_ZIP_SECRET_SETTING_KEY
    ).all()

    assert len(first_secret) >= 32
    assert second_secret == first_secret
    assert len(rows) == 1
    assert rows[0].value_json == {"value": first_secret}


@pytest.mark.asyncio
async def test_temporary_manga_zip_response_removes_file_when_send_is_cancelled(
    monkeypatch,
    tmp_path: Path,
):
    archive_path = tmp_path / "cancelled.zip"
    archive_path.write_bytes(b"zip-content")
    response = main._TemporaryMangaZipResponse(archive_path)

    async def cancelled_file_response(_self, _scope, _receive, _send):
        raise asyncio.CancelledError

    monkeypatch.setattr(main.FileResponse, "__call__", cancelled_file_response)
    with pytest.raises(asyncio.CancelledError):
        await response({}, None, None)

    assert not archive_path.exists()


def test_manga_zip_ticket_and_download_return_sorted_archive(manga_zip_context):
    ctx = manga_zip_context
    ticket_response = ctx.client.post(
        f"/api/chapters/{ctx.chapter.id}/manga-images/zip-ticket"
    )

    assert ticket_response.status_code == 200
    ticket = ticket_response.json()
    assert ticket["expires_in"] == 60
    assert ticket["url"].startswith(
        f"/api/chapters/{ctx.chapter.id}/manga-images/zip?dl_token="
    )

    download_response = ctx.client.get(ticket["url"])
    assert download_response.status_code == 200
    assert download_response.headers["content-type"] == "application/zip"
    assert "filename*=UTF-8''" in download_response.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(download_response.content)) as archive:
        assert archive.namelist() == ["panel_01.png", "panel_02.jpg"]
        assert archive.read("panel_01.png") == b"first-image"
        assert archive.read("panel_02.jpg") == b"second-image"


def test_manga_zip_download_keeps_header_auth_compatibility(manga_zip_context):
    ctx = manga_zip_context

    response = ctx.client.get(
        f"/api/chapters/{ctx.chapter.id}/manga-images/zip"
    )

    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert archive.namelist() == ["panel_01.png", "panel_02.jpg"]


def test_signed_manga_zip_download_bypasses_global_api_token(manga_zip_context, monkeypatch):
    ctx = manga_zip_context
    monkeypatch.setattr(main, "API_TOKEN", "global-api-token")
    ticket_response = ctx.client.post(
        f"/api/chapters/{ctx.chapter.id}/manga-images/zip-ticket",
        headers={"X-API-Token": "global-api-token"},
    )
    assert ticket_response.status_code == 200

    response = ctx.client.get(ticket_response.json()["url"])

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"


def test_manga_zip_ticket_returns_404_without_images(manga_zip_context):
    ctx = manga_zip_context

    response = ctx.client.post(
        f"/api/chapters/{ctx.empty_chapter.id}/manga-images/zip-ticket"
    )

    assert response.status_code == 404


def test_manga_zip_missing_image_returns_502_and_removes_temp_file(
    manga_zip_context,
    monkeypatch,
    tmp_path: Path,
):
    ctx = manga_zip_context
    archive_path = tmp_path / "incomplete.zip"

    def fake_mkstemp(*_args, **_kwargs):
        descriptor = os.open(
            archive_path,
            os.O_CREAT | os.O_RDWR | os.O_TRUNC,
        )
        return descriptor, str(archive_path)

    monkeypatch.setattr(main.tempfile, "mkstemp", fake_mkstemp)
    monkeypatch.setattr(
        main,
        "ensure_local_media_path",
        lambda value, _kind: None if value == "stored/second.jpg" else str(tmp_path / "first.png"),
    )
    (tmp_path / "first.png").write_bytes(b"first-image")

    response = ctx.client.get(
        f"/api/chapters/{ctx.chapter.id}/manga-images/zip"
    )

    assert response.status_code == 502
    assert not archive_path.exists()
