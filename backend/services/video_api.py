"""Lingdong 视频中转 API 客户端。"""
from __future__ import annotations

import asyncio
import base64
import contextvars
import logging
import os
import re
import uuid
from pathlib import Path

import httpx
from dotenv import load_dotenv

from .ai.channels import validate_remote_media_url
from .blocking import run_blocking
from .errors import MissingApiKeyError, UpstreamServiceError
from .media_logging import safe_media_url_for_log

load_dotenv()

logger = logging.getLogger("video_api")


def _redact_upstream_text(
    value: object,
    *secrets: str | None,
    redact_labeled_secrets: bool = True,
) -> str:
    text = str(value or "")
    for secret in secrets:
        plain = str(secret or "").strip()
        if plain:
            text = text.replace(plain, "***")
    if redact_labeled_secrets:
        text = re.sub(r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,;\"']+", r"\1***", text)
        text = re.sub(r"(?i)((?:api[_-]?key|token|secret)\s*[\"']?\s*[:=]\s*[\"']?)[^\s,;\"'}]+", r"\1***", text)
    return text


def _sanitize_upstream_error(value: object, *secrets: str | None) -> str:
    """清理上游错误正文中的认证信息，并限制日志与错误展示长度。"""
    return _redact_upstream_text(value, *secrets)[:500]


def _sanitize_upstream_payload(value, *secrets: str | None, _sensitive_context: bool = False):
    """递归清理上游 JSON 中所有字符串字段的认证信息。"""
    if isinstance(value, dict):
        sanitized = {}
        for key, item in value.items():
            normalized_key = str(key).lower().replace("-", "_")
            sensitive_key = normalized_key in {
                "api_key",
                "apikey",
                "authorization",
                "debug",
                "detail",
                "error",
                "fail_reason",
                "message",
                "secret",
                "token",
            }
            sanitized[key] = _sanitize_upstream_payload(
                item,
                *secrets,
                _sensitive_context=_sensitive_context or sensitive_key,
            )
        return sanitized
    if isinstance(value, list):
        return [
            _sanitize_upstream_payload(item, *secrets, _sensitive_context=_sensitive_context)
            for item in value
        ]
    if isinstance(value, str):
        return _redact_upstream_text(
            value,
            *secrets,
            redact_labeled_secrets=_sensitive_context,
        )
    return value

_VIDEO_OUTPUTS_DIR = Path(__file__).resolve().parent.parent / "video_outputs"
_MANGA_OUTPUTS_DIR = Path(__file__).resolve().parent.parent / "manga_outputs"

# 运行时配置由调用方注入，并随当前请求或异步任务传播。
_RUNTIME_BASE_URL: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "video_runtime_base_url",
    default=None,
)
_RUNTIME_API_KEY: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "video_runtime_api_key",
    default=None,
)
_RUNTIME_MODEL: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "video_runtime_model",
    default=None,
)


def configure(*, base_url: str | None = None, api_key: str | None = None, model: str | None = None):
    """运行时注入视频 API 配置（优先于 .env 默认值）。"""
    if base_url:
        _RUNTIME_BASE_URL.set(base_url.rstrip("/"))
    if api_key:
        _RUNTIME_API_KEY.set(api_key)
    if model:
        _RUNTIME_MODEL.set(model)


def runtime_base_url() -> str:
    """返回当前请求或任务上下文中的视频 API 地址。"""
    return (_RUNTIME_BASE_URL.get() or os.getenv("VIDEO_API_BASE_URL") or "").rstrip("/")


def runtime_api_key() -> str:
    """返回当前请求或任务上下文中的视频 API Key。"""
    return (
        _RUNTIME_API_KEY.get()
        or os.getenv("VIDEO_API_KEY")
        or os.getenv("IMAGE_API_KEY")
        or ""
    ).strip()


def runtime_model() -> str:
    """返回当前请求或任务上下文中的视频模型。"""
    return _RUNTIME_MODEL.get() or os.getenv("VIDEO_MODEL") or ""


