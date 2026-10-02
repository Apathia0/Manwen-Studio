"""Video provider abstraction layer.

Routes video generation requests to the unified video API.
All models are passed through without whitelist validation.
"""
import logging
from typing import Any

from . import video_generation
from .video_adapter import VIDEO_ADAPTER_LINGDONG

logger = logging.getLogger(__name__)


async def submit(
    provider: str,
    model: str,
    prompt: str,
    negative_prompt: str | None,
    duration_seconds: int,
    aspect_ratio: str,
    reference_images: list[str] | None = None,
    seed: int | None = None,
    input_mode: str = "text_to_video",
    api_key: str | None = None,
    base_url: str | None = None,
    adapter_type: str = VIDEO_ADAPTER_LINGDONG,
) -> dict[str, Any]:
    return await video_generation.submit_video_job(
        shot_id=0,
        provider=provider,
        model=model,
        prompt=prompt,
        negative_prompt=negative_prompt or "",
        duration_seconds=duration_seconds,
        aspect_ratio=aspect_ratio,
        reference_images=reference_images,
        seed=seed,
        input_mode=input_mode,
        api_key=api_key,
        base_url=base_url,
        adapter_type=adapter_type,
    )


async def query_status(
    provider: str,
    provider_job_id: str,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    adapter_type: str = VIDEO_ADAPTER_LINGDONG,
) -> dict[str, Any]:
    return await video_generation.query_job_status(
        provider=provider,
        provider_job_id=provider_job_id,
        api_key=api_key,
        base_url=base_url,
        model=model,
        adapter_type=adapter_type,
    )


async def fetch_result(
    provider: str,
    provider_job_id: str,
    shot_id: int,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    adapter_type: str = VIDEO_ADAPTER_LINGDONG,
) -> dict[str, Any]:
    return await video_generation.fetch_job_result(
        provider=provider,
        provider_job_id=provider_job_id,
        shot_id=shot_id,
        api_key=api_key,
        base_url=base_url,
        model=model,
        adapter_type=adapter_type,
    )
