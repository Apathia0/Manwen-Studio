import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models import Base
from services.errors import UpstreamServiceError


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    session._test_engine = engine
    yield session
    session.close()


def test_submit_video_job_transient_submission_failure_triggers_task_retry(monkeypatch, db_session):
    from services.task_manager import TaskManager
    import services.task_manager as task_manager_module
    from services import video_generation

    async def scenario():
        engine = getattr(db_session, "_test_engine")
        monkeypatch.setattr(task_manager_module, "SessionLocal", sessionmaker(bind=engine))

        calls = {"count": 0}

        async def fake_create_video_job(**kwargs):
            calls["count"] += 1
            if calls["count"] == 1:
                raise UpstreamServiceError("upstream 503", retryable=True)
            return {"task_id": "provider-job-1", "status": "queued", "progress": 0}

        monkeypatch.setattr(video_generation.video_api, "create_video_job", fake_create_video_job)

        manager = TaskManager(max_concurrent=1)
        task_id = await manager.submit_task(
            "video-submit-retry",
            "video_render",
            video_generation.submit_video_job,
            timeout=None,
            max_retries=1,
            metadata={"stage": "submitting", "message": "submitting upstream job"},
            shot_id=1,
            provider="sora",
            model="model",
            prompt="prompt",
            negative_prompt="",
            duration_seconds=5,
            aspect_ratio="16:9",
            api_key="test-key",
        )

        result = await manager._running_tasks[task_id]
        await asyncio.sleep(0)

        status = manager.get_task_status(task_id)
        assert calls["count"] == 2
        assert result["provider_job_id"] == "provider-job-1"
        assert status["status"] == "succeeded"
        assert status["retry_count"] == 1
        assert status["result_json"]["provider_job_id"] == "provider-job-1"

    asyncio.run(scenario())


def test_submit_video_job_missing_provider_job_id_raises(monkeypatch):
    from services import video_generation

    async def scenario():
        async def fake_create_video_job(**kwargs):
            return {"status": "queued", "progress": 0}

        monkeypatch.setattr(video_generation.video_api, "create_video_job", fake_create_video_job)

        with pytest.raises(UpstreamServiceError, match="ID"):
            await video_generation.submit_video_job(
                shot_id=1,
                provider="sora",
                model="model",
                prompt="prompt",
                negative_prompt="",
                duration_seconds=5,
                aspect_ratio="16:9",
                api_key="test-key",
            )

    asyncio.run(scenario())


def test_query_job_status_transient_error_is_not_terminal(monkeypatch):
    from services import video_generation

    async def scenario():
        async def fake_query_video_job(**kwargs):
            raise TimeoutError("query timeout")

        monkeypatch.setattr(video_generation.video_api, "query_video_job", fake_query_video_job)

        result = await video_generation.query_job_status(
            provider="sora",
            provider_job_id="provider-job-1",
            api_key="test-key",
        )

        assert result["status"] == "queued"
        assert result["provider_status"] == "query_error"
        assert "query timeout" in result["error"]

    asyncio.run(scenario())
