import os
import time

import pytest
from PIL import Image
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.testclient import TestClient

from services import media_derivatives


def _make_png(path, size=(1600, 900), color=(200, 40, 40)):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path, format="PNG")


def test_parse_width_only_accepts_allowlist():
    assert media_derivatives.parse_width("480") == 480
    assert media_derivatives.parse_width(" 1280 ") == 1280
    for bad in ("", None, "abc", "479", "-480", "99999", "480.5"):
        assert media_derivatives.parse_width(bad) is None


def test_ensure_derivative_resizes_and_keeps_aspect(tmp_path):
    source = tmp_path / "sub" / "a.png"
    _make_png(source)

    derived = media_derivatives.ensure_derivative(source, tmp_path, 480)

    assert derived is not None
    assert derived.parent == tmp_path / media_derivatives.DERIVED_DIRNAME / "sub"
    with Image.open(derived) as image:
        assert image.format == "WEBP"
        assert image.size == (480, 270)


def test_ensure_derivative_does_not_upscale(tmp_path):
    source = tmp_path / "small.png"
    _make_png(source, size=(200, 100))

    derived = media_derivatives.ensure_derivative(source, tmp_path, 480)

    with Image.open(derived) as image:
        assert image.size == (200, 100)


def test_ensure_derivative_rebuilds_when_source_is_newer(tmp_path):
    source = tmp_path / "a.png"
    _make_png(source)
    first = media_derivatives.ensure_derivative(source, tmp_path, 240)
    first_mtime = first.stat().st_mtime

    # 原图被覆盖（新尺寸、更新的 mtime）后，衍生图必须重建
    _make_png(source, size=(800, 800))
    future = time.time() + 5
    os.utime(source, (future, future))
    second = media_derivatives.ensure_derivative(source, tmp_path, 240)

    assert second == first
    assert second.stat().st_mtime >= first_mtime
    with Image.open(second) as image:
        assert image.size == (240, 240)


def test_ensure_derivative_falls_back_on_bad_input(tmp_path):
    broken = tmp_path / "broken.png"
    broken.write_bytes(b"not an image")
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"\x00\x00")

    assert media_derivatives.ensure_derivative(broken, tmp_path, 480) is None
    assert media_derivatives.ensure_derivative(video, tmp_path, 480) is None
    assert media_derivatives.ensure_derivative(tmp_path / "missing.png", tmp_path, 480) is None
    assert media_derivatives.ensure_derivative(broken, tmp_path, 481) is None


@pytest.fixture
def client(tmp_path):
    from main import GeneratedMediaStaticFiles

    _make_png(tmp_path / "ok.png")
    _make_png(tmp_path / "creative_studio" / "secret.png")
    (tmp_path / "clip.mp4").write_bytes(b"video-bytes")
    app = Starlette(routes=[Mount("/static/manga", app=GeneratedMediaStaticFiles(directory=str(tmp_path)))])
    return TestClient(app)


def test_static_serves_original_with_cache_headers(client):
    response = client.get("/static/manga/ok.png")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert "max-age=86400" in response.headers["cache-control"]


def test_static_serves_webp_variant_and_ignores_bad_width(client):
    small = client.get("/static/manga/ok.png?w=480")
    assert small.status_code == 200
    assert small.headers["content-type"] == "image/webp"
    assert "max-age=86400" in small.headers["cache-control"]

    odd = client.get("/static/manga/ok.png?w=123")
    assert odd.status_code == 200
    assert odd.headers["content-type"] == "image/png"

    video = client.get("/static/manga/clip.mp4?w=480")
    assert video.status_code == 200
    assert video.content == b"video-bytes"


def test_static_variant_conditional_request_returns_304(client):
    first = client.get("/static/manga/ok.png?w=480")
    etag = first.headers["etag"]

    again = client.get("/static/manga/ok.png?w=480", headers={"if-none-match": etag})

    assert again.status_code == 304


def test_static_blocks_private_dirs_and_derived_dir(client):
    assert client.get("/static/manga/creative_studio/secret.png").status_code == 404
    assert client.get("/static/manga/creative_studio/secret.png?w=480").status_code == 404
    client.get("/static/manga/ok.png?w=480")
    assert client.get("/static/manga/.derived/ok.png.w480.webp").status_code == 404
    assert client.get("/static/manga/missing.png?w=480").status_code == 404
