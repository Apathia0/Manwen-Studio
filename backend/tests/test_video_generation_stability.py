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

        monkeypatch.setattr(video_generation.video_adapter, "create_video_job", fake_create_video_job)

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

        monkeypatch.setattr(video_generation.video_adapter, "create_video_job", fake_create_video_job)

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


def test_submit_video_job_forwards_video_capabilities(monkeypatch):
    from services import video_generation

    async def scenario():
        captured = {}

        async def fake_create_video_job(**kwargs):
            captured.update(kwargs)
            return {"task_id": "provider-job-1", "status": "queued"}

        monkeypatch.setattr(video_generation.video_adapter, "create_video_job", fake_create_video_job)
        capabilities = {
            "payload_profile": "sora_v2",
            "defaults": {"resolution": "1080P"},
        }

        await video_generation.submit_video_job(
            shot_id=1,
            provider="sora",
            model="model",
            prompt="prompt",
            negative_prompt="",
            duration_seconds=5,
            aspect_ratio="16:9",
            api_key="test-key",
            video_capabilities=capabilities,
        )

        assert captured["video_capabilities"] is capabilities
        assert captured["adapter_type"] == "lingdong_video"
        assert captured["size"] == "1080P"

    asyncio.run(scenario())


def test_submit_video_job_forwards_input_mode_and_seed(monkeypatch):
    from services import video_generation

    async def scenario():
        captured = {}

        async def fake_create_video_job(**kwargs):
            captured.update(kwargs)
            return {"task_id": "provider-job-1", "status": "queued"}

        monkeypatch.setattr(video_generation.video_adapter, "create_video_job", fake_create_video_job)
        await video_generation.submit_video_job(
            shot_id=1,
            provider="sora",
            model="model",
            prompt="prompt",
            negative_prompt="",
            duration_seconds=5,
            aspect_ratio="16:9",
            reference_images=["https://oss.example/a.png"],
            input_mode="image_to_video",
            seed=123,
            api_key="test-key",
        )

        assert captured["input_mode"] == "image_to_video"
        assert captured["seed"] == 123
        assert captured["images"] == ["https://oss.example/a.png"]

    asyncio.run(scenario())


def test_query_job_status_transient_error_is_not_terminal(monkeypatch):
    from services import video_generation

    async def scenario():
        async def fake_query_video_job(*args, **kwargs):
            raise TimeoutError("query timeout")

        monkeypatch.setattr(video_generation.video_adapter, "query_video_job", fake_query_video_job)

        result = await video_generation.query_job_status(
            provider="sora",
            provider_job_id="provider-job-1",
            api_key="test-key",
        )

        assert result["status"] == "queued"
        assert result["provider_status"] == "query_error"
        assert result["error"] == "任务执行超时，请稍后重试"

    asyncio.run(scenario())


def test_shared_video_interfaces_forward_explicit_adapter(monkeypatch):
    from services import video_generation

    async def scenario():
        captured: dict[str, dict] = {}

        async def fake_query(job_id, **kwargs):
            captured["query"] = {"job_id": job_id, **kwargs}
            return {"status": "completed"}

        async def fake_materialize(**kwargs):
            captured["materialize"] = kwargs
            return "/tmp/result.mp4"

        monkeypatch.setattr(video_generation.video_adapter, "query_video_job", fake_query)
        monkeypatch.setattr(video_generation.video_adapter, "materialize_video_job", fake_materialize)

        status = await video_generation.query_job_status(
            provider="sora",
            provider_job_id="provider-job-1",
            api_key="test-key",
            adapter_type="openai_video",
        )
        result = await video_generation.fetch_job_result(
            provider="sora",
            provider_job_id="provider-job-1",
            shot_id=4,
            api_key="test-key",
            adapter_type="openai_video",
        )

        assert status["status"] == "succeeded"
        assert result["video_path"] == "/tmp/result.mp4"
        assert captured["query"]["adapter_type"] == "openai_video"
        assert captured["materialize"]["adapter_type"] == "openai_video"

    asyncio.run(scenario())


def test_query_completion_log_redacts_signed_media_urls(monkeypatch, caplog):
    from services import video_generation

    async def scenario():
        signed_url = (
            "https://user:password@cdn.example.com/v.mp4"
            "?signature=SECRET&token=SECRET#fragment"
        )

        async def fake_query_video_job(*args, **kwargs):
            return {
                "status": "completed",
                "url": signed_url,
                "video_url": signed_url,
                "data": {"video_url": signed_url},
            }

        monkeypatch.setattr(
            video_generation.video_adapter,
            "query_video_job",
            fake_query_video_job,
        )
        with caplog.at_level("INFO", logger="services.video_generation"):
            result = await video_generation.query_job_status(
                provider="sora",
                provider_job_id="provider-job-1",
                api_key="test-key",
            )

        assert result["status"] == "succeeded"
        assert "SECRET" not in caplog.text
        assert "user:password" not in caplog.text
        assert "fragment" not in caplog.text
        assert "https://cdn.example.com/v.mp4" in caplog.text

    asyncio.run(scenario())


