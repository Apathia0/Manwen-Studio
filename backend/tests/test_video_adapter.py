from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest

from services import openai_video, video_adapter, video_api
from services.errors import UpstreamServiceError
from services.video_adapter import VIDEO_ADAPTER_LINGDONG, VIDEO_ADAPTER_OPENAI


class _Client:
    def __init__(self, handler):
        self._handler = handler

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def post(self, url, **kwargs):
        return self._handler("POST", url, kwargs)

    async def get(self, url, **kwargs):
        return self._handler("GET", url, kwargs)

    def stream(self, method, url, **kwargs):
        return self._handler(method, url, kwargs)


class _StreamResponse:
    def __init__(self, chunks: list[bytes], *, content_length: int | None = None):
        self.is_success = True
        self.status_code = 200
        self._chunks = chunks
        self.headers = {"content-type": "video/mp4"}
        if content_length is not None:
            self.headers["content-length"] = str(content_length)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def aiter_bytes(self):
        for chunk in self._chunks:
            yield chunk


def _response(status_code: int, json_data=None, *, content: bytes | None = None) -> httpx.Response:
    request = httpx.Request("GET", "https://api.openai.example/v1/videos/test")
    if content is not None:
        return httpx.Response(status_code, content=content, request=request)
    return httpx.Response(status_code, json=json_data, request=request)


@pytest.mark.asyncio
async def test_openai_create_uses_native_payload_and_single_reference(monkeypatch):
    captured = {}

    def handler(method, url, kwargs):
        captured.update(method=method, url=url, **kwargs)
        return _response(200, {"id": "video-1", "status": "queued"})

    monkeypatch.setattr(openai_video.httpx, "AsyncClient", lambda **kwargs: _Client(handler))

    result = await video_adapter.create_video_job(
        adapter_type=VIDEO_ADAPTER_OPENAI,
        model="sora-2",
        prompt="镜头向前推进",
        aspect_ratio="16:9",
        size="1080P",
        duration_seconds=10,
        images=["https://cdn.example.com/reference.png"],
        api_key="secret-key",
        base_url="https://api.openai.example/v1",
        video_capabilities={
            "limits": {"duration_seconds": {"allowed": [5, 10]}, "max_reference_images": 1},
            "wire": {"size_by_resolution_aspect": {"1080P|16:9": "1920x1080"}},
        },
    )

    assert captured["method"] == "POST"
    assert captured["url"] == "https://api.openai.example/v1/videos"
    assert captured["json"] == {
        "model": "sora-2",
        "prompt": "镜头向前推进",
        "seconds": "10",
        "size": "1920x1080",
        "input_reference": {"image_url": "https://cdn.example.com/reference.png"},
    }
    assert result == {"task_id": "video-1", "status": "queued", "upstream_status": "queued"}


@pytest.mark.asyncio
async def test_openai_rejects_multiple_references_before_http(monkeypatch):
    called = False

    def client_factory(**kwargs):
        nonlocal called
        called = True
        raise AssertionError("不应创建 HTTP 客户端")

    monkeypatch.setattr(openai_video.httpx, "AsyncClient", client_factory)

    with pytest.raises(ValueError, match="最多一张参考图"):
        await video_adapter.create_video_job(
            adapter_type=VIDEO_ADAPTER_OPENAI,
            model="sora-2",
            prompt="测试",
            aspect_ratio="16:9",
            size="720P",
            duration_seconds=5,
            images=["https://cdn.example.com/a.png", "https://cdn.example.com/b.png"],
            api_key="secret-key",
            base_url="https://api.openai.example/v1",
            video_capabilities={
                "limits": {"duration_seconds": {"allowed": [5]}, "max_reference_images": 1},
                "wire": {"size_by_resolution_aspect": {"720P|16:9": "1280x720"}},
            },
        )

    assert called is False


