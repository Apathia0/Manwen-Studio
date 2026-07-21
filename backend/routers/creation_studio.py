"""独立创作台的素材、生成任务与历史记录 API。"""

from __future__ import annotations

import base64
import datetime
import hashlib
import hmac
import logging
import os
import time
import uuid
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from PIL import Image
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import get_db
from models import (
    AiChannel,
    AiModel,
    CreationStudioAsset,
    CreationStudioJob,
    CreationStudioJobInput,
)
from services.creation_studio import execute_creation_studio_job
from services.ai.channels import validate_remote_media_url
from services.ai.context import AIExecutionContext
from services.ai.crypto_secrets import get_secret_key_material
from services.ai.resolver import begin_ai_call, complete_ai_call, resolve_model
from services import video_adapter
from services import video_api as video_api_service
from services.task_manager import task_manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/creation-studio", tags=["creation-studio"])

BACKEND_DIR = Path(__file__).resolve().parent.parent
MANGA_OUTPUTS_DIR = BACKEND_DIR / "manga_outputs"
MAX_IMAGE_BYTES = 15 * 1024 * 1024
MAX_IMAGE_EDGE = 8192
MAX_IMAGE_PIXELS = 40_000_000
ALLOWED_IMAGE_FORMATS = {"PNG", "JPEG", "WEBP"}
IMAGE_FORMAT_SUFFIX = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp"}
ACTIVE_STATUSES = {"queued", "running", "cancel_requested"}
_media_access_secret = os.getenv("CREATION_STUDIO_MEDIA_SECRET", "").strip() or get_secret_key_material()
if len(_media_access_secret) < 32:
    raise RuntimeError("CREATION_STUDIO_MEDIA_SECRET 必须至少包含 32 个字符")
MEDIA_ACCESS_SECRET = _media_access_secret.encode("utf-8")
MEDIA_ACCESS_TTL_SECONDS = 15 * 60


def _main():
    import sys

    module = sys.modules.get("main") or sys.modules.get("__main__")
    if module is None:
        raise RuntimeError("main module not loaded")
    return module


def _require_user(request: Request, db: Session):
    return _main()._require_user(request, db)


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


class CreationStudioJobCreate(BaseModel):
    model_config = {"protected_namespaces": ()}

    media_kind: str
    prompt: str = Field(min_length=1, max_length=12000)
    negative_prompt: str | None = Field(default=None, max_length=4000)
    model_id: int | None = None
    asset_ids: list[int] = Field(default_factory=list, max_length=9)
    count: int = Field(default=1, ge=1, le=4)
    width: int = Field(default=1024, ge=256, le=2048)
    height: int = Field(default=1024, ge=256, le=2048)
    quality: str = "auto"
    reference_mode: str = "character"
    aspect_ratio: str = "16:9"
    resolution: str = "720P"
    duration_seconds: int = Field(default=5, ge=4, le=15)


def _validate_video_submission_capabilities(
    video_capabilities: dict[str, Any] | None,
    payload: CreationStudioJobCreate,
    reference_count: int,
) -> None:
    """在预扣积分前校验模型公开的视频约束。"""
    if not isinstance(video_capabilities, dict):
        return
    limits = video_capabilities.get("limits")
    if not isinstance(limits, dict):
        return
    ratios = limits.get("aspect_ratios")
    if isinstance(ratios, list) and payload.aspect_ratio not in ratios:
        raise HTTPException(400, "当前视频模型不支持该画面比例")
    resolutions = limits.get("resolutions")
    if isinstance(resolutions, list) and payload.resolution not in resolutions:
        raise HTTPException(400, "当前视频模型不支持该清晰度")
    maximum_references = limits.get("max_reference_images")
    if isinstance(maximum_references, int) and reference_count > maximum_references:
        raise HTTPException(400, "参考图数量超过当前视频模型限制")
    duration = limits.get("duration_seconds")
    if isinstance(duration, dict):
        allowed = duration.get("allowed")
        if isinstance(allowed, list) and payload.duration_seconds not in allowed:
            raise HTTPException(400, "当前视频模型不支持该时长")
        minimum, maximum = duration.get("min"), duration.get("max")
        if isinstance(minimum, int) and payload.duration_seconds < minimum:
            raise HTTPException(400, "视频时长低于当前模型最小限制")
        if isinstance(maximum, int) and payload.duration_seconds > maximum:
            raise HTTPException(400, "视频时长超过当前模型最大限制")
    input_modes = video_capabilities.get("input_modes")
    requested_mode = "image_to_video" if reference_count else "text_to_video"
    if isinstance(input_modes, list) and requested_mode not in input_modes:
        raise HTTPException(400, "当前视频模型不支持该输入模式")


