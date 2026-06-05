"""Low-level video API client for New API standard."""
from __future__ import annotations

import asyncio
import base64
import logging
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv

from .errors import MissingApiKeyError

load_dotenv()

logger = logging.getLogger("video_api")

_VIDEO_OUTPUTS_DIR = Path(__file__).resolve().parent.parent / "video_outputs"

# 运行时配置（由调用方通过 configure() 注入）
_runtime_base_url: str | None = None
_runtime_api_key: str | None = None
_runtime_model: str | None = None


def configure(*, base_url: str | None = None, api_key: str | None = None, model: str | None = None):
    """运行时注入视频 API 配置（优先于 .env 默认值）。"""
    global _runtime_base_url, _runtime_api_key, _runtime_model
    if base_url:
        _runtime_base_url = base_url.rstrip("/")
    if api_key:
        _runtime_api_key = api_key
    if model:
        _runtime_model = model


def _resolved_base_url() -> str:
    return (_runtime_base_url or os.getenv("VIDEO_API_BASE_URL") or "https://newapi.aifusion6.cn/v1").rstrip("/")


def _resolved_api_key() -> str:
    return (_runtime_api_key or os.getenv("VIDEO_API_KEY") or os.getenv("IMAGE_API_KEY") or "").strip()


def _resolved_model() -> str:
    return (_runtime_model or os.getenv("VIDEO_MODEL") or "veo3.1-fast")

MAX_RETRIES = 3
RETRY_DELAY = 5
DOWNLOAD_RETRIES = 3
DOWNLOAD_RETRY_DELAY = 3

SUPPORTED_MODELS: dict[str, dict] = {
    "veo2": {"name": "Google Veo 2", "supports_image": False},
    "veo2-fast": {"name": "Google Veo 2 Fast", "supports_image": False},
    "veo2-fast-frames": {"name": "Google Veo 2 Fast (首尾帧)", "supports_image": True},
    "veo3": {"name": "Google Veo 3", "supports_image": False},
    "veo3-fast": {"name": "Google Veo 3 Fast", "supports_image": False},
    "veo3.1": {"name": "Google Veo 3.1", "supports_image": True},
    "veo3.1-fast": {"name": "Google Veo 3.1 Fast", "supports_image": True},
    "veo3.1-4k": {"name": "Google Veo 3.1 4K", "supports_image": False},
    "grok-video-3": {"name": "Grok Video 3", "supports_image": True},
    "jimeng-video-3.0": {"name": "即梦视频 3.0", "supports_image": False},
    "jimeng-video-3.0-fast": {"name": "即梦视频 3.0 Fast", "supports_image": False},
    "jimeng-video-3.5-pro": {"name": "即梦视频 3.5 Pro", "supports_image": False},
    "dance2-fast": {"name": "Dance2 Fast", "supports_image": False},
}

ALLOWED_ASPECT_RATIOS = ["16:9", "9:16", "1:1", "4:3", "3:4", "3:2", "2:3"]
ALLOWED_SIZES = ["720P", "1080P", "4K"]


def _timeout(*, connect: float, read: float, write: float, pool: float = 30.0) -> httpx.Timeout:
    return httpx.Timeout(connect=connect, read=read, write=write, pool=pool)


