"""Video provider abstraction layer.

Routes video generation requests to xbyapp.com's unified video API.
All providers (Veo, Grok, etc.) are accessed through the same endpoint.
"""
import logging
from typing import Any

from . import video_api, video_generation

logger = logging.getLogger(__name__)

# 从 video_api 的 SUPPORTED_MODELS 同步构造供应商注册表
PROVIDER_REGISTRY: dict[str, dict[str, Any]] = {}
for key, info in video_api.SUPPORTED_MODELS.items():
    PROVIDER_REGISTRY[key] = {
        "name": info["name"],
        "supports": ["text_to_video"],
        "default_model": key,
    }
    if info["supports_image"]:
        PROVIDER_REGISTRY[key]["supports"].append("image_to_video")


async def submit(
    provider: str,
    model: str,
    prompt: str,
    negative_prompt: str | None,
    duration_seconds: int,
    aspect_ratio: str,
    reference_images: list[str] | None = None,
    seed: int | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
) -> dict[str, Any]:
    if provider not in PROVIDER_REGISTRY:
        raise ValueError(f"不支持的视频供应商: {provider}")

    return await video_generation.submit_video_job(
        shot_id=0,
        provider=provider,
        model=model or PROVIDER_REGISTRY[provider]["default_model"],
        prompt=prompt,
        negative_prompt=negative_prompt or "",
        duration_seconds=duration_seconds,
        aspect_ratio=aspect_ratio,
        reference_images=reference_images,
        seed=seed,
        api_key=api_key,
        base_url=base_url,
    )


async def query_status(
    provider: str,
    provider_job_id: str,
    api_key: str | None = None,
    base_url: str | None = None,
) -> dict[str, Any]:
    return await video_generation.query_job_status(provider, provider_job_id, api_key, base_url)


async def fetch_result(
    provider: str,
    provider_job_id: str,
    shot_id: int,
    api_key: str | None = None,
    base_url: str | None = None,
) -> dict[str, Any]:
    return await video_generation.fetch_job_result(provider, provider_job_id, shot_id, api_key, base_url)


def get_supported_providers() -> list[dict[str, Any]]:
    return [
        {"key": k, **v}
        for k, v in PROVIDER_REGISTRY.items()
    ]