def _serialize_asset(asset: CreationStudioAsset) -> dict[str, Any]:
    return {
        "id": asset.id,
        "job_id": asset.job_id,
        "media_type": asset.media_type,
        "role": asset.role,
        "public_url": asset.public_url,
        "original_name": asset.original_name,
        "mime_type": asset.mime_type,
        "file_size": asset.file_size,
        "width": asset.width,
        "height": asset.height,
        "duration_seconds": asset.duration_seconds,
        "status": asset.status,
        "created_at": asset.created_at,
    }


def _serialize_job(db: Session, job: CreationStudioJob) -> dict[str, Any]:
    output = db.get(CreationStudioAsset, job.output_asset_id) if job.output_asset_id else None
    links = (
        db.query(CreationStudioJobInput)
        .filter(CreationStudioJobInput.job_id == job.id)
        .order_by(CreationStudioJobInput.position.asc(), CreationStudioJobInput.id.asc())
        .all()
    )
    asset_ids = [link.asset_id for link in links]
    inputs = []
    if asset_ids:
        rows = db.query(CreationStudioAsset).filter(CreationStudioAsset.id.in_(asset_ids)).all()
        by_id = {row.id: row for row in rows}
        inputs = [_serialize_asset(by_id[asset_id]) for asset_id in asset_ids if asset_id in by_id]
    public_parameters = {
        key: value
        for key, value in (job.parameters_json or {}).items()
        if not str(key).startswith("_")
    }
    return {
        "id": job.id,
        "media_kind": job.media_kind,
        "generation_mode": job.generation_mode,
        "prompt": job.prompt,
        "negative_prompt": job.negative_prompt,
        "model_id": job.model_id,
        "model_key": job.model_key,
        "parameters": public_parameters,
        "status": job.status,
        "stage": job.stage,
        "progress": job.progress,
        "background_task_id": job.background_task_id,
        "provider_job_id": job.provider_job_id,
        "error_message": job.error_message,
        "retry_of_job_id": job.retry_of_job_id,
        "inputs": inputs,
        "output": _serialize_asset(output) if output else None,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "completed_at": job.completed_at,
        "updated_at": job.updated_at,
    }


def _owned_asset(db: Session, user_id: int, asset_id: int) -> CreationStudioAsset:
    asset = (
        db.query(CreationStudioAsset)
        .filter(
            CreationStudioAsset.id == asset_id,
            CreationStudioAsset.owner_user_id == user_id,
            CreationStudioAsset.deleted_at.is_(None),
        )
        .first()
    )
    if not asset:
        raise HTTPException(404, "参考素材不存在")
    return asset


def _owned_job(db: Session, user_id: int, job_id: int) -> CreationStudioJob:
    job = (
        db.query(CreationStudioJob)
        .filter(
            CreationStudioJob.id == job_id,
            CreationStudioJob.owner_user_id == user_id,
            CreationStudioJob.deleted_at.is_(None),
        )
        .first()
    )
    if not job:
        raise HTTPException(404, "生成记录不存在")
    return job


def _safe_unlink_asset(asset: CreationStudioAsset) -> bool:
    value = str(asset.storage_path or "").strip()
    if not value:
        return True
    if value.startswith(("http://", "https://")):
        from services import oss as oss_service

        if not oss_service.is_enabled():
            oss_service.auto_configure_from_db()
        return oss_service.delete_by_url(value)
    path = Path(value)
    try:
        resolved = path.resolve()
        allowed_roots = [
            (BACKEND_DIR / "manga_outputs" / "creative_studio").resolve(),
            (BACKEND_DIR / "video_outputs" / "creative_studio").resolve(),
        ]
        if any(resolved.is_relative_to(root) for root in allowed_roots):
            resolved.unlink(missing_ok=True)
            return True
    except OSError:
        logger.warning("删除创作台素材失败 asset_id=%s path=%s", asset.id, value)
    return False


