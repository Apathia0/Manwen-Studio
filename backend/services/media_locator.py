"""媒体资源定位与临时本地化工具。"""

from __future__ import annotations

import hashlib
import logging
import tempfile
from pathlib import Path

import httpx

from services.ai.channels import validate_remote_media_url

logger = logging.getLogger(__name__)

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
_MANGA_OUTPUTS_DIR = _BACKEND_ROOT / "manga_outputs"
_VIDEO_OUTPUTS_DIR = _BACKEND_ROOT / "video_outputs"
_MEDIA_CACHE_DIR = _BACKEND_ROOT / ".media_cache"
_MAX_REMOTE_MEDIA_BYTES = {
    "manga": 25 * 1024 * 1024,
    "video": 512 * 1024 * 1024,
}


def _looks_like_http_url(value: str) -> bool:
    lowered = value.lower()
    return lowered.startswith("http://") or lowered.startswith("https://")


def _normalize_local_candidate(value: str, kind: str) -> Path | None:
    raw = (value or "").strip()
    if not raw:
        return None

    root = _MANGA_OUTPUTS_DIR if kind == "manga" else _VIDEO_OUTPUTS_DIR if kind == "video" else None
    if root is None:
        return None

    if Path(raw).is_absolute() and not raw.startswith(("/static/manga/", "/static/video/")):
        candidate = Path(raw).resolve()
        return candidate if candidate.is_relative_to(root.resolve()) else None

    if kind == "manga":
        if raw.startswith("/static/manga/"):
            candidate = _MANGA_OUTPUTS_DIR / raw[len("/static/manga/"):]
            return candidate.resolve() if candidate.resolve().is_relative_to(root.resolve()) else None
        if raw.startswith("manga_outputs/"):
            candidate = _BACKEND_ROOT / raw
            return candidate.resolve() if candidate.resolve().is_relative_to(root.resolve()) else None
        candidate = _MANGA_OUTPUTS_DIR / raw
        return candidate.resolve() if candidate.resolve().is_relative_to(root.resolve()) else None

    if kind == "video":
        if raw.startswith("/static/video/"):
            candidate = _VIDEO_OUTPUTS_DIR / raw[len("/static/video/"):]
            return candidate.resolve() if candidate.resolve().is_relative_to(root.resolve()) else None
        if raw.startswith("video_outputs/"):
            candidate = _BACKEND_ROOT / raw
            return candidate.resolve() if candidate.resolve().is_relative_to(root.resolve()) else None
        candidate = _VIDEO_OUTPUTS_DIR / raw
        return candidate.resolve() if candidate.resolve().is_relative_to(root.resolve()) else None

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

    tmp_path: Path | None = None
    try:
        safe_url = validate_remote_media_url(raw)
        max_bytes = _MAX_REMOTE_MEDIA_BYTES.get(kind, _MAX_REMOTE_MEDIA_BYTES["manga"])
        with httpx.Client(timeout=httpx.Timeout(30.0, connect=15.0), follow_redirects=False) as client:
            with client.stream("GET", safe_url) as response:
                response.raise_for_status()
                content_length = int(response.headers.get("content-length") or 0)
                if content_length > max_bytes:
                    raise ValueError("远程媒体文件超过大小限制")
                total = 0
                with tempfile.NamedTemporaryFile(delete=False, suffix=suffix, dir=_MEDIA_CACHE_DIR) as tmp:
                    tmp_path = Path(tmp.name)
                    for chunk in response.iter_bytes():
                        total += len(chunk)
                        if total > max_bytes:
                            raise ValueError("远程媒体文件超过大小限制")
                        tmp.write(chunk)
        if tmp_path is None:
            return None
        tmp_path.replace(cached_path)
        return str(cached_path.resolve())
    except Exception as exc:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)
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
        try:
            return validate_remote_media_url(raw)
        except Exception:
            return None
    if kind == "manga":
        if raw.startswith("style-presets/"):
            return f"/static/manga/{raw}"
        if raw.startswith("manga_outputs/"):
            return f"/static/manga/{raw[len('manga_outputs/'):]}"
    if kind == "video":
        if raw.startswith("video_outputs/"):
            return f"/static/video/{raw[len('video_outputs/'):]}"
    return None