def _auth_headers(api_key: str | None = None) -> dict[str, str]:
    key = (api_key or _resolved_api_key() or "").strip()
    if not key:
        raise MissingApiKeyError("Video")
    return {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _output_dir() -> Path:
    _VIDEO_OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    return _VIDEO_OUTPUTS_DIR


def _build_api_url(path: str, base_url: str | None = None) -> str:
    """拼接完整 API URL，自动处理 /v1 前缀去重。

    例: base=https://newapi.aifusion6.cn/v1, path=/v1/video/generations
    → https://newapi.aifusion6.cn/v1/video/generations
    """
    base = (base_url or _resolved_base_url()).rstrip("/")
    normalized = "/" + path.lstrip("/")
    if base.endswith("/v1") and normalized.startswith("/v1/"):
        normalized = normalized[3:]
    return f"{base}{normalized}"


def _resolution_from(aspect_ratio: str, size: str) -> tuple[int, int]:
    """将 aspect_ratio + size 转为实际像素宽高."""
    size_map = {
        "720P": {"long": 1280, "short": 720},
        "1080P": {"long": 1920, "short": 1080},
        "4K": {"long": 3840, "short": 2160},
    }
    dims = size_map.get(size, size_map["720P"])
    if aspect_ratio == "9:16":
        return dims["short"], dims["long"]
    if aspect_ratio == "1:1":
        return dims["short"], dims["short"]
    if aspect_ratio == "4:3":
        return 960 if size == "720P" else 1440 if size == "1080P" else 2880, dims["short"]
    if aspect_ratio == "3:4":
        return dims["short"], 960 if size == "720P" else 1440 if size == "1080P" else 2880
    if aspect_ratio == "3:2":
        return 1080 if size == "720P" else 1620 if size == "1080P" else 3240, dims["short"]
    if aspect_ratio == "2:3":
        return dims["short"], 1080 if size == "720P" else 1620 if size == "1080P" else 3240
    return dims["long"], dims["short"]


def extract_video_url(payload: dict) -> str:
    """从 New API 查询响应中提取视频下载 URL。

    New API 标准响应格式:
      {"task_id":"...", "status":"completed", "url":"https://...", "format":"mp4", ...}
    同时兼容旧的嵌套格式。
    """
    # New API 标准: 顶层 url 字段
    if isinstance(payload.get("url"), str) and payload["url"].strip():
        return payload["url"].strip()
    # 旧格式兼容
    if isinstance(payload.get("video_url"), str) and payload["video_url"].strip():
        return payload["video_url"].strip()
    data = payload.get("data") or payload.get("video") or {}
    if isinstance(data, dict):
        if isinstance(data.get("url"), str) and data["url"].strip():
            return data["url"].strip()
        if isinstance(data.get("video_url"), str) and data["video_url"].strip():
            return data["video_url"].strip()
        nested = data.get("data") or {}
        if isinstance(nested, dict):
            if isinstance(nested.get("url"), str) and nested["url"].strip():
                return nested["url"].strip()
            if isinstance(nested.get("video_url"), str) and nested["video_url"].strip():
                return nested["video_url"].strip()
    # New API 失败时的 error 对象
    error = payload.get("error") or {}
    if isinstance(error, dict) and error.get("message"):
        return ""
    return ""


async def create_video_job(
    *,
    model: str = "",
    prompt: str,
    aspect_ratio: str = "16:9",
    size: str = "720P",
    duration_seconds: int = 5,
    images: list[str] | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
) -> dict:
    """创建视频生成任务 (POST /v1/video/generations)."""
    if not prompt.strip():
        raise ValueError("prompt 不能为空")

    model = model or _resolved_model()
    if aspect_ratio not in ALLOWED_ASPECT_RATIOS:
        aspect_ratio = "16:9"
    if size not in ALLOWED_SIZES:
        size = "720P"

    width, height = _resolution_from(aspect_ratio, size)
    headers = _auth_headers(api_key)
    url = _build_api_url("/v1/video/generations", base_url=base_url)

    payload: dict = {
        "model": model,
        "prompt": prompt.strip(),
        "width": width,
        "height": height,
        "duration": max(4, duration_seconds),
        "n": 1,
    }
    if images:
        payload["image"] = images[0]
        if len(images) > 1:
            payload["image_urls"] = images

    last_err: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logger.info(
                "[video] 提交任务: model=%s prompt_len=%d %dx%d dur=%ds (尝试 %s/%s)",
                model, len(prompt), width, height, duration_seconds, attempt, MAX_RETRIES,
            )
            async with httpx.AsyncClient(timeout=_timeout(connect=30, read=120, write=30)) as client:
                response = await client.post(url, json=payload, headers=headers)

            if response.is_success:
                data = response.json()
                logger.info("[video] 任务提交成功: task_id=%s status=%s",
                            data.get("task_id", ""), data.get("status", ""))
                return data  # {task_id, status}

            status = response.status_code
            body_text = response.text[:500]
            logger.warning("[video] 提交失败 HTTP %s: %s", status, body_text)

            if status == 401:
                raise MissingApiKeyError("Video API Key 无效或未配置")
            if status == 429 or status >= 500:
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(RETRY_DELAY)
                    continue
            raise RuntimeError(f"视频 API 返回错误 (HTTP {status}): {body_text}")
        except httpx.TimeoutException as exc:
            last_err = exc
            if attempt < MAX_RETRIES:
                await asyncio.sleep(RETRY_DELAY)
        except httpx.TransportError as exc:
            last_err = exc
            if attempt < MAX_RETRIES:
                await asyncio.sleep(RETRY_DELAY)

    raise RuntimeError(f"视频任务提交失败，已重试 {MAX_RETRIES} 次") from last_err


async def query_video_job(
    job_id: str,
    *,
    api_key: str | None = None,
    base_url: str | None = None,
) -> dict:
    """查询视频生成任务状态 (GET /v1/video/generations/{task_id})."""
    if not job_id.strip():
        raise ValueError("job_id 不能为空")

    headers = _auth_headers(api_key)
    url = _build_api_url(f"/v1/video/generations/{job_id}", base_url=base_url)

    try:
        async with httpx.AsyncClient(timeout=_timeout(connect=15, read=30, write=15)) as client:
            response = await client.get(url, headers=headers)

        if response.is_success:
            raw = response.json()
            data = raw.get("data") if isinstance(raw, dict) and isinstance(raw.get("data"), dict) else raw
            nested = data.get("data") if isinstance(data, dict) and isinstance(data.get("data"), dict) else {}
            normalized = dict(data) if isinstance(data, dict) else {}
            if isinstance(nested, dict):
                for key in ("url", "video_url", "progress", "status", "seconds", "size", "model", "id", "created_at"):
                    if key in nested and key not in normalized:
                        normalized[key] = nested[key]
                if "status" in nested:
                    normalized["upstream_status"] = nested.get("upstream_status") or nested.get("status")
            if "task_id" not in normalized:
                normalized["task_id"] = job_id
            if "status" not in normalized:
                normalized["status"] = normalized.get("upstream_status") or "unknown"
            logger.info("[video] 查询成功: job=%s status=%s", job_id, normalized.get("status", ""))
            return normalized

        status = response.status_code
        body_text = response.text[:300]
        logger.warning("[video] 查询失败 HTTP %s: %s", status, body_text)
        if status == 401:
            raise MissingApiKeyError("Video API Key 无效")
        if status == 404:
            return {"task_id": job_id, "status": "not_found"}
        return {"task_id": job_id, "status": "unknown", "error": body_text}
    except httpx.TimeoutException:
        return {"task_id": job_id, "status": "unknown", "error": "timeout"}
    except httpx.TransportError as exc:
        return {"task_id": job_id, "status": "unknown", "error": str(exc)}


async def download_video(
    video_url: str,
    *,
    shot_id: int,
    job_id: str,
    api_key: str | None = None,
    output_dir: Path | None = None,
) -> str:
    """从 video_url 下载视频文件到本地."""
    if not video_url.strip():
        raise ValueError("video_url 不能为空")

    output_dir = output_dir or _output_dir()
    shot_dir = output_dir / f"shot_{shot_id}"
    shot_dir.mkdir(parents=True, exist_ok=True)

    ext = ".mp4"
    if video_url.lower().endswith(".webm"):
        ext = ".webm"
    output_path = shot_dir / f"{job_id}{ext}"

    if output_path.exists():
        return str(output_path)

    last_err: Exception | None = None
    for attempt in range(1, DOWNLOAD_RETRIES + 1):
        try:
            async with httpx.AsyncClient(
                timeout=_timeout(connect=30, read=600, write=30),
                follow_redirects=True,
            ) as client:
                response = await client.get(video_url)
            if response.is_success:
                output_path.write_bytes(response.content)
                logger.info("[video] 下载完成: %s -> %s", job_id, output_path)
                return str(output_path)
            if attempt < DOWNLOAD_RETRIES:
                await asyncio.sleep(DOWNLOAD_RETRY_DELAY)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last_err = exc
            if attempt < DOWNLOAD_RETRIES:
                await asyncio.sleep(DOWNLOAD_RETRY_DELAY)

    raise RuntimeError(f"视频下载失败，已重试 {DOWNLOAD_RETRIES} 次") from last_err


def get_supported_models() -> list[dict]:
    return [
        {"key": key, "name": value["name"], "supports_image": value["supports_image"]}
        for key, value in SUPPORTED_MODELS.items()
    ]
