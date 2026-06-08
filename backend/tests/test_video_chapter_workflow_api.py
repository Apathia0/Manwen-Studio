import asyncio
from types import SimpleNamespace

from sqlalchemy.exc import InvalidRequestError

from routers import video as video_router
from schemas import ChapterVideoWorkflowCreate
from services import video_chapter_pipeline


class _FakeDb:
    def __init__(self):
        self.refresh_calls: list[object] = []

    def refresh(self, obj: object):
        self.refresh_calls.append(obj)
        raise InvalidRequestError("Instance is not persistent within this Session")

    def get(self, model, pk):
        if getattr(model, "__name__", "") == "Story":
            return SimpleNamespace(id=pk, owner_user_id=1)
        return None


def test_api_create_chapter_workflow_does_not_refresh_detached_instance(monkeypatch):
    db = _FakeDb()
    init_db_calls: list[dict[str, object]] = []
    detached_workflow = SimpleNamespace(
        id=77,
        chapter_id=440,
        story_id=900,
        workflow_status="pending",
        character_reference_ids=[11, 22],
        video_style="写实电影感",
        duration_per_shot=10,
        total_shots=0,
        completed_shots=0,
        failed_shots=0,
        error_message=None,
        created_at=None,
        updated_at=None,
        shots=[],
    )
    persistent_workflow = SimpleNamespace(
        id=77,
        chapter_id=440,
        story_id=900,
        workflow_status="pending",
        character_reference_ids=[11, 22],
        video_style="写实电影感",
        duration_per_shot=10,
        total_shots=0,
        completed_shots=0,
        failed_shots=0,
        error_message=None,
        created_at=None,
        updated_at=None,
        shots=[],
    )

    monkeypatch.setattr(video_router, "_require_user", lambda request, db_session: SimpleNamespace(id=1))
    monkeypatch.setattr(
        video_router,
        "_require_chapter_for_user",
        lambda chapter_id, user, db_session: SimpleNamespace(id=chapter_id, story_id=900, novel_content="章节正文"),
    )
    monkeypatch.setattr(video_router, "create_chapter_workflow", lambda **kwargs: detached_workflow)

    async def fake_start_background(workflow_id: int, api_key: str | None = None, **kwargs):
        return f"chapter_video_{workflow_id}"

    monkeypatch.setattr(video_router, "start_workflow_background", fake_start_background)
    monkeypatch.setattr(video_router, "_user_deepseek_api_key", lambda request, db_session: "deepseek-key")
    monkeypatch.setattr(video_router, "_user_image_api_key", lambda request: "image-key")
    monkeypatch.setattr(video_router, "get_chapter_workflow", lambda workflow_id: persistent_workflow)
    monkeypatch.setattr(video_router, "init_db", lambda **kwargs: init_db_calls.append(kwargs), raising=False)

    result = asyncio.run(
        video_router.api_create_chapter_workflow(
            body=ChapterVideoWorkflowCreate(chapter_id=440, character_reference_ids=[11, 22], video_style="写实电影感"),
            request=SimpleNamespace(),
            db=db,
        )
    )

    assert result is persistent_workflow
    assert db.refresh_calls == []
    assert init_db_calls == [{"run_migrations": True, "raise_errors": True}]


def test_regenerate_shot_storyboard_uses_workflow_lookup_for_chapter_id(monkeypatch):
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        video_chapter_pipeline,
        'get_shot',
        lambda shot_id: SimpleNamespace(
            id=shot_id,
            workflow_id=55,
            shot_index=2,
            scene_location='旧宅走廊',
            time_of_day='夜',
            characters=['林秋'],
            story_summary='林秋停在走廊中央',
            dialogue_or_narration='她没有继续向前。',
            camera_plan='中景缓慢推近',
            motion_plan='停步，抬眼',
            emotion_plan='迟疑转为警觉',
            storyboard_prompt='现成 prompt',
        ),
    )
    monkeypatch.setattr(video_chapter_pipeline, 'get_workflow', lambda workflow_id: SimpleNamespace(id=workflow_id, chapter_id=440))
    monkeypatch.setattr(video_chapter_pipeline, 'update_shot', lambda *args, **kwargs: None)

    async def fake_generate_manga_image(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(image_path='chapter_440_storyboard.png')

    monkeypatch.setattr(video_chapter_pipeline.image_service, 'generate_manga_image', fake_generate_manga_image)

    result = asyncio.run(video_chapter_pipeline.regenerate_shot_storyboard(99, api_key='image-key'))

    assert captured['chapter_id'] == 440
    assert result is not None


def test_api_create_chapter_workflow_passes_image_api_key(monkeypatch):
    """验证创建章节工作流路由将 image_api_key 传递给 start_workflow_background。"""
    db = _FakeDb()
    captured: dict[str, object] = {}

    async def fake_start_background(
        workflow_id: int,
        api_key: str | None = None,
        image_api_key: str | None = None,
    ):
        captured['workflow_id'] = workflow_id
        captured['api_key'] = api_key
        captured['image_api_key'] = image_api_key
        return f"chapter_video_{workflow_id}"

    monkeypatch.setattr(video_router, "_require_user", lambda request, db_session: SimpleNamespace(id=1))
    monkeypatch.setattr(
        video_router,
        "_require_chapter_for_user",
        lambda chapter_id, user, db_session: SimpleNamespace(id=chapter_id, story_id=900, novel_content="章节正文"),
    )
    monkeypatch.setattr(video_router, "create_chapter_workflow", lambda **kw: SimpleNamespace(id=77))
    monkeypatch.setattr(video_router, "start_workflow_background", fake_start_background)
    monkeypatch.setattr(video_router, "_user_deepseek_api_key", lambda request, db_session: "deepseek-key-123")
    monkeypatch.setattr(video_router, "_user_image_api_key", lambda request: "image-key-456")
    monkeypatch.setattr(video_router, "get_chapter_workflow", lambda workflow_id: SimpleNamespace(id=workflow_id))
    monkeypatch.setattr(video_router, "init_db", lambda **kw: None, raising=False)

    result = asyncio.run(
        video_router.api_create_chapter_workflow(
            body=ChapterVideoWorkflowCreate(chapter_id=440, character_reference_ids=[11, 22], video_style="写实电影感"),
            request=SimpleNamespace(), db=db,
        )
    )

    assert captured.get("image_api_key") == "image-key-456", \
        f"应传递 image-api-key，实际: {captured}"
    assert captured.get("api_key") == "deepseek-key-123", \
        f"应传递 deepseek-key，实际: {captured}"
    assert captured.get("workflow_id") == 77
