import asyncio
import base64
import io
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

import httpx
from dotenv import load_dotenv
from PIL import Image

from .errors import MangaImageGenerationError, MissingApiKeyError
from .scene_safety import sanitize_scene_text

logger = logging.getLogger("image2")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")

load_dotenv()

IMAGE_API_BASE_URL = os.getenv("IMAGE_API_BASE_URL", "https://api.xbyjs.top/v1").rstrip("/")
IMAGE_API_KEY = os.getenv("IMAGE_API_KEY", "")
IMAGE_MODEL = "gpt-image-2"
IMAGE_SIZE = "1024x1536"
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "manga_outputs"

MAX_RETRIES = 3
RETRY_DELAY = 5

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


def _image_auth_headers(api_key: str | None = None, json_content: bool = False) -> dict[str, str]:
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

    if _contains_any(provider_message, QUOTA_KEYWORDS):
        return MangaImageGenerationError(
            code="quota_exhausted",
            user_message="绘图服务额度不足或 token 已耗尽，请充值或更换可用 key。",
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


def _build_manga_style(color_mode: str) -> str:
    if color_mode == "color":
        return (
            "日式彩色漫画页面，纵向多格分镜，2-6 格构图，镜头清晰，人物一致。"
            "可以使用对话气泡和音效字，但避免过度拥挤。"
        )
    return (
        "日式黑白漫画页面，纵向多格分镜，2-6 格构图，黑白高对比，网点和线稿清晰。"
        "可以使用对话气泡和音效字，但避免过度拥挤。"
    )


def _build_full_prompt(
    scene_prompt: str,
    image_number: int,
    total_pages: int,
    all_scenes: list[str] | None,
    character_profiles: str,
    use_ref: bool,
    color_mode: str,
) -> str:
    char_block = ""
    if character_profiles and not use_ref:
        char_block = f"【角色外貌设定】\n{character_profiles.strip()}\n\n"

    ref_block = ""
    if use_ref:
        ref_block = (
            "【人物一致性要求】\n"
            "请严格保持参考图中角色的发型、脸型、服装和整体气质，不要凭空创造新外貌。\n\n"
        )

    style_block = _build_manga_style(color_mode)
    if all_scenes:
        script_context = "\n".join(f"第{i + 1}页：{scene}" for i, scene in enumerate(all_scenes))
        return (
            f"{ref_block}{char_block}"
            f"你正在绘制第 {image_number}/{total_pages} 页漫画。\n"
            f"完整分镜如下，请保持人物、服装和镜头风格一致：\n{script_context}\n\n"
            f"当前只绘制第 {image_number} 页。\n"
            f"{style_block}\n"
            f"{scene_prompt}"
        )
    return f"{ref_block}{char_block}{style_block}\n{scene_prompt}"


def _prepare_ref_blobs(valid_refs: list[Path], progress_label: str) -> list[tuple[str, bytes]]:
    ref_blobs: list[tuple[str, bytes]] = []
    for idx, ref_path in enumerate(valid_refs, start=1):
        try:
            img = Image.open(ref_path)
            max_side = 1024
            ratio = min(max_side / img.width, max_side / img.height)
            if ratio < 1:
                img = img.resize((int(img.width * ratio), int(img.height * ratio)), Image.LANCZOS)
            buf = io.BytesIO()
            img.convert("RGBA").save(buf, format="PNG", optimize=True)
            blob = buf.getvalue()
            ref_blobs.append((f"ref{idx}.png", blob))
            logger.info("[%s] 参考图 %s 已加载: %s -> %.0f KB", progress_label, idx, ref_path.name, len(blob) / 1024)
        except Exception as exc:
            logger.warning("[%s] 参考图加载失败 %s: %s", progress_label, ref_path, exc)
    return ref_blobs


async def _download_generated_image(image_entry: dict, progress_label: str) -> bytes:
    if image_entry.get("b64_json"):
        image_bytes = base64.b64decode(image_entry["b64_json"])
        logger.info("[%s] 收到 b64_json，大小 %s bytes", progress_label, len(image_bytes))
        return image_bytes
    if image_entry.get("url"):
        logger.info("[%s] 收到图片 URL，开始下载", progress_label)
        async with httpx.AsyncClient(timeout=120) as client:
            img_resp = await client.get(image_entry["url"])
            img_resp.raise_for_status()
            image_bytes = img_resp.content
        logger.info("[%s] 图片下载完成，大小 %s bytes", progress_label, len(image_bytes))
        return image_bytes
    raise MangaImageGenerationError(
        code="invalid_response",
        user_message="绘图服务返回了不完整的数据，请重试。",
        retryable=True,
        provider_message="No b64_json or url in image response",
    )


async def generate_manga_image(
    prompt: str,
    chapter_id: int,
    image_number: int,
    all_scenes: list[str] | None = None,
    character_profiles: str = "",
    ref_image_paths: list[str] | None = None,
    color_mode: str = "bw",
    api_key: str | None = None,
) -> ImageGenerationResult:
    total_pages = len(all_scenes) if all_scenes else 1
    progress_label = f"{image_number}/{total_pages}"
    valid_refs = [Path(p) for p in (ref_image_paths or []) if p and Path(p).exists()]
    use_ref = bool(valid_refs)
    ref_blobs = _prepare_ref_blobs(valid_refs, progress_label)

    current_prompt = prompt.strip()
    current_scenes = list(all_scenes) if all_scenes else None
    prompt_sanitized = False
    last_err: MangaImageGenerationError | None = None

    for attempt in range(1, MAX_RETRIES + 1):
        full_prompt = _build_full_prompt(
            current_prompt,
            image_number=image_number,
            total_pages=total_pages,
            all_scenes=current_scenes,
            character_profiles=character_profiles,
            use_ref=use_ref,
            color_mode=color_mode,
        )
        heartbeat_task: asyncio.Task | None = None
        try:
            mode = f"edits({len(ref_blobs)} refs)" if ref_blobs else "generations"
            logger.info("[%s] 开始调用 Image2 API [%s]（尝试 %s/%s）", progress_label, mode, attempt, MAX_RETRIES)
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
            timeout = httpx.Timeout(connect=30, read=600, write=120, pool=30)
            limits = httpx.Limits(max_connections=1, max_keepalive_connections=0)
            async with httpx.AsyncClient(timeout=timeout, limits=limits) as client:
                if ref_blobs:
                    files = [("image", (ref_blobs[0][0], io.BytesIO(ref_blobs[0][1]), "image/png"))] if len(ref_blobs) == 1 else [
                        ("image[]", (name, io.BytesIO(blob), "image/png")) for name, blob in ref_blobs
                    ]
                    resp = await client.post(
                        f"{IMAGE_API_BASE_URL}/images/edits",
                        files=files,
                        data={"model": IMAGE_MODEL, "prompt": full_prompt, "size": IMAGE_SIZE},
                        headers=_image_auth_headers(api_key),
                    )
                else:
                    resp = await client.post(
                        f"{IMAGE_API_BASE_URL}/images/generations",
                        json={"model": IMAGE_MODEL, "prompt": full_prompt, "size": IMAGE_SIZE},
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
            image_entry = data["data"][0]
            image_bytes = normalize_image_bytes(await _download_generated_image(image_entry, progress_label))

            chapter_dir = OUTPUT_DIR / f"chapter_{chapter_id}"
            chapter_dir.mkdir(parents=True, exist_ok=True)
            filename = f"panel_{image_number:02d}_{uuid.uuid4().hex[:8]}.png"
            filepath = chapter_dir / filename
            filepath.write_bytes(image_bytes)
            logger.info("[%s] 已保存到 %s", progress_label, filepath)
            return ImageGenerationResult(
                image_path=f"manga_outputs/chapter_{chapter_id}/{filename}",
                final_prompt=current_prompt,
                prompt_sanitized=prompt_sanitized,
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
            progress_label,
            attempt,
            last_err.code,
            last_err.retryable,
            last_err.provider_message,
        )

        if last_err.should_sanitize and not prompt_sanitized:
            optimized_prompt = last_err.optimized_prompt or _sanitize_scene_prompt(current_prompt)
            if optimized_prompt != current_prompt:
                logger.warning("[%s] 检测到内容风控，自动将当前分镜降敏后重试", progress_label)
                current_prompt = optimized_prompt
                prompt_sanitized = True
                if current_scenes and 0 <= image_number - 1 < len(current_scenes):
                    current_scenes[image_number - 1] = optimized_prompt
                continue

        if attempt < MAX_RETRIES and last_err.retryable:
            logger.info("[%s] %s秒后重试...", progress_label, RETRY_DELAY)
            await asyncio.sleep(RETRY_DELAY)
            continue
        break

    assert last_err is not None
    if prompt_sanitized and not last_err.optimized_prompt:
        last_err.optimized_prompt = current_prompt
    raise last_err
