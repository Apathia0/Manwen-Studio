"""Service layer for video generation task management."""
import logging
from typing import Any

from . import video_adapter, video_api
from . import video_comfyui
from .errors import MissingApiKeyError, UpstreamServiceError, public_error_message
from .media_logging import safe_media_url_for_log

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
    "failure": "failed",
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
    input_mode: str | None = None,
    video_capabilities: dict[str, Any] | None = None,
    adapter_type: str = video_adapter.VIDEO_ADAPTER_LINGDONG,
    reference_audios: list[str] | None = None,
    **kwargs,
) -> dict[str, Any]:
    """提交视频生成任务，根据 provider 分发到不同后端。

    支持:
      - comfyui → 本地 ComfyUI
      - 其他 → New API 兼容端点
    """
    input_mode = input_mode or ("image_to_video" if reference_images else "text_to_video")
    if provider == "comfyui":
        if reference_audios:
            raise ValueError("ComfyUI 视频通道不支持音频参考")
        result = await video_comfyui.submit_job(
            input_mode=input_mode,
            prompt=prompt,
            model=model,
            reference_images=reference_images,
            seed=seed,
            duration_seconds=duration_seconds,
            base_url=base_url,
        )
    else:
        defaults = video_capabilities.get("defaults") if isinstance(video_capabilities, dict) else None
        default_resolution = defaults.get("resolution") if isinstance(defaults, dict) else None
        result = await video_adapter.create_video_job(
            adapter_type=adapter_type,
            model=model or video_api._resolved_model(),
            prompt=prompt,
            aspect_ratio=aspect_ratio or "16:9",
            size=str(kwargs.get("size") or default_resolution or "720P"),
            duration_seconds=duration_seconds,
            images=reference_images or None,
            input_mode=input_mode,
            seed=seed,
            api_key=api_key,
            base_url=base_url,
            video_capabilities=video_capabilities,
            audios=reference_audios or None,
        )
        result["provider_job_id"] = (
            result.get("provider_job_id") or result.get("task_id") or result.get("id") or ""
        )

    provider_job_id = str(result.get("provider_job_id", "") or "").strip()
    provider_status = str(result.get("status", "queued"))
    status = _map_status(provider_status)
    if status in {"failed", "cancelled"} or not provider_job_id:
        error = str(result.get("error") or result.get("message") or "视频上游未返回有效任务 ID")
        raise UpstreamServiceError(
            error,
            retryable=status != "cancelled",
            provider=provider,
        )

    progress = _parse_progress(result.get("progress"))
    logger.info(
        "Video job submitted: shot=%s provider=%s model=%s job_id=%s status=%s",
        shot_id, provider, model, provider_job_id, status,
    )
    return {
        "provider_job_id": provider_job_id,
        "status": status,
        "progress": progress,
        "provider_status": provider_status,
        "enhanced_prompt": result.get("enhanced_prompt", ""),
    }


async def query_job_status(
    provider: str,
    provider_job_id: str,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    adapter_type: str = video_adapter.VIDEO_ADAPTER_LINGDONG,
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
            result = await video_adapter.query_video_job(
                provider_job_id,
                adapter_type=adapter_type,
                api_key=api_key,
                base_url=base_url,
                model=model,
            )
            if str(result.get("status", "")).upper() in ("SUCCESS", "COMPLETED", "SUCCEEDED"):
                raw_data = result.get("data")
                data_url = (
                    video_api.extract_video_url(raw_data)
                    if isinstance(raw_data, dict)
                    else ""
                )
                logger.info(
                    "[video] 完成响应 keys=%s url=%s video_url=%s data_url=%s",
                    list(result.keys()),
                    safe_media_url_for_log(result.get("url", "")),
                    safe_media_url_for_log(result.get("video_url", "")),
                    safe_media_url_for_log(data_url),
                )
            result["video_url"] = video_api.extract_video_url(result)

        provider_status = str(result.get("status", "unknown"))
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
    except MissingApiKeyError as exc:
        logger.error("Failed to query job %s: %s", provider_job_id, exc)
        return {"status": "failed", "progress": 0, "error": public_error_message(exc, "视频服务配置缺失，请联系管理员")}
    except UpstreamServiceError as exc:
        log = logger.warning if exc.retryable else logger.error
        log("Failed to query job %s: %s", provider_job_id, exc)
        return {
            "status": "queued" if exc.retryable else "failed",
            "progress": 0,
            "provider_status": "query_error",
            "error": public_error_message(exc, "视频状态查询失败，请稍后重试"),
        }
    except Exception as exc:
        logger.warning("Transient query failure for job %s: %s", provider_job_id, exc)
        return {
            "status": "queued",
            "progress": 0,
            "provider_status": "query_error",
            "error": public_error_message(exc, "视频状态查询失败，正在自动重试"),
        }


async def fetch_job_result(
    provider: str,
    provider_job_id: str,
    shot_id: int,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    adapter_type: str = video_adapter.VIDEO_ADAPTER_LINGDONG,
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
            result = await video_adapter.query_video_job(
                provider_job_id,
                adapter_type=adapter_type,
                api_key=api_key,
                base_url=base_url,
                model=model,
            )
            video_url = video_api.extract_video_url(result)

        if provider != "comfyui" and adapter_type == video_adapter.VIDEO_ADAPTER_OPENAI:
            local_path = await video_adapter.materialize_video_job(
                adapter_type=adapter_type,
                job_id=provider_job_id,
                query_result=result,
                shot_id=shot_id,
                api_key=api_key,
                base_url=base_url,
            )
        elif not video_url:
            logger.warning("No video URL for job %s", provider_job_id)
            return {
                "video_path": "",
                "thumbnail_path": "",
                "duration_seconds": 0,
                "resolution": "1280x720",
            }

        elif provider == "comfyui":
            local_path = await video_comfyui.download_video(
                video_url=video_url,
                shot_id=shot_id,
                job_id=provider_job_id,
            )
        else:
            local_path = await video_adapter.materialize_video_job(
                adapter_type=adapter_type,
                job_id=provider_job_id,
                query_result=result,
                shot_id=shot_id,
                api_key=api_key,
                base_url=base_url,
            )

        logger.info(
            "Video result fetched: shot=%s job=%s local=%s",
            shot_id, provider_job_id, safe_media_url_for_log(local_path),
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
