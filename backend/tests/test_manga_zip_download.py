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
def manga_export_context(monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
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
    test_session = sessionmaker(bind=engine, expire_on_commit=False)
    db = test_session()
    owner = User(
        email="manga@example.com",
        password_hash="test",
        name="漫画作者",
        role="user",
        status="active",
        email_verified=True,
    )
    intruder = User(
        email="intruder@example.com",
        password_hash="test",
        name="其他用户",
        role="user",
        status="active",
        email_verified=True,
    )
    db.add_all([owner, intruder])
    db.flush()
    story = Story(owner_user_id=owner.id, title="测试漫画")
    db.add(story)
    db.flush()
    chapter = Chapter(story_id=story.id, chapter_number=12, title="导出测试")
    empty_chapter = Chapter(story_id=story.id, chapter_number=13, title="暂无图片")
    db.add_all([chapter, empty_chapter])
    db.flush()

    first_image = MangaImage(
        chapter_id=chapter.id,
        image_number=1,
        image_path="https://cdn.example.com/assets/manga_outputs/chapter_1/first.png",
    )
    second_image = MangaImage(
        chapter_id=chapter.id,
        image_number=2,
        image_path="https://cdn.example.com/assets/manga_outputs/chapter_1/second.jpg?version=2",
    )
    db.add_all([
        first_image,
        second_image,
        PlatformSetting(
            setting_key="oss.public_url_base",
            value_json={"value": "https://cdn.example.com/assets"},
        ),
        PlatformSetting(setting_key="oss.bucket", value_json={"value": "story-bucket"}),
        PlatformSetting(
            setting_key="oss.endpoint",
            value_json={"value": "oss-cn-hangzhou.aliyuncs.com"},
        ),
    ])
    db.commit()

    current_user = {"value": SimpleNamespace(id=owner.id, role="user")}
    monkeypatch.setattr(main, "_require_user", lambda _request, _db: current_user["value"])

    def override_get_db():
        yield db

    main.app.dependency_overrides[get_db] = override_get_db
    client = TestClient(main.app)
    try:
        yield SimpleNamespace(
            client=client,
            db=db,
            owner=owner,
            intruder=intruder,
            chapter=chapter,
            empty_chapter=empty_chapter,
            first_image=first_image,
            second_image=second_image,
            current_user=current_user,
        )
    finally:
        main.app.dependency_overrides.clear()
        client.close()
        db.close()
        engine.dispose()


def _set_setting(ctx, key: str, value: str) -> None:
    row = ctx.db.query(PlatformSetting).filter(PlatformSetting.setting_key == key).one()
    row.value_json = {"value": value}


def test_manga_export_manifest_returns_sorted_public_oss_urls(manga_export_context):
    ctx = manga_export_context

    response = ctx.client.get(
        f"/api/chapters/{ctx.chapter.id}/manga-images/export-manifest"
    )

    assert response.status_code == 200
    assert response.json() == {
        "images": [
            {
                "image_number": 1,
                "filename": "panel_01.png",
                "download_url": ctx.first_image.image_path,
            },
            {
                "image_number": 2,
                "filename": "panel_02.jpg",
                "download_url": ctx.second_image.image_path,
            },
        ]
    }


def test_manga_export_manifest_allows_bucket_endpoint_https_url(manga_export_context):
    ctx = manga_export_context
    _set_setting(ctx, "oss.public_url_base", "")
    ctx.first_image.image_path = (
        "https://story-bucket.oss-cn-hangzhou.aliyuncs.com/"
        "manga_outputs/chapter_1/first.png"
    )
    ctx.second_image.image_path = (
        "https://story-bucket.oss-cn-hangzhou.aliyuncs.com/"
        "manga_outputs/chapter_1/second.webp"
    )
    ctx.db.commit()

    response = ctx.client.get(
        f"/api/chapters/{ctx.chapter.id}/manga-images/export-manifest"
    )

    assert response.status_code == 200
    assert [item["filename"] for item in response.json()["images"]] == [
        "panel_01.png",
        "panel_02.webp",
    ]


@pytest.mark.parametrize(
    "image_path",
    [
        "/static/manga/chapter_1/first.png",
        "https://third-party.example/manga_outputs/chapter_1/first.png",
        "https://cdn.example.com/assets/other_outputs/chapter_1/first.png",
        "http://cdn.example.com/assets/manga_outputs/chapter_1/first.png",
        "https://cdn.example.com/assets/manga_outputs/%2e%2e/private.png",
    ],
)
def test_manga_export_manifest_rejects_non_allowlisted_sources(
    manga_export_context,
    image_path,
):
    ctx = manga_export_context
    ctx.first_image.image_path = image_path
    ctx.db.commit()

    response = ctx.client.get(
        f"/api/chapters/{ctx.chapter.id}/manga-images/export-manifest"
    )

    assert response.status_code == 409
    assert "第 1 页" in response.json()["detail"]


def test_manga_export_manifest_rejects_missing_page(manga_export_context):
    ctx = manga_export_context
    ctx.second_image.image_number = 3
    ctx.db.commit()

    response = ctx.client.get(
        f"/api/chapters/{ctx.chapter.id}/manga-images/export-manifest"
    )

    assert response.status_code == 409
    assert "缺少第 2 页" in response.json()["detail"]


def test_manga_export_manifest_rejects_trailing_page_missing_from_storyboard(
    manga_export_context,
):
    ctx = manga_export_context
    ctx.chapter.manga_storyboard_json = {
        "schema_version": 1,
        "scenes": ["第一页", "第二页", "第三页"],
        "sanitized_indices": [],
    }
    ctx.db.commit()

    response = ctx.client.get(
        f"/api/chapters/{ctx.chapter.id}/manga-images/export-manifest"
    )

    assert response.status_code == 409
    assert "缺少第 3 页" in response.json()["detail"]


def test_manga_export_manifest_returns_409_without_images(manga_export_context):
    ctx = manga_export_context

    response = ctx.client.get(
        f"/api/chapters/{ctx.empty_chapter.id}/manga-images/export-manifest"
    )

    assert response.status_code == 409
    assert "暂无可导出" in response.json()["detail"]


def test_manga_export_manifest_rejects_non_owner(manga_export_context):
    ctx = manga_export_context
    ctx.current_user["value"] = SimpleNamespace(id=ctx.intruder.id, role="user")

    response = ctx.client.get(
        f"/api/chapters/{ctx.chapter.id}/manga-images/export-manifest"
    )

    assert response.status_code == 403


def test_retired_manga_zip_routes_always_return_410_without_reading_images(
    manga_export_context,
    monkeypatch,
):
    ctx = manga_export_context
    monkeypatch.setattr(main, "API_TOKEN", "global-api-token")
    monkeypatch.setattr(
        main,
        "ensure_local_media_path",
        lambda *_args, **_kwargs: pytest.fail("旧 ZIP 路由不应读取图片"),
    )
    monkeypatch.setattr(
        main,
        "_require_user",
        lambda *_args, **_kwargs: pytest.fail("旧 ZIP 路由不应执行鉴权查询"),
    )

    def fail_get_db():
        pytest.fail("旧 ZIP 路由不应创建数据库会话")
        yield

    main.app.dependency_overrides[get_db] = fail_get_db

    ticket_response = ctx.client.post(
        f"/api/chapters/{ctx.chapter.id}/manga-images/zip-ticket"
    )
    zip_response = ctx.client.get(
        f"/api/chapters/{ctx.chapter.id}/manga-images/zip?dl_token=legacy"
    )

    assert ticket_response.status_code == 410
    assert zip_response.status_code == 410
    assert "已停用" in ticket_response.json()["detail"]
    assert "已停用" in zip_response.json()["detail"]
