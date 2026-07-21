from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from models import ChapterVideoShot, ChapterVideoWorkflow, Story
from routers import video
from schemas import ChapterVideoShotCreate


class _ShotQuery:
    def __init__(self, existing_count: int):
        self.existing_count = existing_count
        self.status = None

    def filter(self, *expressions):
        for expression in expressions:
            value = getattr(getattr(expression, "right", None), "value", None)
            if value in {"video_ready", "failed"}:
                self.status = value
        return self

    def count(self):
        if self.status == "video_ready":
            return 1
        if self.status == "failed":
            return 0
        return self.existing_count


class _MaxIndexQuery:
    def filter(self, *_expressions):
        return self

    def scalar(self):
        return 4


class _FakeDb:
    def __init__(self, workflow, story):
        self.workflow = workflow
        self.story = story
        self.added = None
        self.committed = False

    def get(self, model, _object_id):
        if model is ChapterVideoWorkflow:
            return self.workflow
        if model is Story:
            return self.story
        return None

    def query(self, entity):
        if entity is ChapterVideoShot:
            return _ShotQuery(existing_count=2)
        return _MaxIndexQuery()

    def add(self, entity):
        self.added = entity

    def commit(self):
        self.committed = True

    def refresh(self, entity):
        entity.id = 99
        entity.created_at = SimpleNamespace()


@pytest.mark.asyncio
async def test_manual_shot_is_appended_and_updates_workflow_counters(monkeypatch):
    workflow = SimpleNamespace(
        id=7,
        story_id=3,
        workflow_status="completed",
        character_reference_ids=[11, 12],
        total_shots=2,
        completed_shots=2,
        failed_shots=0,
        error_message="旧错误",
    )
    db = _FakeDb(workflow, SimpleNamespace(owner_user_id=5))
    monkeypatch.setattr(video, "_require_user", lambda _request, _db: SimpleNamespace(id=5))

    shot = await video.api_create_chapter_workflow_shot(
        workflow_id=7,
        body=ChapterVideoShotCreate(
            story_summary=" 新增转场镜头 ",
            characters=[" 主角 ", ""],
            scene_location=" 城门 ",
        ),
        request=SimpleNamespace(),
        db=db,
    )

    assert shot.id == 99
    assert shot.shot_index == 5
    assert shot.story_summary == "新增转场镜头"
    assert shot.source_text_span == "新增转场镜头"
    assert shot.characters == ["主角"]
    assert shot.character_reference_ids == [11, 12]
    assert workflow.total_shots == 3
    assert workflow.completed_shots == 1
    assert workflow.failed_shots == 0
    assert workflow.workflow_status == "shots_ready"
    assert workflow.error_message is None
    assert db.committed is True


@pytest.mark.asyncio
async def test_manual_shot_rejects_active_workflow(monkeypatch):
    workflow = SimpleNamespace(id=7, story_id=3, workflow_status="generating_videos")
    db = _FakeDb(workflow, SimpleNamespace(owner_user_id=5))
    monkeypatch.setattr(video, "_require_user", lambda _request, _db: SimpleNamespace(id=5))

    with pytest.raises(HTTPException) as exc_info:
        await video.api_create_chapter_workflow_shot(
            workflow_id=7,
            body=ChapterVideoShotCreate(story_summary="新增镜头"),
            request=SimpleNamespace(),
            db=db,
        )

    assert exc_info.value.status_code == 409
