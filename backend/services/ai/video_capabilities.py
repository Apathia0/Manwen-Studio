from __future__ import annotations

from typing import Any

from fastapi import HTTPException


def validate_video_capability_limits(
    video_capabilities: dict[str, Any] | None,
    *,
    resolution: str | None = None,
    duration_seconds: float | int | None = None,
) -> None:
    """校验视频模型的必填限制及请求的清晰度、时长。"""
    if not isinstance(video_capabilities, dict):
        raise HTTPException(400, "当前视频模型缺少 capabilities，无法确认清晰度与时长限制")
    limits = video_capabilities.get("limits")
    if not isinstance(limits, dict):
        raise HTTPException(400, "当前视频模型必须配置完整 limits")

    if resolution is not None:
        resolutions = limits.get("resolutions")
        if (
            not isinstance(resolutions, list)
            or not resolutions
            or not all(isinstance(item, str) and item.strip() for item in resolutions)
        ):
            raise HTTPException(400, "当前视频模型 limits.resolutions 必须是非空字符串数组")
        if resolution not in resolutions:
            raise HTTPException(400, "当前视频模型不支持该清晰度")

    duration_limit = limits.get("duration_seconds")
    if not isinstance(duration_limit, dict):
        raise HTTPException(400, "当前视频模型必须配置 duration_seconds.allowed 或合法 min/max")
    allowed = duration_limit.get("allowed")
    has_allowed = (
        isinstance(allowed, list)
        and bool(allowed)
        and all(isinstance(item, int) and not isinstance(item, bool) and item > 0 for item in allowed)
    )
    minimum, maximum = duration_limit.get("min"), duration_limit.get("max")
    has_range = (
        isinstance(minimum, int)
        and not isinstance(minimum, bool)
        and minimum > 0
        and isinstance(maximum, int)
        and not isinstance(maximum, bool)
        and maximum >= minimum
    )
    if has_allowed and (minimum is not None or maximum is not None):
        raise HTTPException(400, "视频模型时长请配置 allowed 或 min/max 其中一种")
    if not has_allowed and not has_range:
        raise HTTPException(400, "当前视频模型必须配置 duration_seconds.allowed 或合法 min/max")
    if duration_seconds is None:
        return
    if (
        isinstance(duration_seconds, bool)
        or not isinstance(duration_seconds, (int, float))
        or not float(duration_seconds).is_integer()
        or duration_seconds <= 0
    ):
        raise HTTPException(400, "视频时长必须是正整数秒")
    if has_allowed and duration_seconds not in allowed:
        raise HTTPException(400, "当前视频模型不支持该时长")
    if has_range and (duration_seconds < minimum or duration_seconds > maximum):
        raise HTTPException(400, "视频时长超出当前模型限制")
