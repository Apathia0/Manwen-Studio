import asyncio
import base64
import contextvars
import io
import json
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

import httpx
from PIL import Image

from .blocking import run_blocking
from .errors import MangaImageGenerationError, MissingApiKeyError
from .ai.channels import validate_remote_media_url
from .scene_safety import sanitize_scene_text

logger = logging.getLogger("image2")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")

# 禁用系统代理（部分 Windows 环境有代理配置但未运行，会导致 httpx 连接超时断开）
os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"

# 默认值会被 router 层从 PlatformSetting 数据库动态覆盖
DEFAULT_IMAGE_API_BASE_URL = ""
DEFAULT_IMAGE_MODEL = ""
IMAGE_API_BASE_URL = DEFAULT_IMAGE_API_BASE_URL
IMAGE_API_KEY = ""
IMAGE_MODEL = DEFAULT_IMAGE_MODEL
IMAGE_SIZE = "1920x1080"
IMAGE_QUALITY = ""
IMAGE_BACKGROUND = ""
IMAGE_MODERATION = ""
IMAGE_OUTPUT_FORMAT = ""
IMAGE_OUTPUT_COMPRESSION: int | None = None
IMAGE_INPUT_FIDELITY = ""
_DEFAULT_HTTP_DOWNLOAD_HOSTS = {"nana.code2alita.com"}


def _trusted_http_download_hosts() -> set[str]:
    configured_hosts = {
        item.strip().rstrip(".").lower()
        for item in (os.getenv("IMAGE_HTTP_DOWNLOAD_ALLOWLIST") or "").split(",")
        if item.strip()
    }
    return _DEFAULT_HTTP_DOWNLOAD_HOSTS | configured_hosts


def _safe_generated_image_url(url: str) -> str:
    return validate_remote_media_url(url, allow_http_hosts=_trusted_http_download_hosts())
# 用于所有图片生成请求的负面提示词（抑制解剖学畸形和画面污染）
IMAGE_NEGATIVE_PROMPT = (
    "extra limbs, extra hands, extra feet, extra fingers, six fingers, "
    "deformed face, asymmetric face, blurred face, distorted face, "
    "overlapping body parts, merged characters, duplicated limbs, "
    "missing fingers, cropped limbs, fused body parts, "
    "distorted proportions, unnatural body, twisted body, "
    "disconnected limbs, cross-eyed, "
    "multiple heads, conjoined bodies, "
    "watermark, signature, label, text overlay, Chinese characters on figure, "
    "diagram, infographic, split screen, multi-panel layout, "
    "blurry, low quality, bad anatomy, bad proportions, "
    "poorly drawn, disfigured, mutation, deformed, "
    "jpeg artifacts, compression artifacts, pixelated"
)
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "manga_outputs"

IMAGE2_SIZE_PATTERN = re.compile(r"^\d{1,5}x\d{1,5}$")

MAX_RETRIES = 3
RETRY_DELAY = 5


DEFAULT_IMAGE_SIZE = "1920x1080"

DOWNLOAD_RETRIES = 3
DOWNLOAD_RETRY_DELAY = 3
MAX_REMOTE_IMAGE_BYTES = max(1, int(os.getenv("MAX_REMOTE_IMAGE_BYTES", str(50 * 1024 * 1024))))
PROMPT_TOO_LONG_KEYWORDS = (
    "message too long",
    "prompt too long",
    "messages too long",
    "消息过长",
    "提交的消息过长",
    "上下文过长",
    "context length",
    "maximum context length",
)

CONTENT_POLICY_KEYWORDS = (
    "违反平台政策",
    "内容安全",
    "content policy",
    "content_policy",
    "safety",
    "sensitive",
    "unsafe",
    "审核",
    "风控",
    "政策",
)
QUOTA_KEYWORDS = (
    "quota",
    "insufficient",
    "余额不足",
    "额度不足",
    "credit",
    "exhausted",
    "token",
    "用尽",
)
RATE_LIMIT_KEYWORDS = ("rate limit", "too many requests", "频率", "限流")


@dataclass
class ImageGenerationResult:
    image_path: str
    final_prompt: str
    prompt_sanitized: bool = False


@dataclass(frozen=True)
class ImageRuntimeSettings:
    base_url: str
    model: str
    size: str
    quality: str = ""
    background: str = ""
    moderation: str = ""
    output_format: str = ""
    output_compression: int | None = None
    input_fidelity: str = ""


_IMAGE_RUNTIME: contextvars.ContextVar[ImageRuntimeSettings | None] = contextvars.ContextVar(
    "image2_runtime",
    default=None,
)


def configure_runtime(
    *,
    base_url: str | None = None,
    model: str | None = None,
    size: str | None = None,
    quality: str | None = None,
    background: str | None = None,
    moderation: str | None = None,
    output_format: str | None = None,
    output_compression: int | str | None = None,
    input_fidelity: str | None = None,
) -> None:
    current = _runtime_settings()
    resolved_base_url = current.base_url
    resolved_model = current.model
    if isinstance(base_url, str) and base_url.strip():
        resolved_base_url = base_url.strip().rstrip("/")
    if isinstance(model, str) and model.strip():
        resolved_model = model.strip()
    resolved_size = current.size
    if size is not None:
        resolved_size = _clean_optional_param(size) or DEFAULT_IMAGE_SIZE
    _IMAGE_RUNTIME.set(
        ImageRuntimeSettings(
            base_url=resolved_base_url,
            model=resolved_model,
            size=resolved_size,
            quality=_clean_optional_param(quality),
            background=_clean_optional_param(background),
            moderation=_clean_optional_param(moderation),
            output_format=_clean_optional_param(output_format),
            output_compression=_clean_output_compression(output_compression),
            input_fidelity=_clean_optional_param(input_fidelity),
        )
    )


def _clean_optional_param(value: str | None) -> str:
    if value is None:
        return ""
    cleaned = str(value).strip()
    return "" if cleaned.lower() in ("", "default", "none", "null") else cleaned


def _clean_output_compression(value: int | str | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, str):
        cleaned = _clean_optional_param(value)
        if not cleaned:
            return None
        try:
            value = int(cleaned)
        except ValueError:
            logger.warning("Ignoring invalid image output_compression value: %s", value)
            return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        logger.warning("Ignoring invalid image output_compression value: %s", value)
        return None
    return max(0, min(100, number))


def _runtime_settings() -> ImageRuntimeSettings:
    runtime = _IMAGE_RUNTIME.get()
    if runtime is not None:
        return runtime
    return ImageRuntimeSettings(
        base_url=IMAGE_API_BASE_URL,
        model=IMAGE_MODEL,
        size=IMAGE_SIZE,
        quality=IMAGE_QUALITY,
        background=IMAGE_BACKGROUND,
        moderation=IMAGE_MODERATION,
        output_format=IMAGE_OUTPUT_FORMAT,
        output_compression=IMAGE_OUTPUT_COMPRESSION,
        input_fidelity=IMAGE_INPUT_FIDELITY,
    )


def runtime_base_url() -> str:
    """返回当前请求或任务上下文中的图片 API 地址。"""
    return _runtime_settings().base_url


def runtime_model() -> str:
    """返回当前请求或任务上下文中的图片模型。"""
    return _runtime_settings().model


def _runtime_base_url() -> str:
    """保留旧私有入口，内部统一使用公开 accessor。"""
    return runtime_base_url()


# 上游图片接口（gpt-image-2 系列）的尺寸约束：宽高都必须是 16 的倍数、单边不超过 3840、总像素在 655360~8294400 之间。
# 1920x1080 这类常见的“视频分辨率”不满足（1080 不是 16 的倍数）会被直接 400 拒绝，所以统一在这里对齐。
IMAGE_SIZE_STEP = 16
IMAGE_MAX_EDGE = 3840
IMAGE_MIN_PIXELS = 655_360
IMAGE_MAX_PIXELS = 8_294_400


