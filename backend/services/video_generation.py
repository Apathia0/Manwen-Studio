"""Service layer for video generation task management."""
import logging
from typing import Any

from . import video_api

logger = logging.getLogger(__name__)

_STATUS_MAP = {
    "queued": "running",
    "in_progress": "running",
    "running": "running",
    "completed": "succeeded",
    "succeeded": "succeeded",
    "failed": "failed",
    "not_found": "failed",
}


def _map_status(provider_status: str) -> str:
    return _STATUS_MAP.get(provider_status, "queued")


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
) -> dict[str, Any]:
    """提交视频生成任务到 New API，返回 provider_job_id。"""
    try:
        result = await video_api.create_video_job(
            model=model or video_api.DEFAULT_MODEL,
            prompt=prompt,
            aspect_ratio=aspect_ratio or "16:9",
            duration_seconds=duration_seconds,
            api_key=api_key,
        )
        # New API 创建响应: {task_id, status}
        provider_job_id = result.get("task_id", "")
        status = _map_status(result.get("status", "queued"))
        logger.info(
            "Video job submitted: shot=%s provider=%s job_id=%s status=%s",
            shot_id, provider, provider_job_id, status,
        )
        return {
            "provider_job_id": provider_job_id,
            "status": status,
            "progress": 0,
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
    """查询视频任务在 New API 的实时状态。"""
    if not provider_job_id:
        return {"status": "failed", "progress": 0}

    try:
        result = await video_api.query_video_job(
            job_id=provider_job_id,
            api_key=api_key,
        )
        provider_status = result.get("status", "unknown")
        status = _map_status(provider_status)
        # New API 完成响应: {task_id, status, url, format, metadata, error?}
        video_url = video_api._extract_video_url(result)

        progress = 0
        if status in ("running",):
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
    """获取已完成视频任务的结果，下载视频到本地。"""
    try:
        result = await video_api.query_video_job(
            job_id=provider_job_id,
            api_key=api_key,
        )
        video_url = video_api._extract_video_url(result)

        if not video_url:
            logger.warning("No video URL for job %s", provider_job_id)
            return {
                "video_path": "",
                "thumbnail_path": "",
                "duration_seconds": 0,
                "resolution": "1280x720",
            }

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
