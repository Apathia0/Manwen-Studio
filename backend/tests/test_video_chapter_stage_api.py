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
    monkeypatch.setattr(video_router, "_configure_video_service_from_db", lambda request, db: None)
    monkeypatch.setattr(video_router, "_user_video_api_key", lambda request: ("key", "url", "model"))
    monkeypatch.setattr(video_router, "_get_story_character_reference_asset_ids", lambda story_id, db: [])
    monkeypatch.setattr(video_router, "update_chapter_workflow_status", lambda wid, status: None)

    async def fake_submit_task(task_id=None, coro_func=None, **kwargs):
        """模拟 task_manager.submit_task 直接调用协程函数。"""
        import inspect
        sig = inspect.signature(coro_func)
        call_kwargs = {k: v for k, v in kwargs.items() if k in sig.parameters}
        return await coro_func(**call_kwargs, task_id=task_id)

    monkeypatch.setattr(video_router.task_manager, "submit_task", fake_submit_task)

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

    chapter_mock = SimpleNamespace(novel_content="正文")

    story_mock = SimpleNamespace(id=34, owner_user_id=1)

    plan_mock = SimpleNamespace(id=1, code="free")
    plan_feature_mock = SimpleNamespace(feature_key="video.shot.split.monthly_limit", value_json={"value": 999})
    quota_rule_mock = SimpleNamespace(feature_key="video.shot.split.monthly_limit", reset_period="monthly", deduct_mode="on_success")
    subscription_mock = SimpleNamespace(user_id=1, plan_id=1)

    class FakeDb:
        def get(self, model, pk):
            name = getattr(model, "__name__", "")
            if name == "Chapter":
                return chapter_mock
            if name == "ChapterVideoWorkflow":
                return wf_mock
            if name == "Plan":
                return plan_mock
            return story_mock
        def query(self, model):
            name = getattr(model, "__name__", "")
            class Q:
                def filter(self, *a, **kw):
                    class Q2:
                        def first(self):
                            if name == "Plan":
                                return plan_mock
                            if name == "UserSubscription":
                                return subscription_mock
                            if name == "PlanFeature":
                                return plan_feature_mock
                            if name == "PlanQuotaRule":
                                return quota_rule_mock
                            return None
                    return Q2()
                def all(self):
                    return []
            return Q()
        def add(self, obj):
            pass
        def flush(self):
            pass
        def commit(self):
            pass

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

    async def fake_expand(**kwargs):
        return {"workflow_status": "shots_ready", "expanded_shot_count": 1, "failed_shot_ids": []}

    monkeypatch.setattr(deepseek_service, "parse_chapter_to_shots_lite", fake_parse)
    monkeypatch.setattr(video_chapter_pipeline, "expand_shots_with_role_prompts", fake_expand)

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
    assert result["expanded_shot_count"] == 1


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
    monkeypatch.setattr(video_router, "_get_story_character_reference_asset_ids", lambda story_id, db: [])
    monkeypatch.setattr(video_router, "_check_and_consume_quota_wrapper", lambda *a, **kw: {"used": 0, "limit": 999, "feature_key": "", "period_key": "", "base_limit": 0, "granted": 0})
    monkeypatch.setattr(video_router, "update_chapter_workflow_status", lambda wid, status: None)

    async def fake_submit_task(task_id=None, coro_func=None, **kwargs):
        captured.update(kwargs)
        return task_id

    monkeypatch.setattr(video_router.task_manager, "submit_task", fake_submit_task)

    wf_mock = SimpleNamespace(
        id=99, story_id=34, chapter_id=12, workflow_status="pending",
        total_shots=0, completed_shots=0, failed_shots=0, error_message=None,
        source_text="正文", character_reference_ids=None,
    )
    monkeypatch.setattr(video_router, "get_chapter_workflow", lambda wid: wf_mock)

    story_mock = SimpleNamespace(id=34, owner_user_id=1)
    chapter_mock = SimpleNamespace(novel_content="正文")

    class FakeDb:
        def get(self, model, pk):
            name = getattr(model, "__name__", "")
            if name == "Chapter":
                return chapter_mock
            if name == "ChapterVideoWorkflow":
                return wf_mock
            return story_mock
        def query(self, model):
            class Q:
                def filter(self, *a, **kw): return self
                def first(self): return None
            return Q()
        def commit(self):
            pass

    async def run():
        return await video_router.api_parse_chapter_shots(
            workflow_id=99, request=SimpleNamespace(), db=FakeDb(),
        )

    result = asyncio.run(run())
    assert result["workflow_status"] == "parsing_shots"
    assert result["task_id"].startswith("chapter_video_99_stage_")
    assert captured["workflow_id"] == 99


