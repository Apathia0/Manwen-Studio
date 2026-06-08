"""测试章节视频分阶段工作流。

覆盖：
- 拆镜阶段停在 shots_ready 而非自动进入下一阶段
- 故事版阶段使用 image_api_key 而非 deepseek_key
- 故事版失败停在 generating_storyboards 不自动进入视频阶段
- 阶段路由将 task_id 传递给阶段函数
- run_all_stages 根据工作流状态智能跳过已完成阶段
- 视频阶段仅处理 storyboard_ready 镜头
- 单镜头重新生成与批量生成共享同一底层实现
"""

import asyncio
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models import Base, ChapterVideoShot, ChapterVideoWorkflow
from services import video_chapter_pipeline
from services import deepseek as deepseek_service
from services import image2 as image_service


# ── Fixtures ──────────────────────────────────────────────


@pytest.fixture
def workflow_db(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    monkeypatch.setattr(video_chapter_pipeline, "SessionLocal", Session)
    session = Session()
    workflow = ChapterVideoWorkflow(
        chapter_id=12, story_id=34, source_text="正文",
        workflow_status="pending", character_reference_ids=[101, 202],
        video_style="写实电影感",
    )
    session.add(workflow)
    session.commit()
    session.refresh(workflow)
    session.close()
    yield Session, workflow.id


@pytest.fixture
def workflow_with_shots(workflow_db):
    Session, workflow_id = workflow_db
    session = Session()
    for idx in range(1, 4):
        shot = ChapterVideoShot(
            workflow_id=workflow_id, shot_index=idx,
            source_text_span=f"正文第{idx}段",
            scene_location="客厅", time_of_day="夜",
            characters=["林秋"], story_summary=f"测试镜头{idx}",
            dialogue_or_narration="", camera_plan="中景",
            motion_plan="静止", emotion_plan="平静",
            continuity_notes="保持服装一致", status="pending",
        )
        session.add(shot)
    session.commit()
    session.close()
    return Session, workflow_id


# ── Fix 1: task_id 传递测试 ─────────────────────────────


def test_stage_routes_pass_task_id(monkeypatch):
    """验证阶段路由创建 task_id 并传递给阶段函数。"""
    from routers import video as video_router

    captured_parse_task_id = None
    captured_sb_task_id = None
    captured_vid_task_id = None

    async def fake_parse(*args, **kwargs):
        nonlocal captured_parse_task_id
        captured_parse_task_id = kwargs.get("task_id")
        return {"workflow_status": "shots_ready", "shot_count": 1}

    async def fake_storyboards(*args, **kwargs):
        nonlocal captured_sb_task_id
        captured_sb_task_id = kwargs.get("task_id")
        return {"workflow_status": "storyboards_ready", "shot_count": 1}

    async def fake_videos(*args, **kwargs):
        nonlocal captured_vid_task_id
        captured_vid_task_id = kwargs.get("task_id")
        return {"workflow_status": "videos_ready", "shot_count": 1}

    monkeypatch.setattr(video_router, "parse_chapter_shots", fake_parse)
    monkeypatch.setattr(video_router, "generate_storyboards_for_shots", fake_storyboards)
    monkeypatch.setattr(video_router, "generate_videos_for_shots", fake_videos)
    monkeypatch.setattr(video_router, "_require_user", lambda request, db: SimpleNamespace(id=1))
    monkeypatch.setattr(video_router, "_user_deepseek_api_key", lambda request, db: "test-ds-key")
    monkeypatch.setattr(video_router, "_user_image_api_key", lambda request: "test-img-key")

    wf_mock = SimpleNamespace(
        id=99, story_id=34, chapter_id=12, workflow_status="pending",
        total_shots=0, completed_shots=0, failed_shots=0, error_message=None,
        source_text="正文", character_reference_ids=None,
    )
    wf_sb_mock = SimpleNamespace(
        id=99, story_id=34, chapter_id=12, workflow_status="shots_ready",
        total_shots=3, completed_shots=0, failed_shots=0, error_message=None,
        source_text="正文", character_reference_ids=None,
    )
    wf_vid_mock = SimpleNamespace(
        id=99, story_id=34, chapter_id=12, workflow_status="storyboards_ready",
        total_shots=3, completed_shots=3, failed_shots=0, error_message=None,
        source_text="正文", character_reference_ids=None,
    )

    story_mock = SimpleNamespace(id=34, owner_user_id=1)

    class FakeDb:
        def get(self, model, pk):
            return story_mock
        def query(self, model):
            class Q:
                def filter(self, *a, **kw): return self
                def first(self): return None
            return Q()

    # 测试 /parse 路由
    monkeypatch.setattr(video_router, "get_chapter_workflow", lambda wid: wf_mock)
    result = asyncio.run(video_router.api_parse_chapter_shots(
        workflow_id=99, request=SimpleNamespace(), db=FakeDb(),
    ))
    assert captured_parse_task_id is not None, "/parse 路由未传递 task_id"
    assert "chapter_video" in captured_parse_task_id

    # 测试 /storyboards 路由
    from schemas import ChapterWorkflowStageActionRequest
    monkeypatch.setattr(video_router, "get_chapter_workflow", lambda wid: wf_sb_mock)
    result = asyncio.run(video_router.api_generate_storyboards(
        workflow_id=99, body=ChapterWorkflowStageActionRequest(),
        request=SimpleNamespace(), db=FakeDb(),
    ))
    assert captured_sb_task_id is not None, "/storyboards 路由未传递 task_id"
    assert "chapter_video" in captured_sb_task_id

    # 测试 /videos 路由
    monkeypatch.setattr(video_router, "get_chapter_workflow", lambda wid: wf_vid_mock)
    result = asyncio.run(video_router.api_generate_videos(
        workflow_id=99, body=ChapterWorkflowStageActionRequest(),
        request=SimpleNamespace(), db=FakeDb(),
    ))
    assert captured_vid_task_id is not None, "/videos 路由未传递 task_id"
    assert "chapter_video" in captured_vid_task_id


def test_stage_cancellation_checked_during_processing(monkeypatch, workflow_with_shots):
    """验证生成故事版阶段在处理多个镜头时会检查取消标志。"""
    Session, workflow_id = workflow_with_shots
    checked_count = 0
    original_check = video_chapter_pipeline.task_manager.is_cancellation_requested

    def tracking_check(task_id):
        nonlocal checked_count
        checked_count += 1
        return original_check(task_id)

    monkeypatch.setattr(
        video_chapter_pipeline.task_manager, "is_cancellation_requested", tracking_check
    )

    async def fake_generate_manga_image(**kwargs):
        return SimpleNamespace(image_path="storyboard.png")

    async def fake_generate_shot_storyboard_prompt(*args, **kwargs):
        return "测试故事版 prompt"

    monkeypatch.setattr(image_service, "generate_manga_image", fake_generate_manga_image)
    monkeypatch.setattr(deepseek_service, "generate_shot_storyboard_prompt", fake_generate_shot_storyboard_prompt)

    task_id = f"test_cancel_{uuid.uuid4().hex[:8]}"
    asyncio.run(video_chapter_pipeline.generate_storyboards_for_shots(
        workflow_id=workflow_id, story_id=34, shot_ids=None,
        image_api_key="test-img-key", deepseek_api_key="test-ds-key",
        task_id=task_id,
    ))

    # is_cancellation_requested 至少被调用了
    assert checked_count >= 1


# ── Fix 2: run_all_stages 状态感知 ─────────────────────


def test_run_all_stages_skips_parse_when_shots_ready(monkeypatch, workflow_with_shots):
    """当工作流状态为 shots_ready 时，run_all_stages 应跳过拆镜阶段。"""
    Session, workflow_id = workflow_with_shots

    session = Session()
    wf = session.query(ChapterVideoWorkflow).filter(
        ChapterVideoWorkflow.id == workflow_id
    ).first()
    wf.workflow_status = "shots_ready"
    session.commit()
    session.close()

    parse_called = False
    storyboard_called = False

    async def fake_parse(**kw):
        nonlocal parse_called
        parse_called = True
        return {"workflow_status": "shots_ready", "shot_count": 0}

    async def fake_storyboards(**kw):
        nonlocal storyboard_called
        storyboard_called = True
        return {"workflow_status": "storyboards_ready", "shot_count": 0}

    async def fake_videos(**kw):
        return {"workflow_status": "videos_ready", "shot_count": 0}

    monkeypatch.setattr(video_chapter_pipeline, "parse_chapter_shots", fake_parse)
    monkeypatch.setattr(video_chapter_pipeline, "generate_storyboards_for_shots", fake_storyboards)
    monkeypatch.setattr(video_chapter_pipeline, "generate_videos_for_shots", fake_videos)

    asyncio.run(video_chapter_pipeline.run_all_stages(
        workflow_id=workflow_id, chapter_id=12, story_id=34, source_text="",
        deepseek_api_key="key", image_api_key="key",
    ))

    assert not parse_called, "shots_ready 状态不应调用 parse_chapter_shots"
    assert storyboard_called, "应从故事版阶段继续"


def test_run_all_stages_skips_storyboards_when_storyboards_ready(monkeypatch, workflow_with_shots):
    """当工作流状态为 storyboards_ready 时，应跳过拆镜和故事版。"""
    Session, workflow_id = workflow_with_shots

    session = Session()
    wf = session.query(ChapterVideoWorkflow).filter(
        ChapterVideoWorkflow.id == workflow_id
    ).first()
    wf.workflow_status = "storyboards_ready"
    session.commit()
    session.close()

    parse_called = False
    storyboard_called = False
    video_called = False

    async def fake_parse(**kw):
        nonlocal parse_called
        parse_called = True
        return {"workflow_status": "shots_ready", "shot_count": 0}

    async def fake_storyboards(**kw):
        nonlocal storyboard_called
        storyboard_called = True
        return {"workflow_status": "storyboards_ready", "shot_count": 0}

    async def fake_videos(**kw):
        nonlocal video_called
        video_called = True
        return {"workflow_status": "videos_ready", "shot_count": 0}

    monkeypatch.setattr(video_chapter_pipeline, "parse_chapter_shots", fake_parse)
    monkeypatch.setattr(video_chapter_pipeline, "generate_storyboards_for_shots", fake_storyboards)
    monkeypatch.setattr(video_chapter_pipeline, "generate_videos_for_shots", fake_videos)

    asyncio.run(video_chapter_pipeline.run_all_stages(
        workflow_id=workflow_id, chapter_id=12, story_id=34, source_text="",
        deepseek_api_key="key", image_api_key="key",
    ))

    assert not parse_called, "storyboards_ready 不应调用 parse"
    assert not storyboard_called, "storyboards_ready 不应调用 storyboards"
    assert video_called, "应从视频阶段继续"


# ── Fix 3: 单镜头与批量共享实现 ─────────────────────────


def test_batch_storyboard_uses_same_helper_as_regenerate(monkeypatch, workflow_with_shots):
    """验证批量生成故事版使用的内部实现与重新生成相同。"""
    Session, workflow_id = workflow_with_shots

    regenerate_called = False

    async def fake_regenerate(shot_id, **kwargs):
        nonlocal regenerate_called
        regenerate_called = True
        return SimpleNamespace(id=shot_id)

    monkeypatch.setattr(video_chapter_pipeline, "regenerate_shot_storyboard", fake_regenerate)

    async def fake_generate_shot_storyboard_prompt(*args, **kwargs):
        return "prompt"

    async def fake_generate_manga_image(**kwargs):
        return SimpleNamespace(image_path="test.png")

    monkeypatch.setattr(deepseek_service, "generate_shot_storyboard_prompt", fake_generate_shot_storyboard_prompt)
    monkeypatch.setattr(image_service, "generate_manga_image", fake_generate_manga_image)

    result = asyncio.run(video_chapter_pipeline.generate_storyboards_for_shots(
        workflow_id=workflow_id, story_id=34, shot_ids=None,
        image_api_key="test-img-key", deepseek_api_key="test-ds-key",
    ))

    assert regenerate_called, "批量故事版应调用 regenerate_shot_storyboard"


def test_batch_video_uses_same_helper_as_regenerate(monkeypatch, workflow_with_shots):
    """验证批量视频生成使用的内部实现与重新生成相同。"""
    Session, workflow_id = workflow_with_shots

    session = Session()
    shots = session.query(ChapterVideoShot).filter(
        ChapterVideoShot.workflow_id == workflow_id
    ).all()
    for s in shots:
        s.status = "storyboard_ready"
        s.storyboard_image_url = "/static/manga/test.png"
    session.commit()
    session.close()

    regenerate_called = False

    async def fake_regenerate(shot_id, **kwargs):
        nonlocal regenerate_called
        regenerate_called = True
        return SimpleNamespace(id=shot_id)

    monkeypatch.setattr(video_chapter_pipeline, "regenerate_shot_video", fake_regenerate)

    async def fake_submit_video_job(*args, **kwargs):
        return {"provider_job_id": "test-job"}

    async def fake_poll_video_job(*args, **kwargs):
        return "/static/video/test.mp4"

    async def fake_video_prompt(*args, **kwargs):
        return "video prompt"

    from services import video_generation as video_gen_service
    monkeypatch.setattr(video_gen_service, "submit_video_job", fake_submit_video_job)
    monkeypatch.setattr(video_chapter_pipeline, "_poll_video_job", fake_poll_video_job)
    monkeypatch.setattr(deepseek_service, "generate_shot_video_prompt", fake_video_prompt)

    result = asyncio.run(video_chapter_pipeline.generate_videos_for_shots(
        workflow_id=workflow_id, shot_ids=None,
        image_api_key="test-img-key", deepseek_api_key="test-ds-key",
    ))

    assert regenerate_called, "批量视频应调用 regenerate_shot_video"


# ── Fix 4: 视频阶段仅处理 storyboard_ready 镜头 ───────


def test_video_stage_only_processes_storyboard_ready_shots(monkeypatch, workflow_with_shots):
    """验证视频阶段只处理 storyboard_ready 状态镜头，跳过 pending/failed。"""
    Session, workflow_id = workflow_with_shots

    session = Session()
    shots = session.query(ChapterVideoShot).filter(
        ChapterVideoShot.workflow_id == workflow_id
    ).order_by(ChapterVideoShot.shot_index).all()
    # shot 1: storyboard_ready (应被处理)
    shots[0].status = "storyboard_ready"
    shots[0].storyboard_image_url = "/static/manga/shot1.png"
    # shot 2: failed (应被跳过)
    shots[1].status = "failed"
    shots[1].error_message = "之前失败"
    # shot 3: pending (应被跳过)
    shots[2].status = "pending"
    session.commit()
    session.close()

    processed_shot_ids = []

    async def fake_regenerate(shot_id, **kwargs):
        processed_shot_ids.append(shot_id)
        return SimpleNamespace(id=shot_id)

    monkeypatch.setattr(video_chapter_pipeline, "regenerate_shot_video", fake_regenerate)

    async def fake_submit_video_job(*args, **kwargs):
        return {"provider_job_id": "test-job"}

    async def fake_poll_video_job(*args, **kwargs):
        return "/static/video/test.mp4"

    async def fake_video_prompt(*args, **kwargs):
        return "video prompt"

    from services import video_generation as video_gen_service
    monkeypatch.setattr(video_gen_service, "submit_video_job", fake_submit_video_job)
    monkeypatch.setattr(video_chapter_pipeline, "_poll_video_job", fake_poll_video_job)
    monkeypatch.setattr(deepseek_service, "generate_shot_video_prompt", fake_video_prompt)

    result = asyncio.run(video_chapter_pipeline.generate_videos_for_shots(
        workflow_id=workflow_id, shot_ids=None,
        image_api_key="test-img-key", deepseek_api_key="test-ds-key",
    ))

    # 只有一个 shot 是 storyboard_ready
    assert len(processed_shot_ids) == 1, f"应处理 1 个镜头，实际处理了 {len(processed_shot_ids)}"


# ── 原有测试保持 ─────────────────────────────────────────


def test_parse_stage_stops_at_shots_ready(monkeypatch):
    """拆镜阶段执行完后 workflow_status 应为 shots_ready。"""
    captured = {}

    async def fake_parse(**kwargs):
        captured.update(kwargs)
        return [{
            "shot_index": 1, "source_text_span": "她停下脚步。",
            "scene_location": "客厅", "time_of_day": "夜",
            "characters": ["林秋"], "story_summary": "她停下脚步",
            "dialogue_or_narration": "她没有继续向前。",
            "camera_plan": "中景", "motion_plan": "停步",
            "emotion_plan": "警觉", "continuity_notes": "保持服装一致",
        }]

    monkeypatch.setattr(deepseek_service, "parse_chapter_to_shots", fake_parse)

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    monkeypatch.setattr(video_chapter_pipeline, "SessionLocal", Session)

    session = Session()
    workflow = ChapterVideoWorkflow(
        chapter_id=12, story_id=34, source_text="正文", workflow_status="pending",
    )
    session.add(workflow)
    session.commit()
    workflow_id = workflow.id
    session.close()

    result = asyncio.run(video_chapter_pipeline.parse_chapter_shots(
        workflow_id=workflow_id, chapter_id=12, story_id=34, source_text="正文",
        deepseek_api_key="test-deepseek-key",
    ))

    assert result["workflow_status"] == "shots_ready"
    assert result["shot_count"] == 1


def test_generate_storyboards_uses_image_api_key(monkeypatch, workflow_with_shots):
    """故事版阶段应当使用 image_api_key。"""
    Session, workflow_id = workflow_with_shots
    captured = {}

    async def fake_generate_manga_image(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(image_path="storyboard.png")

    monkeypatch.setattr(image_service, "generate_manga_image", fake_generate_manga_image)

    async def fake_generate_shot_storyboard_prompt(*args, **kwargs):
        return "测试故事版 prompt: 林秋站在客厅中央，灯光昏暗"

    monkeypatch.setattr(deepseek_service, "generate_shot_storyboard_prompt", fake_generate_shot_storyboard_prompt)

    result = asyncio.run(video_chapter_pipeline.generate_storyboards_for_shots(
        workflow_id=workflow_id, story_id=34, shot_ids=None,
        image_api_key="test-image-key", deepseek_api_key="test-deepseek-key",
    ))

    assert captured.get("api_key") == "test-image-key"
    assert result["workflow_status"] == "storyboards_ready"
    assert result["shot_count"] == 3


def test_storyboard_failure_keeps_workflow_in_storyboard_stage(monkeypatch, workflow_with_shots):
    """故事版生成失败后停留在 generating_storyboards。"""
    Session, workflow_id = workflow_with_shots
    call_count = 0

    async def fake_generate_manga_image(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise Exception("Image API auth failed: 401 Unauthorized")
        return SimpleNamespace(image_path="storyboard.png")

    monkeypatch.setattr(image_service, "generate_manga_image", fake_generate_manga_image)

    async def fake_generate_shot_storyboard_prompt(*args, **kwargs):
        return "测试故事版 prompt"

    monkeypatch.setattr(deepseek_service, "generate_shot_storyboard_prompt", fake_generate_shot_storyboard_prompt)

    result = asyncio.run(video_chapter_pipeline.generate_storyboards_for_shots(
        workflow_id=workflow_id, story_id=34, shot_ids=None,
        image_api_key="bad-key", deepseek_api_key="test-deepseek-key",
    ))

    assert result["workflow_status"] == "generating_storyboards"
    assert len(result["failed_shot_ids"]) >= 1


def test_parse_route_accepts_valid_workflow_id(monkeypatch):
    """验证 /parse 路由接受有效 workflow_id。"""
    from routers import video as video_router

    captured = {}

    async def fake_parse(**kwargs):
        captured.update(kwargs)
        return {"workflow_status": "shots_ready", "shot_count": 1}

    monkeypatch.setattr(video_router, "parse_chapter_shots", fake_parse)
    monkeypatch.setattr(video_router, "_require_user", lambda request, db: SimpleNamespace(id=1))
    monkeypatch.setattr(video_router, "_user_deepseek_api_key", lambda request, db: "test-ds-key")

    wf_mock = SimpleNamespace(
        id=99, story_id=34, chapter_id=12, workflow_status="pending",
        total_shots=0, completed_shots=0, failed_shots=0, error_message=None,
        source_text="正文",
    )
    monkeypatch.setattr(video_router, "get_chapter_workflow", lambda wid: wf_mock)

    story_mock = SimpleNamespace(id=34, owner_user_id=1)

    class FakeDb:
        def get(self, model, pk):
            return story_mock
        def query(self, model):
            class Q:
                def filter(self, *a, **kw): return self
                def first(self): return None
            return Q()

    async def run():
        return await video_router.api_parse_chapter_shots(
            workflow_id=99, request=SimpleNamespace(), db=FakeDb(),
        )

    result = asyncio.run(run())
    assert result["workflow_status"] == "shots_ready"
    assert captured["workflow_id"] == 99


# ── Fix 5: 单镜头重新生成路由 key 分离 ──────────────────


def test_regenerate_shot_storyboard_uses_image_api_key(monkeypatch):
    """验证单镜头重新生成故事版路由使用 image_api_key 而非 deepseek_api_key。"""
    from routers import video as video_router
    from schemas import RegenerateShotRequest
    from fastapi import HTTPException

    captured_key = [None]

    async def fake_regenerate(shot_id, api_key=None, prompt_override=None):
        captured_key[0] = api_key
        return None

    monkeypatch.setattr(video_router, "regenerate_shot_storyboard", fake_regenerate)
    monkeypatch.setattr(video_router, "_require_user", lambda request, db: SimpleNamespace(id=1))
    monkeypatch.setattr(video_router, "_user_deepseek_api_key", lambda request, db: "deepseek-key")
    monkeypatch.setattr(video_router, "_user_image_api_key", lambda request: "image-key")
    monkeypatch.setattr(video_router, "get_chapter_workflow",
                        lambda wid: SimpleNamespace(id=wid, story_id=34))

    class FakeDb:
        def get(self, model, pk):
            name = getattr(model, "__name__", "")
            if name == "ChapterVideoShot":
                return SimpleNamespace(id=pk, workflow_id=99)
            return SimpleNamespace(id=34, owner_user_id=1)

        def query(self, model):
            class Q:
                def filter(self, *a, **kw): return self
                def first(self): return None
            return Q()

    with pytest.raises(HTTPException):
        asyncio.run(video_router.api_regenerate_shot_storyboard(
            shot_id=1, body=RegenerateShotRequest(),
            request=SimpleNamespace(), db=FakeDb(),
        ))

    assert captured_key[0] == "image-key", \
        f"应使用 image-api-key，实际使用: {captured_key[0]}"


def test_regenerate_shot_video_uses_image_api_key(monkeypatch):
    """验证单镜头重新生成视频路由使用 image_api_key 而非 deepseek_api_key。"""
    from routers import video as video_router
    from schemas import RegenerateShotRequest
    from fastapi import HTTPException

    captured_key = [None]

    async def fake_regenerate(shot_id, api_key=None, prompt_override=None):
        captured_key[0] = api_key
        return None

    monkeypatch.setattr(video_router, "regenerate_shot_video", fake_regenerate)
    monkeypatch.setattr(video_router, "_require_user", lambda request, db: SimpleNamespace(id=1))
    monkeypatch.setattr(video_router, "_user_deepseek_api_key", lambda request, db: "deepseek-key")
    monkeypatch.setattr(video_router, "_user_image_api_key", lambda request: "image-key")
    monkeypatch.setattr(video_router, "get_chapter_workflow",
                        lambda wid: SimpleNamespace(id=wid, story_id=34))

    class FakeDb:
        def get(self, model, pk):
            name = getattr(model, "__name__", "")
            if name == "ChapterVideoShot":
                return SimpleNamespace(id=pk, workflow_id=99)
            return SimpleNamespace(id=34, owner_user_id=1)

        def query(self, model):
            class Q:
                def filter(self, *a, **kw): return self
                def first(self): return None
            return Q()

    with pytest.raises(HTTPException):
        asyncio.run(video_router.api_regenerate_shot_video(
            shot_id=1, body=RegenerateShotRequest(),
            request=SimpleNamespace(), db=FakeDb(),
        ))

    assert captured_key[0] == "image-key", \
        f"应使用 image-api-key，实际使用: {captured_key[0]}"