@pytest.mark.asyncio
async def test_openai_create_normalizes_structured_error(monkeypatch):
    def handler(method, url, kwargs):
        return _response(400, {"error": {"message": "invalid size", "type": "invalid_request_error", "code": "bad_size"}})

    monkeypatch.setattr(openai_video.httpx, "AsyncClient", lambda **kwargs: _Client(handler))

    with pytest.raises(UpstreamServiceError, match="invalid size") as exc_info:
        await video_adapter.create_video_job(
            adapter_type=VIDEO_ADAPTER_OPENAI,
            model="sora-2",
            prompt="测试",
            aspect_ratio="16:9",
            size="720P",
            duration_seconds=5,
            images=None,
            api_key="secret-key",
            base_url="https://api.openai.example/v1",
            video_capabilities={
                "limits": {"duration_seconds": {"allowed": [5]}},
                "wire": {"size_by_resolution_aspect": {"720P|16:9": "1280x720"}},
            },
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.retryable is False


@pytest.mark.asyncio
async def test_openai_query_uses_native_endpoint_and_normalizes_status(monkeypatch):
    captured = {}

    def handler(method, url, kwargs):
        captured.update(method=method, url=url)
        return _response(200, {"id": "video-1", "status": "completed", "progress": 100})

    monkeypatch.setattr(openai_video.httpx, "AsyncClient", lambda **kwargs: _Client(handler))

    result = await video_adapter.query_video_job(
        "video-1",
        adapter_type=VIDEO_ADAPTER_OPENAI,
        api_key="secret-key",
        base_url="https://api.openai.example/v1",
    )

    assert captured == {"method": "GET", "url": "https://api.openai.example/v1/videos/video-1"}
    assert result["task_id"] == "video-1"
    assert result["status"] == "completed"
    assert result["upstream_status"] == "completed"
    assert result["progress"] == 100


@pytest.mark.asyncio
async def test_openai_materialize_downloads_native_content(monkeypatch, tmp_path):
    monkeypatch.setattr(openai_video, "_VIDEO_OUTPUTS_DIR", tmp_path)

    def handler(method, url, kwargs):
        assert method == "GET"
        assert url == "https://api.openai.example/v1/videos/video-1/content"
        return _StreamResponse([b"video-bytes"], content_length=11)

    monkeypatch.setattr(openai_video.httpx, "AsyncClient", lambda **kwargs: _Client(handler))

    result = await video_adapter.materialize_video_job(
        adapter_type=VIDEO_ADAPTER_OPENAI,
        job_id="video-1",
        query_result={"task_id": "video-1", "status": "completed"},
        shot_id=7,
        api_key="secret-key",
        base_url="https://api.openai.example/v1",
    )

    output_path = Path(result)
    assert output_path == tmp_path / "shot_7" / "video-1.mp4"
    assert output_path.read_bytes() == b"video-bytes"


@pytest.mark.asyncio
async def test_lingdong_dispatch_forwards_input_mode_and_seed(monkeypatch):
    captured = {}

    async def fake_create(**kwargs):
        captured.update(kwargs)
        return {"task_id": "relay-1", "status": "queued"}

    monkeypatch.setattr(video_api, "create_video_job", fake_create)

    result = await video_adapter.create_video_job(
        adapter_type=VIDEO_ADAPTER_LINGDONG,
        model="sora-relay",
        prompt="测试中转",
        aspect_ratio="16:9",
        size="720P",
        duration_seconds=10,
        images=["https://cdn.example.com/a.png"],
        input_mode="image_to_video",
        seed=123,
        api_key="relay-key",
        base_url="https://relay.example.com/v1",
        video_capabilities={"payload_profile": "sora_v2", "wire": {"size_by_resolution_aspect": {"720P|16:9": "1280x720"}}},
    )

    assert captured["input_mode"] == "image_to_video"
    assert captured["seed"] == 123
    assert result["task_id"] == "relay-1"


@pytest.mark.asyncio
async def test_lingdong_dispatch_preserves_pipe_reference(monkeypatch):
    captured = {}

    async def fake_create(**kwargs):
        captured.update(kwargs)
        return {"task_id": "relay-1", "status": "queued"}

    monkeypatch.setattr(video_api, "create_video_job", fake_create)

    result = await video_adapter.create_video_job(
        adapter_type=VIDEO_ADAPTER_LINGDONG,
        model="sora-relay",
        prompt="测试中转",
        aspect_ratio="16:9",
        size="720P",
        duration_seconds=10,
        images=["https://cdn.example.com/a.png", "https://cdn.example.com/b.png"],
        api_key="relay-key",
        base_url="https://relay.example.com/v1",
        video_capabilities={"payload_profile": "sora_v2", "wire": {"size_by_resolution_aspect": {"720P|16:9": "1280x720"}}},
    )

    assert captured["images"] == ["https://cdn.example.com/a.png", "https://cdn.example.com/b.png"]
    assert captured["video_capabilities"]["payload_profile"] == "sora_v2"
    assert result["task_id"] == "relay-1"


@pytest.mark.asyncio
async def test_lingdong_query_uses_existing_client(monkeypatch):
    captured = {}

    async def fake_query(job_id, **kwargs):
        captured.update(job_id=job_id, **kwargs)
        return {"task_id": job_id, "status": "IN_PROGRESS"}

    monkeypatch.setattr(video_api, "query_video_job", fake_query)

    result = await video_adapter.query_video_job(
        "relay-1",
        adapter_type=VIDEO_ADAPTER_LINGDONG,
        api_key="relay-key",
        base_url="https://relay.example.com/v1",
        model="relay-model",
    )

    assert captured == {
        "job_id": "relay-1",
        "api_key": "relay-key",
        "base_url": "https://relay.example.com/v1",
        "model": "relay-model",
    }
    assert result["status"] == "in_progress"
    assert result["upstream_status"] == "IN_PROGRESS"


@pytest.mark.parametrize(
    ("adapter_type", "upstream_status", "expected"),
    [
        (VIDEO_ADAPTER_OPENAI, "pending", "queued"),
        (VIDEO_ADAPTER_OPENAI, "processing", "in_progress"),
        (VIDEO_ADAPTER_OPENAI, "succeeded", "completed"),
        (VIDEO_ADAPTER_OPENAI, "cancelled", "failed"),
        (VIDEO_ADAPTER_LINGDONG, "NOT_START", "queued"),
        (VIDEO_ADAPTER_LINGDONG, "IN_PROGRESS", "in_progress"),
        (VIDEO_ADAPTER_LINGDONG, "SUCCESS", "completed"),
        (VIDEO_ADAPTER_LINGDONG, "FAILURE", "failed"),
    ],
)
@pytest.mark.asyncio
async def test_adapter_create_normalizes_status(monkeypatch, adapter_type, upstream_status, expected):
    async def fake_create(**kwargs):
        return {"task_id": "job-1", "status": upstream_status}

    target = openai_video if adapter_type == VIDEO_ADAPTER_OPENAI else video_api
    monkeypatch.setattr(target, "create_video_job", fake_create)

    result = await video_adapter.create_video_job(
        adapter_type=adapter_type,
        model="video-model",
        prompt="测试状态",
        aspect_ratio="16:9",
        size="720P",
        duration_seconds=5,
        images=None,
        api_key="secret-key",
        base_url="https://api.example.com/v1",
        video_capabilities={
            "limits": {"duration_seconds": {"allowed": [5]}, "max_reference_images": 1},
            "wire": {"size_by_resolution_aspect": {"720P|16:9": "1280x720"}},
        },
    )

    assert result["status"] == expected
    assert result["upstream_status"] == upstream_status


@pytest.mark.parametrize("adapter_type", [VIDEO_ADAPTER_OPENAI, VIDEO_ADAPTER_LINGDONG])
@pytest.mark.asyncio
async def test_adapter_query_treats_unknown_status_as_nonrecoverable_failure(monkeypatch, adapter_type):
    async def fake_query(*args, **kwargs):
        return {"task_id": "job-unknown", "status": "mystery_state"}

    target = openai_video if adapter_type == VIDEO_ADAPTER_OPENAI else video_api
    monkeypatch.setattr(target, "query_video_job", fake_query)

    result = await video_adapter.query_video_job(
        "job-unknown",
        adapter_type=adapter_type,
        api_key="secret-key",
        base_url="https://api.example.com/v1",
        model="video-model",
    )

    assert result["status"] == "failed"
    assert result["upstream_status"] == "mystery_state"
    assert result["error"] == "视频上游返回未知任务状态: mystery_state"
    assert result["retryable"] is False


@pytest.mark.asyncio
async def test_lingdong_submit_with_task_id_but_empty_status_is_queued(monkeypatch):
    """部分网关提交成功只回 task_id 不带 status：应按排队去轮询，不能判成“未知状态”失败。"""
    async def fake_create(**kwargs):
        return {"task_id": "task_abc", "status": ""}

    monkeypatch.setattr(video_api, "create_video_job", fake_create)
    result = await video_adapter.create_video_job(
        adapter_type=VIDEO_ADAPTER_LINGDONG, model="video-model", prompt="测试", aspect_ratio="16:9", size="720P",
        duration_seconds=5, images=None, api_key="k", base_url="https://api.example.com/v1", video_capabilities=None,
    )
    assert result["status"] == "queued"
    assert result["task_id"] == "task_abc"
    assert "error" not in result


@pytest.mark.asyncio
async def test_lingdong_query_with_empty_status_is_still_a_failure(monkeypatch):
    """查询时状态为空仍判失败（只有提交返回才放行为排队）。"""
    async def fake_query(*args, **kwargs):
        return {"task_id": "task_abc", "status": ""}

    monkeypatch.setattr(video_api, "query_video_job", fake_query)
    result = await video_adapter.query_video_job("task_abc", adapter_type=VIDEO_ADAPTER_LINGDONG, api_key="k", base_url="https://api.example.com/v1", model="m")
    assert result["status"] == "failed"


def test_status_map_treats_error_as_failed():
    assert video_adapter._normalize_job_status({"task_id": "t", "status": "error"})["status"] == "failed"


@pytest.mark.asyncio
async def test_openai_error_redacts_api_key_bearer_and_labeled_secrets(monkeypatch):
    api_key = "current-secret-key"
    leaked = f"key={api_key} Authorization: Bearer other-token token=third-secret"

    def handler(method, url, kwargs):
        return _response(400, {"error": {"message": leaked}})

    monkeypatch.setattr(openai_video.httpx, "AsyncClient", lambda **kwargs: _Client(handler))

    with pytest.raises(UpstreamServiceError) as exc_info:
        await openai_video.create_video_job(
            model="sora-2",
            prompt="测试",
            duration_seconds=5,
            wire_size="1280x720",
            image_url=None,
            api_key=api_key,
            base_url="https://api.openai.example/v1",
        )

    message = str(exc_info.value)
    assert api_key not in message
    assert "other-token" not in message
    assert "third-secret" not in message
    assert "***" in message


@pytest.mark.asyncio
async def test_openai_content_rejects_large_content_length_before_writing(monkeypatch, tmp_path):
    monkeypatch.setattr(openai_video, "_VIDEO_OUTPUTS_DIR", tmp_path)
    monkeypatch.setattr(openai_video, "MAX_VIDEO_CONTENT_BYTES", 5)
    response = _StreamResponse([b"abc"], content_length=6)
    monkeypatch.setattr(openai_video.httpx, "AsyncClient", lambda **kwargs: _Client(lambda *args: response))

    with pytest.raises(UpstreamServiceError, match="最大大小"):
        await openai_video.download_video_content(
            "video-large-header",
            shot_id=1,
            api_key="secret-key",
            base_url="https://api.openai.example/v1",
        )

    assert list(tmp_path.rglob("*")) == []


@pytest.mark.asyncio
async def test_openai_content_cleans_temp_file_when_stream_exceeds_limit(monkeypatch, tmp_path):
    monkeypatch.setattr(openai_video, "_VIDEO_OUTPUTS_DIR", tmp_path)
    monkeypatch.setattr(openai_video, "MAX_VIDEO_CONTENT_BYTES", 5)
    response = _StreamResponse([b"abc", b"def"])
    monkeypatch.setattr(openai_video.httpx, "AsyncClient", lambda **kwargs: _Client(lambda *args: response))

    with pytest.raises(UpstreamServiceError, match="最大大小"):
        await openai_video.download_video_content(
            "video-large-stream",
            shot_id=2,
            api_key="secret-key",
            base_url="https://api.openai.example/v1",
        )

    assert not list(tmp_path.rglob("*.tmp"))
    assert not list(tmp_path.rglob("*.mp4"))


@pytest.mark.asyncio
async def test_openai_content_atomically_replaces_temp_file(monkeypatch, tmp_path):
    monkeypatch.setattr(openai_video, "_VIDEO_OUTPUTS_DIR", tmp_path)
    response = _StreamResponse([b"video-", b"bytes"], content_length=11)
    monkeypatch.setattr(openai_video.httpx, "AsyncClient", lambda **kwargs: _Client(lambda *args: response))

    result = await openai_video.download_video_content(
        "video-streamed",
        shot_id=3,
        api_key="secret-key",
        base_url="https://api.openai.example/v1",
    )

    output_path = Path(result)
    assert output_path.read_bytes() == b"video-bytes"
    assert not list(output_path.parent.glob("*.tmp"))


@pytest.mark.asyncio
async def test_lingdong_rejects_images_reference_field_before_http(monkeypatch):
    called = False

    def client_factory(**kwargs):
        nonlocal called
        called = True
        raise AssertionError("不应创建 HTTP 客户端")

    monkeypatch.setattr(video_api.httpx, "AsyncClient", client_factory)

    with pytest.raises(ValueError, match="reference_field"):
        await video_api.create_video_job(
            model="sora-relay",
            prompt="测试",
            images=["https://cdn.example.com/a.png"],
            api_key="relay-key",
            base_url="https://relay.example.com/v1",
            video_capabilities={
                "payload_profile": "sora_v2",
                "wire": {
                    "reference_field": "images",
                    "size_by_resolution_aspect": {"720P|16:9": "1280x720"},
                },
            },
        )

    assert called is False


@pytest.mark.parametrize("input_mode", ["text", "text_to_video"])
@pytest.mark.asyncio
async def test_openai_runtime_rejects_image_request_for_text_only_model(monkeypatch, input_mode):
    called = False

    async def fake_create(**kwargs):
        nonlocal called
        called = True
        return {"task_id": "unexpected", "status": "queued"}

    monkeypatch.setattr(openai_video, "create_video_job", fake_create)

    with pytest.raises(ValueError, match="输入模式"):
        await video_adapter.create_video_job(
            adapter_type=VIDEO_ADAPTER_OPENAI,
            model="text-only-video",
            prompt="测试",
            aspect_ratio="16:9",
            size="720P",
            duration_seconds=5,
            images=["https://cdn.example.com/reference.png"],
            api_key="secret-key",
            base_url="https://api.openai.example/v1",
            video_capabilities={
                "input_modes": [input_mode],
                "limits": {"duration_seconds": {"allowed": [5]}, "max_reference_images": 1},
                "wire": {"size_by_resolution_aspect": {"720P|16:9": "1280x720"}},
            },
        )

    assert called is False


@pytest.mark.parametrize("input_mode", ["image", "image_to_video"])
@pytest.mark.asyncio
async def test_openai_runtime_rejects_text_request_for_image_only_model(monkeypatch, input_mode):
    called = False

    async def fake_create(**kwargs):
        nonlocal called
        called = True
        return {"task_id": "unexpected", "status": "queued"}

    monkeypatch.setattr(openai_video, "create_video_job", fake_create)

    with pytest.raises(ValueError, match="输入模式"):
        await video_adapter.create_video_job(
            adapter_type=VIDEO_ADAPTER_OPENAI,
            model="image-only-video",
            prompt="测试",
            aspect_ratio="16:9",
            size="720P",
            duration_seconds=5,
            images=None,
            api_key="secret-key",
            base_url="https://api.openai.example/v1",
            video_capabilities={
                "input_modes": [input_mode],
                "limits": {"duration_seconds": {"allowed": [5]}, "max_reference_images": 1},
                "wire": {"size_by_resolution_aspect": {"720P|16:9": "1280x720"}},
            },
        )

    assert called is False


@pytest.mark.parametrize("operation", ["create", "query"])
@pytest.mark.asyncio
async def test_openai_200_failed_job_redacts_error_message(monkeypatch, operation):
    api_key = "current-success-key"
    leaked = f"key={api_key} Authorization: Bearer bearer-secret token=labeled-secret"

    def handler(method, url, kwargs):
        error = leaked if operation == "create" else {"message": leaked}
        return _response(200, {"id": "video-failed", "status": "failed", "error": error})

    monkeypatch.setattr(openai_video.httpx, "AsyncClient", lambda **kwargs: _Client(handler))

    if operation == "create":
        result = await openai_video.create_video_job(
            model="sora-2",
            prompt="测试",
            duration_seconds=5,
            wire_size="1280x720",
            image_url=None,
            api_key=api_key,
            base_url="https://api.openai.example/v1",
        )
    else:
        result = await openai_video.query_video_job(
            "video-failed",
            api_key=api_key,
            base_url="https://api.openai.example/v1",
        )

    error = result.get("error", "")
    assert result.get("status") == "failed"
    assert api_key not in error
    assert "bearer-secret" not in error
    assert "labeled-secret" not in error
    assert "***" in error


@pytest.mark.asyncio
async def test_legacy_seedance_15_seconds_is_rejected_without_silent_clamp(monkeypatch):
    called = False

    def client_factory(**kwargs):
        nonlocal called
        called = True
        raise AssertionError("不应创建 HTTP 客户端")

    monkeypatch.setattr(video_api.httpx, "AsyncClient", client_factory)
    with pytest.raises(ValueError, match="最大时长为 12 秒"):
        await video_api.create_video_job(
            model="seedance-1.5-pro",
            prompt="测试 15 秒视频",
            duration_seconds=15,
            api_key="relay-key",
            base_url="https://relay.example.com/v1",
        )
    assert called is False


@pytest.mark.asyncio
async def test_lingdong_logs_do_not_expose_signed_media_url(monkeypatch, caplog):
    class Response:
        is_success = True
        status_code = 200
        text = ""

        @staticmethod
        def json():
            return {"task_id": "safe-log", "status": "queued"}

    monkeypatch.setattr(
        video_api.httpx,
        "AsyncClient",
        lambda **kwargs: _Client(lambda *args: Response()),
    )
    signed_url = "https://user:password@cdn.example.com/media/ref.png?signature=SECRET&token=SECRET#fragment"
    with caplog.at_level("INFO", logger="video_api"):
        await video_api.create_video_job(
            model="sd-2-vip-720",
            prompt="测试日志",
            images=[signed_url],
            api_key="relay-key",
            base_url="https://relay.example.com/v1?token=SECRET",
        )
    assert "SECRET" not in caplog.text
    assert "user:password" not in caplog.text
    assert "cdn.example.com/media/ref.png" in caplog.text


@pytest.mark.asyncio
async def test_lingdong_download_keeps_partial_bytes_out_of_final_path(monkeypatch, tmp_path):
    first_chunk_written = asyncio.Event()
    release_stream = asyncio.Event()

    class DelayedResponse(_StreamResponse):
        async def aiter_bytes(self):
            yield b"partial-"
            first_chunk_written.set()
            await release_stream.wait()
            yield b"complete"

    monkeypatch.setattr(
        video_api.httpx,
        "AsyncClient",
        lambda **kwargs: _Client(lambda *args: DelayedResponse([])),
    )
    monkeypatch.setattr(video_api, "_upload_video_url_to_oss", lambda *args: None)
    monkeypatch.setattr(video_api, "_upload_to_oss_if_enabled", lambda *args: None)
    monkeypatch.setattr(video_api, "validate_remote_media_url", lambda url: url)
    task = asyncio.create_task(
        video_api.download_video(
            "https://cdn.example.com/video.mp4?signature=SECRET",
            shot_id=5,
            job_id="atomic-job",
            output_dir=tmp_path,
        )
    )
    await first_chunk_written.wait()
    final_path = tmp_path / "shot_5" / "atomic-job.mp4"
    final_existed_during_stream = final_path.exists()
    release_stream.set()
    result = await task
    assert final_existed_during_stream is False
    assert Path(result).read_bytes() == b"partial-complete"
    assert not list(final_path.parent.glob("*.tmp"))


@pytest.mark.asyncio
async def test_concurrent_lingdong_downloads_use_independent_temp_files(monkeypatch, tmp_path):
    counter = 0

    def handler(*args):
        nonlocal counter
        counter += 1
        return _StreamResponse([str(counter).encode("ascii"), b"-complete"])

    monkeypatch.setattr(video_api.httpx, "AsyncClient", lambda **kwargs: _Client(handler))
    monkeypatch.setattr(video_api, "_upload_video_url_to_oss", lambda *args: None)
    monkeypatch.setattr(video_api, "_upload_to_oss_if_enabled", lambda *args: None)
    monkeypatch.setattr(video_api, "validate_remote_media_url", lambda url: url)
    results = await asyncio.gather(
        video_api.download_video("https://cdn.example.com/video.mp4", shot_id=6, job_id="same-job", output_dir=tmp_path),
        video_api.download_video("https://cdn.example.com/video.mp4", shot_id=6, job_id="same-job", output_dir=tmp_path),
    )
    assert results[0] == results[1]
    assert Path(results[0]).read_bytes() in {b"1-complete", b"2-complete"}
    assert not list(Path(results[0]).parent.glob("*.tmp"))


# ---------------- 上游官方字段写法（referenceImages / @图N）通过模型参数 JSON 配置 ----------------

DUBAI_STYLE_CAPABILITIES = {
    "payload_profile": "custom",
    "limits": {"duration_seconds": {"min": 4, "max": 15}, "max_reference_images": 9, "aspect_ratios": ["16:9", "9:16"], "resolutions": ["720P"], "max_reference_audios": 3},
    "wire": {
        "duration_field": "duration", "ratio_field": "ratio", "resolution_field": "resolution", "resolution_case": "lower",
        "reference_field": "referenceImages", "audio_reference_field": "referenceAudios", "omit_input_mode": True, "reference_token": "@图{n}",
    },
}


async def _captured_payload(monkeypatch, **overrides):
    captured = {}

    def handler(method, url, kwargs):
        captured["json"] = kwargs.get("json")
        return type("R", (), {"is_success": True, "status_code": 200, "json": lambda self: {"task_id": "t-1", "status": "queued"}})()

    monkeypatch.setattr(video_api.httpx, "AsyncClient", lambda *a, **k: _Client(handler))
    args = dict(
        model="xinyao-2.0-720p-TJ", prompt="连续镜头。@图片2 站在碑前", aspect_ratio="16:9", size="720P", duration_seconds=13,
        images=["https://cdn.example.com/a.jpg", "https://cdn.example.com/b.jpg", "https://cdn.example.com/c.jpg"],
        api_key="k", base_url="https://relay.example.com/v1", video_capabilities=DUBAI_STYLE_CAPABILITIES, input_mode="image_to_video",
    )
    args.update(overrides)
    await video_api.create_video_job(**args)
    return captured["json"]


@pytest.mark.asyncio
async def test_wire_config_sends_only_the_official_fields_with_a_reference_array(monkeypatch):
    payload = await _captured_payload(monkeypatch)
    assert payload["referenceImages"] == ["https://cdn.example.com/a.jpg", "https://cdn.example.com/b.jpg", "https://cdn.example.com/c.jpg"]  # 数组，不是 | 拼成的一个字符串
    assert payload["duration"] == 13 and payload["ratio"] == "16:9" and payload["resolution"] == "720p"
    assert set(payload) == {"model", "prompt", "duration", "ratio", "resolution", "referenceImages"}  # 没有 size / orientation / input_mode / input_reference


@pytest.mark.asyncio
async def test_prompt_mentions_every_reference_as_at_tu_n(monkeypatch):
    payload = await _captured_payload(monkeypatch)
    prompt = payload["prompt"]
    assert "@图2 站在碑前" in prompt and "@图片" not in prompt  # 画布里的 @图片N 转成上游写法
    assert all(f"@图{n}" in prompt for n in (1, 2, 3))  # 缺的 @图1、@图3 自动补上，一一对应


@pytest.mark.asyncio
async def test_audio_references_use_the_official_array_field(monkeypatch):
    payload = await _captured_payload(monkeypatch, audios=["https://cdn.example.com/v.mp3"])
    assert payload["referenceAudios"] == ["https://cdn.example.com/v.mp3"]


def test_reference_token_helper_is_idempotent_and_ordered():
    text = video_api.apply_reference_tokens("@图片1 走向 @图3", 3, "@图{n}")
    assert text.startswith("@图1 走向 @图3") and text.endswith("参考素材：@图2")
    assert video_api.apply_reference_tokens(text, 3, "@图{n}") == text


def test_admin_save_validator_accepts_the_official_wire_style_but_still_rejects_typos():
    from fastapi import HTTPException

    from routers.points_ai import _validate_model_capabilities

    wrapped = {"schema_version": 1, "video": DUBAI_STYLE_CAPABILITIES}
    _validate_model_capabilities(wrapped, "video", "lingdong_video")
    with pytest.raises(HTTPException, match="video 对象"):
        _validate_model_capabilities(DUBAI_STYLE_CAPABILITIES, "video", "lingdong_video")  # 只贴内层会被拒
    for patch in ({"omit_input_mode": "yes"}, {"reference_token": "@图"}, {"reference_field": "referenceImagez"}):
        bad = {"schema_version": 1, "video": {**DUBAI_STYLE_CAPABILITIES, "wire": {**DUBAI_STYLE_CAPABILITIES["wire"], **patch}}}
        with pytest.raises(HTTPException):
            _validate_model_capabilities(bad, "video", "lingdong_video")
    legacy = {"schema_version": 1, "video": {**DUBAI_STYLE_CAPABILITIES, "payload_profile": "legacy_lingdong"}}
    with pytest.raises(HTTPException):
        _validate_model_capabilities(legacy, "video", "lingdong_video")  # referenceImages 只在 custom 档位放行
