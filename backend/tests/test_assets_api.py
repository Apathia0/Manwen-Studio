"""GET /api/assets 跨作品资产中心接口测试"""
import datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import main
from database import Base, get_db
from models import (
    Chapter,
    ChapterVideoShot,
    ChapterVideoWorkflow,
    MangaAsset,
    MangaImage,
    Story,
    User,
    VideoAsset,
)


@pytest.fixture
def assets_context(monkeypatch):
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
        email="assets-owner@example.com",
        password_hash="test",
        name="资产作者",
        role="user",
        status="active",
        email_verified=True,
    )
    intruder = User(
        email="assets-intruder@example.com",
        password_hash="test",
        name="其他用户",
        role="user",
        status="active",
        email_verified=True,
    )
    db.add_all([owner, intruder])
    db.flush()

    story = Story(owner_user_id=owner.id, title="资产测试作品")
    other_story = Story(owner_user_id=intruder.id, title="他人作品")
    db.add_all([story, other_story])
    db.flush()

    chapter = Chapter(story_id=story.id, chapter_number=1, title="第一章")
    db.add(chapter)
    db.flush()

    # 漫画图片：相对路径（manga_outputs/ 前缀）
    manga_img = MangaImage(
        chapter_id=chapter.id,
        image_number=1,
        image_path="manga_outputs/chapter_1/first.png",
        prompt="测试提示词",
        created_at=datetime.datetime(2026, 8, 1, 10, 0, 0),
    )
    # 漫画素材
    manga_asset = MangaAsset(
        owner_user_id=owner.id,
        story_id=story.id,
        chapter_id=chapter.id,
        asset_type="character",
        name="主角立绘",
        storage_path="manga_outputs/assets/hero.png",
        source_type="upload",
        status="active",
        created_at=datetime.datetime(2026, 8, 2, 10, 0, 0),
    )
    # 视频素材（file_path 为图片）
    video_asset = VideoAsset(
        story_id=story.id,
        chapter_id=chapter.id,
        asset_type="storyboard",
        name="故事版参考图",
        file_path="refs/ref.png",
        provider="image2",
        prompt="参考图",
        status="active",
        created_at=datetime.datetime(2026, 8, 3, 10, 0, 0),
    )
    # 视频工作流 + 分镜 + 成片
    workflow = ChapterVideoWorkflow(chapter_id=chapter.id, story_id=story.id)
    db.add(workflow)
    db.flush()
    storyboard_shot = ChapterVideoShot(
        workflow_id=workflow.id,
        shot_index=1,
        storyboard_prompt="少年在月光下抬头望向远方",
        storyboard_image_url="/static/video/shot_1/storyboard.png",
        video_url=None,
        duration_seconds=15,
        status="completed",
        created_at=datetime.datetime(2026, 8, 4, 10, 0, 0),
    )
    video_shot = ChapterVideoShot(
        workflow_id=workflow.id,
        shot_index=2,
        storyboard_prompt="少年转身离开",
        storyboard_image_url="/static/video/shot_2/storyboard.png",
        video_url="/static/video/shot_2/final.mp4",
        duration_seconds=15,
        status="completed",
        created_at=datetime.datetime(2026, 8, 5, 10, 0, 0),
    )
    db.add_all([manga_img, manga_asset, video_asset, storyboard_shot, video_shot])
    db.commit()

    current_user = {"user": SimpleNamespace(id=owner.id, role="user")}
    monkeypatch.setattr(main, "_require_user", lambda _request, _db: current_user["user"])

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
            story=story,
            other_story=other_story,
            chapter=chapter,
            manga_img=manga_img,
            manga_asset=manga_asset,
            video_asset=video_asset,
            storyboard_shot=storyboard_shot,
            video_shot=video_shot,
            current_user=current_user,
        )
    finally:
        main.app.dependency_overrides.clear()
        client.close()
        db.close()
        engine.dispose()


def test_assets_empty_user_returns_empty_lists(assets_context):
    """无任何作品的用户返回空作品列表与空资产列表"""
    ctx = assets_context
    ctx.current_user["user"] = SimpleNamespace(id=999, role="user")

    response = ctx.client.get("/api/assets")

    assert response.status_code == 200
    data = response.json()
    assert data["stories"] == []
    assert data["assets"] == []
    assert data["total"] == 0


def test_assets_returns_owned_stories(assets_context):
    """作品列表只包含当前用户拥有的作品"""
    ctx = assets_context

    response = ctx.client.get("/api/assets")

    assert response.status_code == 200
    data = response.json()
    assert [s["id"] for s in data["stories"]] == [ctx.story.id]
    assert data["stories"][0]["title"] == "资产测试作品"