def _create_media_access_token(asset_id: int, user_id: int) -> str:
    expires_at = int(time.time()) + MEDIA_ACCESS_TTL_SECONDS
    payload = f"{asset_id}:{user_id}:{expires_at}"
    signature = hmac.new(MEDIA_ACCESS_SECRET, payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{payload}:{signature}".encode("utf-8")).decode("ascii").rstrip("=")


def _verify_media_access_token(token: str, asset_id: int) -> int | None:
    try:
        padded = token + "=" * (-len(token) % 4)
        decoded = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
        raw_asset_id, raw_user_id, raw_expires_at, signature = decoded.split(":", 3)
        payload = f"{raw_asset_id}:{raw_user_id}:{raw_expires_at}"
        expected = hmac.new(MEDIA_ACCESS_SECRET, payload.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return None
        if int(raw_asset_id) != asset_id or int(raw_expires_at) < int(time.time()):
            return None
        return int(raw_user_id)
    except (ValueError, UnicodeDecodeError):
        return None


def _reserve_job_billing(job: CreationStudioJob, db: Session) -> AIExecutionContext:
    params = job.parameters_json or {}
    estimate_kwargs = (
        {"video_seconds": int(params.get("duration_seconds") or 5)}
        if job.media_kind == "video"
        else {"image_count": 1}
    )
    ctx = begin_ai_call(
        db,
        user_id=job.owner_user_id,
        modality=job.media_kind,
        task_type=f"creation_studio.{job.media_kind}",
        credential_mode=str(params.get("_credential_mode") or "") or None,
        model_id=job.model_id,
        request_id=f"studio-{job.media_kind}-{job.id}",
        estimate_kwargs=estimate_kwargs,
    )
    if params.get("_custom_base_url") or params.get("_custom_model_key"):
        ctx = replace(
            ctx,
            base_url=str(params.get("_custom_base_url") or ctx.base_url),
            model_key=str(params.get("_custom_model_key") or ctx.model_key),
        )
    job.model_id = ctx.model_id
    job.model_key = ctx.model_key
    existing_runtime = (job.parameters_json or {}).get("_runtime")
    if job.media_kind == "video" and isinstance(existing_runtime, dict):
        snapshot_model_id = existing_runtime.get("model_id")
        job.model_id = snapshot_model_id if isinstance(snapshot_model_id, int) else job.model_id
        job.model_key = str(existing_runtime.get("model") or job.model_key or "").strip()
    elif job.media_kind == "video":
        from services.ai.crypto_secrets import encrypt_secret

        params = dict(job.parameters_json or {})
        effective_adapter = params.get("_effective_video_adapter")
        if effective_adapter is None:
            effective_adapter = ctx.adapter_type
        if "_effective_video_capabilities" in params:
            video_capabilities = params.get("_effective_video_capabilities")
        else:
            model = db.get(AiModel, ctx.model_id) if ctx.model_id else None
            raw_capabilities = model.capabilities_json if model else None
            video_capabilities = raw_capabilities.get("video") if isinstance(raw_capabilities, dict) else None
        params["_runtime"] = {
            "adapter_type": video_adapter.normalize_video_adapter_type(
                effective_adapter,
                legacy_default=True,
            ),
            "base_url": str(ctx.base_url or "").rstrip("/"),
            "model": str(ctx.model_key or "").strip(),
            "model_id": ctx.model_id,
            "video_capabilities": deepcopy(video_capabilities)
            if isinstance(video_capabilities, dict)
            else None,
            "secret_ciphertext": encrypt_secret(ctx.api_key or ""),
        }
        params.pop("_effective_video_adapter", None)
        params.pop("_effective_video_capabilities", None)
        job.parameters_json = params
    db.commit()
    return ctx


async def _enqueue_job(
    job: CreationStudioJob,
    db: Session,
    billing_ctx: AIExecutionContext,
) -> None:
    task_id = f"studio-{uuid.uuid4().hex}"
    job.background_task_id = task_id
    job.status = "queued"
    job.stage = "queued"
    job.progress = 0
    db.commit()
    await task_manager.submit_task(
        task_id,
        f"creation_studio.{job.media_kind}",
        execute_creation_studio_job,
        studio_job_id=job.id,
        billing_ctx=billing_ctx,
        timeout=1800.0,
        max_retries=0,
        quota_user_id=job.owner_user_id,
        quota_feature_key=f"creation_studio.{job.media_kind}",
        quota_usage_event_id=billing_ctx.usage_event_id,
        metadata={
            "studio_job_id": job.id,
            "owner_user_id": job.owner_user_id,
            "media_kind": job.media_kind,
            "running_stage": "starting",
            "running_message": "正在准备生成任务...",
        },
    )


@router.post("/assets")
async def upload_asset(
    request: Request,
    file: UploadFile = File(...),
    media_type: str = Form("image"),
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    if media_type != "image":
        raise HTTPException(400, "当前版本仅支持上传参考图片")

    upload_dir = MANGA_OUTPUTS_DIR / "creative_studio" / f"user_{user.id}" / "references"
    upload_dir.mkdir(parents=True, exist_ok=True)
    temp_path = upload_dir / f"upload_{uuid.uuid4().hex}.tmp"
    digest = hashlib.sha256()
    total = 0
    try:
        with temp_path.open("wb") as target:
            while chunk := await file.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_IMAGE_BYTES:
                    raise HTTPException(413, "参考图片不能超过 15MB")
                digest.update(chunk)
                target.write(chunk)

        try:
            with Image.open(temp_path) as image:
                image.verify()
            with Image.open(temp_path) as image:
                image_format = str(image.format or "").upper()
                width, height = image.size
        except Exception as exc:
            raise HTTPException(400, "上传文件不是有效图片") from exc
        if image_format not in ALLOWED_IMAGE_FORMATS:
            raise HTTPException(400, "仅支持 PNG、JPG 和 WebP 图片")
        if width > MAX_IMAGE_EDGE or height > MAX_IMAGE_EDGE or width * height > MAX_IMAGE_PIXELS:
            raise HTTPException(400, "图片尺寸过大，最长边不能超过 8192 像素且总像素不能超过 4000 万")

        sha256 = digest.hexdigest()
        existing = (
            db.query(CreationStudioAsset)
            .filter(
                CreationStudioAsset.owner_user_id == user.id,
                CreationStudioAsset.sha256 == sha256,
                CreationStudioAsset.role == "upload",
                CreationStudioAsset.deleted_at.is_(None),
            )
            .first()
        )
        if existing:
            temp_path.unlink(missing_ok=True)
            return {"asset": _serialize_asset(existing), "deduplicated": True}

        suffix = IMAGE_FORMAT_SUFFIX[image_format]
        final_path = upload_dir / f"ref_{uuid.uuid4().hex}{suffix}"
        temp_path.replace(final_path)
        asset = CreationStudioAsset(
            owner_user_id=user.id,
            media_type="image",
            role="upload",
            storage_path=str(final_path),
            public_url="",
            original_name=(file.filename or "参考图片")[:255],
            mime_type=f"image/{'jpeg' if image_format == 'JPEG' else image_format.lower()}",
            file_size=total,
            width=width,
            height=height,
            sha256=sha256,
            status="ready",
        )
        db.add(asset)
        db.flush()
        asset.public_url = f"/api/creation-studio/assets/{asset.id}/content"
        db.commit()
        db.refresh(asset)
        return {"asset": _serialize_asset(asset), "deduplicated": False}
    finally:
        await file.close()
        temp_path.unlink(missing_ok=True)


@router.get("/assets")
async def list_assets(request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    assets = (
        db.query(CreationStudioAsset)
        .filter(
            CreationStudioAsset.owner_user_id == user.id,
            CreationStudioAsset.role == "upload",
            CreationStudioAsset.deleted_at.is_(None),
        )
        .order_by(CreationStudioAsset.created_at.desc(), CreationStudioAsset.id.desc())
        .limit(100)
        .all()
    )
    return {"assets": [_serialize_asset(asset) for asset in assets]}


@router.get("/assets/{asset_id}/content")
async def get_asset_content(
    asset_id: int,
    request: Request,
    access_token: str | None = None,
    db: Session = Depends(get_db),
):
    if access_token:
        user_id = _verify_media_access_token(access_token, asset_id)
        if user_id is None:
            raise HTTPException(401, "素材访问链接无效或已过期")
    else:
        user_id = _require_user(request, db).id
    asset = _owned_asset(db, user_id, asset_id)
    value = str(asset.storage_path or "").strip()
    if not value:
        raise HTTPException(404, "素材文件不存在")
    if not value.startswith(("http://", "https://")):
        path = Path(value).resolve()
        allowed_roots = [
            (BACKEND_DIR / "manga_outputs" / "creative_studio").resolve(),
            (BACKEND_DIR / "video_outputs" / "creative_studio").resolve(),
        ]
        if not any(path.is_relative_to(root) for root in allowed_roots) or not path.is_file():
            raise HTTPException(404, "素材文件不存在")
        return FileResponse(path, media_type=asset.mime_type or None)

    remote_url = validate_remote_media_url(value)
    forwarded_headers = {}
    if request.headers.get("range"):
        forwarded_headers["Range"] = request.headers["range"]
    client = httpx.AsyncClient(timeout=httpx.Timeout(connect=15, read=600, write=30, pool=30), follow_redirects=False)
    upstream = await client.send(
        client.build_request("GET", remote_url, headers=forwarded_headers),
        stream=True,
    )
    if upstream.status_code >= 400:
        await upstream.aclose()
        await client.aclose()
        raise HTTPException(502, "远程素材暂时不可用")

    async def stream_remote():
        try:
            async for chunk in upstream.aiter_bytes():
                yield chunk
        finally:
            await upstream.aclose()
            await client.aclose()

    response_headers = {
        key: upstream.headers[key]
        for key in ("content-length", "content-range", "accept-ranges")
        if key in upstream.headers
    }
    return StreamingResponse(
        stream_remote(),
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type") or asset.mime_type,
        headers=response_headers,
    )


@router.get("/assets/{asset_id}/access-url")
async def get_asset_access_url(asset_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    asset = _owned_asset(db, user.id, asset_id)
    if asset.media_type != "video":
        raise HTTPException(400, "仅视频素材需要流式访问链接")
    token = _create_media_access_token(asset.id, user.id)
    return {"url": f"/api/creation-studio/assets/{asset.id}/content?access_token={token}"}


@router.delete("/assets/{asset_id}")
async def delete_asset(asset_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    asset = _owned_asset(db, user.id, asset_id)
    in_use = db.query(CreationStudioJobInput.id).filter(CreationStudioJobInput.asset_id == asset.id).first()
    if in_use:
        raise HTTPException(409, "该素材已被生成记录引用，暂时不能删除")
    if not _safe_unlink_asset(asset):
        raise HTTPException(502, "素材文件删除失败，请稍后重试")
    asset.deleted_at = _utcnow()
    asset.status = "deleted"
    db.commit()
    return {"ok": True}


@router.post("/jobs")
async def create_jobs(payload: CreationStudioJobCreate, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    media_kind = payload.media_kind.strip().lower()
    if media_kind not in {"image", "video"}:
        raise HTTPException(400, "创作类型必须是 image 或 video")
    if media_kind == "video" and payload.count != 1:
        raise HTTPException(400, "视频任务每次只能生成 1 个结果")
    if payload.width % 16 or payload.height % 16:
        raise HTTPException(400, "图片宽高必须是 16 的倍数")
    if payload.quality not in {"auto", "high", "medium", "low"}:
        raise HTTPException(400, "图片质量参数无效")
    if payload.reference_mode not in {"character", "style"}:
        raise HTTPException(400, "参考图用途参数无效")
    if payload.aspect_ratio not in {"16:9", "9:16", "1:1", "4:3", "3:4"}:
        raise HTTPException(400, "视频画面比例无效")
    if payload.resolution not in {"480P", "720P", "1080P", "1K", "2K", "4K"}:
        raise HTTPException(400, "视频清晰度无效")
    selected_model = None
    if payload.model_id is not None:
        selected_model = db.get(AiModel, payload.model_id)
        if (
            not selected_model
            or not selected_model.enabled
            or not selected_model.user_visible
            or selected_model.modality != media_kind
        ):
            raise HTTPException(400, "所选模型不存在、不可用或类型不匹配")

    main_mod = _main()
    credential_mode = main_mod._request_credential_mode(request, db)
    custom_upstream = main_mod._resolve_user_upstream_override(
        request,
        db,
        user=user,
        modality=media_kind,
        mode=credential_mode,
    )
    capabilities = main_mod._user_api_override_capabilities(user, db)
    if credential_mode == "user_key" and not custom_upstream and not capabilities["can_override_api_key"]:
        raise HTTPException(403, "管理员未授权当前账号使用自定义 API Key")

    if media_kind == "video" and selected_model is None:
        selected_model = resolve_model(
            db,
            user.id,
            modality="video",
            task_type="creation_studio.video",
        )

    assets = [_owned_asset(db, user.id, asset_id) for asset_id in dict.fromkeys(payload.asset_ids)]
    if any(asset.media_type != "image" for asset in assets):
        raise HTTPException(400, "当前模型输入仅支持参考图片")
    adapter_type: str | None = None
    video_capabilities: dict[str, Any] | None = None
    if media_kind == "video":
        channel = db.get(AiChannel, selected_model.channel_id) if selected_model else None
        source_adapter_type = video_adapter.normalize_video_adapter_type(
            getattr(channel, "adapter_type", None),
            legacy_default=True,
        )
        adapter_type = (
            video_adapter.VIDEO_ADAPTER_LINGDONG
            if custom_upstream
            else source_adapter_type
        )
        raw_capabilities = selected_model.capabilities_json if selected_model else None
        model_video_capabilities = (
            raw_capabilities.get("video") if isinstance(raw_capabilities, dict) else None
        )
        video_capabilities = (
            model_video_capabilities
            if not custom_upstream or source_adapter_type == video_adapter.VIDEO_ADAPTER_LINGDONG
            else None
        )
        if adapter_type == video_adapter.VIDEO_ADAPTER_OPENAI:
            video_adapter._openai_video_config(
                video_capabilities,
                aspect_ratio=payload.aspect_ratio,
                size=payload.resolution,
                duration_seconds=payload.duration_seconds,
                reference_count=len(assets),
            )
        else:
            _validate_video_submission_capabilities(video_capabilities, payload, len(assets))
            video_api_service.validate_legacy_model_duration(
                model=str(
                    (custom_upstream or {}).get("model_key")
                    or getattr(selected_model, "model_key", "")
                    or ""
                ),
                duration_seconds=payload.duration_seconds,
                video_capabilities=video_capabilities,
            )

    parameters = {
        "size": f"{payload.width}x{payload.height}",
        "width": payload.width,
        "height": payload.height,
        "quality": payload.quality,
        "reference_mode": payload.reference_mode,
        "aspect_ratio": payload.aspect_ratio,
        "resolution": payload.resolution,
        "duration_seconds": payload.duration_seconds,
        "_credential_mode": credential_mode,
        "_custom_base_url": (custom_upstream or {}).get("base_url"),
        "_custom_model_key": (custom_upstream or {}).get("model_key"),
    }
    if media_kind == "video":
        if adapter_type is None:
            raise RuntimeError("创作台视频适配器未解析")
        parameters["_effective_video_adapter"] = adapter_type
        parameters["_effective_video_capabilities"] = (
            deepcopy(video_capabilities) if isinstance(video_capabilities, dict) else None
        )
    jobs: list[CreationStudioJob] = []
    for _ in range(payload.count):
        job = CreationStudioJob(
            owner_user_id=user.id,
            media_kind=media_kind,
            generation_mode=("image_to_video" if media_kind == "video" and assets else "text_to_video")
            if media_kind == "video"
            else ("reference_to_image" if assets else "text_to_image"),
            prompt=payload.prompt.strip(),
            negative_prompt=(payload.negative_prompt or "").strip() or None,
            model_id=selected_model.id if selected_model else payload.model_id,
            parameters_json=parameters,
            status="queued",
            stage="queued",
            progress=0,
        )
        db.add(job)
        db.flush()
        for position, asset in enumerate(assets):
            db.add(
                CreationStudioJobInput(
                    job_id=job.id,
                    asset_id=asset.id,
                    input_role=payload.reference_mode,
                    position=position,
                )
            )
        jobs.append(job)
    db.commit()

    billing_contexts: list[AIExecutionContext] = []
    try:
        for job in jobs:
            billing_contexts.append(_reserve_job_billing(job, db))
    except Exception:
        db.rollback()
        for ctx in billing_contexts:
            complete_ai_call(db, ctx, success=False, error_code="batch_reservation_failed")
        for job in jobs:
            db.delete(job)
        db.commit()
        raise

    submitted_task_ids: list[str] = []
    try:
        for job, billing_ctx in zip(jobs, billing_contexts, strict=True):
            await _enqueue_job(job, db, billing_ctx)
            if job.background_task_id:
                submitted_task_ids.append(job.background_task_id)
    except Exception:
        for task_id in submitted_task_ids:
            task_manager.cancel_task(task_id)
        for ctx in billing_contexts:
            complete_ai_call(db, ctx, success=False, error_code="task_submission_failed")
        for job in jobs:
            job.status = "failed"
            job.stage = "failed"
            job.error_message = "任务提交失败，预扣积分已释放"
            job.completed_at = _utcnow()
        db.commit()
        raise
    return {"jobs": [_serialize_job(db, job) for job in jobs]}


@router.get("/jobs")
async def list_jobs(
    request: Request,
    media_kind: str | None = None,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    query = db.query(CreationStudioJob).filter(
        CreationStudioJob.owner_user_id == user.id,
        CreationStudioJob.deleted_at.is_(None),
    )
    if media_kind in {"image", "video"}:
        query = query.filter(CreationStudioJob.media_kind == media_kind)
    jobs = query.order_by(CreationStudioJob.created_at.desc(), CreationStudioJob.id.desc()).limit(
        max(1, min(100, limit))
    ).all()
    return {"jobs": [_serialize_job(db, job) for job in jobs]}


@router.get("/jobs/{job_id}")
async def get_job(job_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    return {"job": _serialize_job(db, _owned_job(db, user.id, job_id))}


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    job = _owned_job(db, user.id, job_id)
    if job.status not in ACTIVE_STATUSES:
        raise HTTPException(409, "当前任务状态不能取消")
    accepted = bool(job.background_task_id and task_manager.request_cancellation(job.background_task_id))
    if not accepted:
        raise HTTPException(409, "任务执行进程已结束，无法取消")
    job.status = "cancel_requested"
    job.stage = "cancel_requested"
    db.commit()
    return {"job": _serialize_job(db, job)}


@router.post("/jobs/{job_id}/retry")
async def retry_job(job_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    source = _owned_job(db, user.id, job_id)
    if source.status in ACTIVE_STATUSES:
        raise HTTPException(409, "任务仍在执行，不能重试")
    clone = CreationStudioJob(
        owner_user_id=source.owner_user_id,
        media_kind=source.media_kind,
        generation_mode=source.generation_mode,
        prompt=source.prompt,
        negative_prompt=source.negative_prompt,
        model_id=source.model_id,
        model_key=source.model_key,
        parameters_json=deepcopy(source.parameters_json or {}),
        status="queued",
        stage="queued",
        progress=0,
        retry_of_job_id=source.id,
    )
    db.add(clone)
    db.flush()
    links = db.query(CreationStudioJobInput).filter(CreationStudioJobInput.job_id == source.id).all()
    for link in links:
        db.add(
            CreationStudioJobInput(
                job_id=clone.id,
                asset_id=link.asset_id,
                input_role=link.input_role,
                position=link.position,
            )
        )
    db.commit()
    try:
        billing_ctx = _reserve_job_billing(clone, db)
    except Exception:
        db.rollback()
        db.delete(clone)
        db.commit()
        raise
    try:
        await _enqueue_job(clone, db, billing_ctx)
    except Exception:
        complete_ai_call(db, billing_ctx, success=False, error_code="task_submission_failed")
        clone.status = "failed"
        clone.stage = "failed"
        clone.error_message = "任务提交失败，预扣积分已释放"
        clone.completed_at = _utcnow()
        db.commit()
        raise
    return {"job": _serialize_job(db, clone)}


@router.delete("/jobs/{job_id}")
async def delete_job(job_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    job = _owned_job(db, user.id, job_id)
    if job.status in ACTIVE_STATUSES:
        raise HTTPException(409, "请先取消正在执行的任务")
    output = db.get(CreationStudioAsset, job.output_asset_id) if job.output_asset_id else None
    if output and output.owner_user_id == user.id and output.deleted_at is None:
        if not _safe_unlink_asset(output):
            raise HTTPException(502, "生成结果删除失败，请稍后重试")
        output.deleted_at = _utcnow()
        output.status = "deleted"
    job.deleted_at = _utcnow()
    db.commit()
    return {"ok": True}