def _resolved_base_url() -> str:
    """保留旧私有入口，内部统一使用公开 accessor。"""
    return runtime_base_url()


def _resolved_api_key() -> str:
    """保留旧私有入口，内部统一使用公开 accessor。"""
    return runtime_api_key()


def _resolved_model() -> str:
    """保留旧私有入口，内部统一使用公开 accessor。"""
    return runtime_model()

MAX_RETRIES = 3
RETRY_DELAY = 5
DOWNLOAD_RETRIES = 3
DOWNLOAD_RETRY_DELAY = 3
MAX_REMOTE_VIDEO_BYTES = max(1, int(os.getenv("MAX_REMOTE_VIDEO_BYTES", str(2 * 1024 * 1024 * 1024))))



ALLOWED_ASPECT_RATIOS = ["16:9", "9:16", "1:1", "4:3", "3:4", "3:2", "2:3"]
ALLOWED_SIZES = ["720P", "1080P", "1K", "2K", "4K"]

VIDEO_PAYLOAD_PROFILE_LEGACY = "legacy_lingdong"
VIDEO_PAYLOAD_PROFILE_SEEDANCE_FAST = "seedance_fast"
VIDEO_PAYLOAD_PROFILE_SORA_V2 = "sora_v2"
_VIDEO_PAYLOAD_PROFILES = {
    VIDEO_PAYLOAD_PROFILE_LEGACY,
    VIDEO_PAYLOAD_PROFILE_SEEDANCE_FAST,
    VIDEO_PAYLOAD_PROFILE_SORA_V2,
}


def _video_capability_config(video_capabilities: dict | None) -> tuple[str | None, dict]:
    """解析受控的视频能力配置；未配置时保留旧的模型推断行为。"""
    if not isinstance(video_capabilities, dict):
        return None, {}

    profile = video_capabilities.get("payload_profile")
    if profile is None:
        return None, video_capabilities
    if not isinstance(profile, str) or profile not in _VIDEO_PAYLOAD_PROFILES:
        raise ValueError("视频模型 payload_profile 配置无效")
    return profile, video_capabilities


def _validate_video_capability_limits(
    *,
    capabilities: dict,
    aspect_ratio: str,
    size: str,
    duration_seconds: int,
    reference_count: int,
) -> int:
    """校验模型声明的输入限制，并返回经限制裁剪后的时长。"""
    limits = capabilities.get("limits")
    if not isinstance(limits, dict):
        return duration_seconds

    allowed_ratios = limits.get("aspect_ratios")
    if isinstance(allowed_ratios, list) and aspect_ratio not in allowed_ratios:
        raise ValueError("当前视频模型不支持该画面比例")

    allowed_resolutions = limits.get("resolutions")
    if isinstance(allowed_resolutions, list) and size not in allowed_resolutions:
        raise ValueError("当前视频模型不支持该清晰度")

    max_reference_images = limits.get("max_reference_images")
    if isinstance(max_reference_images, int) and max_reference_images >= 0:
        if reference_count > max_reference_images:
            raise ValueError("参考图数量超过当前视频模型限制")

    duration_limit = limits.get("duration_seconds")
    if not isinstance(duration_limit, dict):
        return duration_seconds
    allowed = duration_limit.get("allowed")
    if isinstance(allowed, list) and duration_seconds not in allowed:
        raise ValueError("当前视频模型不支持该时长")
    minimum = duration_limit.get("min")
    maximum = duration_limit.get("max")
    if isinstance(minimum, int) and duration_seconds < minimum:
        raise ValueError("视频时长低于当前模型最小限制")
    if isinstance(maximum, int) and duration_seconds > maximum:
        raise ValueError("视频时长超过当前模型最大限制")
    return duration_seconds


def _validate_video_input_mode(*, capabilities: dict, reference_count: int) -> None:
    """校验模型声明的文生或图生视频输入模式。"""
    input_modes = capabilities.get("input_modes")
    if not isinstance(input_modes, list):
        return
    requested = "image_to_video" if reference_count else "text_to_video"
    aliases = {
        "image_to_video": {"image_to_video", "image"},
        "text_to_video": {"text_to_video", "text"},
    }
    if not any(mode in aliases[requested] for mode in input_modes):
        raise ValueError("当前视频模型不支持该输入模式")


