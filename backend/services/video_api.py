"""Low-level video API client for New API standard."""
from __future__ import annotations

import asyncio
import base64
import logging
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv

from .blocking import run_blocking
from .errors import MissingApiKeyError, UpstreamServiceError

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
    return (_runtime_base_url or os.getenv("VIDEO_API_BASE_URL") or "").rstrip("/")


def _resolved_api_key() -> str:
    return (_runtime_api_key or os.getenv("VIDEO_API_KEY") or os.getenv("IMAGE_API_KEY") or "").strip()


def _resolved_model() -> str:
    return (_runtime_model or os.getenv("VIDEO_MODEL") or "")

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
    # ── Lingdong API (灵动中转站) 模型 ──
    "sd-2-vip": {"name": "Seedance 2.0 VIP (九参素材版)", "supports_image": True},
    "sd-2-vip-720": {"name": "Seedance 2.0 VIP 720", "supports_image": True},
    "seedance-2.0-fast": {"name": "Seedance 2.0 Fast", "supports_image": True},
}

ALLOWED_ASPECT_RATIOS = ["16:9", "9:16", "1:1", "4:3", "3:4", "3:2", "2:3"]
ALLOWED_SIZES = ["720P", "1080P", "1K", "2K", "4K"]


def _timeout(*, connect: float, read: float, write: float, pool: float = 30.0) -> httpx.Timeout:
    return httpx.Timeout(connect=connect, read=read, write=write, pool=pool)


def _auth_headers(api_key: str | None = None, base_url: str | None = None, model: str | None = None) -> dict[str, str]:
    """获取视频 API 认证头，同时校验必要配置是否已注入。"""
    effective_base_url = (base_url or _resolved_base_url() or "").rstrip("/")
    if not effective_base_url:
        raise ValueError("视频 API 地址未配置，请在后台设置中配置 API 地址后重试。")
    effective_model = model or _resolved_model()
    if not effective_model:
        raise ValueError("视频生成模型未配置，请在后台设置中配置模型名称后重试。")
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

    例: base=https://your-api.com/v1, path=/v1/video/generations
    → https://your-api.com/v1/video/generations
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
        # LingDong API: data.result_url
        if isinstance(data.get("result_url"), str) and data["result_url"].strip():
            return data["result_url"].strip()
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
    """创建视频生成任务 (POST /v1/videos - LingDong API)."""
    if not prompt.strip():
        raise ValueError("prompt 不能为空")

    model = model or _resolved_model()
    if aspect_ratio not in ALLOWED_ASPECT_RATIOS:
        aspect_ratio = "16:9"
    model_lower = model.lower()
    # seedance-2.0-fast 的 resolution 参数不接受 720P
    if "seedance" in model_lower and "fast" in model_lower:
        if size not in ("1080P", "1K", "2K", "4K"):
            size = "1080P"
    elif size not in ALLOWED_SIZES:
        size = "720P"

    headers = _auth_headers(api_key, base_url=base_url, model=model)
    url = _build_api_url("/v1/videos", base_url=base_url)

    payload: dict = {
        "model": model,
        "prompt": prompt.strip(),
        "duration": max(4, min(15, duration_seconds)),
    }

    # ── 模型感知参数适配 ──
    # Lingdong API: seedance-2.0-fast 系列使用 ratio+resolution，
    # sd-2-vip 系列使用 size+orientation
    model_lower = model.lower()
    if "seedance" in model_lower and "fast" in model_lower:
        # seedance-2.0-fast / seedance-2.0-fast-xxx
        payload["ratio"] = aspect_ratio
        payload["resolution"] = size
        # 可选的 watermark / first_frame 等不由调用方传入，保持默认
    else:
        # sd-2-vip, sd-2-vip-720 及其他 New API 模型
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
                            logger.info("[video] 本地参考图上 OSS 成功: %s → %s", local_path, oss_url)
                        else:
                            logger.warning("[video] 本地参考图上 OSS 返回空，跳过: %s", local_path)
                    except Exception as exc:
                        logger.warning("[video] 本地参考图上 OSS 失败: %s — %s", local_path, exc)
            else:
                logger.warning("[video] OSS 未配置，无法上传本地参考图: %s", local_paths)
        if oss_urls:
            payload["images"] = oss_urls
            logger.info("[video] 参考图 %d 张: %s",
                         len(oss_urls), [u[:60] for u in oss_urls])
        else:
            logger.warning("[video] 所有参考图均为本地路径且 OSS 上传失败，本次任务无参考图")

    logger.info("[video] 提交任务 payload: model=%s prompt_len=%d duration=%s refs=%s url=%s",
                 model, len(prompt), payload.get("duration"),
                 [u[:60] for u in payload.get("images", [])], url)
    last_err: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            async with httpx.AsyncClient(timeout=_timeout(connect=30, read=300, write=30)) as client:
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
            if "task_id" not in normalized:
                normalized["task_id"] = job_id
            if "status" not in normalized:
                normalized["status"] = normalized.get("upstream_status") or "unknown"
            logger.info("[video] 查询成功: job=%s status=%s err=%s", job_id, normalized.get("status", ""), normalized.get("error", "")[:80])
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

    # OSS URL 直传：如果 OSS 已配置，直接从 video_url 上传到 OSS
    remote_key = f"video_outputs/shot_{shot_id}/{job_id}{ext}"
    oss_direct_url = await run_blocking(_upload_video_url_to_oss, video_url, remote_key)
    if oss_direct_url:
        return oss_direct_url

    last_err: Exception | None = None
    for attempt in range(1, DOWNLOAD_RETRIES + 1):
        try:
            async with httpx.AsyncClient(
                timeout=_timeout(connect=30, read=600, write=30),
                follow_redirects=True,
            ) as client:
                response = await client.get(video_url)
            if response.is_success:
                await run_blocking(output_path.write_bytes, response.content)
                logger.info("[video] 下载完成: %s -> %s", job_id, output_path)
                # OSS 上传（如已配置，上传成功后删除本地文件）
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
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last_err = exc
            if attempt < DOWNLOAD_RETRIES:
                await asyncio.sleep(DOWNLOAD_RETRY_DELAY)

    raise RuntimeError(f"视频下载失败，已重试 {DOWNLOAD_RETRIES} 次") from last_err


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
        db = SessionLocal()
        try:
            def get_setting(key: str, default=None):
                setting = db.query(PlatformSetting).filter(PlatformSetting.setting_key == key).first()
                if not setting:
                    return default
                payload = setting.value_json or {}
                return payload.get("value", default)

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


def get_supported_models() -> list[dict]:
    return [
        {"key": key, "name": value["name"], "supports_image": value["supports_image"]}
        for key, value in SUPPORTED_MODELS.items()
    ]