def _snap_size_to_step(width: int, height: int) -> tuple[int, int]:
    """把宽高对齐到 16 的倍数（四舍五入，1080→1088），并收进上游允许的边长与像素范围，宽高比尽量保持。"""
    step = IMAGE_SIZE_STEP

    def snap(value: float) -> int:
        return max(step, int(value / step + 0.5) * step)

    def floor_step(value: float) -> int:
        return max(step, int(value // step) * step)

    w, h = snap(width), snap(height)
    scale = 1.0
    if max(w, h) > IMAGE_MAX_EDGE:
        scale = IMAGE_MAX_EDGE / max(w, h)
    if w * h * scale * scale > IMAGE_MAX_PIXELS:
        scale = min(scale, (IMAGE_MAX_PIXELS / (w * h)) ** 0.5)
    if scale < 1.0:
        return floor_step(w * scale), floor_step(h * scale)
    if w * h < IMAGE_MIN_PIXELS:
        up = (IMAGE_MIN_PIXELS / (w * h)) ** 0.5
        return snap(w * up + step - 1), snap(h * up + step - 1)
    return w, h


def _normalize_image_size(size: str | None) -> str:
    runtime = _runtime_settings()
    candidate = str(size or getattr(runtime, "size", DEFAULT_IMAGE_SIZE) or "").strip() or DEFAULT_IMAGE_SIZE
    if IMAGE2_SIZE_PATTERN.match(candidate):
        width, height = (int(part) for part in candidate.split("x"))
        snapped_w, snapped_h = _snap_size_to_step(width, height)
        if (snapped_w, snapped_h) != (width, height):
            logger.info("图片尺寸 %s 不符合上游要求（宽高需为 %s 的倍数），已调整为 %sx%s", candidate, IMAGE_SIZE_STEP, snapped_w, snapped_h)
        return f"{snapped_w}x{snapped_h}"
    logger.warning("尺寸格式 %s 不合法，回退到 %s", candidate, DEFAULT_IMAGE_SIZE)
    return _normalize_image_size(DEFAULT_IMAGE_SIZE) if candidate != DEFAULT_IMAGE_SIZE else DEFAULT_IMAGE_SIZE


def _base_image_payload(prompt: str, size: str | None) -> dict[str, str | int]:
    runtime = _runtime_settings()
    payload: dict[str, str | int] = {
        "model": runtime_model(),
        "prompt": prompt,
        "size": _normalize_image_size(size),
    }
    optional: dict[str, str | int | None] = {
        "quality": getattr(runtime, "quality", ""),
        "background": getattr(runtime, "background", ""),
        "moderation": getattr(runtime, "moderation", ""),
        "output_format": getattr(runtime, "output_format", ""),
        "output_compression": getattr(runtime, "output_compression", None),
    }
    for key, value in optional.items():
        if value not in ("", None):
            payload[key] = value
    return payload


def _generation_payload(prompt: str, size: str | None = None) -> dict[str, str | int]:
    return _base_image_payload(prompt, size)


def _edit_payload(prompt: str, size: str | None = None) -> dict[str, str | int]:
    runtime = _runtime_settings()
    payload = _base_image_payload(prompt, size)
    input_fidelity = getattr(runtime, "input_fidelity", "")
    if input_fidelity:
        payload["input_fidelity"] = input_fidelity
    return payload


def _pending_download_path(output_path: Path) -> Path:
    return output_path.with_suffix(output_path.suffix + ".pending.json")


def _save_pending_download(output_path: Path, source_url: str) -> None:
    try:
        _pending_download_path(output_path).write_text(
            json.dumps({"url": source_url, "saved_at": int(time.time())}, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError as exc:
        logger.warning("Failed to save pending download metadata for %s: %s", output_path, exc)


def _clear_pending_download(output_path: Path) -> None:
    try:
        _pending_download_path(output_path).unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("Failed to clear pending download metadata for %s: %s", output_path, exc)


def _load_pending_download(output_path: Path) -> str:
    pending_path = _pending_download_path(output_path)
    if not pending_path.exists():
        return ""
    try:
        payload = json.loads(pending_path.read_text(encoding="utf-8"))
        if isinstance(payload, dict) and isinstance(payload.get("url"), str):
            return payload["url"].strip()
    except Exception:
        return ""
    return ""


def _image_auth_headers(api_key: str | None = None, json_content: bool = False) -> dict[str, str]:
    """获取图片 API 认证头，同时校验必要配置是否已注入。"""
    if not runtime_base_url():
        raise MangaImageGenerationError(
            code="missing_config",
            user_message="图片 API 地址未配置，请在后台设置中配置 API 地址后重试。",
            retryable=False,
            provider_message="IMAGE_API_BASE_URL is empty",
        )
    if not runtime_model():
        raise MangaImageGenerationError(
            code="missing_config",
            user_message="图片生成模型未配置，请在后台设置中配置模型名称后重试。",
            retryable=False,
            provider_message="IMAGE_MODEL is empty",
        )
    key = (api_key or IMAGE_API_KEY or "").strip()
    if not key:
        raise MissingApiKeyError("Image2")
    headers = {"Authorization": f"Bearer {key}"}
    if json_content:
        headers["Content-Type"] = "application/json"
    return headers


def normalize_image_bytes(image_bytes: bytes) -> bytes:
    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            img.verify()
        with Image.open(io.BytesIO(image_bytes)) as img:
            output = io.BytesIO()
            img.convert("RGBA").save(output, format="PNG", optimize=True)
            return output.getvalue()
    except Exception as exc:
        raise MangaImageGenerationError(
            code="invalid_image",
            user_message="上游返回的图片数据无效，请重试。",
            retryable=True,
            provider_message=str(exc),
        ) from exc


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(keyword.lower() in lowered for keyword in keywords)


def _extract_data_image_entry(data: dict, progress_label: str) -> dict:
    """从 API 响应的 data 数组中安全提取第一张图片条目。

    防御性处理以防止上游 API 返回 HTTP 200 但 data 为空的情况。
    """
    image_list = data.get("data")
    if not isinstance(image_list, list):
        logger.error("[%s] API 返回的 data 字段类型异常: type=%s body=%s",
                     progress_label, type(image_list).__name__,
                     json.dumps(data, ensure_ascii=False)[:1000])
        raise MangaImageGenerationError(
            code="invalid_response",
            user_message="绘图服务返回了意外的数据格式，请稍后重试。",
            retryable=True,
            provider_message=f"data field type is {type(image_list).__name__}, expected list",
        )
    if len(image_list) == 0:
        logger.error("[%s] API 返回了空图片列表: %s",
                     progress_label, json.dumps(data, ensure_ascii=False)[:1000])
        raise MangaImageGenerationError(
            code="empty_response",
            user_message="绘图服务返回了空的图片列表，请稍后重试或检查 API 配置。",
            retryable=True,
            provider_message="API returned HTTP 200 with empty data array",
        )
    return image_list[0]


def _extract_provider_message(resp: httpx.Response) -> str:
    try:
        payload = resp.json()
    except Exception:
        text = resp.text.strip()
        return text[:500]
    if isinstance(payload, dict):
        candidates = [
            payload.get("message"),
            payload.get("detail"),
            payload.get("error"),
        ]
        error_obj = payload.get("error")
        if isinstance(error_obj, dict):
            candidates.extend([error_obj.get("message"), error_obj.get("detail"), error_obj.get("code")])
        for item in candidates:
            if isinstance(item, str) and item.strip():
                return item.strip()[:500]
        return json.dumps(payload, ensure_ascii=False)[:500]
    return str(payload)[:500]


def _classify_response_error(
    resp: httpx.Response,
    progress_label: str,
    prompt: str,
    prompt_sanitized: bool,
) -> MangaImageGenerationError:
    provider_message = _extract_provider_message(resp) or f"HTTP {resp.status_code}"
    logger.warning(
        "[%s] 上游响应失败 status=%s body=%s",
        progress_label,
        resp.status_code,
        provider_message,
    )

    if _contains_any(provider_message, CONTENT_POLICY_KEYWORDS):
        optimized_prompt, _ = sanitize_scene_text(prompt)
        return MangaImageGenerationError(
            code="content_policy",
            user_message="当前分镜描述触发了绘图平台的内容风控，系统已尝试自动降敏处理。",
            retryable=not prompt_sanitized,
            provider_message=provider_message,
            status_code=resp.status_code,
            optimized_prompt=optimized_prompt,
            suggestion="可以保留剧情，但把血腥、裸露、极端暴力改成情绪冲突、动作张力和镜头暗示。",
            should_sanitize=not prompt_sanitized,
        )

    if resp.status_code in (401, 403):
        return MangaImageGenerationError(
            code="auth_failed",
            user_message="绘图服务鉴权失败，请检查 API Key 是否有效。",
            retryable=False,
            provider_message=provider_message,
            status_code=resp.status_code,
        )

    if resp.status_code == 429 or _contains_any(provider_message, RATE_LIMIT_KEYWORDS):
        return MangaImageGenerationError(
            code="rate_limited",
            user_message="绘图服务当前限流，请稍后继续生成。",
            retryable=True,
            provider_message=provider_message,
            status_code=resp.status_code,
        )

    # 524 是上游网关在请求可能仍被处理时主动断开连接，自动重试会重复提交计费请求并进一步放大拥塞。
    if resp.status_code == 524:
        return MangaImageGenerationError(
            code="upstream_gateway_timeout",
            user_message="绘图网关等待超时，本次请求未自动重复提交，请稍后手动重试。",
            retryable=False,
            provider_message=provider_message,
            status_code=resp.status_code,
        )

    if _contains_any(provider_message, QUOTA_KEYWORDS):
        return MangaImageGenerationError(
            code="quota_exhausted",
            user_message="绘图服务额度不足或 token 已耗尽，请充值或更换可用 key。",
            retryable=False,
            provider_message=provider_message,
            status_code=resp.status_code,
        )

    if _contains_any(provider_message, PROMPT_TOO_LONG_KEYWORDS):
        return MangaImageGenerationError(
            code="prompt_too_long",
            user_message="当前绘图提示词过长，请缩短分镜描述或改用角色参考图后再试。",
            retryable=False,
            provider_message=provider_message,
            status_code=resp.status_code,
        )

    if resp.status_code >= 500:
        return MangaImageGenerationError(
            code="upstream_server_error",
            user_message="绘图服务暂时异常，请稍后继续生成。",
            retryable=True,
            provider_message=provider_message,
            status_code=resp.status_code,
        )

    return MangaImageGenerationError(
        code="upstream_request_failed",
        user_message="绘图服务拒绝了当前请求，请稍后重试。",
        retryable=False,
        provider_message=provider_message,
        status_code=resp.status_code,
    )


def _build_manga_style(color_mode: str, has_style_ref: bool = False) -> str:
    if has_style_ref:
        output_constraint = (
            "全彩色输出，保留自然且清晰的色彩层次。"
            if color_mode == "color"
            else "黑白或灰度输出，保留清晰的明暗层次。"
        )
        return (
            f"{output_constraint}"
            "具体艺术风格以【画面风格参考锚点】为准，并且只以该图片为唯一依据。严格匹配图片中可见的人物造型比例、五官简化方式、轮廓形状语言、"
            "线条粗细、明暗方法、配色、材质纹理、笔触颗粒、光影以及分格和气泡处理。不要根据角色设定、场景文本、预设名称或"
            "其他文字推断画风；参考图是照片就保持照片级写实，是插画、水彩或漫画就保持对应视觉媒介。只替换人物身份、服装、"
            "道具和场景内容，不改变参考图的视觉语言。"
        )
    if color_mode == "color":
        return (
            "全彩色画面，角色形象鲜明，构图清晰。"
            "画面干净简洁，人物一致，镜头语言明确。"
        )
    return (
        "日式黑白漫画页面，黑白高对比，网点和线稿清晰。"
        "构图简洁明了，角色形象统一。"
    )


_STYLE_PROFILE_KEYWORDS = (
    "画风",
    "艺术风格",
    "视觉风格",
    "绘画风格",
    "媒介",
    "渲染",
    "笔触",
    "线稿",
    "网点",
    "光影风格",
    "整体色调",
    "日式漫画",
    "anime",
    "manga style",
    "art style",
    "rendering style",
    "photorealistic",
    "watercolor",
    "oil painting",
    "concept art",
    "illustration style",
)
_FRAME_RATIO_KEYWORDS = ("画面比例", "图片比例", "宽高比", "画幅比例", "aspect ratio")


def _compress_character_profiles_for_style_reference(character_profiles: str) -> str:
    """移除会覆盖风格参考图的媒介与画幅描述，保留角色身份和造型信息。"""
    cleaned_lines: list[str] = []
    for raw_line in str(character_profiles or "").splitlines():
        line = raw_line.strip()
        if not line:
            if cleaned_lines and cleaned_lines[-1]:
                cleaned_lines.append("")
            continue
        clauses = re.split(r"([，,；;。])", line)
        kept_parts: list[str] = []
        for index in range(0, len(clauses), 2):
            clause = clauses[index].strip()
            separator = clauses[index + 1] if index + 1 < len(clauses) else ""
            normalized = clause.lower()
            if any(keyword in normalized for keyword in _STYLE_PROFILE_KEYWORDS + _FRAME_RATIO_KEYWORDS):
                continue
            if clause:
                kept_parts.append(clause + separator)
        cleaned_line = "".join(kept_parts).strip("，,；;。 ")
        if cleaned_line:
            cleaned_lines.append(cleaned_line)
    while cleaned_lines and not cleaned_lines[-1]:
        cleaned_lines.pop()
    return "\n".join(cleaned_lines)


def _build_full_prompt(
    scene_prompt: str,
    image_number: int,
    total_pages: int,
    all_scenes: list[str] | None,
    character_profiles: str,
    use_ref: bool,
    color_mode: str,
    ref_layout_desc: str = "",
    has_style_ref: bool = False,
    has_character_ref: bool = False,
    suppress_default_style: bool = False,
) -> str:
    """构建完整的提示词内容。

    当有参考图时，在最前面用英文写出"忽略文本外貌描述"的核心规则，
    确保 gpt-image-2 优先读到视觉参考约束，而非后面 DeepSeek 生成的文本外貌描述。
    """
    char_block = ""
    if character_profiles and not has_character_ref:
        effective_profiles = (
            _compress_character_profiles_for_style_reference(character_profiles)
            if has_style_ref
            else character_profiles.strip()
        )
        if effective_profiles:
            char_block = f"【角色外貌设定】\n{effective_profiles}\n\n"

    # 参考图约束块：放在最前，优先级最高
    ref_block = ""
    if use_ref:
        ref_block = (
            "ATTACHED IMAGES ARE AUTHORITATIVE VISUAL REFERENCES. "
            "Follow the role mapping below and never reinterpret a scene, prop, or style image as a character reference. "
            "Use only the references relevant to the current scene content.\n"
        )
        if has_style_ref:
            ref_block += (
                "Below reference images include ART STYLE reference images. "
                "Images labeled '【画面风格参考锚点】' are for ART STYLE ONLY — "
                "match their visible character stylization and body proportions, facial simplification, shape language, "
                "line weight, shading, palette, material texture, brush grain, lighting, panel layout and speech-bubble treatment. "
                "Do not copy character identity, clothing, specific objects or scene layout. "
                "The generated panel artwork must follow the scene script content exactly. Any textual style words in scene or character descriptions are content notes only and must never override the visual style reference.\n"
            )
        # 中文编号说明 —— 说明每张参考图的角色对应关系
        if ref_layout_desc:
            ref_block += ref_layout_desc + "\n"

    style_block = (
        "保持分镜构图、角色、场景和道具清晰一致，不附加额外画风约束。"
        if suppress_default_style
        else _build_manga_style(color_mode, has_style_ref=has_style_ref)
    )

    if all_scenes:
        if has_style_ref:
            return (
                f"{ref_block}{char_block}"
                f"你正在绘制第 {image_number}/{total_pages} 页，当前只绘制本页。\n"
                f"{style_block}\n"
                f"{scene_prompt}"
            )
        idx = image_number - 1
        window_start = max(0, idx - 1)
        window_end = min(len(all_scenes), idx + 2)
        script_context = "\n".join(
            f"第{i + 1}页：{scene}"
            for i, scene in enumerate(all_scenes)
            if window_start <= i < window_end
        )
        return (
            f"{ref_block}{char_block}"
            f"你正在绘制第 {image_number}/{total_pages} 页。\n"
            f"附近分镜如下，请保持人物、服装和镜头风格一致：\n{script_context}\n\n"
            f"当前只绘制第 {image_number} 页。\n"
            f"{style_block}\n"
            f"{scene_prompt}"
        )
    return f"{ref_block}{char_block}{style_block}\n{scene_prompt}"


def _prepare_ref_blobs(
    valid_refs: list[Path],
    progress_label: str,
    ref_roles: list[str] | None = None,
) -> list[tuple[str, bytes]]:
    ref_blobs: list[tuple[str, bytes]] = []
    for idx, ref_path in enumerate(valid_refs, start=1):
        try:
            img = Image.open(ref_path)
            role = _normalize_ref_role(ref_roles[idx - 1] if ref_roles and idx <= len(ref_roles) else "character")
            original_size = img.size
            current_long_side = max(img.width, img.height)
            if role == "style":
                target_long_side = min(1536, max(1024, current_long_side))
                ratio = target_long_side / current_long_side
            elif role == "character":
                # 角色设定板包含三视图、表情和服饰细节，512 像素会丢失关键身份特征。
                ratio = min(1.0, 1024 / current_long_side)
            else:
                ratio = min(1.0, 768 / current_long_side)
            if ratio != 1.0:
                new_w = max(1, int(img.width * ratio))
                new_h = max(1, int(img.height * ratio))
                img = img.resize((new_w, new_h), Image.LANCZOS)
            buf = io.BytesIO()
            # 使用 RGB 而非 RGBA，避免透明度通道增加 token 消耗
            img.convert("RGB").save(buf, format="PNG", optimize=True)
            blob = buf.getvalue()
            ref_blobs.append((f"ref{idx}.png", blob))
            logger.info(
                "[%s] 参考图 %s 已加载: %s role=%s 原始=%sx%s 发送=%sx%s -> %.0f KB",
                progress_label,
                idx,
                ref_path.name,
                role,
                original_size[0],
                original_size[1],
                img.width,
                img.height,
                len(blob) / 1024,
            )
        except Exception as exc:
            logger.warning("[%s] 参考图加载失败 %s: %s", progress_label, ref_path, exc)
    return ref_blobs


def _manga_edit_payload(prompt: str, size: str, ref_roles: list[str]) -> dict[str, object]:
    """按参考图用途构造编辑载荷，纯风格参考不启用高输入保真。"""
    payload: dict[str, object] = _edit_payload(prompt, size)
    normalized_roles = [_normalize_ref_role(role) for role in ref_roles]
    if any(role != "style" for role in normalized_roles):
        payload["input_fidelity"] = _runtime_settings().input_fidelity or "high"
    else:
        payload.pop("input_fidelity", None)
    return payload


def _normalize_ref_role(value: object) -> str:
    role = str(value or "").strip().lower().replace("_reference", "")
    return role if role in {"character", "scene", "prop", "style"} else "character"


def _reference_role_instruction(role: str, label: str, index: int) -> str:
    normalized_role = _normalize_ref_role(role)
    display_label = label or f"参考对象{index}"
    if normalized_role == "style":
        return (
            f"Reference image {index} is ART STYLE reference '{display_label}'. "
            "First match its RENDERING MEDIUM exactly: if it looks like a real photograph or live-action film still, every person must look like a real photographed human "
            "(natural skin texture, realistic proportions, natural lighting and film color grading) and must NOT be drawn as an illustration, concept art, 3D render, anime or game character; "
            "if it is an illustration, anime or 3D image, keep that same medium. "
            "Then match visible character stylization and proportions, facial simplification, shape language, line weight, shading, "
            "palette, texture, brush grain, lighting, panel layout and speech-bubble treatment; do not copy its characters, "
            "character identity, clothing, specific objects or scene layout."
        )
    if normalized_role == "scene":
        return (
            f"Reference image {index} defines ENVIRONMENT '{display_label}'. "
            "Preserve its architecture, spatial layout, materials, lighting and atmosphere; do not treat it as a character."
        )
    if normalized_role == "prop":
        return (
            f"Reference image {index} defines PROP '{display_label}'. "
            "Preserve the object's shape, material, color, scale and distinctive details; do not treat it as a character."
        )
    return (
        f"Reference image {index} defines CHARACTER '{display_label}'. "
        "This is the authoritative identity reference for this character in every panel. "
        "Match the same face geometry, eyes, hairstyle, body proportions, clothing silhouette, colors and accessories exactly. "
        "If the scene text contains conflicting appearance details, preserve the reference identity and treat only temporary "
        "story conditions such as injury, dirt, wetness, expression or pose as scene-specific changes. "
        "Do not redesign, replace or reinterpret this character."
    )


def _composite_region_instruction(role: str, label: str) -> str:
    """描述合成参考图中的单个标记区域，避免把区域误写成独立附件。"""
    normalized_role = _normalize_ref_role(role)
    display_label = label or "未命名参考区域"
    prefix = f"Within composite reference image 1, region labeled '{display_label}'"
    if normalized_role == "scene":
        return f"{prefix} defines an ENVIRONMENT; preserve its layout, architecture, materials and atmosphere."
    if normalized_role == "prop":
        return f"{prefix} defines a PROP; preserve its shape, material, color, scale and distinctive details."
    if normalized_role == "style":
        return f"{prefix} defines ART STYLE only; match its visible visual language without copying its content."
    return f"{prefix} defines a CHARACTER; match facial features, hairstyle, body shape, clothing and accessories."


def _compose_ref_sheet(
    ref_paths: list[Path],
    ref_labels: list[str],
    ref_roles: list[str] | None = None,
) -> tuple[bytes, str]:
    """多角色参考图合拼为紧凑网格图，直接在图上绘制角色名标签。

    图片上直接标注角色名，确保模型"看见"角色对应关系。
    返回 (PNG bytes, 布局描述)。
    """
    from PIL import ImageDraw, ImageFont

    if len(ref_paths) == 1:
        buf = io.BytesIO()
        with Image.open(ref_paths[0]) as img:
            # 在图片底部绘制角色名标签
            draw = ImageDraw.Draw(img)
            label = ref_labels[0] if ref_labels and ref_labels[0] else ""
            if label:
                try:
                    font = ImageFont.truetype("simhei.ttf", 24)
                except Exception:
                    font = ImageFont.load_default()
                bbox = draw.textbbox((0, 0), label, font=font)
                tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
                # 底部半透明背景
                draw.rectangle([0, img.height - th - 10, img.width, img.height], fill=(0, 0, 0, 180))
                draw.text(((img.width - tw) // 2, img.height - th - 5), label, fill=(255, 255, 255), font=font)
            img.convert("RGB").save(buf, format="PNG", optimize=True)
        role = ref_roles[0] if ref_roles else "character"
        desc = _reference_role_instruction(role, label, 1) + "\n"
        return buf.getvalue(), desc

    cell_size = 384
    padding = 8
    label_height = 30
    max_cols = 3

    images: list[Image.Image] = []
    for p in ref_paths:
        try:
            img = Image.open(p).convert("RGB")
            ratio = cell_size / max(img.width, img.height)
            if ratio < 1:
                new_w = max(1, int(img.width * ratio))
                new_h = max(1, int(img.height * ratio))
                img = img.resize((new_w, new_h), Image.LANCZOS)
            canvas = Image.new("RGB", (cell_size, cell_size), (255, 255, 255))
            x = (cell_size - img.width) // 2
            y = (cell_size - img.height) // 2
            canvas.paste(img, (x, y))
            images.append(canvas)
        except Exception as exc:
            logger.warning("合拼参考图加载失败 %s: %s", p, exc)

    if not images:
        raise MangaImageGenerationError(
            code="ref_compose_failed",
            user_message="无法加载任何角色参考图进行合拼。",
            retryable=False,
        )

    count = len(images)
    cols = min(count, max_cols)
    rows = (count + cols - 1) // cols
    total_w = cols * cell_size + (cols - 1) * padding
    total_h = rows * cell_size + (rows - 1) * padding
    composite = Image.new("RGB", (total_w, total_h), (255, 255, 255))

    for i, img in enumerate(images):
        col = i % cols
        row = i // cols
        x_pos = col * (cell_size + padding)
        y_pos = row * (cell_size + padding)
        composite.paste(img, (x_pos, y_pos))

        # 在每张参考图底部绘制角色名
        label = ref_labels[i] if i < len(ref_labels) and ref_labels[i] else f"角色{i + 1}"
        try:
            font = ImageFont.truetype("simhei.ttf", 20)
        except Exception:
            font = ImageFont.load_default()
        draw = ImageDraw.Draw(composite)
        bbox = draw.textbbox((0, 0), label, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        # 黑色半透明背景条
        draw.rectangle(
            [x_pos, y_pos + cell_size - th - 10, x_pos + cell_size, y_pos + cell_size],
            fill=(0, 0, 0, 200),
        )
        draw.text(
            (x_pos + (cell_size - tw) // 2, y_pos + cell_size - th - 5),
            f"「{label}」",
            fill=(255, 255, 255),
            font=font,
        )

    buf = io.BytesIO()
    composite.save(buf, format="PNG", optimize=True)

    labels = []
    for i in range(count):
        label = ref_labels[i] if i < len(ref_labels) and ref_labels[i] else f"角色{i + 1}"
        labels.append(f"「{label}」")

    desc = "REFERENCE IMAGE 1 IS A COMPOSITE REFERENCE SHEET WITH LABELED REGIONS:\n" + "\n".join(
        _composite_region_instruction(
            ref_roles[i] if ref_roles and i < len(ref_roles) else "character",
            ref_labels[i] if i < len(ref_labels) else "",
        )
        for i in range(count)
    ) + "\n"
    return buf.getvalue(), desc


async def _download_generated_image(image_entry: dict, progress_label: str) -> bytes:
    if image_entry.get("b64_json"):
        image_bytes = base64.b64decode(image_entry["b64_json"])
        if len(image_bytes) > MAX_REMOTE_IMAGE_BYTES:
            raise MangaImageGenerationError(
                code="image_too_large",
                user_message="绘图服务返回的图片过大，请调整尺寸后重试。",
                retryable=False,
            )
        logger.info("[%s] 收到 b64_json，大小 %s bytes", progress_label, len(image_bytes))
        return image_bytes
    if image_entry.get("url"):
        logger.info("[%s] 收到图片 URL，开始下载", progress_label)
        safe_url = _safe_generated_image_url(str(image_entry["url"]))
        async with httpx.AsyncClient(timeout=300, follow_redirects=False) as client:
            async with client.stream("GET", safe_url) as img_resp:
                img_resp.raise_for_status()
                image_bytes = await _read_limited_image_bytes(img_resp)
        logger.info("[%s] 图片下载完成，大小 %s bytes", progress_label, len(image_bytes))
        return image_bytes
    raise MangaImageGenerationError(
        code="invalid_response",
        user_message="绘图服务返回了不完整的数据，请重试。",
        retryable=True,
        provider_message="No b64_json or url in image response",
    )

async def _download_image_from_url(url: str, progress_label: str) -> bytes:
    safe_url = _safe_generated_image_url(url)
    last_exc: Exception | None = None
    for attempt in range(1, DOWNLOAD_RETRIES + 1):
        try:
            logger.info("[%s] 开始下载图片 URL（尝试 %s/%s）", progress_label, attempt, DOWNLOAD_RETRIES)
            timeout = httpx.Timeout(connect=45, read=300, write=30, pool=30)
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
                async with client.stream("GET", safe_url) as img_resp:
                    img_resp.raise_for_status()
                    return await _read_limited_image_bytes(img_resp)
        except httpx.ConnectError as exc:
            last_exc = exc
            if attempt < DOWNLOAD_RETRIES:
                await asyncio.sleep(DOWNLOAD_RETRY_DELAY)
                continue
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last_exc = exc
            logger.warning("[%s] 图片下载失败（尝试 %s/%s）: %s", progress_label, attempt, DOWNLOAD_RETRIES, repr(exc))
            if attempt < DOWNLOAD_RETRIES:
                await asyncio.sleep(DOWNLOAD_RETRY_DELAY)
                continue
        except Exception as exc:
            last_exc = exc
            break
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("image download failed without a specific exception")


async def _read_limited_image_bytes(response) -> bytes:
    content_length = response.headers.get("content-length")
    try:
        declared_length = int(content_length) if content_length else 0
    except (TypeError, ValueError):
        declared_length = 0
    if declared_length > MAX_REMOTE_IMAGE_BYTES:
        raise MangaImageGenerationError(
            code="image_too_large",
            user_message="绘图服务返回的图片过大，请调整尺寸后重试。",
            retryable=False,
        )
    chunks: list[bytes] = []
    total = 0
    async for chunk in response.aiter_bytes():
        total += len(chunk)
        if total > MAX_REMOTE_IMAGE_BYTES:
            raise MangaImageGenerationError(
                code="image_too_large",
                user_message="绘图服务返回的图片过大，请调整尺寸后重试。",
                retryable=False,
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _encode_image_to_data_uri(file_path: str, max_size: int = 512) -> str | None:
    """将本地图片压缩并编码为 data URI，max_size 为长边最大像素。"""
    if not os.path.isfile(file_path):
        return None
    try:
        from PIL import Image as PILImage
        from io import BytesIO

        img = Image.open(file_path).convert("RGB")
        w, h = img.size
        if max(w, h) > max_size:
            ratio = max_size / max(w, h)
            img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=85, optimize=True)
        data = buf.getvalue()
        return f"data:image/jpeg;base64,{base64.b64encode(data).decode()}"
    except Exception:
        # fallback: 直接读取原文件
        try:
            with open(file_path, "rb") as fh:
                data = fh.read()
            ext = os.path.splitext(file_path)[1].lower()
            mime_map = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
            mime = mime_map.get(ext, "image/png")
            return f"data:{mime};base64,{base64.b64encode(data).decode()}"
        except Exception:
            return None


async def generate_reference_image(
    prompt: str,
    output_path: Path,
    *,
    api_key: str | None = None,
    size: str = "1024x1024",
    ref_image_paths: list[str] | None = None,
    ref_type: str = "character",
    ref_labels: list[str] | None = None,
    ref_roles: list[str] | None = None,
    prefer_local: bool = False,
) -> str:
    """生成参考/故事板图。

    prefer_local=True 时跳过 OSS URL 直传与结果上传 OSS：结果落本地后直接返回本地路径。
    供画布运行时等以尽快回显为优先的场景使用，避免跨桶直传网络抖动阻塞节点完成。
    """
    progress_label = f"ref:{output_path.stem}"
    current_prompt = prompt.strip()
    last_err: MangaImageGenerationError | None = None
    has_refs = bool(ref_image_paths)

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            prompt_chars = len(current_prompt)
            # 粗略估算 token: 英文 ~4chars/token, 中文 ~2chars/token
            cjk_chars = sum(1 for c in current_prompt if '一' <= c <= '鿿')
            ascii_chars = prompt_chars - cjk_chars
            est_tokens = (cjk_chars // 2) + (ascii_chars // 4)
            logger.info("[%s] 开始生成（尝试 %s/%s）refs=%s prompt_chars=%d est_tokens=%d",
                        progress_label, attempt, MAX_RETRIES,
                        len(ref_image_paths) if has_refs else 0,
                        prompt_chars, est_tokens)
            async with httpx.AsyncClient(timeout=httpx.Timeout(connect=30, read=300, write=120, pool=30)) as client:
                if has_refs:
                    ref_files = []
                    valid_ref_indices: list[int] = []
                    valid_ref_roles: list[str] = []
                    for i, p in enumerate(ref_image_paths):
                        if not os.path.isfile(p):
                            logger.warning("[%s] 参考图片文件不存在: %s", progress_label, p)
                            continue
                        role = _normalize_ref_role(
                            ref_roles[i] if ref_roles and i < len(ref_roles) else ref_type
                        )
                        prepared = await run_blocking(
                            _prepare_ref_blobs,
                            [Path(p)],
                            progress_label,
                            [role],
                        )
                        if not prepared:
                            continue
                        ref_files.append(("image[]", (f"ref_{i}.png", prepared[0][1], "image/png")))
                        valid_ref_indices.append(i)
                        valid_ref_roles.append(role)

                    if ref_files:
                        # 图生图模式：参考图作为风格/角色参考，prompt 描述要生成的新图
                        if ref_roles:
                            mapping = "\n".join(
                                _reference_role_instruction(
                                    ref_roles[source_index] if source_index < len(ref_roles) else "character",
                                    ref_labels[source_index] if ref_labels and source_index < len(ref_labels) else "",
                                    attachment_index,
                                )
                                for attachment_index, source_index in enumerate(valid_ref_indices, start=1)
                            )
                            ref_guide = (
                                f"CREATE A NEW {ref_type.upper()} REFERENCE ASSET. "
                                "Use each attached image only for its declared role.\n"
                                f"REFERENCE IMAGE ROLE MAPPING:\n{mapping}\n\n"
                            )
                        elif ref_type == "style":
                            ref_guide = (
                                f"CREATE A NEW IMAGE. The attached {len(ref_files)} image(s) are STYLE "
                                f"REFERENCE SAMPLES. Match the ART STYLE of the reference EXACTLY: "
                                f"line weight, shading technique, color palette, lighting, "
                                f"and overall aesthetic must be consistent. "
                                f"The content/characters in the reference are for style illustration only "
                                f"-- create an entirely NEW image based on the prompt below. "
                                f"Do NOT reproduce the specific characters or scenes from the reference "
                                f"images.\n\n"
                            )
                        elif ref_type == "character":
                            ref_guide = (
                                f"CREATE A NEW IMAGE. The attached {len(ref_files)} image(s) are CHARACTER "
                                f"REFERENCE SHEETS. Match every character to their reference EXACTLY: "
                                f"face, hair, eyes, outfit, body proportions. "
                                f"Also match the ART STYLE of the reference: line weight, shading technique, "
                                f"color palette, lighting, and overall aesthetic must be consistent. "
                                f"Do NOT edit the reference images -- create an entirely NEW image "
                                f"with the storyboard panels specified below.\n\n"
                            )
                        elif ref_type == "scene":
                            ref_guide = (
                                f"CREATE A NEW IMAGE. The attached {len(ref_files)} image(s) are SCENE "
                                f"REFERENCE IMAGES. Preserve their environment layout, architecture, materials, "
                                f"spatial relationships and recognizable landmarks. Do not copy unrelated people.\n\n"
                            )
                        else:
                            ref_guide = (
                                f"CREATE A NEW IMAGE. The attached {len(ref_files)} image(s) are PROP "
                                f"REFERENCE IMAGES. Preserve the object's shape, materials, colors, scale and "
                                f"distinctive details. Do not reinterpret the prop as a character or scene.\n\n"
                            )
                        logger.info("[%s] 图生图请求 refs=%d prompt=%dchars", progress_label, len(ref_files), len(current_prompt))
                        # 打印完整提示词内容
                        final_api_prompt = ref_guide + current_prompt
                        logger.info("=" * 70)
                        logger.info("[%s] 发送给图片 API 的完整提示词（%d 字符）:", progress_label, len(final_api_prompt))
                        logger.info("-" * 70)
                        for log_line in final_api_prompt.split("\n"):
                            logger.info("[PROMPT] %s", log_line)
                        logger.info("-" * 70)
                        if ref_files:
                            logger.info("[%s] 附带参考图: %d 张", progress_label, len(ref_files))
                        logger.info("=" * 70)
                        resp = await client.post(
                            f"{runtime_base_url()}/images/edits",
                            files=ref_files,
                            data=_manga_edit_payload(final_api_prompt, size, valid_ref_roles),
                            headers=_image_auth_headers(api_key),
                        )
                    else:
                        logger.warning("[%s] 所有参考图片均不可用，降级为纯文本生成", progress_label)
                        resp = await client.post(
                            f"{runtime_base_url()}/images/generations",
                            json=_generation_payload(current_prompt, size),
                            headers=_image_auth_headers(api_key, json_content=True),
                        )
                else:
                    resp = await client.post(
                        f"{runtime_base_url()}/images/generations",
                        json=_generation_payload(current_prompt, size),
                        headers=_image_auth_headers(api_key, json_content=True),
                    )

            if not resp.is_success:
                raise _classify_response_error(resp, progress_label, current_prompt, False)

            data = resp.json()
            image_entry = _extract_data_image_entry(data, progress_label)

            # OSS URL 直传：跳过本地下载
            remote_key = str(output_path.relative_to(OUTPUT_DIR.parent)).replace("\\", "/") if output_path.is_absolute() else str(output_path)
            oss_url = None if prefer_local else await run_blocking(_upload_image_url_to_oss, image_entry, remote_key)
            if oss_url:
                logger.info("[%s] 角色参考图 OSS 直传成功，跳过本地下载", progress_label)
                return oss_url

            image_bytes = await run_blocking(
                normalize_image_bytes,
                await _download_generated_image(image_entry, progress_label),
            )
            output_path.parent.mkdir(parents=True, exist_ok=True)
            await run_blocking(output_path.write_bytes, image_bytes)
            logger.info("[%s] 角色参考图已保存到 %s", progress_label, output_path)
            oss_url = None if prefer_local else await run_blocking(_upload_to_oss_if_enabled, str(output_path))
            if oss_url:
                try:
                    output_path.unlink(missing_ok=True)
                except Exception:
                    pass
                return oss_url
            return str(output_path)
        except httpx.TimeoutException as exc:
            last_err = MangaImageGenerationError(
                code="timeout",
                user_message="角色参考图生成超时，请稍后重试。",
                retryable=True,
                provider_message=repr(exc),
            )
        except httpx.TransportError as exc:
            last_err = MangaImageGenerationError(
                code="network_error",
                user_message="角色参考图生成时网络异常，请稍后重试。",
                retryable=True,
                provider_message=repr(exc),
            )
        except MangaImageGenerationError as exc:
            last_err = exc
        except Exception as exc:
            last_err = MangaImageGenerationError(
                code="unknown_error",
                user_message="角色参考图生成失败，请稍后重试。",
                retryable=True,
                provider_message=repr(exc),
            )

        assert last_err is not None
        logger.error(
            "[%s] 角色参考图尝试 %s 失败: code=%s retryable=%s provider=%s",
            progress_label,
            attempt,
            last_err.code,
            last_err.retryable,
            last_err.provider_message,
        )
        if attempt < MAX_RETRIES and last_err.retryable:
            await asyncio.sleep(RETRY_DELAY)
            continue
        break

    assert last_err is not None
    raise last_err


async def generate_cover_image(
    prompt: str,
    output_path: Path,
    *,
    api_key: str | None = None,
    size: str = "1024x1792",
) -> str:
    progress_label = f"cover:{output_path.stem}"
    current_prompt = prompt.strip()
    last_err: MangaImageGenerationError | None = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logger.info("[%s] 开始生成小说封面（尝试 %s/%s）", progress_label, attempt, MAX_RETRIES)
            async with httpx.AsyncClient(timeout=httpx.Timeout(connect=30, read=300, write=120, pool=30)) as client:
                resp = await client.post(
                    f"{runtime_base_url()}/images/generations",
                    json=_generation_payload(current_prompt, size),
                    headers=_image_auth_headers(api_key, json_content=True),
                )

            if not resp.is_success:
                raise _classify_response_error(resp, progress_label, current_prompt, False)

            data = resp.json()
            image_entry = _extract_data_image_entry(data, progress_label)

            # OSS URL 直传：跳过本地下载
            remote_key = f"manga_outputs/covers/{output_path.name}"
            oss_url = await run_blocking(_upload_image_url_to_oss, image_entry, remote_key)
            if oss_url:
                logger.info("[%s] 封面 OSS 直传成功，跳过本地下载", progress_label)
                return oss_url

            image_bytes = await run_blocking(
                normalize_image_bytes,
                await _download_generated_image(image_entry, progress_label),
            )
            output_path.parent.mkdir(parents=True, exist_ok=True)
            await run_blocking(output_path.write_bytes, image_bytes)
            logger.info("[%s] 小说封面已保存到 %s", progress_label, output_path)
            oss_url = await run_blocking(_upload_to_oss_if_enabled, str(output_path))
            if oss_url:
                try:
                    output_path.unlink(missing_ok=True)
                except Exception:
                    pass
                return oss_url
            return str(output_path)
        except httpx.TimeoutException as exc:
            last_err = MangaImageGenerationError(
                code="timeout",
                user_message="封面生成超时，请稍后重试。",
                retryable=True,
                provider_message=repr(exc),
            )
        except httpx.TransportError as exc:
            last_err = MangaImageGenerationError(
                code="network_error",
                user_message="封面生成时网络异常，请稍后重试。",
                retryable=True,
                provider_message=repr(exc),
            )
        except MangaImageGenerationError as exc:
            last_err = exc
        except Exception as exc:
            last_err = MangaImageGenerationError(
                code="unknown_error",
                user_message="封面生成失败，请稍后重试。",
                retryable=True,
                provider_message=repr(exc),
            )

        assert last_err is not None
        logger.error(
            "[%s] 封面生成尝试 %s 失败: code=%s retryable=%s provider=%s",
            progress_label,
            attempt,
            last_err.code,
            last_err.retryable,
            last_err.provider_message,
        )
        if attempt < MAX_RETRIES and last_err.retryable:
            await asyncio.sleep(RETRY_DELAY)
            continue
        break

    assert last_err is not None
    raise last_err


async def edit_existing_image(
    prompt: str,
    source_image_path: Path,
    output_path: Path,
    *,
    mask_bytes: bytes | None = None,
    api_key: str | None = None,
    size: str | None = None,
    style_reference_path: Path | None = None,
    style_prompt: str | None = None,
    reference_image_paths: list[Path] | None = None,
    reference_labels: list[str] | None = None,
    reference_roles: list[str] | None = None,
) -> str:
    progress_label = f"edit:{source_image_path.stem}"
    current_prompt = prompt.strip()
    if style_prompt and style_prompt.strip():
        current_prompt = f"{current_prompt}\n\nVisual style: {style_prompt.strip()}"

    extra_references: list[tuple[Path, bytes, str, str]] = []
    style_resolved = style_reference_path.resolve() if style_reference_path and style_reference_path.exists() else None
    for index, path in enumerate(reference_image_paths or []):
        if not path.exists():
            continue
        if style_resolved and path.resolve() == style_resolved:
            continue
        try:
            data = await run_blocking(normalize_image_bytes, await run_blocking(path.read_bytes))
        except Exception as exc:
            logger.warning("重绘参考图无法加载，已跳过 path=%s error=%s", path, exc)
            continue
        label = str(reference_labels[index] if reference_labels and index < len(reference_labels) else "").strip()
        role = _normalize_ref_role(reference_roles[index] if reference_roles and index < len(reference_roles) else "character")
        extra_references.append((path, data, label, role))

    mapping_lines = ["Reference image 1 is the SOURCE MANGA PANEL to edit."]
    next_image_index = 2
    if style_resolved:
        mapping_lines.append(_reference_role_instruction("style", "画面风格参考锚点", next_image_index))
        next_image_index += 1
    for _, _, label, role in extra_references:
        mapping_lines.append(_reference_role_instruction(role, label, next_image_index))
        next_image_index += 1
    if len(mapping_lines) > 1:
        current_prompt = "REFERENCE IMAGE ROLE MAPPING:\n" + "\n".join(mapping_lines) + "\n\n" + current_prompt
    if not current_prompt:
        raise MangaImageGenerationError(
            code="missing_prompt",
            user_message="重绘提示词不能为空，请补充你希望修改的内容。",
            retryable=False,
            provider_message="missing prompt",
        )
    if not source_image_path.exists():
        raise MangaImageGenerationError(
            code="missing_source_image",
            user_message="找不到要重绘的原图，请刷新后重试。",
            retryable=False,
            provider_message=str(source_image_path),
        )

    source_bytes = await run_blocking(
        normalize_image_bytes,
        await run_blocking(source_image_path.read_bytes),
    )
    if not size:
        try:
            with Image.open(io.BytesIO(source_bytes)) as img:
                size = f"{img.width}x{img.height}"
        except Exception:
            size = _runtime_settings().size

    last_err: MangaImageGenerationError | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logger.info("[%s] 开始编辑原图（尝试 %s/%s）", progress_label, attempt, MAX_RETRIES)
            files = [
                ("image", (source_image_path.name or "source.png", io.BytesIO(source_bytes), "image/png")),
            ]
            if style_reference_path and style_reference_path.exists():
                style_bytes = await run_blocking(
                    normalize_image_bytes,
                    await run_blocking(style_reference_path.read_bytes),
                )
                files.append(("image", (style_reference_path.name or "style.png", io.BytesIO(style_bytes), "image/png")))
            for ref_path, ref_bytes, _, _ in extra_references:
                files.append(("image", (ref_path.name or "reference.png", io.BytesIO(ref_bytes), "image/png")))
            if mask_bytes:
                files.append(("mask", ("mask.png", io.BytesIO(mask_bytes), "image/png")))

            async with httpx.AsyncClient(timeout=httpx.Timeout(connect=30, read=300, write=120, pool=30)) as client:
                resp = await client.post(
                    f"{runtime_base_url()}/images/edits",
                    files=files,
                    data=_edit_payload(current_prompt, size),
                    headers=_image_auth_headers(api_key),
                )

            if not resp.is_success:
                raise _classify_response_error(resp, progress_label, current_prompt, False)

            data = resp.json()
            image_entry = _extract_data_image_entry(data, progress_label)

            # OSS URL 直传：跳过本地下载
            remote_key = str(output_path.relative_to(OUTPUT_DIR.parent)).replace("\\", "/") if output_path.is_absolute() else str(output_path)
            oss_url = await run_blocking(_upload_image_url_to_oss, image_entry, remote_key)
            if oss_url:
                logger.info("[%s] 图片编辑 OSS 直传成功，跳过本地下载", progress_label)
                return oss_url

            image_bytes = await run_blocking(
                normalize_image_bytes,
                await _download_generated_image(image_entry, progress_label),
            )
            output_path.parent.mkdir(parents=True, exist_ok=True)
            await run_blocking(output_path.write_bytes, image_bytes)
            logger.info("[%s] 图片编辑完成并保存到 %s", progress_label, output_path)
            oss_url = await run_blocking(_upload_to_oss_if_enabled, str(output_path))
            if oss_url:
                try:
                    output_path.unlink(missing_ok=True)
                except Exception:
                    pass
                return oss_url
            return str(output_path)
        except httpx.TimeoutException as exc:
            last_err = MangaImageGenerationError(
                code="timeout",
                user_message="图片重绘超时，请稍后重试。",
                retryable=True,
                provider_message=repr(exc),
            )
        except httpx.TransportError as exc:
            last_err = MangaImageGenerationError(
                code="network_error",
                user_message="图片重绘时网络异常，请稍后重试。",
                retryable=True,
                provider_message=repr(exc),
            )
        except MangaImageGenerationError as exc:
            last_err = exc
        except Exception as exc:
            last_err = MangaImageGenerationError(
                code="unknown_error",
                user_message="图片重绘失败，请稍后重试。",
                retryable=True,
                provider_message=repr(exc),
            )

        assert last_err is not None
        logger.error(
            "[%s] 图片编辑尝试 %s 失败: code=%s retryable=%s provider=%s",
            progress_label,
            attempt,
            last_err.code,
            last_err.retryable,
            last_err.provider_message,
        )
        if attempt < MAX_RETRIES and last_err.retryable:
            await asyncio.sleep(RETRY_DELAY)
            continue
        break

    assert last_err is not None
    raise last_err


async def generate_manga_image(
    prompt: str,
    chapter_id: int,
    image_number: int,
    all_scenes: list[str] | None = None,
    character_profiles: str = "",
    ref_image_paths: list[str] | None = None,
    ref_labels: list[str] | None = None,
    ref_roles: list[str] | None = None,
    color_mode: str = "bw",
    api_key: str | None = None,
    size: str | None = None,
    style_ref_path: str | None = None,
    suppress_default_style: bool = False,
) -> ImageGenerationResult:
    total_pages = len(all_scenes) if all_scenes else 1
    progress_label = f"{image_number}/{total_pages}"
    valid_refs: list[Path] = []
    valid_labels: list[str] = []
    valid_roles: list[str] = []
    for index, raw_path in enumerate(ref_image_paths or []):
        path = Path(raw_path) if raw_path else None
        if not path or not path.exists():
            continue
        try:
            with Image.open(path) as image:
                image.verify()
        except Exception as exc:
            logger.warning("漫画参考图无法解码，已跳过 path=%s error=%s", path, exc)
            continue
        valid_refs.append(path)
        valid_labels.append(str(ref_labels[index] if ref_labels and index < len(ref_labels) else "").strip())
        valid_roles.append(_normalize_ref_role(ref_roles[index] if ref_roles and index < len(ref_roles) else "character"))

    # 注入风格参考锚点图（如已选风格预设），只有成功解码才视为有效风格参考。
    has_style_ref = "style" in valid_roles
    if style_ref_path and Path(style_ref_path).exists():
        style_path = Path(style_ref_path)
        style_decodable = False
        try:
            with Image.open(style_path) as image:
                image.verify()
            style_decodable = True
        except Exception as exc:
            logger.warning("漫画风格参考图无法解码，已忽略 path=%s error=%s", style_path, exc)
        if style_decodable:
            existing_index = next(
                (index for index, path in enumerate(valid_refs) if path.resolve() == style_path.resolve()),
                None,
            )
            if existing_index is None:
                valid_refs.append(style_path)
                valid_labels.append("【画面风格参考锚点】")
                valid_roles.append("style")
            else:
                valid_labels[existing_index] = "【画面风格参考锚点】"
                valid_roles[existing_index] = "style"
            has_style_ref = True

    # 风格参考图固定放在第一位，其他参考图及其标签/角色映射保持原有相对顺序。
    if valid_refs:
        ordered = sorted(
            zip(valid_refs, valid_labels, valid_roles),
            key=lambda item: 0 if item[2] == "style" else 1,
        )
        valid_refs = [item[0] for item in ordered]
        valid_labels = [item[1] for item in ordered]
        valid_roles = [item[2] for item in ordered]

    # 构建策略列表——每个策略都保证角色参考图被使用，绝不降级到无图模式
    strategies: list[tuple[str, bool, list[tuple[str, bytes]], str]] = []
    if valid_refs:
        ref_blobs = await run_blocking(_prepare_ref_blobs, valid_refs, progress_label, valid_roles)
        if len(ref_blobs) > 1:
            # 策略1：多图编辑，并为每张参考图提供明确的资产类型映射。
            multi_desc = (
                "REFERENCE IMAGE ROLE MAPPING:\n"
                + "\n".join(
                    _reference_role_instruction(valid_roles[i], valid_labels[i], i + 1)
                    for i in range(len(ref_blobs))
                )
                + "\n"
            )
            strategies.append(("multi_edits", True, ref_blobs, multi_desc))

            # 策略2：合拼单图编辑——image[] 返回空时的后备，同样用视觉参考保证角色一致
            if "style" not in valid_roles:
                try:
                    comp_blob, comp_desc = await run_blocking(_compose_ref_sheet, valid_refs, valid_labels, valid_roles)
                    strategies.append(("composite_edits", True, [("ref_composite.png", comp_blob)], comp_desc))
                except Exception as exc:
                    logger.warning("[%s] 合拼参考图生成失败，将仅使用多图策略: %s", progress_label, exc)
        elif len(ref_blobs) == 1:
            label = valid_labels[0] if valid_labels else ""
            role = valid_roles[0] if valid_roles else "character"
            desc = _reference_role_instruction(role, label, 1) + "\n"
            strategies.append(("single_edits", True, ref_blobs, desc))
    else:
        # 无参考图可用的兜底：纯文本 generations
        strategies.append(("generations", False, [], ""))

    current_prompt = prompt.strip()
    current_scenes = list(all_scenes) if all_scenes else None
    prompt_sanitized = False
    last_err: MangaImageGenerationError | None = None

    for strategy_name, strategy_use_ref, strategy_blobs, strategy_layout in strategies:
        max_attempts = MAX_RETRIES
        for attempt in range(1, max_attempts + 1):
            full_prompt = _build_full_prompt(
                current_prompt,
                image_number=image_number,
                total_pages=total_pages,
                all_scenes=current_scenes,
                character_profiles=character_profiles,
                use_ref=strategy_use_ref,
                color_mode=color_mode,
                ref_layout_desc=strategy_layout,
                has_style_ref=has_style_ref,
                has_character_ref="character" in valid_roles,
                suppress_default_style=suppress_default_style,
            )
            # 打印完整提示词内容（用户可见 + 不可见的系统约束），方便排查生图问题
            logger.info("=" * 70)
            logger.info("[%s] 发送给图片 API 的完整提示词（%d 字符）:", progress_label, len(full_prompt))
            logger.info("-" * 70)
            for log_line in full_prompt.split("\n"):
                logger.info("[PROMPT] %s", log_line)
            logger.info("-" * 70)
            if strategy_blobs:
                logger.info("[%s] 附带参考图: %d 张", progress_label, len(strategy_blobs))
            logger.info("=" * 70)
            heartbeat_task: asyncio.Task | None = None
            try:
                mode = f"{strategy_name}({len(strategy_blobs)} refs)" if strategy_blobs else "generations"
                logger.info("[%s] 开始调用 Image2 API [%s]（尝试 %s/%s）", progress_label, mode, attempt, max_attempts)
                t0 = time.time()

                async def _heartbeat() -> None:
                    try:
                        while True:
                            await asyncio.sleep(30)
                            waited = int(time.time() - t0)
                            logger.info("[%s] 等待中... 已等待 %ss", progress_label, waited)
                    except asyncio.CancelledError:
                        return

                heartbeat_task = asyncio.create_task(_heartbeat())
                timeout = httpx.Timeout(connect=30, read=300, write=120, pool=30)
                limits = httpx.Limits(max_connections=1, max_keepalive_connections=0)
                async with httpx.AsyncClient(timeout=timeout, limits=limits) as client:
                    if strategy_blobs:
                        if len(strategy_blobs) == 1:
                            name, blob = strategy_blobs[0]
                            files = [("image", (name, io.BytesIO(blob), "image/png"))]
                        else:
                            files = [
                                ("image[]", (name, io.BytesIO(blob), "image/png"))
                                for name, blob in strategy_blobs
                            ]
                        effective_size = size or _runtime_settings().size
                        resp = await client.post(
                            f"{runtime_base_url()}/images/edits",
                            files=files,
                            data=_manga_edit_payload(full_prompt, effective_size, valid_roles),
                            headers=_image_auth_headers(api_key),
                        )
                    else:
                        effective_size = size or _runtime_settings().size
                        resp = await client.post(
                            f"{runtime_base_url()}/images/generations",
                            json=_generation_payload(full_prompt, effective_size),
                            headers=_image_auth_headers(api_key, json_content=True),
                        )

                if heartbeat_task:
                    heartbeat_task.cancel()
                if not resp.is_success:
                    raise _classify_response_error(resp, progress_label, current_prompt, prompt_sanitized)

                try:
                    data = resp.json()
                except Exception as exc:
                    raise MangaImageGenerationError(
                        code="invalid_json",
                        user_message="绘图服务返回了无法解析的数据，请重试。",
                        retryable=True,
                        provider_message=str(exc),
                    ) from exc

                logger.info("[%s] API 返回成功，耗时 %.1fs", progress_label, time.time() - t0)
                image_entry = _extract_data_image_entry(data, progress_label)

                # --- API 调用成功，后续下载/上传失败不再重试 API（避免浪费额度） ---
                try:
                    # OSS URL 直传：如果 API 返回了图片 URL 且 OSS 已配置，直接从 URL 上传到 OSS
                    chapter_dir = OUTPUT_DIR / f"chapter_{chapter_id}"
                    chapter_dir.mkdir(parents=True, exist_ok=True)
                    filename = f"panel_{image_number:02d}_{uuid.uuid4().hex[:8]}.png"
                    remote_key = f"manga_outputs/chapter_{chapter_id}/{filename}"
                    oss_url = await run_blocking(_upload_image_url_to_oss, image_entry, remote_key)
                    if oss_url:
                        logger.info("[%s] OSS URL 直传成功，跳过本地下载: %s", progress_label, oss_url)
                        return ImageGenerationResult(
                            image_path=oss_url,
                            final_prompt=current_prompt,
                            prompt_sanitized=prompt_sanitized,
                        )

                    # 回退到本地下载→保存→上传 OSS
                    image_bytes = await run_blocking(
                        normalize_image_bytes,
                        await _download_generated_image(image_entry, progress_label),
                    )

                    filepath = chapter_dir / filename
                    await run_blocking(filepath.write_bytes, image_bytes)
                    logger.info("[%s] 已保存到 %s", progress_label, filepath)

                    # OSS 上传（如已配置，上传成功后删除本地文件）
                    image_path = f"manga_outputs/chapter_{chapter_id}/{filename}"
                    oss_url = await run_blocking(_upload_to_oss_if_enabled, str(filepath))
                    if oss_url:
                        image_path = oss_url
                        try:
                            filepath.unlink(missing_ok=True)
                            logger.info("[%s] OSS 上传成功，已删除本地文件", progress_label)
                        except Exception:
                            pass

                    return ImageGenerationResult(
                        image_path=image_path,
                        final_prompt=current_prompt,
                        prompt_sanitized=prompt_sanitized,
                    )
                except Exception as download_exc:
                    # API 调用成功但下载/上传失败：不重试，直接报错
                    raise MangaImageGenerationError(
                        code="download_failed",
                        user_message=f"图片已生成但下载失败，请稍后重试。",
                        retryable=False,
                        provider_message=str(download_exc),
                    )

            except httpx.TimeoutException as exc:
                last_err = MangaImageGenerationError(
                    code="timeout",
                    user_message="绘图服务响应超时，请继续生成或稍后再试。",
                    retryable=True,
                    provider_message=repr(exc),
                )
            except httpx.TransportError as exc:
                last_err = MangaImageGenerationError(
                    code="network_error",
                    user_message="绘图服务网络异常，请检查网络后继续生成。",
                    retryable=True,
                    provider_message=repr(exc),
                )
            except MangaImageGenerationError as exc:
                last_err = exc
                # image[] 多图返回空数据时立即切换到合拼单图策略，不浪费重试次数
                if exc.code == "empty_response" and strategy_name == "multi_edits":
                    logger.warning(
                        "[%s] 多图 image[] 返回空数据，切换到合拼单图策略（仍保证角色一致性）",
                        progress_label,
                    )
                    break
            except Exception as exc:
                last_err = MangaImageGenerationError(
                    code="unknown_error",
                    user_message="绘图服务发生未知错误，请稍后继续生成。",
                    retryable=True,
                    provider_message=repr(exc),
                )
            finally:
                if heartbeat_task:
                    heartbeat_task.cancel()

            logger.error(
                "[%s] 尝试 %s 失败: code=%s retryable=%s provider=%s",
                progress_label, attempt, last_err.code, last_err.retryable, last_err.provider_message,
            )

            if last_err.should_sanitize and not prompt_sanitized:
                optimized_prompt = last_err.optimized_prompt or sanitize_scene_text(current_prompt)[0]
                if optimized_prompt != current_prompt:
                    logger.warning("[%s] 检测到内容风控，自动将当前分镜降敏后重试", progress_label)
                    current_prompt = optimized_prompt
                    prompt_sanitized = True
                    if current_scenes and 0 <= image_number - 1 < len(current_scenes):
                        current_scenes[image_number - 1] = optimized_prompt
                    continue

            if attempt < max_attempts and last_err.retryable:
                logger.info("[%s] %s秒后重试...", progress_label, RETRY_DELAY)
                await asyncio.sleep(RETRY_DELAY)
                continue
            break

        # 仅在 multi_edits 空数据时继续下一策略，其他任何失败立刻中断
        if last_err and last_err.code != "empty_response":
            break

    assert last_err is not None
    if prompt_sanitized and not last_err.optimized_prompt:
        last_err.optimized_prompt = current_prompt
    raise last_err


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


def _upload_image_url_to_oss(image_entry: dict, remote_key: str) -> str | None:
    """如果 OSS 已配置且 API 返回了图片 URL，直接从 URL 上传到 OSS。

    跳过本地下载→本地保存→上传 OSS 的流程，直接 CDN → OSS。
    大幅减少耗时，尤其避免 CDN 到本地的慢速下载。

    Args:
        image_entry: API 返回的图片条目（含 url 字段）
        remote_key: OSS 对象键

    Returns:
        OSS 公网 URL，失败返回 None
    """
    image_url = image_entry.get("url") if isinstance(image_entry, dict) else None
    if not image_url:
        return None
    if str(image_url).strip().lower().startswith("http://"):
        logger.info("OSS URL 直传仅支持 HTTPS，改用受信任 HTTP 下载后上传")
        return None
    try:
        from . import oss as oss_service
        if not oss_service.is_enabled():
            _auto_configure_oss()
        if oss_service.is_enabled():
            return oss_service.upload_from_url(str(image_url), remote_key)
    except Exception as exc:
        logger.warning("OSS URL 直传失败（将回退到本地下载）: %s", exc)
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
