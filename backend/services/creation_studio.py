"""独立创作台的图片与视频生成执行服务。"""

from __future__ import annotations

import asyncio
import datetime
import logging
import uuid
from pathlib import Path
from typing import Any

from database import SessionLocal
from models import (
    AiUsageEvent,
    BackgroundTask,
    CreationStudioAsset,
    CreationStudioJob,
    CreationStudioJobInput,
)
from services import image2 as image_service
from services import video_adapter
from services.ai.context import AIExecutionContext
from services.ai.crypto_secrets import decrypt_secret
from services.ai.resolver import complete_ai_call
from services.task_manager import task_manager
from services.errors import public_error_message

logger = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parent.parent
MANGA_OUTPUTS_DIR = BACKEND_DIR / "manga_outputs"
VIDEO_OUTPUTS_DIR = BACKEND_DIR / "video_outputs"


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


def fail_interrupted_creation_studio_jobs(db) -> int:
    """启动时终止失去执行协程的任务，并释放尚未结算的积分。"""
    from services.points import accounts as points_accounts

    jobs = db.query(CreationStudioJob).filter(
        CreationStudioJob.status.in_(["queued", "running", "cancel_requested"]),
        CreationStudioJob.deleted_at.is_(None),
    ).all()
    now = _utcnow()
    for job in jobs:
        request_id = f"studio-{job.media_kind}-{job.id}"
        event = db.query(AiUsageEvent).filter(AiUsageEvent.request_id == request_id).first()
        if event and event.status in {"reserved", "running"}:
            if event.credential_mode == "platform" and event.reserved_points:
                points_accounts.release_reservation(
                    db,
                    event.user_id,
                    event.reserved_points,
                    idempotency_key=f"release:{request_id}",
                    usage_event_id=event.id,
                    metadata={"reason": "service_restart", "studio_job_id": job.id},
                )
            event.status = "failed"
            event.error_code = "service_restart"
            event.completed_at = now

        if job.background_task_id:
            background = db.query(BackgroundTask).filter(
                BackgroundTask.task_id == job.background_task_id
            ).first()
            if background and background.status in {"pending", "running", "retrying"}:
                background.status = "failed"
                background.error_message = "服务重启，任务已终止"
                background.completed_at = now
        job.status = "failed"
        job.stage = "failed"
        job.error_message = "服务重启导致任务中断，请重新生成"
        job.completed_at = now
    if jobs:
        db.commit()
    return len(jobs)


def _public_media_url(path_value: str, media_kind: str) -> str:
    value = str(path_value or "").strip()
    if value.startswith(("http://", "https://", "/static/")):
        return value

    root = MANGA_OUTPUTS_DIR if media_kind == "image" else VIDEO_OUTPUTS_DIR
    route = "manga" if media_kind == "image" else "video"
    path = Path(value)
    try:
        relative = path.resolve().relative_to(root.resolve()).as_posix()
        return f"/static/{route}/{relative}"
    except (OSError, ValueError):
        normalized = value.replace("\\", "/")
        prefix = "manga_outputs/" if media_kind == "image" else "video_outputs/"
        if normalized.startswith(prefix):
            return f"/static/{route}/{normalized[len(prefix):]}"
        return value


def _update_job(job_id: int, **values: Any) -> None:
    db = SessionLocal()
    try:
        job = db.get(CreationStudioJob, job_id)
        if not job:
            return
        for key, value in values.items():
            setattr(job, key, value)
        db.commit()
    finally:
        db.close()


def _load_job_inputs(db, job: CreationStudioJob) -> list[CreationStudioAsset]:
    links = (
        db.query(CreationStudioJobInput)
        .filter(CreationStudioJobInput.job_id == job.id)
        .order_by(CreationStudioJobInput.position.asc(), CreationStudioJobInput.id.asc())
        .all()
    )
    asset_ids = [link.asset_id for link in links]
    if not asset_ids:
        return []
    assets = db.query(CreationStudioAsset).filter(CreationStudioAsset.id.in_(asset_ids)).all()
    by_id = {asset.id: asset for asset in assets}
    return [by_id[asset_id] for asset_id in asset_ids if asset_id in by_id]


