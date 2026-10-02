from __future__ import annotations

from . import openai_video, video_api


VIDEO_ADAPTER_OPENAI = "openai_video"
VIDEO_ADAPTER_LINGDONG = "lingdong_video"
SUPPORTED_VIDEO_ADAPTERS = frozenset({VIDEO_ADAPTER_OPENAI, VIDEO_ADAPTER_LINGDONG})

_VIDEO_STATUS_MAP = {
    "queued": "queued",
    "pending": "queued",
    "not_start": "queued",
    "submitted": "queued",
    "in_progress": "in_progress",
    "processing": "in_progress",
    "running": "in_progress",
    "completed": "completed",
    "succeeded": "completed",
    "success": "completed",
    "failed": "failed",
    "failure": "failed",
    "cancelled": "failed",
    "canceled": "failed",
    "not_found": "failed",
}


def normalize_video_adapter_type(
    adapter_type: str | None,
    *,
    legacy_default: bool = False,
) -> str:
    """规范化视频适配器类型，历史空值仅在显式允许时回退。"""
    normalized = str(adapter_type or "").strip()
    if not normalized and legacy_default:
        return VIDEO_ADAPTER_LINGDONG
    if normalized not in SUPPORTED_VIDEO_ADAPTERS:
        raise ValueError("视频适配器仅支持 openai_video 或 lingdong_video")
    return normalized


def _normalize_job_status(result: dict[str, object]) -> dict[str, object]:
    """将供应商状态收敛为稳定的四态，同时保留原始状态。"""
    normalized = dict(result)
    upstream_status = str(result.get("upstream_status") or result.get("status") or "").strip()
    status = _VIDEO_STATUS_MAP.get(upstream_status.lower())
    normalized["upstream_status"] = upstream_status
    if status is None:
        normalized["status"] = "failed"
        normalized["error"] = f"视频上游返回未知任务状态: {upstream_status or '<empty>'}"
        normalized["retryable"] = False
    else:
        normalized["status"] = status
    return normalized


def _openai_video_config(
    video_capabilities: dict[str, object] | None,
    *,
    aspect_ratio: str,
    size: str,
    duration_seconds: int,
    reference_count: int,
) -> str:
    capabilities = video_capabilities if isinstance(video_capabilities, dict) else {}
    if "payload_profile" in capabilities:
        raise ValueError("OpenAI 视频适配器不支持 payload_profile")
    limits = capabilities.get("limits")
    if not isinstance(limits, dict):
        raise ValueError("OpenAI 视频模型必须配置 limits")
    input_modes = capabilities.get("input_modes")
    if input_modes is not None:
        if not isinstance(input_modes, list):
            raise ValueError("OpenAI 视频模型输入模式配置无效")
        requested_modes = (
            {"image", "image_to_video"}
            if reference_count
            else {"text", "text_to_video"}
        )
        if not any(isinstance(mode, str) and mode in requested_modes for mode in input_modes):
            raise ValueError("当前 OpenAI 视频模型不支持该输入模式")
    duration_limit = limits.get("duration_seconds")
    allowed = duration_limit.get("allowed") if isinstance(duration_limit, dict) else None
    if not isinstance(allowed, list) or duration_seconds not in allowed:
        raise ValueError("当前 OpenAI 视频模型不支持该时长")
    max_references = limits.get("max_reference_images", 1)
    if not isinstance(max_references, int) or max_references < 0 or max_references > 1:
        raise ValueError("OpenAI 视频模型最多支持一张参考图")
    if reference_count > max_references:
        raise ValueError("OpenAI 视频原生接口最多一张参考图")
    wire = capabilities.get("wire")
    if not isinstance(wire, dict) or set(wire) != {"size_by_resolution_aspect"}:
        raise ValueError("OpenAI 视频模型 wire 仅支持 size_by_resolution_aspect")
    mapping = wire.get("size_by_resolution_aspect")
    mapped_size = mapping.get(f"{size}|{aspect_ratio}") if isinstance(mapping, dict) else None
    if not isinstance(mapped_size, str) or not mapped_size.strip():
        raise ValueError(f"OpenAI 视频模型未配置 {size}|{aspect_ratio} 的上游 size")
    return mapped_size.strip()


async def create_video_job(
    *,
    adapter_type: str,
    model: str,
    prompt: str,
    aspect_ratio: str,
    size: str,
    duration_seconds: int,
    images: list[str] | None,
    api_key: str | None,
    base_url: str | None,
    video_capabilities: dict[str, object] | None,
    input_mode: str | None = None,
    seed: int | None = None,
    audios: list[str] | None = None,
) -> dict[str, object]:
    """仅依据 adapter_type 将规范化请求分发给具体视频协议。"""
    adapter = normalize_video_adapter_type(adapter_type)
    if adapter == VIDEO_ADAPTER_LINGDONG:
        result = await video_api.create_video_job(
            model=model,
            prompt=prompt,
            aspect_ratio=aspect_ratio,
            size=size,
            duration_seconds=duration_seconds,
            images=images,
            input_mode=input_mode,
            seed=seed,
            api_key=api_key,
            base_url=base_url,
            video_capabilities=video_capabilities,
            audios=audios or None,
        )
        return _normalize_job_status(result)

    if audios:
        raise ValueError("当前视频协议不支持音频参考，请更换支持音频参考的视频模型")
    references = list(images or [])
    wire_size = _openai_video_config(
        video_capabilities,
        aspect_ratio=aspect_ratio,
        size=size,
        duration_seconds=duration_seconds,
        reference_count=len(references),
    )
    public_references = await video_api.prepare_video_reference_urls(references)
    result = await openai_video.create_video_job(
        model=model,
        prompt=prompt,
        duration_seconds=duration_seconds,
        wire_size=wire_size,
        image_url=public_references[0] if public_references else None,
        api_key=api_key,
        base_url=base_url,
    )
    return _normalize_job_status(dict(result))


async def query_video_job(
    job_id: str,
    *,
    adapter_type: str,
    api_key: str | None,
    base_url: str | None,
    model: str | None = None,
) -> dict[str, object]:
    """仅依据 adapter_type 查询对应协议的任务状态。"""
    adapter = normalize_video_adapter_type(adapter_type)
    if adapter == VIDEO_ADAPTER_LINGDONG:
        result = await video_api.query_video_job(
            job_id,
            api_key=api_key,
            base_url=base_url,
            model=model,
        )
        return _normalize_job_status(result)
    result = await openai_video.query_video_job(job_id, api_key=api_key, base_url=base_url)
    return _normalize_job_status(dict(result))


async def materialize_video_job(
    *,
    adapter_type: str,
    job_id: str,
    query_result: dict[str, object],
    shot_id: int,
    api_key: str | None,
    base_url: str | None,
) -> str:
    """下载或物化对应适配器的完成任务结果。"""
    adapter = normalize_video_adapter_type(adapter_type)
    if adapter == VIDEO_ADAPTER_OPENAI:
        return await openai_video.download_video_content(
            job_id,
            shot_id=shot_id,
            api_key=api_key,
            base_url=base_url,
        )
    video_url = video_api.extract_video_url(query_result)
    if not video_url:
        raise ValueError("Lingdong 视频任务响应缺少结果 URL")
    return await video_api.download_video(
        video_url,
        shot_id=shot_id,
        job_id=job_id,
        api_key=api_key,
        base_url=base_url,
    )