def validate_legacy_model_duration(
    *,
    model: str,
    duration_seconds: int,
    video_capabilities: dict | None = None,
) -> None:
    """校验旧模型名称推断的时长限制，禁止实际请求静默裁剪。"""
    profile, _ = _video_capability_config(video_capabilities)
    if profile is not None:
        return
    model_lower = str(model or "").lower()
    if "seedance" not in model_lower:
        return
    if any(version in model_lower for version in ("1-0", "1.0", "1-5", "1.5")):
        if duration_seconds > 12:
            raise ValueError("当前 Seedance 1.0/1.5 模型最大时长为 12 秒")


def _sora_wire_size(*, capabilities: dict, size: str, aspect_ratio: str) -> str:
    """从模型能力配置取得 Sora 上游 size，绝不臆测供应商枚举值。"""
    wire = capabilities.get("wire")
    size_by_resolution_aspect = wire.get("size_by_resolution_aspect") if isinstance(wire, dict) else None
    if not isinstance(size_by_resolution_aspect, dict):
        raise ValueError("Sora 视频模型缺少 wire.size_by_resolution_aspect 配置")
    mapped_size = size_by_resolution_aspect.get(f"{size}|{aspect_ratio}")
    if not isinstance(mapped_size, str) or not mapped_size.strip():
        raise ValueError(f"Sora 视频模型未配置 {size}|{aspect_ratio} 的上游 size")
    return mapped_size.strip()


def _wire_field(capabilities: dict, key: str, default: str, allowed: set[str]) -> str:
    """读取受白名单保护的上游字段名，避免配置注入任意请求结构。"""
    wire = capabilities.get("wire")
    value = wire.get(key, default) if isinstance(wire, dict) else default
    if not isinstance(value, str) or value not in allowed:
        raise ValueError(f"视频模型 wire.{key} 配置无效")
    return value


def _timeout(*, connect: float, read: float, write: float, pool: float = 30.0) -> httpx.Timeout:
    return httpx.Timeout(connect=connect, read=read, write=write, pool=pool)


