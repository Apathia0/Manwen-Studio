from __future__ import annotations

from services import oss


def test_upload_from_url_log_redacts_signed_source_url(monkeypatch, caplog):
    signed_url = (
        "https://user:password@cdn.example.com/v.mp4"
        "?signature=SECRET&token=SECRET#fragment"
    )

    class Response:
        headers = {"content-length": "5"}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def raise_for_status(self):
            return None

        def iter_bytes(self):
            yield b"video"

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def stream(self, method, url):
            return Response()

    class Bucket:
        def put_object(self, remote_key, data, headers=None):
            assert data.read() == b"video"

    monkeypatch.setattr(oss, "is_enabled", lambda: True)
    monkeypatch.setattr(oss, "_get_client", lambda: Bucket())
    monkeypatch.setattr(oss, "validate_remote_media_url", lambda value: value)
    monkeypatch.setattr("httpx.Client", Client)
    monkeypatch.setattr(oss, "_build_public_url", lambda key: f"https://oss.example.com/{key}")

    with caplog.at_level("INFO", logger="oss_service"):
        result = oss.upload_from_url(signed_url, "video/result.mp4")

    assert result == "https://oss.example.com/video/result.mp4"
    assert "SECRET" not in caplog.text
    assert "user:password" not in caplog.text
    assert "fragment" not in caplog.text
    assert "https://cdn.example.com/v.mp4" in caplog.text