# ── Fix 5: 单镜头重新生成路由 key 分离 ──────────────────


def test_regenerate_shot_storyboard_uses_image_api_key(monkeypatch):
    """验证单镜头重新生成故事版路由使用 image_api_key 而非 deepseek_api_key。"""
    from routers import video as video_router
    from schemas import RegenerateShotRequest
    from fastapi import HTTPException

    captured_key = [None]

    async def fake_regenerate(shot_id, api_key=None, prompt_override=None, ref_asset_ids=None):
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


def test_regenerate_shot_storyboard_passes_reference_asset_ids(monkeypatch):
    """验证单镜头重新生成故事版路由会把引用资产 ID 传给服务层。"""
    from routers import video as video_router
    from schemas import RegenerateShotRequest

    captured: dict[str, object] = {}

    async def fake_regenerate(shot_id, api_key=None, prompt_override=None, ref_asset_ids=None):
        captured.update({
            "shot_id": shot_id,
            "api_key": api_key,
            "prompt_override": prompt_override,
            "ref_asset_ids": ref_asset_ids,
        })
        return SimpleNamespace(id=shot_id, workflow_id=99)

    monkeypatch.setattr(video_router, "regenerate_shot_storyboard", fake_regenerate)
    monkeypatch.setattr(video_router, "_require_user", lambda request, db: SimpleNamespace(id=1))
    monkeypatch.setattr(video_router, "_user_image_api_key", lambda request: "image-key")
    monkeypatch.setattr(video_router, "_configure_image_service_from_db", lambda request, db: None)
    monkeypatch.setattr(video_router, "get_chapter_workflow",
                        lambda wid: SimpleNamespace(id=wid, story_id=34))
    monkeypatch.setattr(video_router, "_check_and_consume_quota_wrapper", lambda *a, **kw: {"used": 0, "limit": 999, "feature_key": "", "period_key": "", "base_limit": 0, "granted": 0})
    monkeypatch.setattr(video_router, "ChapterVideoShotOut", SimpleNamespace(model_validate=lambda shot: shot))

    class FakeDb:
        def get(self, model, pk):
            name = getattr(model, "__name__", "")
            if name == "ChapterVideoShot":
                return SimpleNamespace(id=pk, workflow_id=99)
            return SimpleNamespace(id=34, owner_user_id=1)

    result = asyncio.run(video_router.api_regenerate_shot_storyboard(
        shot_id=1,
        body=RegenerateShotRequest(prompt_override="测试 prompt", reference_asset_ids=[7, 9]),
        request=SimpleNamespace(),
        db=FakeDb(),
    ))

    assert captured == {
        "shot_id": 1,
        "api_key": "image-key",
        "prompt_override": "测试 prompt",
        "ref_asset_ids": [7, 9],
    }
    assert result.id == 1


def test_regenerate_shot_video_uses_image_api_key(monkeypatch):
    """验证单镜头重新生成视频路由使用 image_api_key 而非 deepseek_api_key。"""
    from routers import video as video_router
    from schemas import RegenerateShotRequest
    from fastapi import HTTPException

    captured_key = [None]

    async def fake_regenerate(shot_id, api_key=None, prompt_override=None, **kwargs):
            captured_key[0] = api_key
            return None

    monkeypatch.setattr(video_router, "regenerate_shot_video", fake_regenerate)
    monkeypatch.setattr(video_router, "_require_user", lambda request, db: SimpleNamespace(id=1))
    monkeypatch.setattr(video_router, "_user_deepseek_api_key", lambda request, db: "deepseek-key")
    monkeypatch.setattr(video_router, "_user_image_api_key", lambda request: "image-key")
    monkeypatch.setattr(video_router, "_configure_video_service_from_db", lambda request, db: None)
    monkeypatch.setattr(video_router, "_user_video_api_key", lambda request: ("image-key", "url", "model"))
    monkeypatch.setattr(video_router, "get_chapter_workflow",
                        lambda wid: SimpleNamespace(id=wid, story_id=34))
    monkeypatch.setattr(video_router, "_check_and_consume_quota_wrapper",
                        lambda *a, **kw: {"used": 0, "limit": 999, "feature_key": "", "period_key": "", "base_limit": 0, "granted": 0})

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


# ── Fix 6: 路由级别 image_api_key 存在性校验 ────────────


