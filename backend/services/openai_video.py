from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any, TypedDict

import httpx

from .errors import MissingApiKeyError, UpstreamServiceError


_VIDEO_OUTPUTS_DIR = Path(__file__).resolve().parent.parent / "video_outputs"
MAX_VIDEO_CONTENT_BYTES = 2 * 1024 * 1024 * 1024


def _redact_error_text(value: object, api_key: str | None) -> str:
    """清理当前密钥、Bearer 凭据和带标签的敏感值。"""
    text = str(value or "")
    key = str(api_key or "").strip()
    if key:
        text = text.replace(key, "***")
    text = re.sub(r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,;\"']+", r"\1***", text)
    text = re.sub(
        r"(?i)((?:api[_-]?key|key|token|secret)\s*[\"']?\s*[:=]\s*[\"']?)[^\s,;\"'}]+",
        r"\1***",
        text,
    )
    return text[:500]


class NormalizedVideoJob(TypedDict, total=False):
    task_id: str
    status: str
    upstream_status: str
    progress: int | float
    error: str


def _api_url(base_url: str | None, path: str) -> str:
    base = str(base_url or "").strip().rstrip("/")
    if not base:
        raise ValueError("OpenAI 视频 API 地址未配置")
    normalized = "/" + path.lstrip("/")
    if base.endswith("/v1") and normalized.startswith("/v1/"):
        normalized = normalized[3:]
    return f"{base}{normalized}"


def _headers(api_key: str | None) -> dict[str, str]:
    key = str(api_key or "").strip()
    if not key:
        raise MissingApiKeyError("OpenAI Video")
    return {"Authorization": f"Bearer {key}", "Accept": "application/json"}


def _error_message(response: httpx.Response, api_key: str | None) -> str:
    try:
        payload = response.json()
    except ValueError:
        return _redact_error_text(response.text, api_key) or "上游返回未知错误"
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict) and isinstance(error.get("message"), str):
        return _redact_error_text(error["message"], api_key)
    return _redact_error_text(error or payload, api_key)


def _raise_response_error(response: httpx.Response, api_key: str | None) -> None:
    status_code = response.status_code
    raise UpstreamServiceError(
        f"OpenAI 视频 API 返回错误 (HTTP {status_code}): {_error_message(response, api_key)}",
        retryable=status_code == 429 or status_code >= 500,
        provider="OpenAI Video",
        status_code=status_code,
    )


def _normalize_job(
    payload: Any,
    *,
    api_key: str | None,
    fallback_job_id: str | None = None,
) -> NormalizedVideoJob:
    if not isinstance(payload, dict):
        raise UpstreamServiceError(
            "OpenAI 视频 API 响应格式无效",
            retryable=False,
            provider="OpenAI Video",
        )
    job_id = str(payload.get("id") or fallback_job_id or "").strip()
    if not job_id:
        raise UpstreamServiceError(
            "OpenAI 视频 API 响应缺少任务 ID",
            retryable=False,
            provider="OpenAI Video",
        )
    upstream_status = str(payload.get("status") or "unknown").strip().lower()
    normalized: NormalizedVideoJob = {
        "task_id": job_id,
        "status": upstream_status,
        "upstream_status": upstream_status,
    }
    progress = payload.get("progress")
    if isinstance(progress, (int, float)) and not isinstance(progress, bool):
        normalized["progress"] = progress
    error = payload.get("error")
    if isinstance(error, dict) and isinstance(error.get("message"), str):
        normalized["error"] = _redact_error_text(error["message"], api_key)
    elif isinstance(error, str) and error.strip():
        normalized["error"] = _redact_error_text(error.strip(), api_key)
    return normalized


async def create_video_job(
    *,
    model: str,
    prompt: str,
    duration_seconds: int,
    wire_size: str,
    image_url: str | None,
    api_key: str | None,
    base_url: str | None,
) -> NormalizedVideoJob:
    """通过 OpenAI 官方 Videos API 创建任务。"""
    payload: dict[str, object] = {
        "model": model,
        "prompt": prompt.strip(),
        "seconds": str(duration_seconds),
        "size": wire_size,
    }
    if image_url:
        payload["input_reference"] = {"image_url": image_url}
    headers = _headers(api_key)
    headers["Content-Type"] = "application/json"
    async with httpx.AsyncClient(timeout=httpx.Timeout(300.0)) as client:
        response = await client.post(
            _api_url(base_url, "/v1/videos"),
            json=payload,
            headers=headers,
        )
    if not response.is_success:
        _raise_response_error(response, api_key)
    return _normalize_job(response.json(), api_key=api_key)


async def query_video_job(
    job_id: str,
    *,
    api_key: str | None,
    base_url: str | None,
) -> NormalizedVideoJob:
    """查询 OpenAI 官方视频任务并返回统一状态。"""
    if not job_id.strip():
        raise ValueError("job_id 不能为空")
    async with httpx.AsyncClient(timeout=httpx.Timeout(300.0)) as client:
        response = await client.get(
            _api_url(base_url, f"/v1/videos/{job_id}"),
            headers=_headers(api_key),
        )
    if not response.is_success:
        _raise_response_error(response, api_key)
    return _normalize_job(response.json(), api_key=api_key, fallback_job_id=job_id)


async def download_video_content(
    job_id: str,
    *,
    shot_id: int,
    api_key: str | None,
    base_url: str | None,
) -> str:
    """从 OpenAI 官方 content 端点下载已完成的视频。"""
    safe_job_id = re.sub(r"[^A-Za-z0-9._-]+", "_", job_id).strip("._")[:128] or uuid.uuid4().hex
    output_path = _VIDEO_OUTPUTS_DIR / f"shot_{shot_id}" / f"{safe_job_id}.mp4"
    temp_path = output_path.with_suffix(f".{uuid.uuid4().hex}.tmp")
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(600.0), follow_redirects=False) as client:
            async with client.stream(
                "GET",
                _api_url(base_url, f"/v1/videos/{job_id}/content"),
                headers=_headers(api_key),
            ) as response:
                if not response.is_success:
                    await response.aread()
                    _raise_response_error(response, api_key)
                content_length = response.headers.get("content-length")
                try:
                    declared_length = int(content_length) if content_length else 0
                except (TypeError, ValueError):
                    declared_length = 0
                if declared_length > MAX_VIDEO_CONTENT_BYTES:
                    raise UpstreamServiceError(
                        "OpenAI 视频内容超过允许的最大大小",
                        retryable=False,
                        provider="OpenAI Video",
                    )
                output_path.parent.mkdir(parents=True, exist_ok=True)
                total_bytes = 0
                with temp_path.open("wb") as output_file:
                    async for chunk in response.aiter_bytes():
                        total_bytes += len(chunk)
                        if total_bytes > MAX_VIDEO_CONTENT_BYTES:
                            raise UpstreamServiceError(
                                "OpenAI 视频内容超过允许的最大大小",
                                retryable=False,
                                provider="OpenAI Video",
                            )
                        output_file.write(chunk)
        temp_path.replace(output_path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise
    return str(output_path)