def _create_output_asset(
    db,
    *,
    job: CreationStudioJob,
    media_kind: str,
    storage_path: str,
    public_url: str,
) -> CreationStudioAsset:
    asset = CreationStudioAsset(
        owner_user_id=job.owner_user_id,
        job_id=job.id,
        media_type=media_kind,
        role="output",
        storage_path=storage_path,
        public_url=public_url,
        original_name=Path(storage_path).name if not storage_path.startswith("http") else None,
        mime_type="image/png" if media_kind == "image" else "video/mp4",
        status="ready",
    )
    db.add(asset)
    db.flush()
    asset.public_url = f"/api/creation-studio/assets/{asset.id}/content"
    job.output_asset_id = asset.id
    return asset


def _combined_prompt(job: CreationStudioJob) -> str:
    prompt = job.prompt.strip()
    negative = (job.negative_prompt or "").strip()
    if negative:
        return f"{prompt}\n\n画面中不要出现：{negative}"
    return prompt


def _delete_generated_media(path_value: str) -> None:
    value = str(path_value or "").strip()
    if value.startswith(("http://", "https://")):
        from services import oss as oss_service

        if not oss_service.is_enabled():
            oss_service.auto_configure_from_db()
        oss_service.delete_by_url(value)
        return
    path = Path(value)
    if path.is_file():
        path.unlink(missing_ok=True)


async def _run_image_job(
    job_id: int,
    execution_task_id: str,
    billing_ctx: AIExecutionContext,
) -> dict[str, Any]:
    db = SessionLocal()
    ctx = billing_ctx
    usage_completed = False
    try:
        job = db.get(CreationStudioJob, job_id)
        if not job:
            raise RuntimeError("创作台任务不存在")
        if task_manager.is_cancellation_requested(execution_task_id):
            raise asyncio.CancelledError
        params = job.parameters_json or {}
        inputs = _load_job_inputs(db, job)
        local_refs = [asset.storage_path for asset in inputs if Path(asset.storage_path).is_file()]
        size = str(params.get("size") or "1024x1024")

        job.status = "running"
        job.stage = "generating"
        job.progress = 12
        job.started_at = _utcnow()
        db.commit()
        task_manager.update_task_metadata(
            execution_task_id,
            stage="generating",
            message="正在生成图片...",
            progress=12,
        )

        job.model_id = ctx.model_id
        job.model_key = ctx.model_key
        db.commit()

        if task_manager.is_cancellation_requested(execution_task_id):
            complete_ai_call(db, ctx, success=False, error_code="cancelled")
            usage_completed = True
            raise asyncio.CancelledError

        image_service.configure_runtime(
            base_url=ctx.base_url,
            model=ctx.model_key,
            size=size,
            quality=str(params.get("quality") or ""),
        )
        output_path = (
            MANGA_OUTPUTS_DIR
            / "creative_studio"
            / f"user_{job.owner_user_id}"
            / f"job_{job.id}_{uuid.uuid4().hex}.png"
        )
        generated_path = await image_service.generate_reference_image(
            _combined_prompt(job),
            output_path,
            api_key=ctx.api_key,
            size=size,
            ref_image_paths=local_refs,
            ref_type=str(params.get("reference_mode") or "character"),
        )
        if task_manager.is_cancellation_requested(execution_task_id):
            _delete_generated_media(generated_path)
            raise asyncio.CancelledError

        public_url = _public_media_url(generated_path, "image")
        asset = _create_output_asset(
            db,
            job=job,
            media_kind="image",
            storage_path=generated_path,
            public_url=public_url,
        )
        job.stage = "materializing"
        job.progress = 98
        complete_ai_call(db, ctx, success=True, image_count=1, commit=False)
        usage_completed = True
        job.status = "succeeded"
        job.stage = "completed"
        job.progress = 100
        job.completed_at = _utcnow()
        job.error_message = None
        db.commit()
        return {"job_id": job.id, "asset_id": asset.id, "output_url": public_url}
    except asyncio.CancelledError:
        if ctx is not None and not usage_completed:
            try:
                complete_ai_call(
                    db,
                    ctx,
                    success=False,
                    error_code="cancelled",
                )
            except Exception:
                logger.exception("创作台图片任务取消时积分释放失败 job_id=%s", job_id)
        _update_job(
            job_id,
            status="cancelled",
            stage="cancelled",
            error_message="任务已取消，预扣积分已释放",
            completed_at=_utcnow(),
        )
        raise
    except Exception as exc:
        logger.exception("创作台图片任务失败 job_id=%s", job_id)
        if ctx is not None and not usage_completed:
            try:
                complete_ai_call(db, ctx, success=False, error_code=type(exc).__name__)
            except Exception:
                logger.exception("创作台图片任务积分释放失败 job_id=%s", job_id)
        _update_job(
            job_id,
            status="failed",
            stage="failed",
            error_message=public_error_message(exc, "创作台图片生成失败，请稍后重试"),
            completed_at=_utcnow(),
        )
        raise
    finally:
        task_manager.clear_cancellation_flag(execution_task_id)
        db.close()


