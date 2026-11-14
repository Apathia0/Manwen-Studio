"""视频音频参考：能力声明才允许提交、上游字段受白名单保护、画布端口与运行时校验。"""

from types import SimpleNamespace

import pytest

from routers import video_canvas as canvas_api
from services import video_adapter, video_api, video_canvas_runtime as runtime

IMAGES = ["https://example.com/a.png"]
AUDIOS = ["https://example.com/voice.mp3"]


class _Capture:
    """替换 httpx 客户端，记录发往上游的 JSON。"""

    def __init__(self, monkeypatch):
        self.payload: dict = {}
        capture = self

        class Response:
            is_success = True
            status_code = 200
            text = ""

            @staticmethod
            def json():
                return {"task_id": "task-1", "status": "queued"}

        class Client:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def post(self, url, json, headers):
                capture.payload.update(json)
                return Response()

        monkeypatch.setattr(video_api.httpx, "AsyncClient", Client)


def caps(**limits):
    return {"payload_profile": "custom", "limits": limits, "input_modes": ["text_to_video", "image_to_video"], "wire": {"reference_field": "input_reference"}}


async def submit(**kwargs):
    return await video_api.create_video_job(model="sd-2-vip-720", prompt="镜头推进", api_key="k", base_url="https://example.com", **kwargs)


@pytest.mark.asyncio
async def test_audio_is_rejected_when_model_does_not_declare_support(monkeypatch):
    _Capture(monkeypatch)
    with pytest.raises(ValueError, match="未声明音频参考能力"):
        await submit(images=IMAGES, audios=AUDIOS, video_capabilities=caps())


@pytest.mark.asyncio
async def test_audio_is_appended_to_pipe_separated_input_reference(monkeypatch):
    capture = _Capture(monkeypatch)
    await submit(images=IMAGES, audios=AUDIOS, video_capabilities=caps(max_reference_audios=2))
    assert capture.payload["input_reference"] == "https://example.com/a.png|https://example.com/voice.mp3"


@pytest.mark.asyncio
async def test_audio_only_reference_is_supported(monkeypatch):
    capture = _Capture(monkeypatch)
    await submit(audios=AUDIOS, video_capabilities=caps(max_reference_audios=1))
    assert capture.payload["input_reference"] == "https://example.com/voice.mp3"


@pytest.mark.asyncio
async def test_dedicated_audio_field_keeps_images_and_audio_separate(monkeypatch):
    capture = _Capture(monkeypatch)
    video = caps(max_reference_audios=1)
    video["wire"]["audio_reference_field"] = "reference_audio_urls"
    await submit(images=IMAGES, audios=AUDIOS, video_capabilities=video)
    assert capture.payload["input_reference"] == "https://example.com/a.png"
    assert capture.payload["reference_audio_urls"] == AUDIOS


@pytest.mark.asyncio
async def test_audio_count_and_total_limits_are_enforced(monkeypatch):
    _Capture(monkeypatch)
    with pytest.raises(ValueError, match="音频参考数量超过"):
        await submit(audios=AUDIOS * 2, video_capabilities=caps(max_reference_audios=1))
    with pytest.raises(ValueError, match="参考素材总数超过"):
        await submit(images=IMAGES, audios=AUDIOS, video_capabilities=caps(max_reference_audios=2, max_reference_total=1))


@pytest.mark.asyncio
async def test_unknown_audio_wire_field_is_rejected(monkeypatch):
    _Capture(monkeypatch)
    video = caps(max_reference_audios=1)
    video["wire"]["audio_reference_field"] = "anything_else"
    with pytest.raises(ValueError, match="audio_reference_field"):
        await submit(audios=AUDIOS, video_capabilities=video)


@pytest.mark.asyncio
async def test_images_only_requests_are_unchanged(monkeypatch):
    capture = _Capture(monkeypatch)
    await submit(images=IMAGES, video_capabilities=caps())
    assert capture.payload["input_reference"] == "https://example.com/a.png"


@pytest.mark.asyncio
async def test_openai_protocol_rejects_audio_reference():
    with pytest.raises(ValueError, match="不支持音频参考"):
        await video_adapter.create_video_job(
            adapter_type=video_adapter.VIDEO_ADAPTER_OPENAI, model="m", prompt="p", aspect_ratio="16:9", size="720P",
            duration_seconds=5, images=None, api_key="k", base_url="https://x", video_capabilities={}, audios=AUDIOS,
        )


def test_audio_node_connects_only_to_video_audio_port():
    def graph(target_type, target_handle):
        return {"nodes": [
            {"id": "a", "type": "audio", "position": {"x": 0, "y": 0}, "data": {"config": {}}},
            {"id": "t", "type": target_type, "position": {"x": 0, "y": 0}, "data": {"config": {}}},
        ], "edges": [{"id": "e", "source": "a", "target": "t", "sourceHandle": "audio", "targetHandle": target_handle}]}

    assert canvas_api._validate_graph(graph("video", "audio"))["errors"] == []
    assert canvas_api._validate_graph(graph("image", "references"))["errors"]
    assert canvas_api._validate_graph(graph("video", "image"))["errors"]


def test_runtime_requires_declared_audio_capability():
    with pytest.raises(RuntimeError, match="未声明音频参考能力"):
        runtime._require_audio_reference_capability({"limits": {}}, 1)
    with pytest.raises(RuntimeError, match="最多支持 1 个"):
        runtime._require_audio_reference_capability({"limits": {"max_reference_audios": 1}}, 2)
    runtime._require_audio_reference_capability({"limits": {"max_reference_audios": 2}}, 2)


def test_runtime_audio_urls_only_accept_valid_audio_assets_of_the_story():
    audio = SimpleNamespace(story_id=3, status="active", asset_type="audio", file_path="/static/video/a.mp3")
    image = SimpleNamespace(story_id=3, status="active", asset_type="image", file_path="/static/manga/a.png")
    foreign = SimpleNamespace(story_id=9, status="active", asset_type="audio", file_path="/static/video/b.mp3")
    db = SimpleNamespace(get=lambda model, asset_id: {1: audio, 2: image, 3: foreign}.get(asset_id))
    canvas = SimpleNamespace(story_id=3)
    assert runtime._audio_reference_urls([{"asset_id": 1}, {"asset_id": 1}], canvas, db) == ["/static/video/a.mp3"]
    for bad in (2, 3, 99):
        with pytest.raises(RuntimeError, match="音频参考已失效"):
            runtime._audio_reference_urls([{"asset_id": bad}], canvas, db)