def test_regenerate_shot_video_upstream_error_returns_502(monkeypatch):
    """Upstream provider failures should not bubble up as server tracebacks."""
    from fastapi import HTTPException
    from routers import video as video_router
    from schemas import RegenerateShotRequest
    from services.errors import UpstreamServiceError

    async def fake_regenerate(*args, **kwargs):
        raise UpstreamServiceError(
            "Lingdong video task failed. Please check media URLs and request parameters.",
            retryable=False,
            provider="sora",
        )

    monkeypatch.setattr(video_router, "regenerate_shot_video", fake_regenerate)
    monkeypatch.setattr(video_router, "_require_user", lambda request, db: SimpleNamespace(id=1))
    monkeypatch.setattr(video_router, "_user_deepseek_api_key", lambda request, db: "deepseek-key")
    monkeypatch.setattr(video_router, "_configure_video_service_from_db", lambda request, db: None)
    monkeypatch.setattr(video_router, "_user_video_api_key", lambda request: ("image-key", "url", "model"))
    monkeypatch.setattr(video_router, "_check_and_consume_quota_wrapper", lambda *a, **kw: {"used": 0, "limit": 999, "feature_key": "", "period_key": "", "base_limit": 0, "granted": 0})
    monkeypatch.setattr(
        video_router,
        "get_chapter_workflow",
        lambda wid: SimpleNamespace(id=wid, story_id=34),
    )

    class FakeDb:
        def get(self, model, pk):
            name = getattr(model, "__name__", "")
            if name == "ChapterVideoShot":
                return SimpleNamespace(id=pk, workflow_id=99)
            return SimpleNamespace(id=34, owner_user_id=1)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            video_router.api_regenerate_shot_video(
                shot_id=1,
                body=RegenerateShotRequest(),
                request=SimpleNamespace(),
                db=FakeDb(),
            )
        )

    assert exc_info.value.status_code == 502
    assert "Lingdong video task failed" in exc_info.value.detail


def test_storyboard_route_rejects_missing_image_api_key(monkeypatch):
    """/storyboards 路由在缺少 image_api_key 时返回 400。"""
    from routers import video as video_router
    from schemas import ChapterWorkflowStageActionRequest
    from fastapi import HTTPException

    monkeypatch.setattr(video_router, "_require_user", lambda request, db: SimpleNamespace(id=1))
    monkeypatch.setattr(video_router, "_user_deepseek_api_key", lambda request, db: "deepseek-key")
    monkeypatch.setattr(video_router, "_user_image_api_key", lambda request: None)
    monkeypatch.setattr(video_router, "get_chapter_workflow",
                        lambda wid: SimpleNamespace(id=wid, story_id=34, workflow_status="shots_ready"))

    class FakeDb:
        def get(self, model, pk):
            return SimpleNamespace(id=34, owner_user_id=1)

        def query(self, model):
            class Q:
                def filter(self, *a, **kw): return self
                def first(self): return None
            return Q()

    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(video_router.api_generate_storyboards(
            workflow_id=99, body=ChapterWorkflowStageActionRequest(),
            request=SimpleNamespace(), db=FakeDb(),
        ))

    assert excinfo.value.status_code == 400
    assert "Image" in str(excinfo.value.detail)


def test_video_route_rejects_missing_image_api_key(monkeypatch):
    """/videos 路由在缺少 image_api_key 时返回 400。"""
    from routers import video as video_router
    from schemas import ChapterWorkflowStageActionRequest
    from fastapi import HTTPException

    monkeypatch.setattr(video_router, "_require_user", lambda request, db: SimpleNamespace(id=1))
    monkeypatch.setattr(video_router, "_user_deepseek_api_key", lambda request, db: "deepseek-key")
    monkeypatch.setattr(video_router, "_user_image_api_key", lambda request: None)
    monkeypatch.setattr(video_router, "get_chapter_workflow",
                        lambda wid: SimpleNamespace(id=wid, story_id=34, workflow_status="storyboards_ready"))

    class FakeDb:
        def get(self, model, pk):
            return SimpleNamespace(id=34, owner_user_id=1)

        def query(self, model):
            class Q:
                def filter(self, *a, **kw): return self
                def first(self): return None
            return Q()

    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(video_router.api_generate_videos(
            workflow_id=99, body=ChapterWorkflowStageActionRequest(),
            request=SimpleNamespace(), db=FakeDb(),
        ))

    assert excinfo.value.status_code == 400
    assert "Image" in str(excinfo.value.detail)