def test_manga_image_filters_by_owned_story(assets_context):
    """漫画图片按所属作品过滤，且不泄露他人作品数据"""
    ctx = assets_context

    response = ctx.client.get("/api/assets", params={"kind": "manga_image"})

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    asset = data["assets"][0]
    assert asset["kind"] == "manga_image"
    assert asset["media_type"] == "image"
    assert asset["story_id"] == ctx.story.id
    assert asset["chapter_id"] == ctx.chapter.id
    assert asset["name"] == "漫画图 1"
    assert asset["meta"] == {"image_number": 1, "prompt": "测试提示词"}


def test_manga_image_not_visible_to_other_user(assets_context):
    """其他用户无法看到他人作品下的漫画图片"""
    ctx = assets_context
    ctx.current_user["user"] = SimpleNamespace(id=ctx.intruder.id, role="user")

    response = ctx.client.get("/api/assets", params={"kind": "manga_image"})

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 0
    assert data["assets"] == []


def test_manga_image_relative_path_converted_to_public_url(assets_context):
    """相对路径 manga_outputs/... 转换为 /static/manga/... 公开 URL"""
    ctx = assets_context

    response = ctx.client.get("/api/assets", params={"kind": "manga_image"})

    assert response.status_code == 200
    data = response.json()
    assert data["assets"][0]["url"] == "/static/manga/chapter_1/first.png"


def test_manga_asset_relative_path_converted_to_public_url(assets_context):
    """漫画素材的相对路径同样转换为 /static/manga/... 公开 URL"""
    ctx = assets_context

    response = ctx.client.get("/api/assets", params={"kind": "manga_asset"})

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    asset = data["assets"][0]
    assert asset["kind"] == "manga_asset"
    assert asset["media_type"] == "image"
    assert asset["name"] == "主角立绘"
    assert asset["url"] == "/static/manga/assets/hero.png"
    assert asset["meta"] == {"asset_type": "character", "source_type": "upload"}


def test_video_asset_url_conversion(assets_context):
    """视频素材 file_path 通过 _to_video_url 转换为 /static/video/... URL"""
    ctx = assets_context

    response = ctx.client.get("/api/assets", params={"kind": "video_asset"})

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    asset = data["assets"][0]
    assert asset["kind"] == "video_asset"
    assert asset["media_type"] == "image"
    assert asset["url"] == "/static/video/refs/ref.png"
    assert asset["meta"]["asset_type"] == "storyboard"
    assert asset["meta"]["provider"] == "image2"


def test_video_storyboard_kind(assets_context):
    """视频分镜：有故事版图且无成片，URL 原样透传"""
    ctx = assets_context

    response = ctx.client.get("/api/assets", params={"kind": "video_storyboard"})

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    asset = data["assets"][0]
    assert asset["kind"] == "video_storyboard"
    assert asset["media_type"] == "image"
    assert asset["story_id"] == ctx.story.id
    assert asset["chapter_id"] == ctx.chapter.id
    assert asset["name"] == "分镜 少年在月光下抬头望向远方"
    assert asset["url"] == "/static/video/shot_1/storyboard.png"
    assert asset["meta"] == {"duration_seconds": 15, "status": "completed"}


def test_video_shot_kind(assets_context):
    """视频片段：有成片，media_type 为 video"""
    ctx = assets_context

    response = ctx.client.get("/api/assets", params={"kind": "video_shot"})

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    asset = data["assets"][0]
    assert asset["kind"] == "video_shot"
    assert asset["media_type"] == "video"
    assert asset["name"] == "视频片段"
    assert asset["url"] == "/static/video/shot_2/final.mp4"
    assert asset["meta"] == {"duration_seconds": 15, "status": "completed"}


def test_assets_merged_sorted_by_created_at_desc(assets_context):
    """五个来源合并后按创建时间倒序排列"""
    ctx = assets_context

    response = ctx.client.get("/api/assets")

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 5
    kinds = [a["kind"] for a in data["assets"]]
    assert kinds == ["video_shot", "video_storyboard", "video_asset", "manga_asset", "manga_image"]


def test_assets_story_id_filter(assets_context):
    """story_id 过滤只返回指定作品下的资产"""
    ctx = assets_context

    response = ctx.client.get("/api/assets", params={"story_id": ctx.story.id})

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 5
    assert all(a["story_id"] == ctx.story.id for a in data["assets"])


def test_assets_invalid_kind_returns_400(assets_context):
    """非法 kind 返回 400"""
    ctx = assets_context

    response = ctx.client.get("/api/assets", params={"kind": "not_a_kind"})

    assert response.status_code == 400


def test_assets_offset_limit_pagination(assets_context):
    """offset/limit 分页生效，total 为合并后的总数"""
    ctx = assets_context

    response = ctx.client.get("/api/assets", params={"limit": 2, "offset": 1})

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 5
    assert len(data["assets"]) == 2
    assert [a["kind"] for a in data["assets"]] == ["video_storyboard", "video_asset"]