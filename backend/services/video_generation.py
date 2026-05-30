"""Service layer for video generation task management."""
import logging
from typing import Any

from . import video_api
from . import video_comfyui

logger = logging.getLogger(__name__)


def _parse_progress(raw: Any) -> int:
    """安全解析 progress 字段，兼容 '0%' 字符串格式和数字格式。"""
    if raw is None:
        return 0
    if isinstance(raw, (int, float)):
        return int(raw)
    if isinstance(raw, str):
        cleaned = raw.strip().rstrip("%").strip()
        try:
            return int(cleaned) if cleaned else 0
        except ValueError:
            return 0
    return 0

_STATUS_MAP = {
    "pending": "queued",
    "queued": "running",
    "submitted": "running",
    "processing": "running",
    "in_progress": "running",
    "running": "running",
    "done": "succeeded",
    "success": "succeeded",
    "completed": "succeeded",
    "succeeded": "succeeded",
    "failed": "failed",
    "error": "failed",
    "cancelled": "cancelled",
    "canceled": "cancelled",
    "not_found": "failed",
}


def _map_status(provider_status: str) -> str:
    normalized = str(provider_status or "").strip().lower()
    return _STATUS_MAP.get(normalized, "queued")


async def submit_video_job(
    shot_id: int,
    provider: str,
    model: str,
    prompt: str,
    negative_prompt: str,
    duration_seconds: int,
    aspect_ratio: str,
    reference_images: list[str] | None = None,
    seed: int | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    input_mode: str = "text_to_video",
    **kwargs,
) -> dict[str, Any]:
    """提交视频生成任务，根据 provider 分发到不同后端。

    支持:
      - comfyui → 本地 ComfyUI
      - 其他 (sora/mock 等) → New API (api.xbyjs.top)
    """
    try:
        if provider == "comfyui":
            result = await video_comfyui.submit_job(
                input_mode=input_mode,
                prompt=prompt,
                model=model,
                reference_images=reference_images,
                duration_seconds=duration_seconds,
                base_url=base_url,
            )
        else:
            result = await video_api.create_video_job(
                model=model or video_api._resolved_model(),
                prompt=prompt,
                aspect_ratio=aspect_ratio or "16:9",
                duration_seconds=duration_seconds,
                images=reference_images,
                api_key=api_key,
                base_url=base_url,
            )
            result["provider_job_id"] = result.get("task_id", "")

        provider_job_id = result.get("provider_job_id", "")
        status = _map_status(result.get("status", "queued"))
        progress = _parse_progress(result.get("progress"))
        logger.info(
            "Video job submitted: shot=%s provider=%s model=%s job_id=%s status=%s",
            shot_id, provider, model, provider_job_id, status,
        )
        return {
            "provider_job_id": provider_job_id,
            "status": status,
            "progress": progress,
            "provider_status": result.get("status", ""),
            "enhanced_prompt": result.get("enhanced_prompt", ""),
        }
    except Exception as exc:
        logger.error("Failed to submit video job for shot %s: %s", shot_id, exc)
        return {
            "provider_job_id": "",
            "status": "failed",
            "progress": 0,
            "error": str(exc),
        }


async def query_job_status(
    provider: str,
    provider_job_id: str,
    api_key: str | None = None,
    base_url: str | None = None,
) -> dict[str, Any]:
    """查询视频任务状态，根据 provider 分发到不同后端。"""
    if not provider_job_id:
        return {"status": "failed", "progress": 0}

    try:
        if provider == "comfyui":
            result = await video_comfyui.query_job(
                provider_job_id=provider_job_id,
                base_url=base_url,
            )
        else:
            result = await video_api.query_video_job(
                job_id=provider_job_id,
                api_key=api_key,
                base_url=base_url,
            )
            result["video_url"] = video_api.extract_video_url(result)

        provider_status = result.get("status", "unknown")
        status = _map_status(provider_status)
        video_url = result.get("video_url", "")

        progress = _parse_progress(result.get("progress"))
        if progress == 0 and status == "running":
            progress = 50
        elif status == "succeeded":
            progress = 100

        logger.info(
            "Job query: %s -> provider=%s our=%s url=%s",
            provider_job_id, provider_status, status,
            bool(video_url),
        )
        return {
            "status": status,
            "progress": progress,
            "video_url": video_url,
            "provider_status": provider_status,
            "enhanced_prompt": result.get("enhanced_prompt", ""),
            "error": result.get("error", ""),
        }
    except Exception as exc:
        logger.error("Failed to query job %s: %s", provider_job_id, exc)
        return {"status": "failed", "progress": 0, "error": str(exc)}


async def fetch_job_result(
    provider: str,
    provider_job_id: str,
    shot_id: int,
    api_key: str | None = None,
    base_url: str | None = None,
) -> dict[str, Any]:
    """获取已完成视频任务的结果，根据 provider 分发下载。"""
    try:
        if provider == "comfyui":
            result = await video_comfyui.query_job(
                provider_job_id=provider_job_id,
                base_url=base_url,
            )
            video_url = result.get("video_url", "")
        else:
            result = await video_api.query_video_job(
                job_id=provider_job_id,
                api_key=api_key,
                base_url=base_url,
            )
            video_url = video_api.extract_video_url(result)

        if not video_url:
            logger.warning("No video URL for job %s", provider_job_id)
            return {
                "video_path": "",
                "thumbnail_path": "",
                "duration_seconds": 0,
                "resolution": "1280x720",
            }

        if provider == "comfyui":
            local_path = await video_comfyui.download_video(
                video_url=video_url,
                shot_id=shot_id,
                job_id=provider_job_id,
            )
        else:
            local_path = await video_api.download_video(
                video_url=video_url,
                shot_id=shot_id,
                job_id=provider_job_id,
                api_key=api_key,
            )

        logger.info(
            "Video result fetched: shot=%s job=%s local=%s",
            shot_id, provider_job_id, local_path,
        )
        return {
            "video_path": local_path,
            "thumbnail_path": "",
            "duration_seconds": 0,
            "resolution": "1280x720",
        }
    except Exception as exc:
        logger.error("Failed to fetch job result %s: %s", provider_job_id, exc)
        return {
            "video_path": "",
            "thumbnail_path": "",
            "duration_seconds": 0,
            "resolution": "1280x720",
        }