def test_result_fetched_log_redacts_signed_local_path(monkeypatch, caplog):
    from services import video_generation

    async def scenario():
        signed_url = (
            "https://user:password@cdn.example.com/v.mp4"
            "?signature=SECRET&token=SECRET#fragment"
        )

        async def fake_query_video_job(*args, **kwargs):
            return {"status": "completed", "video_url": signed_url}

        async def fake_materialize_video_job(**kwargs):
            return signed_url

        monkeypatch.setattr(
            video_generation.video_adapter,
            "query_video_job",
            fake_query_video_job,
        )
        monkeypatch.setattr(
            video_generation.video_adapter,
            "materialize_video_job",
            fake_materialize_video_job,
        )
        with caplog.at_level("INFO", logger="services.video_generation"):
            result = await video_generation.fetch_job_result(
                provider="sora",
                provider_job_id="provider-job-1",
                shot_id=4,
                api_key="test-key",
            )

        assert result["video_path"] == signed_url
        assert "SECRET" not in caplog.text
        assert "user:password" not in caplog.text
        assert "fragment" not in caplog.text
        assert "https://cdn.example.com/v.mp4" in caplog.text

    asyncio.run(scenario())


def test_provider_router_forwards_explicit_adapter(monkeypatch):
    from services import video_provider_router

    async def scenario():
        captured: dict[str, dict] = {}

        async def fake_submit(**kwargs):
            captured["submit"] = kwargs
            return {"provider_job_id": "job-1"}

        async def fake_query(*args, **kwargs):
            captured["query"] = kwargs
            return {"status": "succeeded"}

        async def fake_fetch(*args, **kwargs):
            captured["fetch"] = kwargs
            return {"video_path": "/tmp/video.mp4"}

        monkeypatch.setattr(video_provider_router.video_generation, "submit_video_job", fake_submit)
        monkeypatch.setattr(video_provider_router.video_generation, "query_job_status", fake_query)
        monkeypatch.setattr(video_provider_router.video_generation, "fetch_job_result", fake_fetch)

        await video_provider_router.submit(
            provider="sora",
            model="model",
            prompt="prompt",
            negative_prompt=None,
            duration_seconds=5,
            aspect_ratio="16:9",
            adapter_type="openai_video",
        )
        await video_provider_router.query_status(
            "sora", "job-1", model="openai-model", adapter_type="openai_video"
        )
        await video_provider_router.fetch_result(
            "sora", "job-1", 1, model="openai-model", adapter_type="openai_video"
        )

        assert captured["submit"]["adapter_type"] == "openai_video"
        assert captured["query"]["adapter_type"] == "openai_video"
        assert captured["fetch"]["adapter_type"] == "openai_video"
        assert captured["query"]["model"] == "openai-model"
        assert captured["fetch"]["model"] == "openai-model"

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("status_code", "expected_error"),
    [
        (400, "视频状态查询失败，请稍后重试"),
        (404, "请求的资源不存在或已被删除"),
    ],
)
def test_query_job_status_nonretryable_openai_error_is_terminal(monkeypatch, status_code, expected_error):
    from services import video_generation

    async def scenario():
        async def fake_query_video_job(*args, **kwargs):
            raise UpstreamServiceError(
                f"OpenAI HTTP {status_code}", retryable=False,
                provider="OpenAI Video", status_code=status_code,
            )

        monkeypatch.setattr(video_generation.video_adapter, "query_video_job", fake_query_video_job)
        result = await video_generation.query_job_status(
            provider="sora", provider_job_id="provider-job-1",
            api_key="test-key", adapter_type="openai_video",
        )
        assert result == {
            "status": "failed", "progress": 0,
            "provider_status": "query_error", "error": expected_error,
        }

    asyncio.run(scenario())


@pytest.mark.parametrize("status_code", [429, 500, 503])
def test_query_job_status_retryable_openai_error_remains_queued(monkeypatch, status_code):
    from services import video_generation

    async def scenario():
        async def fake_query_video_job(*args, **kwargs):
            raise UpstreamServiceError(
                f"OpenAI HTTP {status_code}", retryable=True,
                provider="OpenAI Video", status_code=status_code,
            )

        monkeypatch.setattr(video_generation.video_adapter, "query_video_job", fake_query_video_job)
        result = await video_generation.query_job_status(
            provider="sora", provider_job_id="provider-job-1",
            api_key="test-key", adapter_type="openai_video",
        )
        assert result["status"] == "queued"
        assert result["provider_status"] == "query_error"

    asyncio.run(scenario())
