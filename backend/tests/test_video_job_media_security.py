from __future__ import annotations

import json
import inspect

import pytest
from pydantic import ValidationError

from routers import video
from schemas import VideoRenderRequest


SIGNED_URL = (
    "https://user:password@cdn.example.com/path/video.mp4"
    "?X-Amz-Signature=SIGNED_SECRET&token=QUERY_SECRET#FRAGMENT_SECRET"
)
DATA_URI = "data:image/png;base64,BASE64_SECRET_PAYLOAD"


def _serialized(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def test_video_render_request_rejects_more_than_nine_reference_assets():
    with pytest.raises(ValidationError):
        VideoRenderRequest(reference_asset_ids=list(range(1, 11)))


def test_persisted_video_payload_keeps_asset_metadata_without_media_secrets():
    payload = {
        "prompt": "测试",
        "reference_asset_ids": [8, 3],
        "reference_roles": ["storyboard", "character"],
        "reference_image_urls": [SIGNED_URL],
        "submitted_reference_images": [DATA_URI, SIGNED_URL],
        "source": {"url": SIGNED_URL, "preview": DATA_URI},
    }

    sanitized = video._sanitize_video_job_request_payload(payload)
    text = _serialized(sanitized)

    assert sanitized["reference_asset_ids"] == [8, 3]
    assert sanitized["reference_roles"] == ["storyboard", "character"]
    assert "https://cdn.example.com/path/video.mp4" in text
    assert "SIGNED_SECRET" not in text
    assert "QUERY_SECRET" not in text
    assert "FRAGMENT_SECRET" not in text
    assert "user:password" not in text
    assert "BASE64_SECRET_PAYLOAD" not in text
    assert "data:image" not in text


def test_provider_result_is_recursively_sanitized_before_persistence_and_api():
    provider_result = {
        "status": "succeeded",
        "url": SIGNED_URL,
        "nested": [{"video_url": SIGNED_URL, "raw": DATA_URI}],
    }

    sanitized = video._sanitize_video_provider_result(provider_result)
    text = _serialized(sanitized)

    assert sanitized["status"] == "succeeded"
    assert sanitized["url"] == "https://cdn.example.com/path/video.mp4"
    assert "SIGNED_SECRET" not in text
    assert "QUERY_SECRET" not in text
    assert "FRAGMENT_SECRET" not in text
    assert "user:password" not in text
    assert "BASE64_SECRET_PAYLOAD" not in text
    assert "data:image" not in text


def test_router_media_log_boundary_redacts_signed_url():
    safe_value = video.safe_media_url_for_log(SIGNED_URL)

    assert safe_value == "https://cdn.example.com/path/video.mp4"
    assert "SIGNED_SECRET" not in safe_value
    assert "QUERY_SECRET" not in safe_value
    assert "FRAGMENT_SECRET" not in safe_value
    assert "user:password" not in safe_value


def test_router_media_logs_do_not_emit_raw_url_variables():
    source = inspect.getsource(video)

    assert 'logger.warning("风格参考图文件不存在或无法下载: %s", ref_url)' not in source
    assert 'list(update_data.keys()), update_data.get("image_url", "(未发送)")' not in source
    assert 'logger.warning("Could not resolve path for clip %s: %s", clip_id, clip.video_path)' not in source


def test_reference_encoder_rejects_oversized_file_before_read(tmp_path, monkeypatch):
    path = tmp_path / "large.png"
    path.write_bytes(b"12345")
    monkeypatch.setattr(video, "MAX_VIDEO_REFERENCE_FILE_BYTES", 4)
    monkeypatch.setattr(video, "MAX_VIDEO_REFERENCE_TOTAL_BYTES", 100)
    monkeypatch.setattr(video, "MAX_VIDEO_REFERENCE_BASE64_BYTES", 100)

    with pytest.raises(ValueError, match="单个参考文件"):
        video._encode_reference_files_to_base64_data_uris([str(path)])


def test_reference_encoder_rejects_cumulative_size_before_any_read(tmp_path, monkeypatch):
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    first.write_bytes(b"1234")
    second.write_bytes(b"5678")
    monkeypatch.setattr(video, "MAX_VIDEO_REFERENCE_FILE_BYTES", 10)
    monkeypatch.setattr(video, "MAX_VIDEO_REFERENCE_TOTAL_BYTES", 7)
    monkeypatch.setattr(video, "MAX_VIDEO_REFERENCE_BASE64_BYTES", 100)
    read_calls: list[str] = []
    original_open = open

    def tracking_open(file, mode="r", *args, **kwargs):
        if "b" in mode:
            read_calls.append(str(file))
        return original_open(file, mode, *args, **kwargs)

    monkeypatch.setattr("builtins.open", tracking_open)

    with pytest.raises(ValueError, match="累计大小"):
        video._encode_reference_files_to_base64_data_uris([str(first), str(second)])
    assert read_calls == []


def test_reference_encoder_rejects_projected_base64_before_read(tmp_path, monkeypatch):
    path = tmp_path / "projected.png"
    path.write_bytes(b"1234")
    monkeypatch.setattr(video, "MAX_VIDEO_REFERENCE_FILE_BYTES", 10)
    monkeypatch.setattr(video, "MAX_VIDEO_REFERENCE_TOTAL_BYTES", 10)
    monkeypatch.setattr(video, "MAX_VIDEO_REFERENCE_BASE64_BYTES", 4)
    read_calls: list[str] = []
    original_open = open

    def tracking_open(file, mode="r", *args, **kwargs):
        if "b" in mode:
            read_calls.append(str(file))
        return original_open(file, mode, *args, **kwargs)

    monkeypatch.setattr("builtins.open", tracking_open)

    with pytest.raises(ValueError, match="Base64"):
        video._encode_reference_files_to_base64_data_uris([str(path)])
    assert read_calls == []


def test_prepare_video_references_preserves_mixed_input_order(tmp_path, monkeypatch):
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    monkeypatch.setattr(video, "MAX_VIDEO_REFERENCE_FILE_BYTES", 100)
    monkeypatch.setattr(video, "MAX_VIDEO_REFERENCE_TOTAL_BYTES", 100)
    monkeypatch.setattr(video, "MAX_VIDEO_REFERENCE_BASE64_BYTES", 200)

    prepared = video._prepare_video_reference_images([
        str(first),
        "https://cdn.example.com/remote.png?token=TRANSIENT",
        str(second),
    ])

    assert prepared[0].startswith("data:image/png;base64,")
    assert prepared[1] == "https://cdn.example.com/remote.png?token=TRANSIENT"
    assert prepared[2].startswith("data:image/png;base64,")


def test_prepare_video_references_rejects_more_than_nine_before_read(monkeypatch):
    monkeypatch.setattr(
        video,
        "_encode_reference_files_to_base64_data_uris",
        lambda _paths: pytest.fail("引用数量超限时不应读取或编码文件"),
    )

    with pytest.raises(ValueError, match="最多允许 9 张"):
        video._prepare_video_reference_images([f"C:/refs/{index}.png" for index in range(10)])