async def _run_video_job(
    job_id: int,
    execution_task_id: str,
    billing_ctx: AIExecutionContext,
) -> dict[str, Any]:
    db = SessionLocal()
    ctx = billing_ctx
    usage_completed = False
    try:
        job = db.get(CreationStudioJob, job_id)
        if not job:
            raise RuntimeError("创作台任务不存在")
        if task_manager.is_cancellation_requested(execution_task_id):
            raise asyncio.CancelledError
        params = job.parameters_json or {}
        inputs = _load_job_inputs(db, job)
        reference_images = [asset.storage_path or asset.public_url for asset in inputs]
        duration_seconds = int(params.get("duration_seconds") or 5)
        runtime = params.get("_runtime")
        if not isinstance(runtime, dict):
            raise RuntimeError("创作台视频任务缺少运行时快照，请重新生成")
        try:
            runtime_api_key = decrypt_secret(str(runtime.get("secret_ciphertext") or ""))
        except Exception as exc:
            raise RuntimeError("创作台视频任务凭据快照无法解密") from exc
        runtime_adapter = video_adapter.normalize_video_adapter_type(
            str(runtime.get("adapter_type") or "")
        )
        runtime_base_url = str(runtime.get("base_url") or "").rstrip("/")
        runtime_model = str(runtime.get("model") or "").strip()
        runtime_model_id = runtime.get("model_id")
        runtime_capabilities = runtime.get("video_capabilities")
        if runtime_capabilities is not None and not isinstance(runtime_capabilities, dict):
            raise RuntimeError("创作台视频任务能力快照无效")

        job.status = "running"
        job.stage = "submitting"
        job.progress = 5
        job.started_at = _utcnow()
        db.commit()
        task_manager.update_task_metadata(
            execution_task_id,
            stage="submitting",
            message="正在提交视频任务...",
            progress=5,
        )

        job.model_id = runtime_model_id if isinstance(runtime_model_id, int) else job.model_id
        job.model_key = runtime_model
        db.commit()

        if task_manager.is_cancellation_requested(execution_task_id):
            complete_ai_call(db, ctx, success=False, error_code="cancelled")
            usage_completed = True
            raise asyncio.CancelledError

        submit_result = await video_adapter.create_video_job(
            adapter_type=runtime_adapter,
            model=runtime_model,
            prompt=_combined_prompt(job),
            aspect_ratio=str(params.get("aspect_ratio") or "16:9"),
            size=str(params.get("resolution") or "720P"),
            duration_seconds=duration_seconds,
            images=reference_images or None,
            api_key=runtime_api_key,
            base_url=runtime_base_url,
            video_capabilities=runtime_capabilities,
        )
        provider_job_id = str(
            submit_result.get("task_id")
            or submit_result.get("provider_job_id")
            or submit_result.get("id")
            or ""
        ).strip()
        if not provider_job_id:
            raise RuntimeError("视频服务未返回任务 ID")
        job.provider_job_id = provider_job_id
        job.stage = "provider_processing"
        job.progress = 10
        db.commit()
        task_manager.update_task_metadata(
            execution_task_id,
            stage="provider_processing",
            message="视频正在生成，请稍候...",
            progress=10,
        )

        query_result: dict[str, object] = {}
        while True:
            if task_manager.is_cancellation_requested(execution_task_id):
                raise asyncio.CancelledError

            result = await video_adapter.query_video_job(
                provider_job_id,
                adapter_type=runtime_adapter,
                api_key=runtime_api_key,
                base_url=runtime_base_url,
                model=runtime_model,
            )
            raw_status = str(result.get("status") or "").strip().lower()
            if raw_status in {"done", "success", "completed", "succeeded"}:
                query_result = result
                break
            if raw_status in {"failed", "failure", "error", "cancelled", "canceled", "not_found"}:
                raise RuntimeError(str(result.get("error") or result.get("message") or "视频生成失败"))

            raw_progress = result.get("progress")
            try:
                provider_progress = int(float(str(raw_progress or 0).rstrip("%")))
            except ValueError:
                provider_progress = 0
            job.progress = max(10, min(88, provider_progress or job.progress + 1))
            db.commit()
            task_manager.update_task_metadata(
                execution_task_id,
                stage="provider_processing",
                message="视频正在生成，请稍候...",
                progress=job.progress,
            )
            await asyncio.sleep(3)

        job.stage = "materializing"
        job.progress = 92
        db.commit()
        task_manager.update_task_metadata(
            execution_task_id,
            stage="materializing",
            message="正在保存视频结果...",
            progress=92,
        )
        generated_path = await video_adapter.materialize_video_job(
            adapter_type=runtime_adapter,
            query_result=query_result,
            shot_id=job.id,
            job_id=provider_job_id,
            api_key=runtime_api_key,
            base_url=runtime_base_url,
        )
        public_url = _public_media_url(generated_path, "video")
        asset = _create_output_asset(
            db,
            job=job,
            media_kind="video",
            storage_path=generated_path,
            public_url=public_url,
        )
        complete_ai_call(db, ctx, success=True, video_seconds=duration_seconds, commit=False)
        usage_completed = True
        job.status = "succeeded"
        job.stage = "completed"
        job.progress = 100
        job.completed_at = _utcnow()
        job.error_message = None
        db.commit()
        return {"job_id": job.id, "asset_id": asset.id, "output_url": public_url}
    except asyncio.CancelledError:
        if ctx is not None and not usage_completed:
            try:
                complete_ai_call(
                    db,
                    ctx,
                    success=False,
                    error_code="cancelled",
                )
            except Exception:
                logger.exception("创作台视频任务取消时积分释放失败 job_id=%s", job_id)
        _update_job(
            job_id,
            status="cancelled",
            stage="cancelled",
            error_message="任务已取消，预扣积分已释放",
            completed_at=_utcnow(),
        )
        raise
    except Exception as exc:
        logger.exception("创作台视频任务失败 job_id=%s", job_id)
        if ctx is not None and not usage_completed:
            try:
                complete_ai_call(db, ctx, success=False, error_code=type(exc).__name__)
            except Exception:
                logger.exception("创作台视频任务积分释放失败 job_id=%s", job_id)
        _update_job(
            job_id,
            status="failed",
            stage="failed",
            error_message=public_error_message(exc, "创作台视频生成失败，请稍后重试"),
            completed_at=_utcnow(),
        )
        raise
    finally:
        task_manager.clear_cancellation_flag(execution_task_id)
        db.close()


async def execute_creation_studio_job(
    studio_job_id: int,
    *,
    billing_ctx: AIExecutionContext,
    task_id: str | None = None,
    story_id: int | None = None,
    chapter_id: int | None = None,
    shot_id: int | None = None,
) -> dict[str, Any]:
    """由通用任务管理器调用的创作台执行入口。"""
    del story_id, chapter_id, shot_id
    execution_task_id = task_id or f"creation-studio-{studio_job_id}"
    db = SessionLocal()
    try:
        job = db.get(CreationStudioJob, studio_job_id)
        if not job:
            raise RuntimeError("创作台任务不存在")
        media_kind = job.media_kind
    finally:
        db.close()
    if media_kind == "image":
        return await _run_image_job(studio_job_id, execution_task_id, billing_ctx)
    if media_kind == "video":
        return await _run_video_job(studio_job_id, execution_task_id, billing_ctx)
    raise RuntimeError(f"不支持的创作类型: {media_kind}")