def _auth_headers(api_key: str | None = None, base_url: str | None = None, model: str | None = None) -> dict[str, str]:
    """获取视频 API 认证头，同时校验必要配置是否已注入。"""
    effective_base_url = (base_url or runtime_base_url() or "").rstrip("/")
    if not effective_base_url:
        raise ValueError("视频 API 地址未配置，请在后台设置中配置 API 地址后重试。")
    effective_model = model or runtime_model()
    if not effective_model:
        raise ValueError("视频生成模型未配置，请在后台设置中配置模型名称后重试。")
    key = (api_key or runtime_api_key() or "").strip()
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

    例: base=https://your-api.com/v1, path=/v1/video/generations
    → https://your-api.com/v1/video/generations
    """
    base = (base_url or runtime_base_url()).rstrip("/")
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


def _aspect_to_orientation(aspect_ratio: str) -> str:
    """将 aspect_ratio（如 '16:9'、'9:16'）转为 LingDong 的 orientation 参数。"""
    parts = aspect_ratio.strip().split(":")
    if len(parts) == 2:
        try:
            w, h = int(parts[0]), int(parts[1])
            return "landscape" if w >= h else "portrait"
        except ValueError:
            pass
    return "landscape"


def _is_valid_url(s: str) -> bool:
    return s.startswith("http://") or s.startswith("https://")


async def prepare_video_reference_urls(images: list[str]) -> list[str]:
    """将参考图解析为上游可访问 URL，本地输入必须成功上传 OSS。"""
    if not images:
        return []
    oss_urls: list[str] = []
    local_paths: list[str] = []
    for image in images:
        normalized = image.strip()
        if normalized.lower().startswith(("http://", "https://")):
            oss_urls.append(normalized)
        elif normalized.startswith("/static/manga/"):
            local_paths.append(str(_MANGA_OUTPUTS_DIR / normalized[len("/static/manga/"):]))
        elif normalized.startswith("/static/video/"):
            local_paths.append(str(_VIDEO_OUTPUTS_DIR / normalized[len("/static/video/"):]))
        else:
            local_paths.append(normalized)
    if local_paths:
        from . import oss as oss_service

        if not oss_service.is_enabled():
            oss_service.auto_configure_from_db()
        if oss_service.is_enabled():
            for local_path in local_paths:
                try:
                    oss_url = await run_blocking(oss_service.upload_file, local_path)
                    if oss_url:
                        oss_urls.append(oss_url)
                        logger.info(
                            "[video] 本地参考图上 OSS 成功: %s → %s",
                            local_path,
                            safe_media_url_for_log(oss_url),
                        )
                    else:
                        logger.warning("[video] 本地参考图上 OSS 返回空: %s", local_path)
                except Exception as exc:
                    logger.warning("[video] 本地参考图上 OSS 失败: %s — %s", local_path, exc)
    if len(oss_urls) != len(images):
        raise UpstreamServiceError(
            "部分本地参考图无法上传到 OSS，已停止提交视频任务",
            retryable=False,
            provider="Video",
        )
    return oss_urls


def extract_video_url(payload: dict) -> str:
    """从 New API 查询响应中提取视频下载 URL。

    New API 标准响应格式:
      {"task_id":"...", "status":"completed", "url":"https://...", "format":"mp4", ...}
    同时兼容 Volcengine Seedance（result_url 顶层）、LingDong（data.result_url）等格式。
    注意：FAILURE 状态下 result_url 可能包含错误消息而非有效 URL，需做 http 前缀校验。
    """
    def _try(v: str) -> str | None:
        s = v.strip()
        return s if _is_valid_url(s) else None

    def _lookup(d: dict, *keys: str) -> str | None:
        for k in keys:
            val = d.get(k)
            if isinstance(val, str) and val.strip():
                return _try(val)
        return None

    # 顶层字段
    found = _lookup(payload, "url", "video_url", "result_url")
    if found:
        return found

    data = payload.get("data") or payload.get("video") or {}
    if isinstance(data, dict):
        found = _lookup(data, "result_url", "url", "video_url")
        if found:
            return found

        content = data.get("content") or {}
        if isinstance(content, dict):
            found = _lookup(content, "video_url", "url")
            if found:
                return found

        nested = data.get("data") or {}
        if isinstance(nested, dict):
            found = _lookup(nested, "url", "video_url")
            if found:
                return found

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
    video_capabilities: dict | None = None,
) -> dict:
    """创建视频生成任务 (POST /v1/videos - LingDong API)."""
    if not prompt.strip():
        raise ValueError("prompt 不能为空")

    model = model or runtime_model()
    payload_profile, capabilities = _video_capability_config(video_capabilities)
    validate_legacy_model_duration(
        model=model,
        duration_seconds=duration_seconds,
        video_capabilities=video_capabilities,
    )
    if aspect_ratio not in ALLOWED_ASPECT_RATIOS:
        aspect_ratio = "16:9"

    # 未声明 profile 时，完整保留既有的模型名称推断和默认值。
    model_lower = model.lower()
    if payload_profile is None and "seedance" in model_lower and "fast" in model_lower:
        if size not in ("1080P", "1K", "2K", "4K"):
            size = "1080P"
    elif payload_profile is None and size not in ALLOWED_SIZES:
        size = "720P"

    duration_seconds = _validate_video_capability_limits(
        capabilities=capabilities,
        aspect_ratio=aspect_ratio,
        size=size,
        duration_seconds=duration_seconds,
        reference_count=len(images or []),
    )
    _validate_video_input_mode(
        capabilities=capabilities,
        reference_count=len(images or []),
    )

    headers = _auth_headers(api_key, base_url=base_url, model=model)
    url = _build_api_url("/v1/videos", base_url=base_url)

    # ── 模型感知参数适配 ──
    model_lower = model.lower()
    is_seedance = "seedance" in model_lower

    effective_duration = duration_seconds

    payload: dict = {
        "model": model,
        "prompt": prompt.strip(),
    }
    if payload_profile != VIDEO_PAYLOAD_PROFILE_SORA_V2:
        payload["duration"] = effective_duration

    # Seedance 专属字段：seconds（字符串形式 duration）+ orientation
    if payload_profile is None and is_seedance:
        payload["seconds"] = str(effective_duration)

    # 显式 profile 优先，未配置时继续沿用旧的模型名称分支。
    if payload_profile == VIDEO_PAYLOAD_PROFILE_SORA_V2:
        duration_field = _wire_field(capabilities, "duration_field", "duration", {"duration", "seconds"})
        wire = capabilities.get("wire")
        duration_as_string = bool(wire.get("duration_as_string")) if isinstance(wire, dict) else False
        payload[duration_field] = str(effective_duration) if duration_as_string else effective_duration
        payload["size"] = _sora_wire_size(
            capabilities=capabilities,
            size=size,
            aspect_ratio=aspect_ratio,
        )
    elif payload_profile == VIDEO_PAYLOAD_PROFILE_SEEDANCE_FAST:
        payload["seconds"] = str(effective_duration)
        payload["ratio"] = aspect_ratio
        payload["resolution"] = size
    elif payload_profile is None and is_seedance and "fast" in model_lower:
        payload["ratio"] = aspect_ratio
        payload["resolution"] = size
    else:
        payload["size"] = "large"
        payload["orientation"] = _aspect_to_orientation(aspect_ratio)

    if images:
        # ── 自动将本地图片上传到 OSS，确保第三方 API 可访问 ──
        oss_urls: list[str] = []
        local_paths: list[str] = []
        for img in images:
            img = img.strip()
            if img.lower().startswith(("http://", "https://")):
                oss_urls.append(img)
            elif img.startswith("/static/manga/"):
                local_path = str(_MANGA_OUTPUTS_DIR / img[len("/static/manga/"):])
                local_paths.append(local_path)
            elif img.startswith("/static/video/"):
                local_path = str(_VIDEO_OUTPUTS_DIR / img[len("/static/video/"):])
                local_paths.append(local_path)
            else:
                local_paths.append(img)
        if local_paths:
            # 确保 OSS 已从数据库加载配置
            from . import oss as oss_service
            if not oss_service.is_enabled():
                oss_service.auto_configure_from_db()
            if oss_service.is_enabled():
                for local_path in local_paths:
                    try:
                        oss_url = await run_blocking(oss_service.upload_file, local_path)
                        if oss_url:
                            oss_urls.append(oss_url)
                            logger.info(
                                "[video] 本地参考图上 OSS 成功: %s → %s",
                                local_path,
                                safe_media_url_for_log(oss_url),
                            )
                        else:
                            logger.warning("[video] 本地参考图上 OSS 返回空，跳过: %s", local_path)
                    except Exception as exc:
                        logger.warning("[video] 本地参考图上 OSS 失败: %s — %s", local_path, exc)
            else:
                logger.warning("[video] OSS 未配置，无法上传本地参考图: %s", local_paths)
        if len(oss_urls) != len(images):
            raise UpstreamServiceError(
                "部分本地参考图无法上传到 OSS，已停止提交视频任务",
                retryable=False,
                provider="Video",
            )
        if oss_urls:
            # 灵动与 Seedance 系列统一使用管道符分隔的 input_reference。
            reference_field = _wire_field(
                capabilities,
                "reference_field",
                "input_reference",
                {"input_reference"},
            )
            payload[reference_field] = "|".join(oss_urls)
            ref_log = "|".join(safe_media_url_for_log(item) for item in oss_urls)
            logger.info("[video] 参考图 %d 张: %s",
                         len(oss_urls), ref_log[:120])
        else:
            logger.warning("[video] 所有参考图均为本地路径且 OSS 上传失败，本次任务无参考图")

    ref_preview = "|".join(
        safe_media_url_for_log(item)
        for item in str(payload.get("input_reference") or "").split("|")
        if item
    )[:120]
    logger.info("[video] 提交任务 payload: model=%s prompt_len=%d duration=%s input_reference=%s url=%s",
                 model, len(prompt), payload.get("duration"), ref_preview, safe_media_url_for_log(url))
    last_err: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            async with httpx.AsyncClient(timeout=_timeout(connect=30, read=300, write=30)) as client:
                response = await client.post(url, json=payload, headers=headers)

            if response.is_success:
                data = _sanitize_upstream_payload(response.json(), api_key)
                logger.info("[video] 任务提交成功: task_id=%s status=%s",
                            data.get("task_id", ""), data.get("status", ""))
                return data  # {task_id, status}

            status = response.status_code
            body_text = _sanitize_upstream_error(response.text, api_key)
            logger.warning("[video] 提交失败 HTTP %s: %s", status, body_text)

            if status == 401:
                raise MissingApiKeyError("Video API Key 无效或未配置")
            if status == 429 or status >= 500:
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(RETRY_DELAY)
                    continue
            if status == 429 or status >= 500:
                raise UpstreamServiceError(
                    f"视频 API 暂时不可用 (HTTP {status}): {body_text}",
                    retryable=True,
                    provider="Video",
                    status_code=status,
                )
            raise UpstreamServiceError(
                f"视频 API 返回错误 (HTTP {status}): {body_text}",
                retryable=False,
                provider="Video",
                status_code=status,
            )
        except httpx.TimeoutException as exc:
            last_err = exc
            if attempt < MAX_RETRIES:
                await asyncio.sleep(RETRY_DELAY)
        except httpx.TransportError as exc:
            last_err = exc
            if attempt < MAX_RETRIES:
                await asyncio.sleep(RETRY_DELAY)

    raise UpstreamServiceError(
        f"视频任务提交失败，已重试 {MAX_RETRIES} 次",
        retryable=True,
        provider="Video",
    ) from last_err


async def query_video_job(
    job_id: str,
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
) -> dict:
    """查询视频生成任务状态 (GET /v1/video/generations/{task_id})."""
    if not job_id.strip():
        raise ValueError("job_id 不能为空")

    headers = _auth_headers(api_key, base_url=base_url, model=model)
    url = _build_api_url(f"/v1/video/generations/{job_id}", base_url=base_url)

    try:
        async with httpx.AsyncClient(timeout=_timeout(connect=15, read=300, write=15)) as client:
            response = await client.get(url, headers=headers)

        if response.is_success:
            raw = response.json()
            data = raw.get("data") if isinstance(raw, dict) and isinstance(raw.get("data"), dict) else raw
            nested = data.get("data") if isinstance(data, dict) and isinstance(data.get("data"), dict) else {}
            normalized = dict(data) if isinstance(data, dict) else {}
            if isinstance(nested, dict):
                for key in ("url", "video_url", "result_url", "progress", "status", "seconds", "size", "model", "id", "created_at"):
                    if key in nested and key not in normalized:
                        normalized[key] = nested[key]
                if "status" in nested:
                    normalized["upstream_status"] = nested.get("upstream_status") or nested.get("status")
            # LingDong API 在失败时返回 fail_reason 而非 error
            if "error" not in normalized:
                if isinstance(data, dict) and isinstance(data.get("fail_reason"), str) and data["fail_reason"].strip():
                    normalized["error"] = data["fail_reason"]
                elif isinstance(nested, dict) and isinstance(nested.get("fail_reason"), str) and nested["fail_reason"].strip():
                    normalized["error"] = nested["fail_reason"]
            if normalized.get("error"):
                normalized["error"] = _sanitize_upstream_error(normalized["error"], api_key)
            if "task_id" not in normalized:
                normalized["task_id"] = job_id
            if "status" not in normalized:
                normalized["status"] = normalized.get("upstream_status") or "unknown"
            normalized = _sanitize_upstream_payload(normalized, api_key)
            logger.info("[video] 查询成功: job=%s status=%s err=%s", job_id, normalized.get("status", ""), normalized.get("error", "")[:80])
            return normalized

        status = response.status_code
        body_text = _sanitize_upstream_error(response.text, api_key)[:300]
        logger.warning("[video] 查询失败 HTTP %s: %s", status, body_text)
        if status == 401:
            raise MissingApiKeyError("Video API Key 无效")
        if status == 404:
            return {"task_id": job_id, "status": "not_found"}
        return {"task_id": job_id, "status": "unknown", "error": body_text}
    except httpx.TimeoutException:
        return {"task_id": job_id, "status": "unknown", "error": "timeout"}
    except httpx.TransportError as exc:
        return {"task_id": job_id, "status": "unknown", "error": _sanitize_upstream_error(exc, api_key)}


async def download_video(
    video_url: str,
    *,
    shot_id: int,
    job_id: str,
    api_key: str | None = None,
    base_url: str | None = None,
    output_dir: Path | None = None,
) -> str:
    """从 video_url 下载视频文件到本地。

    当 video_url 是第三方直链（如火山引擎 TOS 签名 URL）时，
    优先通过 new-api 内容端点 (GET /v1/videos/{job_id}/content) 代理下载，
    避免签名过期或跨域访问问题。
    """
    if not video_url.strip():
        raise ValueError("video_url 不能为空")
    video_url = validate_remote_media_url(video_url)

    output_dir = output_dir or _output_dir()
    shot_dir = output_dir / f"shot_{shot_id}"
    shot_dir.mkdir(parents=True, exist_ok=True)

    ext = ".mp4"
    if video_url.lower().endswith(".webm"):
        ext = ".webm"
    safe_job_id = re.sub(r"[^A-Za-z0-9._-]+", "_", job_id).strip("._")[:128]
    if not safe_job_id:
        safe_job_id = uuid.uuid4().hex
    output_path = shot_dir / f"{safe_job_id}{ext}"

    if output_path.exists():
        return str(output_path)

    # OSS URL 直传：如果 OSS 已配置，直接从 video_url 上传到 OSS
    remote_key = f"video_outputs/shot_{shot_id}/{safe_job_id}{ext}"
    oss_direct_url = await run_blocking(_upload_video_url_to_oss, video_url, remote_key)
    if oss_direct_url:
        return oss_direct_url

    # 构建下载 URL 列表：优先 new-api 内容端点，原始 URL 为回退
    download_urls: list[tuple[str, dict[str, str] | None]] = []
    if base_url and api_key:
        base = base_url.rstrip("/")
        content_url = f"{base}/v1/videos/{job_id}/content"
        download_urls.append((content_url, {"Authorization": f"Bearer {api_key}"}))
    download_urls.append((video_url, None))

    last_err: Exception | None = None
    for url, extra_headers in download_urls:
        safe_url = validate_remote_media_url(url)
        for attempt in range(1, DOWNLOAD_RETRIES + 1):
            temp_path = output_path.with_name(f".{output_path.name}.{uuid.uuid4().hex}.tmp")
            try:
                headers: dict[str, str] = dict(extra_headers) if extra_headers else {}
                if not extra_headers and api_key and ("/v1/videos/" in url and "/content" in url):
                    headers["Authorization"] = f"Bearer {api_key}"
                async with httpx.AsyncClient(
                    timeout=_timeout(connect=30, read=600, write=30),
                    follow_redirects=False,
                    headers=headers if headers else None,
                ) as client:
                    async with client.stream("GET", safe_url) as response:
                        if not response.is_success:
                            continue
                        media_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                        if media_type and not (media_type.startswith("video/") or media_type == "application/octet-stream"):
                            raise RuntimeError(f"视频下载返回了不支持的内容类型: {media_type}")
                        content_length = response.headers.get("content-length")
                        try:
                            declared_length = int(content_length) if content_length else 0
                        except (TypeError, ValueError):
                            declared_length = 0
                        if declared_length > MAX_REMOTE_VIDEO_BYTES:
                            raise RuntimeError("视频文件超过允许的最大大小")
                        total_bytes = 0
                        with temp_path.open("wb") as output_file:
                            async for chunk in response.aiter_bytes():
                                total_bytes += len(chunk)
                                if total_bytes > MAX_REMOTE_VIDEO_BYTES:
                                    raise RuntimeError("视频文件超过允许的最大大小")
                                output_file.write(chunk)
                if temp_path.exists():
                    os.replace(temp_path, output_path)
                    logger.info("[video] 下载完成: %s -> %s", job_id, output_path)
                    oss_url = await run_blocking(_upload_to_oss_if_enabled, str(output_path))
                    if oss_url:
                        try:
                            output_path.unlink(missing_ok=True)
                            logger.info("[video] OSS 上传成功，已删除本地文件: %s", output_path)
                        except Exception:
                            pass
                        return oss_url
                    return str(output_path)
                if attempt < DOWNLOAD_RETRIES:
                    await asyncio.sleep(DOWNLOAD_RETRY_DELAY)
            except (httpx.TimeoutException, httpx.TransportError, RuntimeError) as exc:
                last_err = exc
                temp_path.unlink(missing_ok=True)
                if attempt < DOWNLOAD_RETRIES:
                    await asyncio.sleep(DOWNLOAD_RETRY_DELAY)
            finally:
                temp_path.unlink(missing_ok=True)
        logger.warning("[video] 下载来源失败: %s", safe_media_url_for_log(url))

    raise RuntimeError(f"视频下载失败，已重试所有来源") from last_err


def _upload_video_url_to_oss(source_url: str, remote_key: str) -> str | None:
    """如果 OSS 已配置，从视频 URL 直接上传到 OSS，跳过本地下载。"""
    try:
        from . import oss as oss_service
        if not oss_service.is_enabled():
            from .oss import auto_configure_from_db
            auto_configure_from_db()
        if oss_service.is_enabled():
            return oss_service.upload_from_url(str(source_url), remote_key)
    except Exception as exc:
        logger.warning("视频 URL 直传 OSS 失败（将回退到本地下载）: %s", exc)
    return None


def _upload_to_oss_if_enabled(local_path: str) -> str | None:
    """如果 OSS 已配置，上传文件并返回公网 URL。

    首次调用时会自动从数据库加载配置（如果尚未配置）。
    """
    try:
        from . import oss as oss_service
        if not oss_service.is_enabled():
            _auto_configure_oss()
        if oss_service.is_enabled():
            return oss_service.upload_file(local_path)
    except Exception as exc:
        logger.warning("OSS 上传失败（不影响本地文件）: %s", exc)
    return None


def _auto_configure_oss() -> None:
    """从数据库自动加载 OSS 配置。"""
    try:
        from database import SessionLocal
        from models import PlatformSetting
        from services.ai.crypto_secrets import read_platform_setting_payload
        db = SessionLocal()
        try:
            def get_setting(key: str, default=None):
                setting = db.query(PlatformSetting).filter(PlatformSetting.setting_key == key).first()
                if not setting:
                    return default
                return read_platform_setting_payload(setting.value_json, default)

            from . import oss as oss_service
            enabled = bool(get_setting("oss.enabled", False))
            if enabled:
                oss_service.configure(
                    enabled=True,
                    access_key_id=str(get_setting("oss.access_key_id", "") or "").strip(),
                    access_key_secret=str(get_setting("oss.access_key_secret", "") or "").strip(),
                    endpoint=str(get_setting("oss.endpoint", "") or "").strip(),
                    bucket=str(get_setting("oss.bucket", "") or "").strip(),
                    public_url_base=str(get_setting("oss.public_url_base", "") or "").strip(),
                )
                logger.info("OSS 已自动从数据库加载配置")
        finally:
            db.close()
    except Exception as exc:
        logger.warning("OSS 自动配置加载失败: %s", exc)



