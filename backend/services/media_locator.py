"""媒体资源定位与临时本地化工具。"""

from __future__ import annotations

import hashlib
import logging
import tempfile
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
_MANGA_OUTPUTS_DIR = _BACKEND_ROOT / "manga_outputs"
_VIDEO_OUTPUTS_DIR = _BACKEND_ROOT / "video_outputs"
_MEDIA_CACHE_DIR = _BACKEND_ROOT / ".media_cache"


def _looks_like_http_url(value: str) -> bool:
    lowered = value.lower()
    return lowered.startswith("http://") or lowered.startswith("https://")


def _normalize_local_candidate(value: str, kind: str) -> Path | None:
    raw = (value or "").strip()
    if not raw:
        return None

    if Path(raw).is_absolute():
        return Path(raw)

    if kind == "manga":
        if raw.startswith("/static/manga/"):
            return _MANGA_OUTPUTS_DIR / raw[len("/static/manga/"):]
        if raw.startswith("manga_outputs/"):
            return _BACKEND_ROOT / raw
        return _MANGA_OUTPUTS_DIR / raw

    if kind == "video":
        if raw.startswith("/static/video/"):
            return _VIDEO_OUTPUTS_DIR / raw[len("/static/video/"):]
        if raw.startswith("video_outputs/"):
            return _BACKEND_ROOT / raw
        return _VIDEO_OUTPUTS_DIR / raw

    return None


def resolve_local_media_path(value: str | None, kind: str) -> str | None:
    raw = (value or "").strip()
    if not raw or _looks_like_http_url(raw):
        return None
    candidate = _normalize_local_candidate(raw, kind)
    if candidate and candidate.exists():
        return str(candidate.resolve())
    return None


def ensure_local_media_path(value: str | None, kind: str) -> str | None:
    raw = (value or "").strip()
    if not raw:
        return None

    local_path = resolve_local_media_path(raw, kind)
    if local_path:
        return local_path

    if not _looks_like_http_url(raw):
        return None

    suffix = Path(raw.split("?", 1)[0]).suffix or (".png" if kind == "manga" else ".bin")
    cache_name = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24] + suffix
    _MEDIA_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cached_path = _MEDIA_CACHE_DIR / cache_name
    if cached_path.exists():
        return str(cached_path.resolve())

    try:
        with httpx.Client(timeout=httpx.Timeout(30.0, connect=15.0), follow_redirects=True) as client:
            response = client.get(raw)
            response.raise_for_status()
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix, dir=_MEDIA_CACHE_DIR) as tmp:
            tmp.write(response.content)
            tmp_path = Path(tmp.name)
        tmp_path.replace(cached_path)
        return str(cached_path.resolve())
    except Exception as exc:
        logger.warning("下载媒体资源失败 %s: %s", raw, exc)
        return None


def resolve_reference_input(value: str | None, kind: str) -> str | None:
    raw = (value or "").strip()
    if not raw:
        return None
    local_path = resolve_local_media_path(raw, kind)
    if local_path:
        return local_path
    if _looks_like_http_url(raw):
        return raw
    return None
