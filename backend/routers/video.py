"""Video production workflow router.

Handles screenplay, shot breakdown, storyboard, video generation,
asset management, and video project compilation endpoints.
"""

from __future__ import annotations

import asyncio
import base64
import datetime
from io import BytesIO
import json
import logging
import os
import uuid
from pathlib import Path
import re
import httpx

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, UploadFile, File
from PIL import Image, UnidentifiedImageError
from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse
from starlette.background import BackgroundTask as ResponseBackgroundTask

from database import SessionLocal, get_db, init_db
_VIDEO_OUTPUTS_DIR = Path(__file__).resolve().parent.parent / "video_outputs"
_MANGA_OUTPUTS_DIR = Path(__file__).resolve().parent.parent / "manga_outputs"

SHOT_TYPES = [
    "全景 (Wide Shot)", "中景 (Medium Shot)", "近景 (Close-up)",
    "特写 (Extreme Close-up)", "远景 (Extreme Wide Shot)",
    "过肩镜头 (Over-the-shoulder)", "主观镜头 (POV)",
    "俯拍 (High Angle)", "仰拍 (Low Angle)", "荷兰角 (Dutch Angle)",
    "推拉镜头 (Zoom)", "跟拍 (Tracking Shot)", "环绕镜头 (Orbit Shot)",
]

def _to_video_url(local_path: str) -> str:
    if not local_path:
        return ""
    if local_path.startswith("/static/video/"):
        return local_path
    if local_path.startswith("http://") or local_path.startswith("https://"):
        return local_path
    p = Path(local_path)
    if not p.is_absolute():
        # 相对路径直接拼接
        return f"/static/video/{p.as_posix()}"
    # 绝对路径：尝试相对于 _VIDEO_OUTPUTS_DIR
    try:
        rel = p.resolve().relative_to(_VIDEO_OUTPUTS_DIR.resolve())
        return f"/static/video/{rel.as_posix()}"
    except ValueError:
        return f"/static/video/{p.name}"


def _from_video_url(video_url: str) -> str | None:
    url = video_url.strip()
    if not url:
        return None
    if url.startswith("http://") or url.startswith("https://"):
        return url
    if os.path.isabs(url):
        return url
    if url.startswith("/static/video/"):
        rel = url[len("/static/video/"):]
        return str(_VIDEO_OUTPUTS_DIR / rel)
    return str(Path(__file__).resolve().parent.parent / url)


def _validate_video_asset_storage_path(value: str | None) -> str:
    """限制客户端创建的视频资产只能引用受控媒体目录或公网 HTTPS。"""
    raw = str(value or "").strip()
    if not raw:
        return ""
    if raw.lower().startswith(("http://", "https://")):
        return validate_remote_media_url(raw)

    normalized = raw.replace("\\", "/")
    # 跨平台拒绝 Windows 驱动器路径（CI 在 Linux 上运行，Path.is_absolute 不识别 C:/）
    if re.match(r'^[A-Za-z]:/', normalized):
        raise HTTPException(422, "视频素材路径不在受控媒体目录内")
    if normalized.startswith("/static/video/"):
        candidate = (_VIDEO_OUTPUTS_DIR / normalized[len("/static/video/"):]).resolve()
        root = _VIDEO_OUTPUTS_DIR.resolve()
    elif normalized.startswith("video_outputs/"):
        candidate = (Path(__file__).resolve().parent.parent / normalized).resolve()
        root = _VIDEO_OUTPUTS_DIR.resolve()
    elif normalized.startswith("/static/manga/"):
        candidate = (_MANGA_OUTPUTS_DIR / normalized[len("/static/manga/"):]).resolve()
        root = _MANGA_OUTPUTS_DIR.resolve()
    elif normalized.startswith("manga_outputs/"):
        candidate = (Path(__file__).resolve().parent.parent / normalized).resolve()
        root = _MANGA_OUTPUTS_DIR.resolve()
    elif not Path(raw).is_absolute():
        candidate = (_VIDEO_OUTPUTS_DIR / normalized).resolve()
        root = _VIDEO_OUTPUTS_DIR.resolve()
    else:
        raise HTTPException(422, "视频素材路径不在受控媒体目录内")

    if not candidate.is_relative_to(root):
        raise HTTPException(422, "视频素材路径不在受控媒体目录内")
    return normalized


from models import (
    AiModel,
    BackgroundTask,
    Chapter,
    ChapterVideoWorkflow,
    ChapterVideoShot,
    PlatformSetting,
    ScriptScene,
    Story,
    StoryCharacterVersion,
    User,
    UserSession,
    VideoAsset,
    VideoGenerationJob,
    VideoProject,
    VideoStylePreset,
    RenderedClip,
    MangaAsset,
    MangaAssetBinding,
    VideoShot,
)
from schemas import (
    ChapterStylePresetUpdate,
    ChapterVideoWorkflowCreate,
    ChapterVideoWorkflowOut,
    ChapterVideoWorkflowListOut,
    ChapterVideoWorkflowStatusOut,
    ChapterVideoShotCreate,
    ChapterVideoShotOut,
    CreateVideoAssetRequest,
    CreateVideoProjectRequest,
    CompileProjectRequest,
    GeneratePromptsRequest,
    GenerateScreenplayRequest,
    GenerateShotsRequest,
    GenerateShotFramesRequest,
    RegenerateScenesRequest,
    RegenerateShotFrameRequest,
    RegenerateShotRequest,
    ChapterWorkflowStageActionRequest,
    RetryJobRequest,
    ScriptSceneUpdate,
    StoryboardActionRequest,
    StoryboardRenderRequest,
    VideoGenerationJobOut,
    VideoProjectUpdate,
    VideoRenderRequest,
    VideoShotUpdate,
    VideoStylePresetCreate,
    VideoStylePresetUpdate,
    StoryStylePresetUpdate,
    ShotStylePresetUpdate,
    UpdateAssetScopeRequest,
    PromoteAssetRequest,
)
from services.screenplay import generate_screenplay, regenerate_scenes
from services.storyboard import generate_shots, generate_shot_prompts as generate_shot_prompts_service
from services import deepseek as deepseek_service
from services import image2 as image2_service
from services.ai.channels import validate_remote_media_url
from services.visual_asset_prompts import analyze_visual_assets
from services.visual_asset_generation import generate_visual_asset_image
from services import video_generation as video_gen_service
from services.media_locator import ensure_local_media_path, resolve_local_media_path, resolve_reference_input
from services.media_logging import safe_media_url_for_log
from services import video_api as video_api_service
from services import video_adapter as video_adapter_service
from services import video_qa
from services.blocking import run_blocking
from services.errors import UpstreamServiceError, public_error_message
from services.video_compiler import compile_project
from services.task_manager import task_manager
from services.video_chapter_pipeline import (
    create_workflow as create_chapter_workflow,
    get_workflow as get_chapter_workflow,
    get_workflows_for_chapter as get_chapter_workflows,
    update_workflow_status as update_chapter_workflow_status,
    regenerate_shot_storyboard,
    regenerate_shot_video,
    reanalyze_shot_prompts,
    reanalyze_storyboard_prompts,
    concat_chapter_videos,
    validate_character_consistency,
    parse_chapter_shots,
    generate_storyboards_for_shots,
    generate_videos_for_shots,
    generate_shot_details_batch,
    assemble_video_prompt_text,
    generate_workflow_screenplay,
    build_shot_source_from_screenplay,
    _build_chapter_storyboard_asset,
    _strip_storyboard_style_directives,
)

# 模块级标记：init_db 在整个进程生命周期中只调用一次
_db_schema_verified: bool = False

logger = logging.getLogger("video_router")

router = APIRouter()

SHOT_DURATION_SECONDS = 15
DEFAULT_VIDEO_DURATION_SECONDS = 15
MAX_VIDEO_DURATION_SECONDS = 60
MAX_VIDEO_REFERENCE_COUNT = 9
MAX_VIDEO_REFERENCE_FILE_BYTES = max(
    1,
    int(os.getenv("MAX_VIDEO_REFERENCE_FILE_BYTES", str(30 * 1024 * 1024))),
)
MAX_VIDEO_REFERENCE_TOTAL_BYTES = max(
    MAX_VIDEO_REFERENCE_FILE_BYTES,
    int(os.getenv("MAX_VIDEO_REFERENCE_TOTAL_BYTES", str(270 * 1024 * 1024))),
)
MAX_VIDEO_REFERENCE_BASE64_BYTES = max(
    1,
    int(os.getenv("MAX_VIDEO_REFERENCE_BASE64_BYTES", str(360 * 1024 * 1024))),
)
MANGA_ASSET_BATCH_MAX_ITEMS = 50
MANGA_ASSET_GENERATION_CONCURRENCY = max(
    1,
    min(8, int(os.getenv("MANGA_ASSET_GENERATION_CONCURRENCY", "2") or "2")),
)


def _same_story_video_asset_types(asset_type: str | None) -> list[str]:
    story_types = [
        "story_character_reference",
        "character_reference",
        "scene_reference",
        "prop_reference",
        "storyboard_frame",
    ]
    if asset_type:
        return [asset_type] if asset_type in story_types else []
    return story_types


def _backfill_storyboard_assets_for_story(db: Session, story_id: int) -> int:
    rows = (
        db.query(ChapterVideoShot, ChapterVideoWorkflow)
        .join(ChapterVideoWorkflow, ChapterVideoShot.workflow_id == ChapterVideoWorkflow.id)
        .filter(
            ChapterVideoWorkflow.story_id == story_id,
            ChapterVideoShot.storyboard_image_url.isnot(None),
            ChapterVideoShot.storyboard_image_url != "",
        )
        .all()
    )
    if not rows:
        return 0

    existing_shot_ids: set[int] = set()
    existing_paths: set[str] = set()
    existing_assets = (
        db.query(VideoAsset)
        .filter(
            VideoAsset.story_id == story_id,
            VideoAsset.asset_type == "storyboard_frame",
            VideoAsset.status == "active",
        )
        .all()
    )
    for asset in existing_assets:
        meta = asset.meta_json or {}
        chapter_shot_id = meta.get("chapter_video_shot_id")
        if chapter_shot_id is not None:
            try:
                existing_shot_ids.add(int(chapter_shot_id))
            except (TypeError, ValueError):
                pass
        if asset.file_path:
            existing_paths.add(asset.file_path)

    created = 0
    for shot, workflow in rows:
        file_path = shot.storyboard_image_url or ""
        if shot.id in existing_shot_ids or file_path in existing_paths:
            continue
        asset = _build_chapter_storyboard_asset(
            workflow=workflow,
            shot=shot,
            file_path=file_path,
            prompt=shot.storyboard_prompt,
            provider="backfill",
            source_asset_ids=None,
            source_type="ai_generated",
        )
        db.add(asset)
        created += 1
    if created:
        db.commit()
    return created


def _flatten_task_status(task_status: dict | None) -> dict:
    """Return stable public status fields from task_manager.get_task_status()."""
    if not task_status:
        return {
            "stage": None,
            "message": None,
            "provider_status": None,
            "retry_count": 0,
            "max_retries": 0,
            "next_retry_at": None,
        }
    meta = task_status.get("metadata_json") if isinstance(task_status.get("metadata_json"), dict) else {}
    return {
        "stage": task_status.get("stage") or meta.get("stage"),
        "message": task_status.get("message") or meta.get("message"),
        "provider_status": meta.get("provider_status"),
        "retry_count": task_status.get("retry_count", 0),
        "max_retries": task_status.get("max_retries", 0),
        "next_retry_at": task_status.get("next_retry_at") or meta.get("next_retry_at"),
    }


def _flatten_background_task(task: BackgroundTask | None) -> dict:
    if not task:
        return _flatten_task_status(None)
    meta = task.metadata_json if isinstance(task.metadata_json, dict) else {}
    return {
        "stage": meta.get("stage"),
        "message": meta.get("message") or task.error_message,
        "provider_status": meta.get("provider_status"),
        "retry_count": task.retry_count,
        "max_retries": task.max_retries,
        "next_retry_at": meta.get("next_retry_at"),
        "task_id": task.task_id,
        "task_status": task.status,
        "error_message": task.error_message,
    }


def _latest_chapter_workflow_task(db: Session, workflow_id: int) -> BackgroundTask | None:
    prefix = f"chapter_video_{workflow_id}_"
    active = (
        db.query(BackgroundTask)
        .filter(BackgroundTask.task_id.startswith(prefix, autoescape=True))
        .filter(BackgroundTask.status.in_(["pending", "running", "retrying"]))
        .order_by(BackgroundTask.created_at.desc())
        .first()
    )
    if active:
        return active
    return (
        db.query(BackgroundTask)
        .filter(BackgroundTask.task_id.startswith(prefix, autoescape=True))
        .order_by(BackgroundTask.created_at.desc())
        .first()
    )


# 鈹€鈹€鈹€ Helper functions (mirrored from main.py patterns) 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

def _user_video_api_key(request: Request) -> tuple[str | None, str, str]:
    """Return (api_key, base_url, model) for current request/user context."""
    key = (request.headers.get("x-video-api-key") or "").strip()
    db = getattr(request.state, "db", None)
    if db is None:
        return key or None, video_api_service._resolved_base_url(), video_api_service._resolved_model()

    try:
        import main as main_mod

        dual = main_mod._resolve_dual_track_runtime(request, db, modality="video")
        if dual:
            request.state.dual_track_video = dual
            return dual["api_key"], dual["base_url"], dual["model_key"]
    except HTTPException:
        raise
    except Exception:
        logger.exception("video 路由双轨视频解析失败")

    user = getattr(request.state, "current_user", None)
    capabilities = _user_api_override_capabilities(user, db)
    admin_base_url = str(_get_platform_setting("api.video.base_url", db, video_api_service._resolved_base_url())).strip()
    admin_model = str(_get_platform_setting("api.video.model", db, video_api_service._resolved_model())).strip()
    admin_api_key = str(_get_platform_setting("api.video.api_key", db, "") or "").strip()

    import main as main_mod

    requested_mode = main_mod._request_credential_mode(request, db)
    custom_upstream = main_mod._resolve_user_upstream_override(
        request,
        db,
        user=user,
        modality="video",
        mode=requested_mode,
    )
    resolved_base_url = (custom_upstream or {}).get("base_url") or admin_base_url
    resolved_model = (custom_upstream or {}).get("model_key") or admin_model

    if custom_upstream:
        return custom_upstream["api_key"], resolved_base_url.rstrip("/"), resolved_model
    if requested_mode == "user_key" and not capabilities["can_override_api_key"]:
        raise HTTPException(403, "管理员未授权当前账号使用自定义 API Key")

    if capabilities["can_override_api_key"] and key:
        effective_key = key
    elif admin_api_key:
        effective_key = admin_api_key
    else:
        effective_key = key or None

    return effective_key, resolved_base_url.rstrip("/"), resolved_model


_VIDEO_RUNTIME_SNAPSHOT_KEY = "_runtime"
_VIDEO_USAGE_EVENT_ID_KEY = "billing_usage_event_id"


def _build_video_runtime_snapshot(
    request: Request,
    db: Session,
    *,
    api_key: str | None,
    base_url: str,
    model: str,
) -> dict:
    """保存视频任务后续轮询所需的上游快照，API Key 仅以密文存储。"""
    from services.ai.crypto_secrets import encrypt_secret

    dual = getattr(request.state, "dual_track_video", None)
    if isinstance(dual, dict):
        mode = str(dual.get("mode") or "platform")
        channel_id = dual.get("channel_id")
        custom_upstream = bool(dual.get("custom_upstream"))
        adapter_type = _current_video_adapter_type(request)
    else:
        import main as main_mod

        mode = main_mod._request_credential_mode(request, db)
        channel_id = None
        custom_upstream = mode == "user_key" and bool(
            (request.headers.get("x-video-base-url") or "").strip()
            or (request.headers.get("x-video-model") or "").strip()
        )
        adapter_type = video_adapter_service.VIDEO_ADAPTER_LINGDONG
    return {
        "credential_mode": mode,
        "base_url": str(base_url or "").rstrip("/"),
        "model": str(model or "").strip(),
        "channel_id": int(channel_id) if channel_id is not None else None,
        "custom_upstream": custom_upstream,
        "adapter_type": adapter_type,
        "secret_ciphertext": encrypt_secret(api_key or ""),
    }


def _video_provider_metadata(runtime_snapshot: dict, usage_event_id: int | None = None) -> dict:
    metadata = {_VIDEO_RUNTIME_SNAPSHOT_KEY: runtime_snapshot}
    if usage_event_id:
        metadata[_VIDEO_USAGE_EVENT_ID_KEY] = int(usage_event_id)
    return metadata


def _current_video_capabilities(request: Request, db: Session, model_key: str) -> dict | None:
    """仅为当前选中的平台视频模型透传受控 capabilities。"""
    runtime = getattr(getattr(request, "state", None), "dual_track_video", None)
    if not isinstance(runtime, dict) or runtime.get("custom_upstream"):
        return None
    if str(runtime.get("model_key") or "").strip() != str(model_key or "").strip():
        return None
    model_id = runtime.get("model_id")
    if not isinstance(model_id, int):
        return None
    model = db.get(AiModel, model_id)
    raw = model.capabilities_json if model else None
    video = raw.get("video") if isinstance(raw, dict) else None
    return video if isinstance(video, dict) else None


def _current_video_adapter_type(request: Request) -> str:
    """读取权威渠道适配器；历史与自定义上游固定按 Lingdong 协议处理。"""
    runtime = getattr(getattr(request, "state", None), "dual_track_video", None)
    if not isinstance(runtime, dict) or runtime.get("custom_upstream"):
        return video_adapter_service.VIDEO_ADAPTER_LINGDONG
    return video_adapter_service.normalize_video_adapter_type(
        runtime.get("adapter_type"),
        legacy_default=True,
    )


def _validate_video_request_before_billing(
    *,
    adapter_type: str,
    model: str,
    video_capabilities: dict | None,
    aspect_ratio: str,
    duration_seconds: int,
    reference_count: int,
) -> None:
    """在计费和上游提交前验证视频协议能力。"""
    if video_capabilities is not None:
        from services.ai.video_capabilities import validate_video_capability_limits

        validate_video_capability_limits(
            video_capabilities,
            duration_seconds=duration_seconds,
        )
    if adapter_type == video_adapter_service.VIDEO_ADAPTER_LINGDONG:
        video_api_service.validate_legacy_model_duration(
            model=model,
            duration_seconds=duration_seconds,
            video_capabilities=video_capabilities,
        )
        return
    video_adapter_service._openai_video_config(
        video_capabilities,
        aspect_ratio=aspect_ratio,
        size="720P",
        duration_seconds=duration_seconds,
        reference_count=reference_count,
    )


def _chapter_video_reference_count(
    shot: ChapterVideoShot,
    workflow: ChapterVideoWorkflow,
    explicit_reference_ids: list[int] | None,
    db: Session,
) -> int:
    """按章节流水线的确定性来源统计预提交参考图数量。"""
    if explicit_reference_ids is not None:
        reference_ids = list(dict.fromkeys(explicit_reference_ids))
    else:
        reference_ids = list(dict.fromkeys(
            list(getattr(shot, "character_reference_ids", None) or [])
            + list(getattr(shot, "scene_reference_ids", None) or [])
            + list(getattr(shot, "prop_reference_ids", None) or [])
        ))
    count = len(reference_ids)
    if getattr(workflow, "style_reference_image_url", None):
        count += 1
    else:
        chapter_id = getattr(workflow, "chapter_id", None)
        chapter = db.get(Chapter, chapter_id) if chapter_id else None
        preset_id = getattr(chapter, "video_style_preset_id", None) if chapter else None
        preset = db.get(VideoStylePreset, preset_id) if preset_id else None
        if preset and getattr(preset, "image_url", None):
            count += 1
    return count


def _chapter_video_target_shots(
    db: Session,
    workflow_id: int,
    shot_ids: list[int] | None,
) -> list[ChapterVideoShot]:
    """返回与章节视频流水线实际执行条件一致的计费目标。"""
    query = db.query(ChapterVideoShot).filter(ChapterVideoShot.workflow_id == workflow_id)
    if shot_ids:
        query = query.filter(
            ChapterVideoShot.id.in_(shot_ids),
            ChapterVideoShot.status.in_(["storyboard_ready", "video_generating", "pending"]),
        )
    else:
        query = query.filter(ChapterVideoShot.status == "storyboard_ready")
    return query.order_by(ChapterVideoShot.shot_index).all()


def _video_billing_usage_event_id(job: VideoGenerationJob) -> int | None:
    metadata = job.provider_payload_json if isinstance(job.provider_payload_json, dict) else {}
    raw_value = metadata.get(_VIDEO_USAGE_EVENT_ID_KEY)
    try:
        return int(raw_value) if raw_value else None
    except (TypeError, ValueError):
        return None


def _refund_video_billing(
    db: Session,
    *,
    job: VideoGenerationJob | None = None,
    usage_event_id: int | None = None,
    reason: str,
    commit: bool = True,
) -> None:
    resolved_usage_event_id = usage_event_id or (_video_billing_usage_event_id(job) if job else None)
    if not resolved_usage_event_id:
        return
    from services.ai.resolver import refund_ai_call

    refund_ai_call(db, resolved_usage_event_id, error_code=reason, commit=commit)


def _settle_video_billing(
    db: Session,
    *,
    job: VideoGenerationJob | None = None,
    usage_event_id: int | None = None,
    video_seconds: int | float | None = None,
    commit: bool = True,
) -> None:
    resolved_usage_event_id = usage_event_id or (_video_billing_usage_event_id(job) if job else None)
    if not resolved_usage_event_id:
        return
    from services.ai.resolver import complete_ai_call_by_usage_event

    duration = video_seconds if video_seconds is not None else (job.duration_seconds if job else 0)
    complete_ai_call_by_usage_event(
        db,
        resolved_usage_event_id,
        success=True,
        video_seconds=max(0, float(duration or 0)),
        commit=commit,
    )


def _fail_video_job_and_refund(
    db: Session,
    job: VideoGenerationJob,
    *,
    error_message: str,
    reason: str,
) -> None:
    """在同一事务中标记视频无产物失败并退回原始积分。"""
    job.status = "failed"
    job.error_message = error_message
    job.completed_at = job.completed_at or datetime.datetime.utcnow()
    _refund_video_billing(db, job=job, reason=reason, commit=False)
    db.commit()


def _resolve_video_job_runtime(
    job: VideoGenerationJob,
    request: Request,
    db: Session,
) -> tuple[str | None, str, str]:
    """使用任务创建时的上游信息解析轮询凭据，兼容无快照的旧任务。"""
    provider_metadata = job.provider_payload_json if isinstance(job.provider_payload_json, dict) else {}
    snapshot = provider_metadata.get(_VIDEO_RUNTIME_SNAPSHOT_KEY)
    if not isinstance(snapshot, dict):
        raise HTTPException(409, "旧版本视频任务缺少上游快照，请重新提交任务")

    base_url = str(snapshot.get("base_url") or "").rstrip("/")
    model = str(snapshot.get("model") or job.model or "").strip()
    mode = str(snapshot.get("credential_mode") or "platform")

    if mode == "user_key":
        import main as main_mod

        current_user = getattr(request.state, "current_user", None) or _require_user(request, db)
        capabilities = main_mod._user_api_override_capabilities(current_user, db)
        if not capabilities["can_override_api_key"]:
            raise HTTPException(403, "管理员已撤销当前账号使用自定义 API Key 的权限")
        if snapshot.get("custom_upstream") and not capabilities["can_override_api_url"]:
            raise HTTPException(403, "管理员已撤销当前账号使用自定义 API URL 的权限")

    secret_ciphertext = str(snapshot.get("secret_ciphertext") or "").strip()
    if not secret_ciphertext:
        raise HTTPException(409, "视频任务缺少凭据快照，请重新提交任务")
    try:
        from services.ai.crypto_secrets import decrypt_secret

        api_key = decrypt_secret(secret_ciphertext)
    except Exception as exc:
        raise HTTPException(500, "视频任务凭据快照无法解密") from exc
    if not api_key:
        raise HTTPException(500, "视频任务凭据快照为空")
    if mode == "user_key" and snapshot.get("custom_upstream") and base_url:
        from services.ai.channels import validate_user_base_url

        base_url = validate_user_base_url(base_url)
    return api_key, base_url, model


def _video_job_adapter_type(job: VideoGenerationJob) -> str:
    """从任务快照恢复协议；历史任务不根据模型名推断，固定回退 Lingdong。"""
    provider_metadata = job.provider_payload_json if isinstance(job.provider_payload_json, dict) else {}
    snapshot = provider_metadata.get(_VIDEO_RUNTIME_SNAPSHOT_KEY)
    raw_adapter = snapshot.get("adapter_type") if isinstance(snapshot, dict) else None
    return video_adapter_service.normalize_video_adapter_type(raw_adapter, legacy_default=True)


def _user_image_api_key(request: Request) -> str | None:
    import main as main_mod
    # 与主应用共享运行时解析，避免视频资产生成绕过目录模型能力配置。
    return main_mod._user_image_api_key(request)


def _get_platform_setting(key: str, db: Session, default=None):
    from services.ai.crypto_secrets import read_platform_setting_payload

    setting = db.query(PlatformSetting).filter(PlatformSetting.setting_key == key).first()
    if not setting:
        return default
    return read_platform_setting_payload(setting.value_json, default)


def _user_api_override_capabilities(user: User | None, db: Session) -> dict[str, bool]:
    import main as main_mod

    return main_mod._user_api_override_capabilities(user, db)


def _configure_image_service_from_db(request: Request, db: Session) -> None:
    """从数据库读取图片 API 配置并注入 image2 服务。

    ⚠️ 必须在调用任何图片生成函数前调用此函数！
    否则 image2._image_auth_headers 会抛出 '图片 API 地址未配置' 错误。
    """
    _user_image_api_key(request)


def _configure_video_service_from_db(request: Request, db: Session) -> None:
    """从数据库读取视频 API 配置并注入 video_api 服务。

    ⚠️ 必须在调用任何视频生成函数前调用此函数！
    """
    api_key, base_url, model = _user_video_api_key(request)
    video_api_service.configure(base_url=base_url, api_key=api_key, model=model)


def _configure_oss_from_db(db: Session) -> None:
    """从数据库读取 OSS 配置并注入 oss 服务。

    在生成文件后调用 upload_file() 时会自动使用此配置。
    """
    from services import oss as oss_service
    enabled = bool(_get_platform_setting("oss.enabled", db, False))
    access_key_id = str(_get_platform_setting("oss.access_key_id", db, "") or "").strip()
    access_key_secret = str(_get_platform_setting("oss.access_key_secret", db, "") or "").strip()
    endpoint = str(_get_platform_setting("oss.endpoint", db, "") or "").strip()
    bucket = str(_get_platform_setting("oss.bucket", db, "") or "").strip()
    public_url_base = str(_get_platform_setting("oss.public_url_base", db, "") or "").strip()
    oss_service.configure(
        enabled=enabled,
        access_key_id=access_key_id,
        access_key_secret=access_key_secret,
        endpoint=endpoint,
        bucket=bucket,
        public_url_base=public_url_base,
    )


def _resolve_video_provider(request_provider: str | None, db: Session | None) -> str:
    """Resolve effective video provider with platform/env/request fallback."""
    if db is not None:
        admin_provider = str(_get_platform_setting("api.video.provider", db, "") or "").strip()
        if admin_provider:
            logger.info("浣跨敤骞冲彴璁剧疆閰嶇疆鐨勮棰戜緵搴斿晢: %s", admin_provider)
            return admin_provider
    env_provider = (os.getenv("VIDEO_PROVIDER") or "").strip()
    if env_provider:
        logger.info("浣跨敤鐜鍙橀噺閰嶇疆鐨勮棰戜緵搴斿晢: %s", env_provider)
        return env_provider
    if request_provider and request_provider not in ("", "mock", "sora"):
        return request_provider
    return request_provider or "mock"


def _user_deepseek_api_key(request: Request, db: Session) -> str | None:
    try:
        import main as main_mod

        dual = main_mod._resolve_dual_track_runtime(request, db, modality="text")
        if dual:
            deepseek_service.configure_runtime(
                base_url=dual["base_url"] or deepseek_service.DEEPSEEK_BASE_URL,
                model=dual["model_key"] or deepseek_service.DEEPSEEK_MODEL,
            )
            request.state.dual_track_text = dual
            return dual["api_key"]
    except HTTPException:
        raise
    except Exception:
        logger.exception("video 路由双轨文本解析失败")

    override = request.headers.get("x-deepseek-api-key") or None
    user = getattr(request.state, "current_user", None)
    capabilities = _user_api_override_capabilities(user, db)
    admin_base_url = str(_get_platform_setting("api.deepseek.base_url", db, deepseek_service.DEEPSEEK_BASE_URL)).strip()
    admin_model = str(_get_platform_setting("api.deepseek.model", db, deepseek_service.DEEPSEEK_MODEL)).strip()
    import main as main_mod

    requested_mode = main_mod._request_credential_mode(request, db)
    custom_upstream = main_mod._resolve_user_upstream_override(
        request,
        db,
        user=user,
        modality="text",
        mode=requested_mode,
    )
    resolved_base_url = (custom_upstream or {}).get("base_url") or admin_base_url
    resolved_model = (custom_upstream or {}).get("model_key") or admin_model

    deepseek_service.configure_runtime(base_url=resolved_base_url, model=resolved_model)

    if custom_upstream:
        return custom_upstream["api_key"]
    if requested_mode == "user_key" and not capabilities["can_override_api_key"]:
        raise HTTPException(403, "管理员未授权当前账号使用自定义 API Key")
    if capabilities["can_override_api_key"] and override:
        return override
    return _get_platform_setting("api.deepseek.api_key", db, "") or None


def _parse_auth_token(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
        return token or None
    return None


def _require_user(request: Request, db: Session) -> User:
    import main as main_mod

    return main_mod._require_user(request, db)


def _require_chapter(chapter_id: int, db: Session) -> Chapter:
    chapter = db.get(Chapter, chapter_id)
    if not chapter:
        raise HTTPException(404, "章节未找到")
    return chapter


def _require_story_for_user(story_id: int, user: User, db: Session) -> Story:
    story = db.get(Story, story_id)
    if not story:
        raise HTTPException(404, "作品未找到")
    if story.owner_user_id != user.id:
        raise HTTPException(403, "作品访问被拒绝")
    return story


def _require_chapter_for_user(chapter_id: int, user: User, db: Session) -> Chapter:
    chapter = _require_chapter(chapter_id, db)
    story = chapter.story
    if not story:
        raise HTTPException(404, "作品未找到")
    if story.owner_user_id != user.id:
        raise HTTPException(403, "章节访问被拒绝")
    return chapter


@router.post("/api/stories/{story_id}/manga-assets/upload", status_code=201)
async def upload_manga_asset(
    story_id: int,
    request: Request,
    file: UploadFile = File(...),
    asset_type: str = Form("character_reference"),
    name: str = Form(""),
    chapter_id: int | None = Form(None),
    bind_to_chapter: bool = Form(False),
    binding_label: str = Form(""),
    db: Session = Depends(get_db),
):
    """上传独立漫画资产，写入漫画资源目录并创建资产记录。"""
    user = _require_user(request, db)
    _require_story_for_user(story_id, user, db)
    allowed_types = {"character_reference", "scene_reference", "prop_reference", "style_reference"}
    if asset_type not in allowed_types:
        raise HTTPException(422, "不支持的漫画资产类型")
    if chapter_id is not None:
        chapter = _require_chapter_for_user(chapter_id, user, db)
        if chapter.story_id != story_id:
            raise HTTPException(400, "章节不属于当前作品")
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(400, "请上传图片文件")

    content = await file.read()
    if not content:
        raise HTTPException(422, "上传文件不能为空")
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(413, "图片不能超过 10MB")
    suffix = Path(file.filename or "asset.png").suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
        raise HTTPException(422, "仅支持 JPG、PNG、WebP 图片")
    try:
        with Image.open(BytesIO(content)) as image:
            image.verify()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise HTTPException(422, "上传文件不是有效图片") from exc

    asset_name = name.strip() or Path(file.filename or "漫画资产").stem
    if len(asset_name) > 255:
        raise HTTPException(422, "资产名称不能超过 255 个字符")
    if bind_to_chapter and chapter_id is None:
        raise HTTPException(422, "自动绑定资产时必须提供 chapter_id")
    resolved_binding_label = binding_label.strip() or asset_name
    if len(resolved_binding_label) > 255:
        raise HTTPException(422, "绑定名称不能超过 255 个字符")
    relative_dir = Path(f"story_{story_id}") / "assets"
    filename = f"asset_{uuid.uuid4().hex}{suffix}"
    target_dir = _MANGA_OUTPUTS_DIR / relative_dir
    target_path = target_dir / filename
    await run_blocking(target_dir.mkdir, parents=True, exist_ok=True)
    await run_blocking(target_path.write_bytes, content)

    # 优先上传 OSS，只有 OSS 未启用或上传失败时才保留本地文件作为兜底。
    from services import oss as oss_service
    _configure_oss_from_db(db)
    oss_url = await run_blocking(oss_service.upload_file, str(target_path)) if oss_service.is_enabled() else None
    if oss_url:
        try:
            target_path.unlink(missing_ok=True)
        except Exception:
            pass
        storage_path = oss_url
        storage_provider = "oss"
    else:
        storage_path = f"manga_outputs/{relative_dir.as_posix()}/{filename}"
        storage_provider = "local"

    asset = MangaAsset(
        owner_user_id=user.id,
        story_id=story_id,
        chapter_id=chapter_id,
        asset_type=asset_type,
        name=asset_name,
        storage_path=storage_path,
        source_type="upload",
        status="active",
        metadata_json={"mime_type": file.content_type, "original_filename": file.filename or filename, "storage_provider": storage_provider},
    )
    try:
        db.add(asset)
        db.flush()
        if bind_to_chapter:
            db.add(MangaAssetBinding(
                asset_id=asset.id,
                story_id=story_id,
                chapter_id=chapter_id,
                binding_role=asset_type.replace("_reference", ""),
                label=resolved_binding_label,
                priority=0,
                is_required=False,
            ))
        db.commit()
    except Exception:
        db.rollback()
        if target_path.exists():
            await run_blocking(target_path.unlink)
        raise
    db.refresh(asset)
    return {
        "id": asset.id,
        "owner_user_id": asset.owner_user_id,
        "story_id": asset.story_id,
        "chapter_id": asset.chapter_id,
        "asset_type": asset.asset_type,
        "name": asset.name,
        "storage_path": asset.storage_path,
        "source_type": asset.source_type,
        "status": asset.status,
        "metadata": asset.metadata_json,
        "created_at": asset.created_at.isoformat() if asset.created_at else None,
    }


@router.delete("/api/manga-assets/{asset_id}/managed")
async def delete_managed_manga_asset(asset_id: int, request: Request, db: Session = Depends(get_db)):
    """删除漫画资产记录、章节绑定及对应的 OSS 或本地文件。"""
    user = _require_user(request, db)
    asset = db.get(MangaAsset, asset_id)
    if not asset:
        raise HTTPException(404, "漫画资产未找到")
    if asset.owner_user_id != user.id:
        raise HTTPException(403, "漫画资产访问被拒绝")

    storage_path = str(asset.storage_path or "").replace("\\", "/")
    local_file: Path | None = None
    prefix = "manga_outputs/"
    if storage_path.startswith(prefix):
        candidate = (_MANGA_OUTPUTS_DIR / storage_path[len(prefix):]).resolve()
        allowed_root = (_MANGA_OUTPUTS_DIR / f"story_{asset.story_id}" / "assets").resolve()
        if candidate.is_relative_to(allowed_root):
            local_file = candidate

    db.query(MangaAssetBinding).filter(MangaAssetBinding.asset_id == asset.id).delete(synchronize_session=False)
    db.delete(asset)
    db.commit()
    if local_file and local_file.exists():
        await run_blocking(local_file.unlink)
    elif storage_path.startswith(("http://", "https://")):
        from services import oss as oss_service
        _configure_oss_from_db(db)
        await run_blocking(oss_service.delete_by_url, storage_path)
    return {"ok": True}


def _serialize_managed_manga_asset(asset: MangaAsset) -> dict[str, object]:
    return {
        "id": asset.id,
        "owner_user_id": asset.owner_user_id,
        "story_id": asset.story_id,
        "chapter_id": asset.chapter_id,
        "asset_type": asset.asset_type,
        "name": asset.name,
        "storage_path": asset.storage_path,
        "source_type": asset.source_type,
        "status": asset.status,
        "metadata": asset.metadata_json,
        "created_at": asset.created_at.isoformat() if asset.created_at else None,
    }


def _managed_manga_asset_local_path(storage_path: str) -> Path | None:
    normalized = str(storage_path or "").replace("\\", "/")
    if normalized.startswith("manga_outputs/"):
        candidate = (_MANGA_OUTPUTS_DIR / normalized[len("manga_outputs/"):]).resolve()
    elif normalized.startswith("/static/manga/"):
        candidate = (_MANGA_OUTPUTS_DIR / normalized[len("/static/manga/"):]).resolve()
    elif Path(normalized).is_absolute():
        candidate = Path(normalized).resolve()
    else:
        return None
    return candidate if candidate.is_relative_to(_MANGA_OUTPUTS_DIR.resolve()) else None


@router.post("/api/manga-assets/{asset_id}/redraw")
async def redraw_managed_manga_asset(asset_id: int, request: Request, db: Session = Depends(get_db)):
    """重绘漫画资产，并在成功后原子切换到新图片。"""
    user = _require_user(request, db)
    asset = db.get(MangaAsset, asset_id)
    if not asset:
        raise HTTPException(404, "漫画资产未找到")
    if asset.owner_user_id != user.id:
        raise HTTPException(403, "漫画资产访问被拒绝")

    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(422, "请求体必须是对象")
    prompt = str(body.get("prompt") or "").strip()
    if not prompt:
        raise HTTPException(422, "重绘提示词不能为空")
    if len(prompt) > 24000:
        raise HTTPException(422, "重绘提示词不能超过 24000 个字符")
    mode = str(body.get("mode") or "full").strip().lower()
    if mode not in {"full", "partial"}:
        raise HTTPException(422, "重绘方式仅支持 full 或 partial")

    old_local_path = _managed_manga_asset_local_path(asset.storage_path)
    source_value = str(asset.storage_path or "").strip()
    if source_value.startswith(("http://", "https://")):
        source_value = validate_remote_media_url(source_value)
    source_path_text = str(old_local_path) if old_local_path and old_local_path.exists() else ensure_local_media_path(source_value, "manga")
    if not source_path_text:
        raise HTTPException(404, "漫画资产原图不存在，请刷新后重试")
    source_path = Path(source_path_text)

    mask_bytes: bytes | None = None
    if mode == "partial":
        encoded_mask = str(body.get("mask") or "").strip()
        if not encoded_mask:
            raise HTTPException(422, "局部重绘必须提供涂抹蒙版")
        if len(encoded_mask) > 20 * 1024 * 1024:
            raise HTTPException(413, "重绘蒙版不能超过 20MB")
        try:
            mask_bytes = base64.b64decode(encoded_mask.split(",", 1)[-1], validate=True)
            with Image.open(BytesIO(mask_bytes)) as mask_image:
                mask_image.verify()
        except Exception as exc:
            raise HTTPException(422, "重绘蒙版不是有效图片") from exc

    relative_dir = Path(f"story_{asset.story_id}") / "assets"
    output_dir = _MANGA_OUTPUTS_DIR / relative_dir
    output_path = output_dir / f"asset_redraw_{uuid.uuid4().hex}.png"
    await run_blocking(output_dir.mkdir, parents=True, exist_ok=True)

    _check_and_consume_quota_wrapper(
        user.id,
        "manga.image.generate.monthly_limit",
        1,
        db,
        deduct=False,
        request=request,
        provider_kind="image",
    )
    api_key = _user_image_api_key(request)
    _configure_image_service_from_db(request, db)
    try:
        saved_path = await image2_service.edit_existing_image(
            prompt=prompt,
            source_image_path=source_path,
            output_path=output_path,
            mask_bytes=mask_bytes,
            api_key=api_key or None,
        )
    except Exception as exc:
        if output_path.exists():
            await run_blocking(output_path.unlink)
        logger.warning("漫画资产重绘失败 asset_id=%s: %s", asset.id, exc)
        raise HTTPException(502, public_error_message(exc, "重绘漫画资产失败，请稍后重试")) from exc

    saved_text = str(saved_path or "").strip()
    asset.storage_path = saved_text if saved_text.startswith(("http://", "https://")) else f"manga_outputs/{relative_dir.as_posix()}/{output_path.name}"
    metadata = dict(asset.metadata_json or {})
    try:
        previous_revision = max(0, int(metadata.get("revision") or 0))
    except (TypeError, ValueError):
        previous_revision = 0
    metadata.update({
        "prompt": prompt,
        "provider": "image2",
        "revision": previous_revision + 1,
        "redraw_mode": mode,
    })
    asset.metadata_json = metadata
    asset.source_type = "generated"
    db.commit()
    db.refresh(asset)

    _check_and_consume_quota_wrapper(
        user.id,
        "manga.image.generate.monthly_limit",
        1,
        db,
        deduct=True,
        request=request,
        provider_kind="image",
    )
    if old_local_path and old_local_path != output_path and old_local_path.exists():
        await run_blocking(old_local_path.unlink)
    return _serialize_managed_manga_asset(asset)


_MANGA_ASSET_ANALYSIS_TYPES = {"character_reference", "scene_reference", "prop_reference"}


def _normalize_manga_asset_analysis_suggestions(raw_suggestions: object) -> list[dict[str, object]]:
    """校验并限制章节级漫画资产分析缓存。"""
    if not isinstance(raw_suggestions, list):
        return []
    normalized: list[dict[str, object]] = []
    for item in raw_suggestions[:18]:
        if not isinstance(item, dict):
            continue
        asset_type = str(item.get("asset_type") or "").strip()
        name = str(item.get("name") or "").strip()[:255]
        if asset_type not in _MANGA_ASSET_ANALYSIS_TYPES or not name:
            continue
        candidates: list[dict[str, object]] = []
        raw_candidates = item.get("candidates")
        if isinstance(raw_candidates, list):
            for candidate in raw_candidates[:4]:
                if not isinstance(candidate, dict) or isinstance(candidate.get("id"), bool):
                    continue
                try:
                    candidate_id = int(candidate.get("id"))
                except (TypeError, ValueError):
                    continue
                candidate_type = str(candidate.get("asset_type") or "").strip()
                if candidate_id <= 0 or candidate_type not in _MANGA_ASSET_ANALYSIS_TYPES:
                    continue
                try:
                    match_score = int(candidate.get("match_score") or 0)
                except (TypeError, ValueError):
                    match_score = 0
                candidates.append({
                    "id": candidate_id,
                    "name": str(candidate.get("name") or "").strip()[:255],
                    "asset_type": candidate_type,
                    "storage_path": str(candidate.get("storage_path") or "").strip()[:500],
                    "match_score": max(0, min(match_score, 100)),
                    "match_reason": str(candidate.get("match_reason") or "").strip()[:500],
                })
        normalized.append({
            "asset_type": asset_type,
            "name": name,
            "description": str(item.get("description") or "").strip()[:4000],
            "evidence": str(item.get("evidence") or "").strip()[:2000],
            "prompt": str(item.get("prompt") or "").strip()[:24000],
            "candidates": candidates,
        })
    return normalized


def _stored_manga_asset_analysis_suggestions(chapter: Chapter) -> list[dict[str, object]]:
    payload = chapter.manga_asset_analysis_json
    if isinstance(payload, dict):
        return _normalize_manga_asset_analysis_suggestions(payload.get("suggestions"))
    return []


@router.get("/api/chapters/{chapter_id}/manga-assets/analysis")
async def get_chapter_manga_asset_analysis(
    chapter_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """读取当前章节已保存的漫画资产分析。"""
    user = _require_user(request, db)
    chapter = _require_chapter_for_user(chapter_id, user, db)
    return {"chapter_id": chapter.id, "suggestions": _stored_manga_asset_analysis_suggestions(chapter)}


@router.put("/api/chapters/{chapter_id}/manga-assets/analysis")
async def save_chapter_manga_asset_analysis(
    chapter_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """显式保存用户编辑后的漫画资产提示词。"""
    user = _require_user(request, db)
    chapter = _require_chapter_for_user(chapter_id, user, db)
    body = await request.json()
    if not isinstance(body, dict) or not isinstance(body.get("suggestions"), list):
        raise HTTPException(422, "suggestions 必须是数组")
    suggestions = _normalize_manga_asset_analysis_suggestions(body["suggestions"])
    chapter.manga_asset_analysis_json = {"version": 1, "suggestions": suggestions}
    db.commit()
    return {"chapter_id": chapter.id, "suggestions": suggestions}


@router.post("/api/chapters/{chapter_id}/manga-assets/analyze")
async def analyze_chapter_manga_assets(chapter_id: int, request: Request, db: Session = Depends(get_db)):
    """分析当前章节中适合建立一致性参考的角色、场景和道具。"""
    user = _require_user(request, db)
    chapter = _require_chapter_for_user(chapter_id, user, db)
    chapter_text = str(chapter.novel_content or "").strip()
    if not chapter_text:
        raise HTTPException(422, "当前章节没有可分析的正文")
    story = chapter.story
    character_context = str(getattr(story, "character_profiles", "") or "").strip()
    structured_characters = getattr(story, "characters", None)

    _check_and_consume_quota_wrapper(
        user.id,
        "ai.text.advanced_calls.monthly_limit",
        1,
        db,
        deduct=False,
        request=request,
        provider_kind="text",
    )
    api_key = _user_deepseek_api_key(request, db)
    if not api_key:
        raise HTTPException(400, "文本 AI 服务未配置")

    try:
        result = await analyze_visual_assets(
            chapter_text=chapter_text,
            character_context=character_context,
            structured_characters=structured_characters,
            api_key=api_key,
            max_items=6,
        )
    except Exception as exc:
        logger.exception("漫画资产分析失败 chapter_id=%s", chapter_id)
        raise HTTPException(502, public_error_message(exc, "漫画资产分析失败，请稍后重试")) from exc

    type_map = {
        "characters": "character_reference",
        "scenes": "scene_reference",
        "props": "prop_reference",
    }
    existing_assets = (
        db.query(MangaAsset)
        .filter(
            MangaAsset.story_id == chapter.story_id,
            MangaAsset.owner_user_id == user.id,
            MangaAsset.status == "active",
        )
        .order_by(MangaAsset.id.desc())
        .all()
    )
    normalized: list[dict[str, object]] = []
    for group, asset_type in type_map.items():
        items = result.get(group, []) if isinstance(result, dict) else []
        if not isinstance(items, list):
            continue
        for item in items[:6]:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()[:255]
            if not name:
                continue
            def normalize_match_text(value: str) -> str:
                return re.sub(r"[^\w\u4e00-\u9fff]+", "", value.lower())

            normalized_name = normalize_match_text(name)
            ranked_candidates: list[tuple[int, MangaAsset]] = []
            for asset in existing_assets:
                if asset.asset_type != asset_type:
                    continue
                normalized_asset_name = normalize_match_text(asset.name)
                score = 100 if normalized_asset_name == normalized_name else 0
                if not score and len(normalized_name) >= 2 and normalized_name in normalized_asset_name:
                    score = 70
                if not score and len(normalized_asset_name) >= 2 and normalized_asset_name in normalized_name:
                    score = 60
                if score:
                    ranked_candidates.append((score, asset))
            ranked_candidates.sort(key=lambda item: (-item[0], -item[1].id))
            candidates = [
                {
                    "id": asset.id,
                    "name": asset.name,
                    "asset_type": asset.asset_type,
                    "storage_path": asset.storage_path,
                    "match_score": score,
                    "match_reason": "名称完全匹配" if score == 100 else "名称相近，请确认形象是否一致",
                }
                for score, asset in ranked_candidates[:4]
            ]
            normalized.append({
                "asset_type": asset_type,
                "name": name,
                "description": str(item.get("description") or "").strip()[:4000],
                "evidence": str(item.get("evidence") or "").strip()[:2000],
                "prompt": str(item.get("prompt") or "").strip()[:24000],
                "candidates": candidates,
            })

    normalized = _normalize_manga_asset_analysis_suggestions(normalized)
    chapter.manga_asset_analysis_json = {"version": 1, "suggestions": normalized}
    _check_and_consume_quota_wrapper(
        user.id,
        "ai.text.advanced_calls.monthly_limit",
        1,
        db,
        deduct=True,
        request=request,
        provider_kind="text",
    )
    db.commit()
    return {"chapter_id": chapter.id, "suggestions": normalized}


def _validate_manga_asset_generation_item(body: object) -> dict[str, str]:
    if not isinstance(body, dict):
        raise HTTPException(422, "资产生成项必须是对象")
    asset_type = str(body.get("asset_type") or "").strip()
    allowed_types = {"character_reference", "scene_reference", "prop_reference"}
    if asset_type not in allowed_types:
        raise HTTPException(422, "仅支持生成角色、场景或道具资产")
    name = str(body.get("name") or "").strip()
    prompt = str(body.get("prompt") or "").strip()
    if not name:
        raise HTTPException(422, "资产名称不能为空")
    if len(name) > 255:
        raise HTTPException(422, "资产名称不能超过 255 个字符")
    if not prompt:
        raise HTTPException(422, "资产提示词不能为空")
    if len(prompt) > 24000:
        raise HTTPException(422, "资产提示词不能超过 24000 个字符")
    return {"asset_type": asset_type, "name": name, "prompt": prompt}


async def _generate_and_bind_manga_asset(
    *,
    db: Session,
    chapter_id: int,
    story_id: int,
    user_id: int,
    item: dict[str, str],
    api_key: str | None,
) -> dict:
    asset_type = item["asset_type"]
    name = item["name"]
    prompt = item["prompt"]

    relative_dir = Path(f"story_{story_id}") / "assets"
    filename = f"asset_{uuid.uuid4().hex}.png"
    target_dir = _MANGA_OUTPUTS_DIR / relative_dir
    target_path = target_dir / filename
    await run_blocking(target_dir.mkdir, parents=True, exist_ok=True)

    try:
        saved_path = await generate_visual_asset_image(
            prompt=prompt,
            output_path=target_path,
            asset_type=asset_type,
            api_key=api_key or None,
            size="1920x1080",
        )
    except Exception as exc:
        if target_path.exists():
            await run_blocking(target_path.unlink)
        logger.warning("漫画资产图片生成失败 chapter_id=%s name=%s: %s", chapter_id, name, exc)
        raise

    saved_text = str(saved_path or "").strip()
    storage_path = saved_text if saved_text.startswith(("http://", "https://")) else f"manga_outputs/{relative_dir.as_posix()}/{filename}"
    asset = MangaAsset(
        owner_user_id=user_id,
        story_id=story_id,
        chapter_id=chapter_id,
        asset_type=asset_type,
        name=name,
        storage_path=storage_path,
        source_type="generated",
        status="active",
        metadata_json={"prompt": prompt, "provider": "image2"},
    )
    try:
        db.add(asset)
        db.flush()
        db.add(MangaAssetBinding(
            asset_id=asset.id,
            story_id=story_id,
            chapter_id=chapter_id,
            binding_role=asset_type.replace("_reference", ""),
            label=name,
            priority=0,
            is_required=False,
        ))
        db.commit()
    except Exception:
        db.rollback()
        if target_path.exists():
            await run_blocking(target_path.unlink)
        raise
    db.refresh(asset)
    return {
        "id": asset.id,
        "owner_user_id": asset.owner_user_id,
        "story_id": asset.story_id,
        "chapter_id": asset.chapter_id,
        "asset_type": asset.asset_type,
        "name": asset.name,
        "storage_path": asset.storage_path,
        "source_type": asset.source_type,
        "status": asset.status,
        "metadata": asset.metadata_json,
        "created_at": asset.created_at.isoformat() if asset.created_at else None,
    }


async def _run_manga_asset_batch(
    *,
    items: list[dict[str, str]],
    user_id: int,
    api_key: str | None,
    billing_usage_event_id: int | None,
    style_ref_paths: list[str] | None = None,
    task_id: str | None = None,
    story_id: int | None = None,
    chapter_id: int | None = None,
    shot_id: int | None = None,
) -> dict:
    del shot_id, style_ref_paths
    if story_id is None or chapter_id is None:
        raise ValueError("漫画资产批量任务缺少作品或章节信息")

    concurrency = min(len(items), MANGA_ASSET_GENERATION_CONCURRENCY)
    semaphore = asyncio.Semaphore(concurrency)
    progress_lock = asyncio.Lock()
    results: list[dict | None] = [None] * len(items)
    completed = 0
    failed = 0
    running_indices: set[int] = set()

    async def update_progress(index: int, *, state: str, result: dict | None = None, error: str | None = None) -> None:
        nonlocal completed, failed
        async with progress_lock:
            if state == "running":
                running_indices.add(index)
            else:
                running_indices.discard(index)
                if state == "succeeded":
                    completed += 1
                else:
                    failed += 1
                results[index] = {
                    "index": index,
                    "name": items[index]["name"],
                    "asset_type": items[index]["asset_type"],
                    "status": state,
                    "asset": result,
                    "error": error,
                }
            task_manager.update_task_metadata(
                task_id,
                stage="generating_assets",
                message=f"正在并行生成资产图，已完成 {completed + failed}/{len(items)} 张",
                total=len(items),
                completed=completed,
                failed=failed,
                running_indices=sorted(running_indices),
                concurrency=concurrency,
            )

    async def generate_one(index: int, item: dict[str, str]) -> None:
        async with semaphore:
            await update_progress(index, state="running")
            item_db = SessionLocal()
            try:
                asset = await _generate_and_bind_manga_asset(
                    db=item_db,
                    chapter_id=chapter_id,
                    story_id=story_id,
                    user_id=user_id,
                    item=item,
                    api_key=api_key,
                )
                await update_progress(index, state="succeeded", result=asset)
            except Exception as exc:
                item_db.rollback()
                logger.exception(
                    "批量生成漫画资产失败 chapter_id=%s index=%s name=%s",
                    chapter_id,
                    index,
                    item["name"],
                )
                await update_progress(
                    index,
                    state="failed",
                    error=public_error_message(exc, "漫画资产生成失败，请稍后重试"),
                )
            finally:
                item_db.close()

    try:
        await asyncio.gather(*(generate_one(index, item) for index, item in enumerate(items)))
    finally:
        if billing_usage_event_id:
            billing_db = SessionLocal()
            try:
                from services.ai.resolver import complete_ai_call_by_usage_event

                complete_ai_call_by_usage_event(
                    billing_db,
                    billing_usage_event_id,
                    success=True,
                    image_count=completed,
                    usage_source="provider",
                )
            finally:
                billing_db.close()
            task_manager.update_task_metadata(
                task_id,
                billing_usage_event_id=0,
                billing_settled_images=completed,
            )

    task_manager.update_task_metadata(
        task_id,
        stage="succeeded",
        message=f"批量生成完成：成功 {completed} 张，失败 {failed} 张",
        total=len(items),
        completed=completed,
        failed=failed,
        running_indices=[],
        concurrency=concurrency,
    )
    return {
        "status": "completed",
        "total": len(items),
        "completed": completed,
        "failed": failed,
        "items": [result for result in results if result is not None],
    }


@router.post("/api/chapters/{chapter_id}/manga-assets/generate", status_code=201)
async def generate_chapter_manga_asset(
    chapter_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """根据可编辑提示词生成漫画资产并自动绑定到当前章节。"""
    user = _require_user(request, db)
    chapter = _require_chapter_for_user(chapter_id, user, db)
    item = _validate_manga_asset_generation_item(await request.json())
    _check_and_consume_quota_wrapper(
        user.id,
        "manga.image.generate.monthly_limit",
        1,
        db,
        deduct=False,
        request=request,
        provider_kind="image",
    )
    api_key = _user_image_api_key(request)
    _configure_image_service_from_db(request, db)
    try:
        asset = await _generate_and_bind_manga_asset(
            db=db,
            chapter_id=chapter.id,
            story_id=chapter.story_id,
            user_id=user.id,
            item=item,
            api_key=api_key,
        )
    except Exception as exc:
        raise HTTPException(502, public_error_message(exc, "生成漫画资产失败，请稍后重试")) from exc
    _check_and_consume_quota_wrapper(
        user.id,
        "manga.image.generate.monthly_limit",
        1,
        db,
        deduct=True,
        request=request,
        provider_kind="image",
    )
    return asset


@router.post("/api/chapters/{chapter_id}/manga-assets/generate-batch", status_code=202)
async def generate_chapter_manga_assets_batch(
    chapter_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """提交章节漫画资产批量出图任务，响应返回后仍在后台并发执行。"""
    user = _require_user(request, db)
    chapter = _require_chapter_for_user(chapter_id, user, db)
    body = await request.json()
    raw_items = body.get("items") if isinstance(body, dict) else None
    if not isinstance(raw_items, list) or not raw_items:
        raise HTTPException(422, "请至少选择一个待生成资产")
    if len(raw_items) > MANGA_ASSET_BATCH_MAX_ITEMS:
        raise HTTPException(422, f"单次最多生成 {MANGA_ASSET_BATCH_MAX_ITEMS} 个资产")
    items = [_validate_manga_asset_generation_item(item) for item in raw_items]

    quota_result = _check_and_consume_quota_wrapper(
        user.id,
        "manga.image.generate.monthly_limit",
        len(items),
        db,
        deduct=False,
        request=request,
        provider_kind="image",
    )
    api_key = _user_image_api_key(request)
    _configure_image_service_from_db(request, db)
    import main as main_mod

    usage_event_id = quota_result.get("usage_event_id")
    main_mod._detach_pending_platform_points(request, usage_event_id)
    task_id = f"manga_asset_batch_{chapter.id}_{uuid.uuid4().hex[:12]}"
    try:
        await task_manager.submit_task(
            task_id=task_id,
            task_type="manga_asset_batch_generation",
            coro_func=_run_manga_asset_batch,
            items=items,
            user_id=user.id,
            api_key=api_key,
            billing_usage_event_id=usage_event_id,
            story_id=chapter.story_id,
            chapter_id=chapter.id,
            timeout=max(600.0, len(items) * 180.0),
            max_retries=0,
            quota_user_id=user.id,
            quota_feature_key="manga.image.generate.monthly_limit",
            quota_amount=len(items),
            quota_usage_event_id=usage_event_id,
            metadata={
                "owner_user_id": user.id,
                "stage": "queued",
                "message": f"{len(items)} 个资产已加入后台生成队列",
                "running_stage": "generating_assets",
                "running_message": "正在并行生成漫画资产图",
                "total": len(items),
                "completed": 0,
                "failed": 0,
                "running_indices": [],
                "concurrency": min(len(items), MANGA_ASSET_GENERATION_CONCURRENCY),
                "item_names": [item["name"] for item in items],
            },
        )
    except Exception as exc:
        if usage_event_id:
            refund_db = SessionLocal()
            try:
                from services.ai.resolver import refund_ai_call

                refund_ai_call(refund_db, usage_event_id, error_code="task_submission_failed")
            finally:
                refund_db.close()
        raise HTTPException(500, public_error_message(exc, "提交漫画资产后台任务失败，请稍后重试")) from exc

    return {
        "task_id": task_id,
        "status": "pending",
        "total": len(items),
        "message": "资产已加入后台生成队列，关闭弹窗或网页不会中断任务",
    }


def _require_shot_for_user(shot_id: int, user: User, db: Session) -> VideoShot:
    shot = db.get(VideoShot, shot_id)
    if not shot:
        raise HTTPException(404, "视频分镜未找到")
    if not shot.scene:
        raise HTTPException(404, "场景未找到")
    _require_chapter_for_user(shot.scene.chapter_id, user, db)
    return shot


def _require_video_asset_for_user(asset_id: int, user: User, db: Session) -> VideoAsset:
    asset = db.get(VideoAsset, asset_id)
    if not asset:
        raise HTTPException(404, "视频素材未找到")

    linked_story_ids: set[int] = set()
    chapter_id = None
    if asset.story_id is not None:
        linked_story_ids.add(asset.story_id)
    if asset.chapter_id is not None:
        chapter = db.get(Chapter, asset.chapter_id)
        if not chapter:
            raise HTTPException(404, "视频素材关联章节不存在")
        linked_story_ids.add(chapter.story_id)
        chapter_id = chapter.id
    if asset.scene_id is not None:
        scene = db.get(ScriptScene, asset.scene_id)
        if not scene:
            raise HTTPException(404, "视频素材关联场景不存在")
        scene_chapter = db.get(Chapter, scene.chapter_id)
        if not scene_chapter:
            raise HTTPException(404, "视频素材关联场景的章节不存在")
        linked_story_ids.add(scene_chapter.story_id)
        chapter_id = chapter_id or scene_chapter.id
    if asset.shot_id is not None:
        shot = db.get(VideoShot, asset.shot_id)
        if not shot or not shot.scene:
            raise HTTPException(404, "视频素材关联分镜不存在")
        shot_chapter = db.get(Chapter, shot.scene.chapter_id)
        if not shot_chapter:
            raise HTTPException(404, "视频素材关联分镜的章节不存在")
        linked_story_ids.add(shot_chapter.story_id)
        chapter_id = chapter_id or shot_chapter.id
    if not linked_story_ids:
        raise HTTPException(404, "视频素材未关联有效章节")
    if len(linked_story_ids) != 1:
        raise HTTPException(409, "视频素材关联的作品不一致")

    if chapter_id is not None:
        _require_chapter_for_user(chapter_id, user, db)
    else:
        _require_story_for_user(next(iter(linked_story_ids)), user, db)
    return asset


def _require_reference_assets_for_story(
    asset_ids: list[int],
    story_id: int,
    db: Session,
) -> list[VideoAsset]:
    if not asset_ids:
        return []
    unique_ids = list(dict.fromkeys(int(asset_id) for asset_id in asset_ids))
    assets = db.query(VideoAsset).filter(VideoAsset.id.in_(unique_ids)).all()
    asset_map = {asset.id: asset for asset in assets}
    if len(asset_map) != len(unique_ids):
        raise HTTPException(404, "参考素材不存在")

    for asset_id in unique_ids:
        asset = asset_map[asset_id]
        linked_story_ids: set[int] = set()
        if asset.story_id is not None:
            linked_story_ids.add(asset.story_id)
        if asset.chapter_id is not None:
            chapter = db.get(Chapter, asset.chapter_id)
            if not chapter:
                raise HTTPException(404, "参考素材关联章节不存在")
            linked_story_ids.add(chapter.story_id)
        if asset.scene_id is not None:
            scene = db.get(ScriptScene, asset.scene_id)
            chapter = db.get(Chapter, scene.chapter_id) if scene else None
            if not chapter:
                raise HTTPException(404, "参考素材关联场景不存在")
            linked_story_ids.add(chapter.story_id)
        if asset.shot_id is not None:
            shot = db.get(VideoShot, asset.shot_id)
            chapter = db.get(Chapter, shot.scene.chapter_id) if shot and shot.scene else None
            if not chapter:
                raise HTTPException(404, "参考素材关联分镜不存在")
            linked_story_ids.add(chapter.story_id)
        if linked_story_ids != {story_id}:
            raise HTTPException(403, "参考素材不属于当前作品")

    return [asset_map[asset_id] for asset_id in unique_ids]





def _serialize_datetime(dt: datetime.datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.isoformat()


def _serialize_scene(scene: ScriptScene) -> dict:
    return {
        "id": scene.id,
        "chapter_id": scene.chapter_id,
        "scene_number": scene.scene_number,
        "title": scene.title or "",
        "location": scene.location or "",
        "time_of_day": scene.time_of_day or "",
        "characters": scene.characters_json or [],
        "summary": scene.summary or "",
        "dialogue": scene.dialogue_json or [],
        "voiceover": scene.voiceover or "",
        "mood": scene.mood or "",
        "estimated_duration_seconds": scene.estimated_duration_seconds,
        "concept_art_asset_id": scene.concept_art_asset_id,
        "source_type": scene.source_type or "",
        "status": scene.status or "draft",
        "created_at": _serialize_datetime(scene.created_at),
        "updated_at": _serialize_datetime(scene.updated_at),
    }


def _serialize_shot(shot: VideoShot) -> dict:
    return {
        "id": shot.id,
        "scene_id": shot.scene_id,
        "shot_number": shot.shot_number,
        "title": shot.title or "",
        "shot_type": shot.shot_type or "",
        "camera_angle": shot.camera_angle or "",
        "camera_movement": shot.camera_movement or "",
        "composition": shot.composition or "",
        "action_description": shot.action_description or "",
        "dialogue": shot.dialogue or "",
        "sound_design": shot.sound_design or "",
        "duration_seconds": shot.duration_seconds,
        "storyboard_prompt": shot.storyboard_prompt or "",
        "video_prompt": shot.video_prompt or "",
        "negative_prompt": shot.negative_prompt or "",
        "first_frame_prompt": shot.first_frame_prompt or "",
        "last_frame_prompt": shot.last_frame_prompt or "",
        "character_prompts_json": shot.character_prompts_json or [],
        "continuity_notes": shot.continuity_notes or "",
        "character_involvement": shot.character_involvement,
        "scene_mood": shot.scene_mood,
        "status": shot.status or "draft",
        "created_at": _serialize_datetime(shot.created_at),
        "updated_at": _serialize_datetime(shot.updated_at),
    }


def _serialize_usage(used: int, limit: int) -> dict:
    return {
        "used": used,
        "limit": limit,
        "remaining": max(0, limit - used),
    }


def _safe_dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _normalize_style_name(name: str | None) -> str:
    if not name:
        return ""
    trimmed = name.strip()
    aliases = {
        "3A娓告垙娓叉瀽": "3A娓告垙娓叉煋",
        "3D娓告垙娓叉煋": "3A娓告垙娓叉煋",
    }
    return aliases.get(trimmed, trimmed)


def _merge_style_prompt(base_prompt: str, style_template: str | None, style_name: str | None) -> str:
    base = (base_prompt or "").strip()
    template = (style_template or "").strip()
    name = (style_name or "").strip()
    style_text = template.strip(". ") if template else (name if name else "")
    if not style_text:
        return base
    if not base:
        return style_text
    # 风格指令放在开头作为最高优先级约束，确保不被后续内容覆盖
    if len(base) > 300:
        return f"STYLE DIRECTIVE (highest priority): {style_text}. ALL content below must follow this style. Do NOT apply any other art style.\n\n{base}"
    # 短提示词：前缀方式
    return f"{style_text}. {base}"


def _merge_style_prompt_for_reference_image(
    base_prompt: str,
    style_ref_path: str | None,
    style_template: str | None,
    style_name: str | None,
) -> str:
    """已有风格参考图时只保留内容提示词，避免文字预设覆盖图片画风。"""
    base = (base_prompt or "").strip()
    return base if style_ref_path else _merge_style_prompt(base, style_template, style_name)


def _build_shot_asset_context(shot: VideoShot, asset_type: str, target_name: str = "") -> str:
    """从 shot 已提取的关键元素构建资产生成上下文，确保形象与时代背景一致。

    asset_type: "character" | "prop" | "scene"
    target_name: 角色名或道具名，用于精准匹配 character_prompts_json / key_props_json
    """
    parts: list[str] = []

    if asset_type == "character" and target_name:
        char_prompts = shot.character_prompts_json or []
        for cp in char_prompts:
            if isinstance(cp, dict) and cp.get("name") == target_name:
                parts.append(f"角色形象：{cp.get('prompt', '')}")
                break

    if asset_type == "prop" and target_name:
        key_props = shot.key_props_json or []
        for kp in key_props:
            kp_str = str(kp)
            if target_name in kp_str:
                parts.append(f"道具描述：{kp_str}")
                break

    if asset_type == "scene":
        scene_candidates = shot.scene_asset_candidates_json or []
        if scene_candidates:
            parts.append(f"场景元素：{'；'.join(str(s) for s in scene_candidates)}")

    if shot.story_summary:
        parts.append(f"情节背景：{shot.story_summary}")
    if shot.scene_location:
        loc = shot.scene_location
        if shot.time_of_day:
            loc = f"{loc}，{shot.time_of_day}"
        parts.append(f"场景时空：{loc}")
    if shot.key_props_json and asset_type != "prop":
        parts.append(f"关键道具：{'；'.join(str(p) for p in shot.key_props_json)}")
    if shot.source_text_span:
        parts.append(f"原文段落：{shot.source_text_span[:500]}")

    if not parts:
        return ""
    return "\n".join(parts)


def _extract_character_notes(character_profiles: str | None, character_names: list[str]) -> dict[str, str]:
    text = (character_profiles or "").strip()
    if not text or not character_names:
        return {}
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    notes: dict[str, str] = {}
    for name in character_names:
        for idx, ln in enumerate(lines):
            if name in ln:
                snippet = [ln]
                if idx + 1 < len(lines):
                    snippet.append(lines[idx + 1])
                notes[name] = " ".join(snippet)[:300]
                break
    return notes


def _find_character_struct(story: Story | None, character_name: str) -> dict | None:
    if not story or not isinstance(story.characters, list):
        return None
    target = (character_name or "").strip()
    if not target:
        return None
    for c in story.characters:
        if not isinstance(c, dict):
            continue
        name = str(c.get("name") or "").strip()
        if name and (name == target or target in name or name in target):
            return c
    return None


def _build_character_sheet_prompt(
    character_name: str,
    story: Story | None,
    note_from_profiles: str,
    inherited_prompt: str,
) -> str:
    c = _find_character_struct(story, character_name) or {}
    role = str(c.get("role") or "").strip()
    arc = str(c.get("arc") or "").strip()
    traits = ""
    bf = c.get("big_five")
    if isinstance(bf, dict):
        traits = _compact_json(bf, 180)

    card = (
        "Character design sheet, one-page turnaround board. "
        "Required layout: front view portrait, side view portrait, back view portrait, full-body standing pose, "
        "4 facial expressions (neutral, surprised, smiling, focused), "
        "and outfit/detail callouts including accessories and material notes. "
        "Include a clear costume breakdown panel and color palette chips. "
        "Use orthographic-like character-sheet composition with clean labels and consistent proportions. "
        "Clean light background, no scene background, no story event text overlays. "
        f"Character name: {character_name}. "
        f"Role: {role}. Character arc: {arc}. "
        f"Personality profile (Big Five): {traits}. "
        f"Appearance details: {note_from_profiles or 'detailed facial features, hairstyle, eye shape, body type, signature colors required'}. "
        f"Reference anchor: {inherited_prompt or 'consistent identity markers across all frames'}. "
        "Mandatory consistency: lock face shape, eye distance, nose bridge contour, lip shape, jawline angle, hair parting, and 3 signature color swatches across ALL generated frames. "
        "This is a master reference sheet for video animation consistency. Every subsequent frame MUST match these identity markers exactly."
    )
    return card


def _get_active_frame_assets_for_shot(shot_id: int, db: Session) -> list[VideoAsset]:
    return (
        db.query(VideoAsset)
        .filter(
            VideoAsset.shot_id == shot_id,
            VideoAsset.asset_type == "frame",
            VideoAsset.status == "active",
        )
        .order_by(VideoAsset.created_at.desc())
        .all()
    )


def _collect_shot_reference_asset_ids(
    shot: VideoShot,
    db: Session,
    include_characters: bool = False,
    include_scene: bool = False,
    include_storyboard: bool = False,
    include_frames: bool = False,
    explicit_asset_ids: list[int] | None = None,
) -> list[int]:
    ids: list[int] = []
    if include_characters and shot.scene:
        ids.extend([a.id for a in _select_character_reference_assets_for_scene(shot.scene, db, limit=12)])
    if include_scene and shot.scene and shot.scene.concept_art_asset_id:
        ids.append(int(shot.scene.concept_art_asset_id))
    if include_storyboard and shot.storyboard_asset_id:
        ids.append(int(shot.storyboard_asset_id))
    if include_frames:
        ids.extend([a.id for a in _get_active_frame_assets_for_shot(shot.id, db)])
    if explicit_asset_ids:
        explicit_ids = [int(x) for x in explicit_asset_ids if str(x).isdigit()]
        chapter = shot.scene.chapter if shot.scene and shot.scene.chapter else None
        if chapter is None and shot.scene:
            chapter = db.get(Chapter, shot.scene.chapter_id)
        story_id = chapter.story_id if chapter else None
        if story_id is None:
            raise HTTPException(404, "分镜未关联有效作品")
        _require_reference_assets_for_story(explicit_ids, story_id, db)
        ids.extend(explicit_ids)
    return list(dict.fromkeys(ids))


def _split_frame_assets(ref_assets: list[VideoAsset]) -> tuple[VideoAsset | None, VideoAsset | None, list[VideoAsset]]:
    """从参考资产中分离首帧、尾帧和其他参考图。"""
    first_frame: VideoAsset | None = None
    last_frame: VideoAsset | None = None
    other: list[VideoAsset] = []
    for a in ref_assets:
        sub = a.asset_subtype or ""
        if sub == "first_frame":
            first_frame = a
        elif sub == "last_frame":
            last_frame = a
        else:
            other.append(a)
    return first_frame, last_frame, other


def _get_previous_shot_last_frame(shot: VideoShot, db: Session) -> VideoAsset | None:
    """获取同一场景中前一个镜头的尾帧资产，用于视频连贯继承。"""
    if not shot.scene_id or not shot.shot_number:
        return None
    prev_shot = (
        db.query(VideoShot)
        .filter(
            VideoShot.scene_id == shot.scene_id,
            VideoShot.shot_number < shot.shot_number,
        )
        .order_by(VideoShot.shot_number.desc())
        .first()
    )
    if not prev_shot:
        return None
    return (
        db.query(VideoAsset)
        .filter(
            VideoAsset.shot_id == prev_shot.id,
            VideoAsset.asset_type == "frame",
            VideoAsset.asset_subtype == "last_frame",
            VideoAsset.status == "active",
        )
        .order_by(VideoAsset.created_at.desc())
        .first()
    )


def _select_character_reference_assets_for_scene(scene: ScriptScene, db: Session, limit: int = 6) -> list[VideoAsset]:
    chapter_id = scene.chapter_id
    scene_characters = [str(c).strip() for c in (scene.characters_json or []) if str(c).strip()]
    matched: list[VideoAsset] = []
    used_ids: set[int] = set()
    chapter = db.get(Chapter, chapter_id) if chapter_id else None
    story_id = chapter.story_id if chapter else None

    # 第一级：Story 级角色库默认版本参考图
    if story_id and scene_characters:
        for ch in scene_characters:
            version = db.query(StoryCharacterVersion).filter(
                StoryCharacterVersion.story_id == story_id,
                StoryCharacterVersion.character_name == ch,
                StoryCharacterVersion.is_default == True,
                StoryCharacterVersion.ref_asset_id.isnot(None),
            ).first()
            if version and version.ref_asset_id and version.ref_asset_id not in used_ids:
                asset = db.get(VideoAsset, version.ref_asset_id)
                if asset and asset.status == "active":
                    matched.append(asset)
                    used_ids.add(version.ref_asset_id)
                    if len(matched) >= limit:
                        return matched[:limit]

    # 第二级：Chapter 级 character_reference 资产（兜底）
    all_chapter_assets = (
        db.query(VideoAsset)
        .filter(
            VideoAsset.chapter_id == chapter_id,
            VideoAsset.asset_type == "character_reference",
            VideoAsset.status == "active",
        )
        .order_by(VideoAsset.created_at.desc())
        .all()
    )
    if not scene_characters:
        for a in all_chapter_assets:
            if a.id not in used_ids:
                matched.append(a)
                used_ids.add(a.id)
        return matched[:limit]

    for ch in scene_characters:
        for a in all_chapter_assets:
            if a.id in used_ids:
                continue
            if ch in (a.name or "") or ch in (a.prompt or ""):
                matched.append(a)
                used_ids.add(a.id)
                break

    if len(matched) < limit:
        for a in all_chapter_assets:
            if a.id in used_ids:
                continue
            matched.append(a)
            if len(matched) >= limit:
                break
    return matched[:limit]


def _select_scene_reference_assets_for_shot(shot: VideoShot, db: Session, limit: int = 3) -> list[VideoAsset]:
    """选择当前 shot 可用的场景参考图资产（继承逻辑）。"""
    matched: list[VideoAsset] = []
    used_ids: set[int] = set()

    current_assets = (
        db.query(VideoAsset)
        .filter(
            VideoAsset.shot_id == shot.id,
            VideoAsset.asset_type == "scene_reference",
            VideoAsset.status == "active",
        )
        .order_by(VideoAsset.created_at.desc())
        .all()
    )
    for a in current_assets:
        if a.id not in used_ids:
            matched.append(a)
            used_ids.add(a.id)
            if len(matched) >= limit:
                return matched[:limit]

    if shot.scene_id:
        sibling_assets = (
            db.query(VideoAsset)
            .filter(
                VideoAsset.scene_id == shot.scene_id,
                VideoAsset.asset_type == "scene_reference",
                VideoAsset.shot_id != shot.id,
                VideoAsset.status == "active",
            )
            .order_by(VideoAsset.created_at.desc())
            .all()
        )
        for a in sibling_assets:
            if a.id not in used_ids:
                matched.append(a)
                used_ids.add(a.id)
                if len(matched) >= limit:
                    return matched[:limit]

    if shot.scene and shot.scene.concept_art_asset_id:
        concept_id = shot.scene.concept_art_asset_id
        if concept_id not in used_ids:
            asset = db.get(VideoAsset, concept_id)
            if asset and asset.status == "active":
                matched.append(asset)
                used_ids.add(concept_id)

    return matched[:limit]


def _select_prop_reference_assets_for_shot(shot: VideoShot, db: Session, limit: int = 6) -> list[VideoAsset]:
    """选择当前 shot 可用的道具参考图资产（继承逻辑）。"""
    matched: list[VideoAsset] = []
    used_ids: set[int] = set()

    prop_names: list[str] = []
    if shot.prop_prompts_json:
        for item in shot.prop_prompts_json:
            if isinstance(item, dict):
                name = str(item.get("name") or "").strip()
                if name:
                    prop_names.append(name)

    current_assets = (
        db.query(VideoAsset)
        .filter(
            VideoAsset.shot_id == shot.id,
            VideoAsset.asset_type == "prop_reference",
            VideoAsset.status == "active",
        )
        .order_by(VideoAsset.created_at.desc())
        .all()
    )
    for a in current_assets:
        if a.id not in used_ids:
            matched.append(a)
            used_ids.add(a.id)
            if len(matched) >= limit:
                return matched[:limit]

    if shot.scene_id and prop_names:
        sibling_assets = (
            db.query(VideoAsset)
            .filter(
                VideoAsset.scene_id == shot.scene_id,
                VideoAsset.asset_type == "prop_reference",
                VideoAsset.shot_id != shot.id,
                VideoAsset.status == "active",
            )
            .order_by(VideoAsset.created_at.desc())
            .all()
        )
        for name in prop_names:
            for a in sibling_assets:
                if a.id in used_ids:
                    continue
                if name in (a.name or ""):
                    matched.append(a)
                    used_ids.add(a.id)
                    break
            if len(matched) >= limit:
                return matched[:limit]

    chapter_id = shot.scene.chapter_id if shot.scene else None
    if chapter_id and prop_names:
        chapter_assets = (
            db.query(VideoAsset)
            .filter(
                VideoAsset.chapter_id == chapter_id,
                VideoAsset.asset_type == "prop_reference",
                VideoAsset.status == "active",
            )
            .order_by(VideoAsset.created_at.desc())
            .all()
        )
        for name in prop_names:
            for a in chapter_assets:
                if a.id in used_ids:
                    continue
                if name in (a.name or ""):
                    matched.append(a)
                    used_ids.add(a.id)
                    break
            if len(matched) >= limit:
                return matched[:limit]

    return matched[:limit]


def _build_reference_constraints_block(character_assets: list[VideoAsset]) -> str:
    """构建参考资产使用说明，按资产类型给出中文编号的角色标注。"""
    if not character_assets:
        return ""

    # 按资产类型分组
    groups: dict[str, list[VideoAsset]] = {}
    for a in character_assets:
        at = a.asset_type or "reference"
        groups.setdefault(at, []).append(a)

    # 按固定顺序排列：故事版 → 人物 → 场景 → 道具 → 首尾帧
    type_order = [
        ("storyboard_frame", "故事版图片"),
        ("character_reference", "人物参考图"),
        ("story_character_reference", "人物参考图"),
        ("scene_reference", "场景参考图"),
        ("prop_reference", "道具参考图"),
        ("style_reference", "风格参考图"),
        ("style", "风格参考图"),
        ("frame", "首尾帧参考图"),
    ]

    ordered_groups: list[tuple[str, list[VideoAsset]]] = []
    seen_types: set[str] = set()
    for at, label in type_order:
        if at in groups and at not in seen_types:
            ordered_groups.append((label, groups[at]))
            seen_types.add(at)
    for at, assets in groups.items():
        if at not in seen_types:
            ordered_groups.append((f"{at}参考图", assets))
            seen_types.add(at)

    # 全局编号
    img_index = 0
    guide_parts: list[str] = []
    constraint_parts: list[str] = []

    for label, assets in ordered_groups:
        for a in assets[:3]:  # 每种最多 3 张
            img_index += 1
            name = a.name or "未命名"
            guide_parts.append(f"图{img_index}是{label}：{name}")

    # 按类型生成约束
    for label, assets in ordered_groups:
        if not assets:
            continue
        if "故事版" in label:
            constraint_parts.append(
                "故事版图片是导演蓝图：必须严格遵循分镜脚本中的镜头运动、人物动作、情绪变化和时间分配，不得偏离。"
            )
        elif "人物" in label:
            constraint_parts.append(
                "人物参考图确保角色一致性：视频中角色的外貌、服装、发型、体型必须与人物参考图完全一致，禁止任何变化。"
            )
        elif "场景" in label:
            constraint_parts.append(
                "场景参考图确保环境一致性：光线、色调、空间布局、建筑细节必须与场景参考图保持一致。"
            )
        elif "道具" in label:
            constraint_parts.append(
                "道具参考图确保道具一致性：材质、颜色、大小、形状、纹理必须与道具参考图完全相同。"
            )
        elif "风格" in label:
            constraint_parts.append(
                "风格参考图只决定画面媒介、笔触、色调、光影和渲染质感，不复制其中的角色、场景或道具。"
            )

    parts = ["<<<REFERENCE_ASSET_GUIDE>>>"]
    parts.append("以下参考图已传入视频模型。各图片编号和用途如下：")
    parts.extend(guide_parts)
    parts.append("")
    parts.append("<<<CONSTRAINT_RULES>>>")
    parts.extend(constraint_parts)
    parts.append(
        "核心约束：所有参考图中的视觉元素（角色外貌、场景环境、道具外观）"
        "必须在视频全过程中保持完全一致，不得漂移、不得变化、不得重新解读。"
    )
    return "\n".join(parts)


def _resolve_asset_reference_urls(
    asset_ids: list[int],
    db: Session,
    request: Request | None = None,
) -> list[str]:
    if not asset_ids:
        return []

    assets = db.query(VideoAsset).filter(VideoAsset.id.in_(asset_ids)).all()
    url_map = {a.id: a.file_path for a in assets}

    seen: set[str] = set()
    urls: list[str] = []
    for aid in asset_ids:
        fp = url_map.get(aid)
        if not fp or fp in seen:
            continue
        seen.add(fp)

        resolved = resolve_reference_input(fp, "video")
        if resolved:
            urls.append(resolved)
            continue

        normalized = _to_video_url(fp)
        if normalized:
            urls.append(normalized)

    logger.info("解析 %d 个参考资产为 %d 个参考输入", len(asset_ids), len(urls))
    return urls


def _sanitize_media_boundary_value(value):
    """递归移除持久化、响应和日志边界中的媒体凭据与内联二进制。"""
    if isinstance(value, dict):
        return {
            str(key): sanitized
            for key, item in value.items()
            if (sanitized := _sanitize_media_boundary_value(item)) is not None
        }
    if isinstance(value, (list, tuple)):
        return [
            sanitized
            for item in value
            if (sanitized := _sanitize_media_boundary_value(item)) is not None
        ]
    if isinstance(value, str):
        text = value.strip()
        if text.lower().startswith("data:"):
            return None
        if text.lower().startswith(("http://", "https://")):
            return safe_media_url_for_log(text)
    return value


def _sanitize_video_job_request_payload(payload: dict | None) -> dict:
    """生成只含资产标识、角色元数据和安全 URL 标识的任务快照。"""
    sanitized = _sanitize_media_boundary_value(payload or {})
    return sanitized if isinstance(sanitized, dict) else {}


def _sanitize_video_provider_result(result: dict | None) -> dict:
    """递归清理供应商结果，禁止签名参数和 Base64 越过安全边界。"""
    sanitized = _sanitize_media_boundary_value(result or {})
    return sanitized if isinstance(sanitized, dict) else {}


def _projected_base64_size(raw_size: int) -> int:
    return 4 * ((raw_size + 2) // 3)


def _encode_reference_files_to_base64_data_uris(file_paths: list[str]) -> list[str]:
    """先完成整批大小预检，再以分块方式编码本地参考文件。"""
    import base64 as b64

    inspected: list[tuple[str, int]] = []
    total_bytes = 0
    projected_bytes = 0
    for file_path in file_paths:
        try:
            size = os.stat(file_path).st_size
        except OSError as exc:
            raise ValueError(f"无法读取参考文件: {file_path}") from exc
        if size > MAX_VIDEO_REFERENCE_FILE_BYTES:
            raise ValueError("单个参考文件超过 30 MiB 限制")
        total_bytes += size
        projected_bytes += _projected_base64_size(size)
        if total_bytes > MAX_VIDEO_REFERENCE_TOTAL_BYTES:
            raise ValueError("参考文件累计大小超过限制")
        if projected_bytes > MAX_VIDEO_REFERENCE_BASE64_BYTES:
            raise ValueError("参考文件投影 Base64 大小超过限制")
        inspected.append((file_path, size))

    encoded: list[str] = []
    mime_map = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }
    for file_path, _size in inspected:
        chunks: list[bytes] = []
        carry = b""
        with open(file_path, "rb") as fh:
            while chunk := fh.read(1024 * 1024):
                block = carry + chunk
                aligned = len(block) - (len(block) % 3)
                if aligned:
                    chunks.append(b64.b64encode(block[:aligned]))
                carry = block[aligned:]
        if carry:
            chunks.append(b64.b64encode(carry))
        mime = mime_map.get(os.path.splitext(file_path)[1].lower(), "image/png")
        encoded.append(f"data:{mime};base64,{b''.join(chunks).decode('ascii')}")
    return encoded


def _preencode_local_video_references(
    file_paths: list[str],
    *,
    remote_reference_count: int = 0,
) -> list[str]:
    """在读取任一文件前同时校验引用总数与本地文件预算。"""
    if len(file_paths) + remote_reference_count > MAX_VIDEO_REFERENCE_COUNT:
        raise ValueError(f"视频参考输入最多允许 {MAX_VIDEO_REFERENCE_COUNT} 张")
    return _encode_reference_files_to_base64_data_uris(file_paths)


def _prepare_video_reference_images(reference_inputs: list[str]) -> list[str]:
    """整批预检本地引用，并保持本地文件与远程 URL 的原始顺序。"""
    if len(reference_inputs) > MAX_VIDEO_REFERENCE_COUNT:
        raise ValueError(f"视频参考输入最多允许 {MAX_VIDEO_REFERENCE_COUNT} 张")
    local_paths = [
        value
        for value in reference_inputs
        if not value.lower().startswith(("http://", "https://", "data:"))
    ]
    encoded_local = iter(
        _preencode_local_video_references(
            local_paths,
            remote_reference_count=len(reference_inputs) - len(local_paths),
        )
    )
    return [
        value
        if value.lower().startswith(("http://", "https://", "data:"))
        else next(encoded_local)
        for value in reference_inputs
    ]


def _validate_video_reference_count(reference_count: int) -> None:
    """在计费和上游调用前拒绝超出供应商硬上限的最终引用集合。"""
    if reference_count > MAX_VIDEO_REFERENCE_COUNT:
        raise ValueError(f"视频参考输入最多允许 {MAX_VIDEO_REFERENCE_COUNT} 张")


def _encode_file_to_base64_data_uri(file_path: str) -> str | None:
    """兼容单文件调用，并复用整批预检与分块编码。"""
    try:
        return _encode_reference_files_to_base64_data_uris([file_path])[0]
    except OSError:
        logger.warning("无法读取参考图片文件: %s", safe_media_url_for_log(file_path))
        return None


def _resolve_asset_file_paths(assets: list[VideoAsset]) -> list[str]:
    """将资产解析为图片模型可读取的受控本地路径。"""
    paths: list[str] = []
    for asset in assets:
        fp = (asset.file_path or "").strip()
        if not fp:
            continue
        local = ensure_local_media_path(fp, "video") or ensure_local_media_path(fp, "manga")
        if local:
            paths.append(local)
        else:
            logger.warning("找不到参考图片文件: %s", fp)
    return paths


def _resolve_visual_asset_references(
    assets: list[VideoAsset],
) -> list[tuple[VideoAsset, str, str, str]]:
    """解析并对齐角色、场景、道具资产的路径、标签和角色。"""
    role_map = {
        "character_reference": "character",
        "story_character_reference": "character",
        "scene_reference": "scene",
        "prop_reference": "prop",
        "style_reference": "style",
        "style": "style",
    }
    resolved: list[tuple[VideoAsset, str, str, str]] = []
    for asset in assets:
        role = role_map.get(asset.asset_type or "")
        if not role:
            continue
        paths = _resolve_asset_file_paths([asset])
        if paths:
            resolved.append((asset, paths[0], asset.name or "", role))
    return resolved


def _resolve_frame_reference_inputs(
    assets: list[VideoAsset],
    style_ref_path: str | None = None,
) -> tuple[list[str], list[str], list[str]]:
    """解析首尾帧参考图，并保证路径、标签和角色严格同序。"""
    role_map = {
        "character_reference": "character",
        "story_character_reference": "character",
        "scene_reference": "scene",
        "prop_reference": "prop",
        "style_reference": "style",
        "style": "style",
        "storyboard_frame": "scene",
        "frame": "scene",
    }
    ref_paths: list[str] = []
    ref_labels: list[str] = []
    ref_roles: list[str] = []
    for asset in assets:
        role = role_map.get(asset.asset_type or "")
        if not role:
            continue
        paths = _resolve_asset_file_paths([asset])
        if not paths or paths[0] in ref_paths:
            continue
        ref_paths.append(paths[0])
        ref_labels.append(asset.name or "")
        ref_roles.append(role)
    ordered = sorted(
        zip(ref_paths, ref_labels, ref_roles),
        key=lambda item: 1 if item[2] == "style" else 0,
    )
    ref_paths = [item[0] for item in ordered]
    ref_labels = [item[1] for item in ordered]
    ref_roles = [item[2] for item in ordered]
    if style_ref_path:
        if style_ref_path in ref_paths:
            existing_index = ref_paths.index(style_ref_path)
            ref_paths.pop(existing_index)
            ref_labels.pop(existing_index)
            ref_roles.pop(existing_index)
        ref_paths.append(style_ref_path)
        ref_labels.append("画面风格参考锚点")
        ref_roles.append("style")
    return ref_paths, ref_labels, ref_roles


def _compact_json(value: object, limit: int = 600) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False)
    except Exception:
        text = str(value)
    return text[:limit]


def _build_story_grounding_block(
    story: Story | None,
    chapter: Chapter | None,
    scene: ScriptScene | None,
) -> str:
    if not story:
        return ""
    parts: list[str] = []
    if story.description:
        parts.append(f"Story premise: {(story.description or '')[:280]}")
    if isinstance(story.story_bible, dict) and story.story_bible:
        creative = story.story_bible.get("creative_brief")
        writing = story.story_bible.get("writing_guidance")
        import_guidance = story.story_bible.get("import_guidance")
        if creative:
            parts.append(f"Creative brief: {_compact_json(creative, 500)}")
        if writing:
            parts.append(f"Writing guidance: {_compact_json(writing, 500)}")
        if import_guidance:
            parts.append(f"Author constraints: {_compact_json(import_guidance, 500)}")
    if isinstance(story.outline, dict) and story.outline:
        parts.append(f"Outline context: {_compact_json(story.outline, 700)}")
    if isinstance(story.characters, list) and story.characters:
        parts.append(f"Character roster: {_compact_json(story.characters[:8], 700)}")
    if story.character_profiles:
        parts.append(f"Character appearance profiles: {(story.character_profiles or '')[:900]}")
    if story.video_character_profiles:
        parts.append(f"Video character design cards: {(story.video_character_profiles or '')[:1200]}")
    if chapter and chapter.novel_content:
        parts.append(f"Chapter source text excerpt: {(chapter.novel_content or '')[:900]}")
    if scene:
        parts.append(f"Scene summary: {(scene.summary or '')[:400]}")
        parts.append(f"Scene mood/location: {(scene.mood or '')} / {(scene.location or '')}")
        if scene.characters_json:
            parts.append(f"Scene characters: {_compact_json(scene.characters_json, 240)}")
    if not parts:
        return ""
    return " | ".join(parts)


def _build_character_design_grounding_block(
    story: Story | None,
    character_name: str,
    note_from_profiles: str,
) -> str:
    if not story:
        return f"Character: {character_name}"
    c = _find_character_struct(story, character_name) or {}
    parts: list[str] = [f"Character: {character_name}"]
    role = str(c.get("role") or "").strip()
    arc = str(c.get("arc") or "").strip()
    if role:
        parts.append(f"Role: {role}")
    if arc:
        parts.append(f"Arc cues: {arc[:260]}")
    rel = c.get("relationships")
    if isinstance(rel, list) and rel:
        parts.append(f"Relations: {_compact_json(rel[:6], 360)}")
    if note_from_profiles:
        parts.append(f"Appearance profile: {note_from_profiles[:420]}")
    if story.character_profiles and not note_from_profiles:
        parts.append(f"Story character profiles: {(story.character_profiles or '')[:600]}")
    return " | ".join(parts)


def _build_shot_asset_grounding_block(
    story: Story | None,
    chapter: Chapter | None,
    scene: ScriptScene | None,
    shot: VideoShot,
) -> str:
    scene_summary = (scene.summary or "").strip() if scene else ""
    scene_location = (scene.location or "").strip() if scene else ""
    scene_mood = (scene.mood or "").strip() if scene else ""
    characters = scene.characters_json if scene and isinstance(scene.characters_json, list) else []
    core = (
        f"Shot core: #{shot.shot_number} {shot.title or ''} | "
        f"{shot.shot_type or 'medium'} | {shot.camera_angle or 'eye_level'} | "
        f"{shot.camera_movement or 'static'} | dur={shot.duration_seconds or 5}s | "
        f"composition={shot.composition or ''} | action={shot.action_description or ''} | "
        f"dialogue={shot.dialogue or ''} | sound={shot.sound_design or ''} | continuity={shot.continuity_notes or ''}"
    )
    scene_block = (
        f"Scene: summary={scene_summary[:300]} | location={scene_location[:120]} | "
        f"mood={scene_mood[:120]} | characters={_compact_json(characters, 220)}"
    )
    story_block = _build_story_grounding_block(story, chapter, scene)
    if story_block:
        return f"{core} || {scene_block} || {story_block}"
    return f"{core} || {scene_block}"


def _resolve_effective_style_for_shot(
    shot: VideoShot,
    db: Session,
    requested_style_name: str | None = None,
) -> dict:
    requested = _normalize_style_name(requested_style_name)
    if requested:
        preset = (
            db.query(VideoStylePreset)
            .filter(VideoStylePreset.name == requested)
            .first()
        )
        if preset:
            return {
                "name": preset.name,
                "prompt_template": preset.prompt_template or "",
                "image_style_params": _safe_dict(preset.image_style_params),
                "video_style_params": _safe_dict(preset.video_style_params),
                "source": "request",
            }
        return {
            "name": requested,
            "prompt_template": "",
            "image_style_params": {},
            "video_style_params": {},
            "source": "request_raw",
        }

    shot_name = _normalize_style_name(shot.style_preset)
    if shot_name:
        preset = db.query(VideoStylePreset).filter(VideoStylePreset.name == shot_name).first()
        if preset:
            return {
                "name": preset.name,
                "prompt_template": preset.prompt_template or "",
                "image_style_params": _safe_dict(preset.image_style_params),
                "video_style_params": _safe_dict(preset.video_style_params),
                "source": "shot",
            }
        return {
            "name": shot_name,
            "prompt_template": "",
            "image_style_params": {},
            "video_style_params": {},
            "source": "shot_raw",
        }

    chapter = shot.scene.chapter if shot.scene else None
    if chapter and chapter.video_style_preset_id:
        preset = db.get(VideoStylePreset, chapter.video_style_preset_id)
        if preset:
            return {
                "name": preset.name,
                "prompt_template": preset.prompt_template or "",
                "image_style_params": _safe_dict(preset.image_style_params),
                "video_style_params": _safe_dict(preset.video_style_params),
                "source": "chapter",
            }

    story = chapter.story if chapter else None
    if story and getattr(story, "video_style_preset_id", None):
        preset = db.get(VideoStylePreset, story.video_style_preset_id)
        if preset:
            return {
                "name": preset.name,
                "prompt_template": preset.prompt_template or "",
                "image_style_params": _safe_dict(preset.image_style_params),
                "video_style_params": _safe_dict(preset.video_style_params),
                "source": "story",
            }

    fallback_name = "写实电影感"
    preset = db.query(VideoStylePreset).filter(VideoStylePreset.name == fallback_name).first()
    if preset:
        return {
            "name": preset.name,
            "prompt_template": preset.prompt_template or "",
            "image_style_params": _safe_dict(preset.image_style_params),
            "video_style_params": _safe_dict(preset.video_style_params),
            "source": "default",
        }

    return {
        "name": fallback_name,
        "prompt_template": "",
        "image_style_params": {},
        "video_style_params": {},
        "source": "default_raw",
    }


def _resolve_effective_style_for_scene(
    scene: ScriptScene,
    db: Session,
    requested_style_name: str | None = None,
) -> dict:
    requested = _normalize_style_name(requested_style_name)
    if requested:
        preset = db.query(VideoStylePreset).filter(VideoStylePreset.name == requested).first()
        if preset:
            return {
                "name": preset.name,
                "prompt_template": preset.prompt_template or "",
                "image_style_params": _safe_dict(preset.image_style_params),
                "video_style_params": _safe_dict(preset.video_style_params),
                "source": "request",
            }
        return {
            "name": requested,
            "prompt_template": "",
            "image_style_params": {},
            "video_style_params": {},
            "source": "request_raw",
        }

    chapter = scene.chapter
    if chapter and chapter.video_style_preset_id:
        preset = db.get(VideoStylePreset, chapter.video_style_preset_id)
        if preset:
            return {
                "name": preset.name,
                "prompt_template": preset.prompt_template or "",
                "image_style_params": _safe_dict(preset.image_style_params),
                "video_style_params": _safe_dict(preset.video_style_params),
                "source": "chapter",
            }

    story = chapter.story if chapter else None
    if story and getattr(story, "video_style_preset_id", None):
        preset = db.get(VideoStylePreset, story.video_style_preset_id)
        if preset:
            return {
                "name": preset.name,
                "prompt_template": preset.prompt_template or "",
                "image_style_params": _safe_dict(preset.image_style_params),
                "video_style_params": _safe_dict(preset.video_style_params),
                "source": "story",
            }

    fallback_name = "写实电影感"
    preset = db.query(VideoStylePreset).filter(VideoStylePreset.name == fallback_name).first()
    if preset:
        return {
            "name": preset.name,
            "prompt_template": preset.prompt_template or "",
            "image_style_params": _safe_dict(preset.image_style_params),
            "video_style_params": _safe_dict(preset.video_style_params),
            "source": "default",
        }

    return {
        "name": fallback_name,
        "prompt_template": "",
        "image_style_params": {},
        "video_style_params": {},
        "source": "default_raw",
    }


def _resolve_workflow_style_ref_path(
    chapter_id: int,
    db: Session,
    style_preset_name: str | None = None,
) -> str | None:
    """解析工作流的风格参考图文件绝对路径。

    用于图生图模式：将顶部预选的风格参考图作为 img2img 源图传入 Image2 API，
    确保生成的角色/场景/道具图片的画风与风格参考图完全一致。
    """
    wf = db.query(ChapterVideoWorkflow).filter(
        ChapterVideoWorkflow.chapter_id == chapter_id
    ).order_by(ChapterVideoWorkflow.created_at.desc()).first()

    ref_url = None
    # 镜头显式覆盖风格时，参考图也必须切换到该预设，避免文字与图片风格不一致。
    if wf and wf.style_reference_image_url:
        ref_url = wf.style_reference_image_url.strip()

    if not ref_url and wf and wf.video_style:
        preset = db.query(VideoStylePreset).filter(VideoStylePreset.name == wf.video_style.strip()).first()
        if preset and preset.image_url:
            ref_url = preset.image_url.strip()

    if not ref_url and style_preset_name:
        preset_name = style_preset_name.strip()
        preset = db.query(VideoStylePreset).filter(VideoStylePreset.name == preset_name).first()
        if not preset and preset_name.isdigit():
            preset = db.get(VideoStylePreset, int(preset_name))
        if preset and preset.image_url:
            ref_url = preset.image_url.strip()

    if not ref_url:
        chapter = db.query(Chapter).filter(Chapter.id == chapter_id).first()
        if chapter and chapter.video_style_preset_id:
            preset = db.get(VideoStylePreset, chapter.video_style_preset_id)
            if preset and preset.image_url:
                ref_url = preset.image_url.strip()
        if not ref_url and chapter and chapter.story_id:
            story = db.get(Story, chapter.story_id)
            if story and getattr(story, "video_style_preset_id", None):
                preset = db.get(VideoStylePreset, story.video_style_preset_id)
                if preset and preset.image_url:
                    ref_url = preset.image_url.strip()

    if not ref_url:
        return None

    resolved_path = ensure_local_media_path(ref_url, "manga")
    if resolved_path:
        return resolved_path
    logger.warning(
        "风格参考图文件不存在或无法下载: %s",
        safe_media_url_for_log(ref_url),
    )
    return None


def _clear_chapter_scenes(chapter_id: int, db: Session) -> None:
    scenes = (
        db.query(ScriptScene)
        .filter(ScriptScene.chapter_id == chapter_id)
        .all()
    )
    for scene in scenes:
        db.delete(scene)
    db.flush()


def _clear_scene_shots(scene_id: int, db: Session) -> None:
    shots = (
        db.query(VideoShot)
        .filter(VideoShot.scene_id == scene_id)
        .all()
    )
    for shot in shots:
        db.delete(shot)
    db.flush()


# 鈹€鈹€鈹€ Chapter Screenplay Endpoints 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

@router.post("/api/chapters/{chapter_id}/screenplay/generate")
async def generate_chapter_screenplay(
    chapter_id: int,
    body: GenerateScreenplayRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    chapter = _require_chapter_for_user(chapter_id, user, db)
    _check_and_consume_quota_wrapper(
        user.id,
        "ai.text.advanced_calls.monthly_limit",
        1,
        db,
        deduct=False,
        request=request,
        provider_kind="text",
    )

    # 娉ㄥ叆鏁呬簨绾т笂涓嬫枃淇℃伅
    story = chapter.story

    # Generate screenplay via mock service
    result = await generate_screenplay(
        chapter_content=chapter.novel_content or "",
        style=body.style or "cinematic",
        scene_count_hint=body.scene_count_hint or 5,
        target_duration_seconds=body.target_duration_seconds or 90,
        api_key=_user_deepseek_api_key(request, db),
        # Context injection
        story_memory=getattr(story, 'story_memory', None),
        chapter_memory_summary=chapter.memory_summary,
        story_outline=getattr(story, 'outline', None),
        strict_ai=True,
    )

    _clear_chapter_scenes(chapter_id, db)
    chapter.screenplay_text = result.get("screenplay", "")

    # Save scenes to database
    scenes = []
    for scene_data in result["scenes"]:
        scene = ScriptScene(
            chapter_id=chapter_id,
            scene_number=scene_data["scene_number"],
            title=scene_data["title"],
            location=scene_data["location"],
            time_of_day=scene_data["time_of_day"],
            characters_json=scene_data.get("characters", []),
            summary=scene_data["summary"],
            dialogue_json=scene_data.get("dialogue", []),
            voiceover=scene_data.get("voiceover", ""),
            mood=scene_data.get("mood", "涓珛"),
            estimated_duration_seconds=scene_data["estimated_duration_seconds"],
            source_type="generated",
            status="draft",
        )
        db.add(scene)
        scenes.append(scene)

    db.commit()
    _check_and_consume_quota_wrapper(
        user.id,
        "ai.text.advanced_calls.monthly_limit",
        1,
        db,
        deduct=True,
        request=request,
        provider_kind="text",
    )

    # Refresh to get IDs
    for scene in scenes:
        db.refresh(scene)

    return {
        "chapter_id": chapter_id,
        "screenplay": chapter.screenplay_text or "",
        "scenes": [_serialize_scene(s) for s in scenes],
    }


@router.get("/api/chapters/{chapter_id}/screenplay/scenes")
async def list_chapter_scenes(
    chapter_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    chapter = _require_chapter_for_user(chapter_id, user, db)

    scenes = (
        db.query(ScriptScene)
        .filter(ScriptScene.chapter_id == chapter_id)
        .order_by(ScriptScene.scene_number.asc())
        .all()
    )

    return {
        "chapter_id": chapter_id,
        "screenplay": chapter.screenplay_text or "",
        "scenes": [_serialize_scene(s) for s in scenes],
    }


@router.post("/api/chapters/{chapter_id}/screenplay/scenes/regenerate")
async def regenerate_chapter_scenes(
    chapter_id: int,
    body: RegenerateScenesRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    chapter = _require_chapter_for_user(chapter_id, user, db)
    _check_and_consume_quota_wrapper(
        user.id,
        "ai.text.advanced_calls.monthly_limit",
        1,
        db,
        deduct=False,
        request=request,
        provider_kind="text",
    )

    _clear_chapter_scenes(chapter_id, db)

    # Generate new scenes
    scenes_data = await regenerate_scenes(
        existing_screenplay=chapter.screenplay_text or chapter.novel_content or "",
        instruction=body.instruction or "閲嶆柊鐢熸垚",
        scene_count_hint=body.scene_count_hint or 4,
        api_key=_user_deepseek_api_key(request, db),
        strict_ai=True,
    )

    scenes = []
    for scene_data in scenes_data:
        scene = ScriptScene(
            chapter_id=chapter_id,
            scene_number=scene_data["scene_number"],
            title=scene_data["title"],
            location=scene_data["location"],
            time_of_day=scene_data["time_of_day"],
            characters_json=scene_data.get("characters", []),
            summary=scene_data["summary"],
            dialogue_json=scene_data.get("dialogue", []),
            voiceover=scene_data.get("voiceover", ""),
            mood=scene_data.get("mood", "涓珛"),
            estimated_duration_seconds=scene_data["estimated_duration_seconds"],
            source_type="regenerated",
            status="draft",
        )
        db.add(scene)
        scenes.append(scene)

    db.commit()
    _check_and_consume_quota_wrapper(
        user.id,
        "ai.text.advanced_calls.monthly_limit",
        1,
        db,
        deduct=True,
        request=request,
        provider_kind="text",
    )

    for scene in scenes:
        db.refresh(scene)

    return {
        "chapter_id": chapter_id,
        "scenes": [_serialize_scene(s) for s in scenes],
    }


# 鈹€鈹€鈹€ Scene Endpoints 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

# --- Chapter Storyboard (chapter-level, skip scenes) ---

@router.get("/api/chapters/{chapter_id}/storyboard")
async def list_chapter_storyboard(chapter_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    chapter = _require_chapter_for_user(chapter_id, user, db)
    scenes = db.query(ScriptScene).filter(ScriptScene.chapter_id == chapter_id).order_by(ScriptScene.scene_number.asc()).all()
    all_shots = []
    for scene in scenes:
        shots = db.query(VideoShot).filter(VideoShot.scene_id == scene.id).order_by(VideoShot.shot_number.asc()).all()
        all_shots.extend([_serialize_shot(s) for s in shots])
    return {"chapter_id": chapter_id, "shots": all_shots}


@router.post("/api/chapters/{chapter_id}/storyboard/generate")
async def generate_chapter_storyboard(chapter_id: int, body: dict, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    chapter = _require_chapter_for_user(chapter_id, user, db)
    story = chapter.story
    if not chapter.novel_content or not chapter.novel_content.strip():
        raise HTTPException(400, "Chapter content is empty")
    _check_and_consume_quota_wrapper(
        user.id,
        "ai.text.advanced_calls.monthly_limit",
        1,
        db,
        deduct=False,
        request=request,
        provider_kind="text",
    )

    shot_count_hint = int(body.get("shot_count_hint") or 0) or 0
    style_preset = str(body.get("style_preset") or "").strip() or "cinematic"

    character_context = ""
    if story and getattr(story, 'character_profiles', None):
        character_context += "Character profiles: " + str(story.character_profiles)[:500] + "\n"
    if story and isinstance(getattr(story, 'characters', None), list):
        character_context += "Cast: " + json.dumps(story.characters[:8], ensure_ascii=False) + "\n"

    hint_line = ("Target approximately " + str(shot_count_hint) + " shots.") if shot_count_hint else ""
    ai_prompt = (
        "You are a professional film director. Read the chapter below and design a storyboard "
        "that tells the core story with cinematic impact.\n\n"
        "Your task:\n"
        "1. Understand the chapter's narrative arc, emotional beats, and key turning points.\n"
        "2. Filter and trim: keep only scenes that drive the story forward. Remove filler "
        "and non-essential dialogue.\n"
        "3. Design shots that form a coherent visual narrative -- each shot should naturally "
        "lead to the next.\n"
        "4. Use varied shot types (wide establishing -> medium action -> close-up emotion) "
        "to create cinematic rhythm.\n\n"
        "Output a strict JSON: {\"shots\": [{...}]}.\n\n"
        "Each shot MUST have ALL of these fields:\n"
        "  shot_number, title, shot_type, camera_angle, camera_movement,\n"
        "  composition, action_description, dialogue, sound_design, duration_seconds,\n"
        "  storyboard_prompt, video_prompt, negative_prompt, continuity_notes,\n"
        "  character_involvement, scene_mood, status\n\n"
        "Guidelines:\n"
        "- Shot count: decide based on the story's dramatic needs. " + hint_line +
        "A typical chapter needs 8-25 well-crafted shots. Quality over quantity.\n"
        "- Duration: default 15s per shot. The AI director must decide how many internal storyboard beats fit inside this 15-second shot based on content density and cinematic pacing.\n"
        "- character_involvement: JSON array of character names in this shot.\n"
        "- scene_mood: describe the emotional atmosphere.\n"
        "- shot_type from: " + json.dumps(SHOT_TYPES, ensure_ascii=False) + ".\n"
        "- Use camera movement and framing to enhance storytelling.\n"
        "- Ensure visual continuity across shots.\n"
        "- End with a satisfying conclusion.\n"
        "- Style: " + style_preset + ".\n"
        "- status: draft for all shots.\n\n" +
        character_context +
        "Chapter text:\n" + (chapter.novel_content or "")[:6000]
    )

    api_key = _user_deepseek_api_key(request, db)
    if not api_key:
        raise HTTPException(400, "DeepSeek API key not configured")

    payload = {
        "model": deepseek_service.runtime_model(),
        "messages": [
            {"role": "system", "content": "You are a storyboard director. Output strict JSON only."},
            {"role": "user", "content": ai_prompt},
        ],
        "stream": False,
        "max_tokens": 16384,
        "response_format": {"type": "json_object"},
    }

    try:
        async with httpx.AsyncClient(timeout=300) as client:
            resp = await client.post(
                f"{deepseek_service.runtime_base_url()}/chat/completions",
                json=payload,
                headers=deepseek_service._deepseek_auth_headers(api_key),
            )
            resp.raise_for_status()
            ai_data = resp.json()
            deepseek_service._record_response_usage(ai_data)
            ai_content = str(ai_data["choices"][0]["message"]["content"] or "").strip()
    except Exception as e:
        logger.exception("Chapter storyboard AI call failed")
        raise HTTPException(502, f"AI storyboard generation failed: {e}")

    raw_result = deepseek_service._extract_json_object(ai_content)
    raw_shots = raw_result.get("shots") if isinstance(raw_result, dict) else []
    if not isinstance(raw_shots, list) or not raw_shots:
        raw_shots = _fallback_chapter_storyboard(chapter.novel_content, max(8, shot_count_hint or 12))

    chapter_scene = db.query(ScriptScene).filter(
        ScriptScene.chapter_id == chapter_id, ScriptScene.source_type == "chapter_storyboard"
    ).first()
    # 从分镜数据中提取所有出场角色
    all_chars = set()
    for sd in raw_shots:
        if isinstance(sd, dict):
            ci = sd.get("character_involvement")
            if isinstance(ci, list):
                all_chars.update(str(c).strip() for c in ci if str(c).strip())
            elif isinstance(ci, str) and ci.strip():
                try:
                    parsed = json.loads(ci)
                    if isinstance(parsed, list):
                        all_chars.update(str(c).strip() for c in parsed if str(c).strip())
                except Exception:
                    all_chars.add(ci.strip())

    if chapter_scene:
        _clear_scene_shots(chapter_scene.id, db)
        chapter_scene.characters_json = sorted(all_chars)
        db.flush()
    else:
        chapter_scene = ScriptScene(
            chapter_id=chapter_id, scene_number=0,
            title=f"Chapter {chapter.chapter_number} Storyboard",
            location="", time_of_day="", characters_json=sorted(all_chars),
            summary=f"Chapter-level storyboard, {len(raw_shots)} shots",
            dialogue_json=[], source_type="chapter_storyboard", status="draft",
        )
        db.add(chapter_scene)
        db.flush()

    shots = []
    default_dur = min(SHOT_DURATION_SECONDS, max(5, 135 // max(1, len(raw_shots))))
    for idx, sd in enumerate(raw_shots):
        if not isinstance(sd, dict):
            continue
        n = _normalize_chapter_shot(sd, idx + 1, default_dur)
        shot = VideoShot(
            scene_id=chapter_scene.id, shot_number=n["shot_number"], title=n["title"],
            shot_type=n.get("shot_type"), camera_angle=n.get("camera_angle"),
            camera_movement=n.get("camera_movement"), composition=n.get("composition"),
            action_description=n.get("action_description"), dialogue=n.get("dialogue"),
            sound_design=n.get("sound_design"), duration_seconds=n.get("duration_seconds"),
            storyboard_prompt=n.get("storyboard_prompt"), video_prompt=n.get("video_prompt"),
            negative_prompt=n.get("negative_prompt"), continuity_notes=n.get("continuity_notes"),
            character_involvement=n.get("character_involvement"), scene_mood=n.get("scene_mood"),
            status="draft",
        )
        db.add(shot)
        shots.append(shot)

    db.commit()
    _check_and_consume_quota_wrapper(
        user.id,
        "ai.text.advanced_calls.monthly_limit",
        1,
        db,
        deduct=True,
        request=request,
        provider_kind="text",
    )
    for shot in shots:
        db.refresh(shot)
    return {
        "chapter_id": chapter_id, "shots": [_serialize_shot(s) for s in shots],
        "total_count": len(shots),
    }


def _normalize_chapter_shot(raw, index, default_duration):
    return {
        "shot_number": int(raw.get("shot_number") or index),
        "title": (str(raw.get("title") or "").strip() or f"Shot {index}"),
        "shot_type": str(raw.get("shot_type") or "medium").strip(),
        "camera_angle": str(raw.get("camera_angle") or "eye_level").strip(),
        "camera_movement": str(raw.get("camera_movement") or "static").strip(),
        "composition": str(raw.get("composition") or "").strip(),
        "action_description": str(raw.get("action_description") or "").strip(),
        "dialogue": str(raw.get("dialogue") or "").strip() or None,
        "sound_design": str(raw.get("sound_design") or "").strip() or None,
        "duration_seconds": min(SHOT_DURATION_SECONDS, int(raw.get("duration_seconds") or default_duration)),
        "storyboard_prompt": str(raw.get("storyboard_prompt") or "").strip() or None,
        "video_prompt": str(raw.get("video_prompt") or "").strip() or None,
        "negative_prompt": str(raw.get("negative_prompt") or "").strip() or None,
        "continuity_notes": str(raw.get("continuity_notes") or "").strip() or None,
        "character_involvement": str(raw.get("character_involvement") or "").strip() or None,
        "scene_mood": str(raw.get("scene_mood") or "").strip() or None,
        "status": "draft",
    }


def _fallback_chapter_storyboard(chapter_content, shot_count_hint):
    paragraphs = [p.strip() for p in chapter_content.split("\n") if p.strip()]
    if not paragraphs:
        paragraphs = [chapter_content]
    key_paragraphs = [p for p in paragraphs if len(p) > 20]
    if not key_paragraphs:
        key_paragraphs = paragraphs
    count = min(len(key_paragraphs), 16)
    step = max(1, len(key_paragraphs) // count)
    candidates = key_paragraphs[::step][:count]
    return [{
        "shot_number": i + 1, "title": f"Shot {i + 1}",
        "shot_type": "medium" if i % 3 != 0 else "wide",
        "camera_angle": "eye_level", "camera_movement": "static",
        "composition": "", "action_description": p[:200],
        "dialogue": None, "sound_design": None, "duration_seconds": SHOT_DURATION_SECONDS,
        "storyboard_prompt": None, "video_prompt": None,
        "negative_prompt": None, "continuity_notes": None,
        "character_involvement": None, "scene_mood": None,
        "status": "draft",
    } for i, p in enumerate(candidates)]


@router.patch("/api/scenes/{scene_id}")
async def update_scene(
    scene_id: int,
    body: ScriptSceneUpdate,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    scene = db.get(ScriptScene, scene_id)
    if not scene:
        raise HTTPException(404, "场景未找到")
    _require_chapter_for_user(scene.chapter_id, user, db)

    update_data = body.model_dump(exclude_unset=True)
    field_map = {
        "characters": "characters_json",
        "dialogue": "dialogue_json",
    }
    for field, value in update_data.items():
        if value is not None:
            setattr(scene, field_map.get(field, field), value)

    scene.updated_at = datetime.datetime.utcnow()
    db.commit()
    db.refresh(scene)

    return _serialize_scene(scene)


@router.post("/api/scenes/{scene_id}/shots/generate")
async def generate_scene_shots(
    scene_id: int,
    body: GenerateShotsRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    scene = db.get(ScriptScene, scene_id)
    if not scene:
        raise HTTPException(404, "场景未找到")
    _require_chapter_for_user(scene.chapter_id, user, db)
    _check_and_consume_quota_wrapper(
        user.id,
        "ai.text.advanced_calls.monthly_limit",
        1,
        db,
        deduct=False,
        request=request,
        provider_kind="text",
    )

    # 娉ㄥ叆瑙掕壊涓婁笅鏂囦俊鎭?
    chapter = db.query(Chapter).filter(Chapter.id == scene.chapter_id).first()
    story = db.query(Story).filter(Story.id == chapter.story_id).first() if chapter else None
    character_profiles = getattr(story, 'character_profiles', None) if story else None
    scene_characters = scene.characters_json or []

    # Generate shots via mock service
    shots_data = await generate_shots(
        scene_title=scene.title or "",
        scene_summary=scene.summary or "",
        scene_dialogue=scene.dialogue_json or [],
        scene_mood=scene.mood or "",
        shot_count_hint=body.shot_count_hint or 4,
        duration_budget_seconds=body.duration_budget_seconds or 40,
        style=body.style or "cinematic",
        api_key=_user_deepseek_api_key(request, db),
        # Context injection
        character_profiles=character_profiles,
        scene_characters=scene_characters,
        strict_ai=True,
    )

    _clear_scene_shots(scene_id, db)

    shots = []
    for shot_data in shots_data:
        shot = VideoShot(
            scene_id=scene_id,
            shot_number=shot_data["shot_number"],
            title=shot_data["title"],
            shot_type=shot_data["shot_type"],
            camera_angle=shot_data["camera_angle"],
            camera_movement=shot_data["camera_movement"],
            composition=shot_data["composition"],
            action_description=shot_data["action_description"],
            dialogue=shot_data.get("dialogue", ""),
            sound_design=shot_data.get("sound_design", ""),
            duration_seconds=shot_data["duration_seconds"],
            storyboard_prompt=shot_data.get("storyboard_prompt", ""),
            video_prompt=shot_data.get("video_prompt", ""),
            negative_prompt=shot_data.get("negative_prompt", ""),
            continuity_notes=shot_data.get("continuity_notes", ""),
            character_involvement=shot_data.get("character_involvement"),
            scene_mood=shot_data.get("scene_mood"),
            status="draft",
        )
        db.add(shot)
        shots.append(shot)

    db.commit()
    _check_and_consume_quota_wrapper(
        user.id,
        "ai.text.advanced_calls.monthly_limit",
        1,
        db,
        deduct=True,
        request=request,
        provider_kind="text",
    )

    for shot in shots:
        db.refresh(shot)

    return {
        "scene_id": scene_id,
        "shots": [_serialize_shot(s) for s in shots],
    }


@router.get("/api/scenes/{scene_id}/shots")
async def list_scene_shots(
    scene_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    scene = db.get(ScriptScene, scene_id)
    if not scene:
        raise HTTPException(404, "场景未找到")
    _require_chapter_for_user(scene.chapter_id, user, db)

    shots = (
        db.query(VideoShot)
        .filter(VideoShot.scene_id == scene_id)
        .order_by(VideoShot.shot_number.asc())
        .all()
    )

    return {
        "scene_id": scene_id,
        "shots": [_serialize_shot(s) for s in shots],
    }


# 鈹€鈹€鈹€ Concept Art Endpoints 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

@router.post("/api/scenes/{scene_id}/concept-art/generate")
async def generate_scene_concept_art(
    scene_id: int,
    body: dict,
    request: Request,
    db: Session = Depends(get_db),
):
    """Generate concept art for a scene. Creates a VideoAsset with asset_type='scene_reference'."""
    user = _require_user(request, db)
    scene = db.get(ScriptScene, scene_id)
    if not scene:
        raise HTTPException(404, "场景未找到")
    _require_chapter_for_user(scene.chapter_id, user, db)

    overwrite = body.get("overwrite", False)
    explicit_ref_ids_raw = body.get("reference_asset_ids") or []
    explicit_ref_ids = [int(x) for x in explicit_ref_ids_raw if str(x).isdigit()]

    chapter = db.query(Chapter).filter(Chapter.id == scene.chapter_id).first()
    story = db.query(Story).filter(Story.id == chapter.story_id).first() if chapter else None
    scene_summary = scene.summary or ""
    scene_location = scene.location or ""
    scene_mood = scene.mood or ""
    characters = scene.characters_json or []
    character_profiles = getattr(story, 'character_profiles', None) if story else ""

    grounding = _build_story_grounding_block(story, chapter, scene)
    prompt_base = (
        f"Scene concept art: {scene_summary}. Location: {scene_location}. Mood: {scene_mood}. "
        f"Characters involved: {', '.join(str(c) for c in characters)}. "
        f"{character_profiles[:300] if character_profiles else ''}. "
        f"Grounding context: {grounding}"
    )
    ref_assets = _select_character_reference_assets_for_scene(scene, db)
    if explicit_ref_ids:
        explicit_assets = _require_reference_assets_for_story(explicit_ref_ids, chapter.story_id, db)
        id_set = {a.id for a in ref_assets}
        for a in explicit_assets:
            if a.id not in id_set:
                ref_assets.append(a)
                id_set.add(a.id)
    resolved_refs = _resolve_visual_asset_references(ref_assets)
    ref_assets = [asset for asset, _, _, _ in resolved_refs]
    ref_block = _build_reference_constraints_block(ref_assets)
    ref_paths = [path for _, path, _, _ in resolved_refs]
    prompt = f"{prompt_base} {ref_block}".strip()
    ref_labels = [label for _, _, label, _ in resolved_refs]
    ref_roles = [role for _, _, _, role in resolved_refs]

    scene_dir = _VIDEO_OUTPUTS_DIR / f"scene_{scene_id}"
    scene_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"concept_art_{timestamp}.png"
    full_path = scene_dir / filename

    api_key = _user_image_api_key(request)

    # 配额预检
    _check_and_consume_quota_wrapper(user.id, "manga.image.generate.monthly_limit", 1, db, deduct=False)

    try:
        saved_path = await generate_visual_asset_image(
            prompt=prompt,
            output_path=full_path,
            asset_type="scene_reference",
            api_key=api_key or None,
            size="1920x1080",
            reference_paths=ref_paths if ref_paths else None,
            reference_labels=ref_labels if ref_labels else None,
            reference_roles=ref_roles if ref_roles else None,
        )
    except Exception as e:
        logger.warning("Concept art generation failed: %s", e)
        raise HTTPException(502, f"姒傚康鍥剧敓鎴愬け璐? {e}")

    relative_file_path = f"scene_{scene_id}/{filename}"
    file_path = saved_path if str(saved_path).startswith(("http://", "https://")) else relative_file_path

    existing_assets = (
        db.query(VideoAsset)
        .filter(VideoAsset.scene_id == scene_id, VideoAsset.asset_type == "scene_reference")
        .all()
    )
    if overwrite and existing_assets:
        existing_ids = {a.id for a in existing_assets}
        if scene.concept_art_asset_id in existing_ids:
            scene.concept_art_asset_id = None
            db.flush()
        for asset in existing_assets:
            db.delete(asset)
        db.flush()

    asset = VideoAsset(
        story_id=chapter.story_id if chapter else None,
        chapter_id=scene.chapter_id,
        scene_id=scene_id,
        asset_type="scene_reference",
        name=f"Scene {scene.scene_number} concept art",
        file_path=str(file_path),
        prompt=prompt,
        source_asset_ids_json=[a.id for a in ref_assets] if ref_assets else None,
        style_preset=None,
        status="active",
    )
    db.add(asset)
    db.flush()

    scene.concept_art_asset_id = asset.id

    db.commit()
    # 配额扣减
    _check_and_consume_quota_wrapper(
        user.id,
        "manga.image.generate.monthly_limit",
        1,
        db,
        deduct=True,
        request=request,
        provider_kind="image",
    )
    db.refresh(asset)

    return {
        "scene_id": scene_id,
        "asset": {
            "id": asset.id,
            "asset_type": asset.asset_type,
            "name": asset.name,
            "file_path": _to_video_url(asset.file_path),
            "style_preset": asset.style_preset,
        },
    }


@router.get("/api/scenes/{scene_id}/concept-art")
async def get_scene_concept_art(
    scene_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Get concept art asset for a scene."""
    user = _require_user(request, db)
    scene = db.get(ScriptScene, scene_id)
    if not scene:
        raise HTTPException(404, "场景未找到")
    _require_chapter_for_user(scene.chapter_id, user, db)

    assets = (
        db.query(VideoAsset)
        .filter(VideoAsset.scene_id == scene_id, VideoAsset.asset_type == "scene_reference")
        .order_by(VideoAsset.created_at.desc())
        .all()
    )

    return {
        "scene_id": scene_id,
        "assets": [
            {
                "id": a.id,
                "asset_type": a.asset_type,
                "name": a.name,
                "file_path": _to_video_url(a.file_path),
                "prompt": a.prompt,
                "style_preset": a.style_preset,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in assets
        ],
    }


# 鈹€鈹€鈹€ Video Models 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€




# 鈹€鈹€鈹€ Shot Endpoints 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

@router.patch("/api/shots/{shot_id}")
async def update_shot(
    shot_id: int,
    body: VideoShotUpdate,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    shot = db.get(VideoShot, shot_id)
    if not shot:
        raise HTTPException(404, "分镜未找到")
    if not shot.scene:
        raise HTTPException(404, "场景未找到")
    _require_chapter_for_user(shot.scene.chapter_id, user, db)

    update_values = body.model_dump(exclude_unset=True)
    for field, value in update_values.items():
        if field == "duration_seconds" and value is not None:
            value = max(1, min(SHOT_DURATION_SECONDS, int(value)))
        setattr(shot, field, value)
    shot.updated_at = datetime.datetime.utcnow()
    db.commit()
    db.refresh(shot)
    return _serialize_shot(shot)


@router.post("/api/shots/{shot_id}/video/render-stream")
async def render_shot_video_stream(
    shot_id: int,
    body: VideoRenderRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """SSE-streaming video render endpoint.

    Events:
      event: progress -> { job_id, progress, stage, message }
      event: done      -> { job_id, clip }
      event: error     -> { job_id, error }
    """
    user = _require_user(request, db)
    shot = db.get(VideoShot, shot_id)
    if not shot:
        raise HTTPException(404, "分镜未找到")
    if not shot.scene:
        raise HTTPException(404, "场景未找到")
    _require_chapter_for_user(shot.scene.chapter_id, user, db)

    effective_provider = _resolve_video_provider(body.provider, db)

    duration = max(
        1,
        min(
            MAX_VIDEO_DURATION_SECONDS,
            int(body.duration_seconds or shot.duration_seconds or DEFAULT_VIDEO_DURATION_SECONDS),
        ),
    )
    source_storyboard_asset_id = body.source_storyboard_asset_id or shot.storyboard_asset_id
    auto_reference_asset_ids = _collect_shot_reference_asset_ids(
        shot,
        db,
        include_characters=False,
        include_scene=False,
        include_storyboard=False,
        include_frames=False,
        explicit_asset_ids=body.reference_asset_ids or [],
    )
    auto_reference_asset_ids = list(dict.fromkeys(auto_reference_asset_ids))
    if body.use_reference_assets:
        reference_image_urls = _resolve_asset_reference_urls(auto_reference_asset_ids, db, request)
    else:
        auto_reference_asset_ids = []
        reference_image_urls = []
    input_mode = body.input_mode
    if not input_mode:
        has_ref_images = bool(reference_image_urls)
        has_storyboard = source_storyboard_asset_id and shot.storyboard_locked
        if has_storyboard:
            input_mode = "image_to_video"
        else:
            input_mode = "text_to_video"

    ref_assets = db.query(VideoAsset).filter(VideoAsset.id.in_(auto_reference_asset_ids)).all() if auto_reference_asset_ids else []
    first_frame_asset, last_frame_asset, other_refs = _split_frame_assets(ref_assets)
    ref_block = _build_reference_constraints_block(ref_assets)

    ordered_reference_inputs: list[str] = []
    # 用户未选首帧时，自动继承前一个镜头的尾帧作为连贯参考
    prev_last_frame = _get_previous_shot_last_frame(shot, db) if not first_frame_asset else None
    if prev_last_frame:
        p = _resolve_asset_file_paths([prev_last_frame])
        if p:
            ordered_reference_inputs.append(p[0])
            if not first_frame_asset:
                logger.info("Shot %s: 继承前镜头尾帧作为首帧连贯参考", shot_id)
    if first_frame_asset:
        path = _resolve_asset_file_paths([first_frame_asset])
        if path:
            ordered_reference_inputs.append(path[0])
    ordered_reference_inputs.extend(
        _resolve_asset_reference_urls([a.id for a in other_refs], db, request)
        if other_refs else []
    )
    if last_frame_asset:
        path = _resolve_asset_file_paths([last_frame_asset])
        if path:
            ordered_reference_inputs.append(path[0])

    style_ctx = _resolve_effective_style_for_shot(shot, db, requested_style_name=body.style)
    style_name = style_ctx["name"]
    video_style_params = style_ctx["video_style_params"]
    style_template = style_ctx["prompt_template"]
    style_ref_path = _resolve_workflow_style_ref_path(shot.scene.chapter_id, db, style_name)
    if style_ref_path:
        if style_ref_path not in ordered_reference_inputs:
            ordered_reference_inputs.append(style_ref_path)
    ordered_images = _prepare_video_reference_images(ordered_reference_inputs)
    if ordered_images:
        input_mode = "image_to_video"

    api_key, base_url, resolved_model = _user_video_api_key(request)
    resolved_model = body.model or resolved_model
    video_capabilities = _current_video_capabilities(request, db, resolved_model)
    adapter_type = _current_video_adapter_type(request)
    runtime_snapshot = _build_video_runtime_snapshot(
        request,
        db,
        api_key=api_key,
        base_url=base_url,
        model=resolved_model,
    )
    aspect_ratio = body.aspect_ratio or video_style_params.get("aspect_ratio") or "16:9"
    _validate_video_request_before_billing(
        adapter_type=adapter_type,
        model=resolved_model,
        video_capabilities=video_capabilities,
        aspect_ratio=aspect_ratio,
        duration_seconds=duration,
        reference_count=len(ordered_images),
    )
    quota_result = _reserve_video_billing(
        request,
        db,
        user_id=user.id,
        video_seconds=duration,
    )
    grounding = _build_story_grounding_block(shot.scene.chapter.story if shot.scene and shot.scene.chapter else None, shot.scene.chapter if shot.scene else None, shot.scene)
    storyboard_guide = ""
    if shot.storyboard_prompt:
        storyboard_guide = (
            f"\n\n<<<故事版蓝图_STORYBOARD_BLUEPRINT>>>\n"
            f"以下分镜脚本是视频生成的导演蓝图，视频必须严格遵循：\n"
            f"{shot.storyboard_prompt}\n"
            f"<<<蓝图结束_END_BLUEPRINT>>>\n"
            f"核心要求：生成的视频必须严格匹配蓝图中的每一个时间段、镜头运动方式、"
            f"角色动作和情绪变化，不得偏离分镜脚本的任何细节。"
        )
    full_prompt = _merge_style_prompt(
        f"{body.prompt or storyboard_guide} {ref_block} Grounding: {grounding}".strip(),
        style_template, style_name,
    )
    logger.info("视频提交提示词 shot=%s:\n%s", shot_id, full_prompt)
    stream_state = {"task_submitted": False}

    async def event_generator():
        nonlocal db, base_url
        job_id = None
        
        try:
            yield {"event": "progress", "data": json.dumps({"progress": 0, "stage": "submitting", "message": "正在提交视频生成任务..."})}

            task_id = f"video_render_{shot_id}_{int(datetime.datetime.utcnow().timestamp())}"
            await task_manager.submit_task(
                task_id=task_id,
                task_type="video_render",
                coro_func=_submit_and_monitor_video_job,
                billing_usage_event_id=quota_result.get("usage_event_id"),
                shot_id=shot_id,
                provider=effective_provider,
                model=resolved_model,
                prompt=full_prompt,
                negative_prompt=body.negative_prompt or shot.negative_prompt or "",
                duration_seconds=duration,
                aspect_ratio=aspect_ratio,
                reference_images=ordered_images if ordered_images else None,
                api_key=api_key,
                base_url=base_url,
                input_mode=input_mode,
                video_capabilities=video_capabilities,
                adapter_type=adapter_type,
                timeout=600,
                max_retries=0,
                quota_user_id=user.id,
                quota_feature_key="video.generate.count.monthly_limit",
                quota_amount=duration,
                quota_usage_event_id=quota_result.get("usage_event_id"),
                metadata={
                    "stage": "submitting",
                    "message": "正在提交视频生成任务...",
                    "provider_status": "submitting",
                    "running_stage": "submitting",
                    "running_message": "正在提交视频生成任务...",
                },
            )
            stream_state["task_submitted"] = True

            job_status = "pending"
            provider_job_id = task_id

            from models import VideoGenerationJob
            job = VideoGenerationJob(
                shot_id=shot_id,
                provider=effective_provider,
                provider_job_id=provider_job_id,
                model=resolved_model,
                request_payload_json=_sanitize_video_job_request_payload({
                    "model": resolved_model,
                    "prompt": full_prompt,
                    "duration_seconds": duration,
                    "aspect_ratio": aspect_ratio,
                    "style": style_name,
                    "input_mode": input_mode,
                    "reference_asset_ids": auto_reference_asset_ids,
                    "reference_sources": [
                        {"asset_id": asset_id, "source": "video_asset"}
                        for asset_id in auto_reference_asset_ids
                    ],
                    "reference_summary": {
                        "count": len(ordered_images),
                        "roles": ["reference" for _ in ordered_images],
                    },
                }),
                provider_payload_json=_video_provider_metadata(runtime_snapshot, quota_result.get("usage_event_id")),
                status=job_status,
                progress=0,
                duration_seconds=duration,
                aspect_ratio=aspect_ratio,
                error_message=None,
                input_mode=input_mode,
                source_storyboard_asset_id=source_storyboard_asset_id if input_mode == "image_to_video" else None,
                reference_asset_ids_json=auto_reference_asset_ids,
            )
            db.add(job)
            db.flush()
            job_id = job.id
            
            shot.status = "rendering"
            shot.updated_at = datetime.datetime.utcnow()

            db.commit()

            yield {"event": "progress", "data": json.dumps({"job_id": job_id, "progress": 10, "stage": "submitted", "message": "任务已提交，等待生成..."})}

            poll_count = 0
            max_polls = 120
            download_attempted = False

            provider = effective_provider

            while poll_count < max_polls:
                poll_count += 1
                
                # 通过 TaskManager 查询后台任务状态
                task_status = task_manager.get_task_status(task_id)
                task_fields = _flatten_task_status(task_status)
                if task_status is None:
                    current_status = "queued"
                    progress = 0
                elif task_status["status"] == "succeeded":
                    # 提交任务成功，继续轮询上游真实生成状态；不要把“提交成功”当作“视频完成”。
                    result = task_status.get("result_json") or {}
                    provider_job_id = result.get("provider_job_id", provider_job_id)
                    task_fields["provider_status"] = result.get("provider_status") or task_fields.get("provider_status")
                    if provider_job_id and not provider_job_id.startswith("video_render_"):
                        latest = await video_gen_service.query_job_status(
                            provider=provider,
                            provider_job_id=provider_job_id,
                            api_key=api_key,
                            base_url=base_url,
                            adapter_type=adapter_type,
                        )
                        current_status = latest.get("status", "queued") or "queued"
                        progress = int(latest.get("progress") or 0)
                        task_fields["provider_status"] = latest.get("provider_status") or current_status
                        if current_status == "succeeded":
                            task_fields["stage"] = "downloading"
                            task_fields["message"] = "视频生成完成，正在下载入库..."
                        elif task_fields["provider_status"] == "query_error":
                            task_fields["stage"] = "generating"
                            task_fields["message"] = "上游查询较慢，稍后继续同步状态..."
                        else:
                            task_fields["stage"] = "generating"
                            task_fields["message"] = latest.get("message") or "上游生成中..."

                        write_db = SessionLocal()
                        try:
                            db_job = write_db.get(VideoGenerationJob, job_id)
                            if db_job:
                                db_job.provider_job_id = provider_job_id
                                db_job.provider_result_json = _sanitize_video_provider_result({
                                    **(db_job.provider_result_json or {}),
                                    **latest,
                                })
                                db_job.status = current_status if current_status in {"queued", "running", "succeeded", "failed", "cancelled"} else "running"
                                db_job.progress = progress
                                if latest.get("error"):
                                    db_job.error_message = public_error_message(
                                        latest["error"],
                                        "视频生成失败，请稍后重试",
                                    )
                                if current_status in {"succeeded", "failed", "cancelled"}:
                                    db_job.completed_at = datetime.datetime.utcnow()
                                if current_status in {"failed", "cancelled"}:
                                    _refund_video_billing(
                                        write_db,
                                        job=db_job,
                                        reason=f"provider_{current_status}",
                                        commit=False,
                                    )
                                write_db.commit()
                        finally:
                            write_db.close()

                        if current_status in {"failed", "cancelled"}:
                            error_msg = public_error_message(
                                latest.get("error"),
                                "视频生成失败，请稍后重试",
                            )
                            yield {"event": "error", "data": json.dumps({"job_id": job_id, "error": error_msg}, ensure_ascii=False)}
                            return
                    else:
                        current_status = "queued"
                        progress = 15
                        task_fields["stage"] = "submitting"
                        task_fields["message"] = "任务已提交，等待上游任务编号..."
                elif task_status["status"] == "failed":
                    error_msg = public_error_message(task_status.get("error_message"), "视频任务提交失败，请稍后重试")
                    yield {"event": "error", "data": json.dumps({"job_id": job_id, "error": error_msg})}
                    
                    write_db = SessionLocal()
                    try:
                        db_job = write_db.get(VideoGenerationJob, job_id)
                        if db_job:
                            db_job.status = "failed"
                            db_job.error_message = error_msg
                            db_job.completed_at = datetime.datetime.utcnow()
                            _refund_video_billing(
                                write_db,
                                job=db_job,
                                reason="submission_failed",
                                commit=False,
                            )
                            write_db.commit()
                    finally:
                        write_db.close()
                    return
                elif task_status["status"] == "pending":
                    current_status = "queued"
                    progress = 0
                elif task_status["status"] == "retrying":
                    current_status = "retrying"
                    progress = 30
                elif task_status["status"] == "running":
                    current_status = "running"
                    progress = 50
                else:
                    # 处理其他未知状态，默认作为 running
                    current_status = "running"
                    progress = 50
                
                if current_status == "succeeded":
                    existing_db = SessionLocal()
                    try:
                        existing_clip = existing_db.query(RenderedClip).filter(
                            RenderedClip.job_id == job_id,
                        ).first()
                        if existing_clip:
                            yield {"event": "done", "data": json.dumps({
                                "job_id": job_id,
                                "clip": {
                                    "id": existing_clip.id,
                                    "shot_id": existing_clip.shot_id,
                                    "video_path": _to_video_url(existing_clip.video_path),
                                    "duration_seconds": existing_clip.duration_seconds,
                                    "resolution": existing_clip.resolution,
                                },
                            }, ensure_ascii=False)}
                            return
                    finally:
                        existing_db.close()
                    if not download_attempted:
                        progress_val = max(progress, 80)
                        yield {"event": "progress", "data": json.dumps({
                            "job_id": job_id,
                            "progress": progress_val,
                            "stage": "downloading",
                            "message": "视频生成完成，正在下载入库...",
                            "provider_status": task_fields.get("provider_status"),
                            "retry_count": task_fields.get("retry_count", 0),
                            "max_retries": task_fields.get("max_retries", 0),
                            "next_retry_at": task_fields.get("next_retry_at"),
                        }, ensure_ascii=False)}
                        download_attempted = True
                    
                    try:
                        result = await video_gen_service.fetch_job_result(
                            provider=provider,
                            provider_job_id=provider_job_id,
                            shot_id=shot_id,
                            api_key=api_key,
                            base_url=base_url,
                            adapter_type=adapter_type,
                        )
                    except Exception as exc:
                        logger.exception("视频结果下载失败 job_id=%s", job_id)
                        error_msg = public_error_message(exc, "视频结果下载失败，请稍后重试")
                        write_db = SessionLocal()
                        try:
                            db_job = write_db.get(VideoGenerationJob, job_id)
                            db_shot = write_db.get(VideoShot, shot_id)
                            if db_shot:
                                db_shot.status = "failed"
                                db_shot.updated_at = datetime.datetime.utcnow()
                            if db_job:
                                _fail_video_job_and_refund(
                                    write_db,
                                    db_job,
                                    error_message=error_msg,
                                    reason="result_download_failed",
                                )
                            else:
                                write_db.commit()
                        finally:
                            write_db.close()
                        yield {"event": "error", "data": json.dumps({"job_id": job_id, "error": error_msg}, ensure_ascii=False)}
                        return
                    
                    video_path = result.get("video_path", "")
                    
                    if video_path:
                        write_db = SessionLocal()
                        try:
                            clip = RenderedClip(
                                shot_id=shot_id,
                                job_id=job_id,
                                video_path=_to_video_url(video_path),
                                duration_seconds=duration,
                                resolution=aspect_ratio,
                                version=1,
                                is_active=True,
                                source_storyboard_asset_id=source_storyboard_asset_id if input_mode == "image_to_video" else None,
                                style_preset=style_name,
                                review_status="pending",
                            )
                            write_db.add(clip)
                            
                            db_job = write_db.get(VideoGenerationJob, job_id)
                            if db_job:
                                db_job.status = "succeeded"
                                db_job.progress = 100
                                db_job.completed_at = datetime.datetime.utcnow()
                                _settle_video_billing(
                                    write_db,
                                    job=db_job,
                                    video_seconds=duration,
                                    commit=False,
                                )
                            
                            write_db.commit()
                            write_db.refresh(clip)
                            
                            yield {"event": "done", "data": json.dumps({
                                "job_id": job_id,
                                "clip": {
                                    "id": clip.id,
                                    "shot_id": clip.shot_id,
                                    "video_path": _to_video_url(clip.video_path),
                                    "duration_seconds": clip.duration_seconds,
                                    "resolution": clip.resolution,
                                }
                            })}
                        finally:
                            write_db.close()
                    else:
                        error_msg = "视频生成成功但未返回可下载文件"
                        write_db = SessionLocal()
                        try:
                            db_job = write_db.get(VideoGenerationJob, job_id)
                            db_shot = write_db.get(VideoShot, shot_id)
                            if db_shot:
                                db_shot.status = "failed"
                                db_shot.updated_at = datetime.datetime.utcnow()
                            if db_job:
                                _fail_video_job_and_refund(
                                    write_db,
                                    db_job,
                                    error_message=error_msg,
                                    reason="result_missing_video_path",
                                )
                            else:
                                write_db.commit()
                        finally:
                            write_db.close()
                        yield {"event": "error", "data": json.dumps({"job_id": job_id, "error": error_msg}, ensure_ascii=False)}
                    return
                
                progress_val = max(15, min(75, int(progress) or (poll_count * 5 + 15)))
                # 根据 current_status 动态映射 stage 和 message
                if current_status == "queued":
                    stage = "queued"
                    message = task_fields.get("message") or "等待执行..."
                elif current_status == "retrying":
                    stage = "retrying"
                    message = task_fields.get("message") or "生成失败，正在重试..."
                else:
                    stage = task_fields.get("stage") or "generating"
                    message = task_fields.get("message") or f"视频生成中... ({progress_val}%)"
                yield {"event": "progress", "data": json.dumps({
                    "job_id": job_id,
                    "progress": progress_val,
                    "stage": stage,
                    "message": message,
                    "provider_status": task_fields.get("provider_status"),
                    "retry_count": task_fields.get("retry_count", 0),
                    "max_retries": task_fields.get("max_retries", 0),
                    "next_retry_at": task_fields.get("next_retry_at"),
                }, ensure_ascii=False)}
                
                await asyncio.sleep(3)
            
            yield {"event": "error", "data": json.dumps({"job_id": job_id, "error": "视频生成超时，请稍后重试"}, ensure_ascii=False)}
            
        except asyncio.CancelledError:
            if not stream_state["task_submitted"]:
                refund_db = SessionLocal()
                try:
                    _refund_video_billing(
                        refund_db,
                        usage_event_id=quota_result.get("usage_event_id"),
                        reason="stream_cancelled_before_submission",
                    )
                finally:
                    refund_db.close()
            yield {"event": "error", "data": json.dumps({"job_id": job_id, "error": "视频任务已取消"}, ensure_ascii=False)}
            raise
        except Exception as e:
            logger.exception("SSE video render failed")
            if not stream_state["task_submitted"]:
                refund_db = SessionLocal()
                try:
                    _refund_video_billing(
                        refund_db,
                        usage_event_id=quota_result.get("usage_event_id"),
                        reason="stream_failed_before_submission",
                    )
                finally:
                    refund_db.close()
            yield {
                "event": "error",
                "data": json.dumps({
                    "job_id": job_id,
                    "error": public_error_message(e, "视频生成失败，请稍后重试"),
                }, ensure_ascii=False),
            }

    def refund_unsubmitted_stream() -> None:
        if stream_state["task_submitted"]:
            return
        refund_db = SessionLocal()
        try:
            _refund_video_billing(
                refund_db,
                usage_event_id=quota_result.get("usage_event_id"),
                reason="stream_not_started_before_submission",
            )
        except Exception:
            logger.exception("视频流清理未提交账单失败 shot_id=%s", shot_id)
        finally:
            refund_db.close()

    return EventSourceResponse(
        event_generator(),
        background=ResponseBackgroundTask(refund_unsubmitted_stream),
    )


@router.get("/api/shots/{shot_id}/clips")
async def list_shot_clips(
    shot_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    shot = db.get(VideoShot, shot_id)
    if not shot:
        raise HTTPException(404, "分镜未找到")
    if not shot.scene:
        raise HTTPException(404, "场景未找到")
    _require_chapter_for_user(shot.scene.chapter_id, user, db)

    clips = (
        db.query(RenderedClip)
        .filter(RenderedClip.shot_id == shot_id)
        .order_by(RenderedClip.is_active.desc(), RenderedClip.version.desc())
        .all()
    )

    active_clip = next((c for c in clips if c.is_active), None)

    return {
        "shot_id": shot_id,
        "active_clip_id": active_clip.id if active_clip else None,
        "clips": [
            {
                "id": c.id,
                "shot_id": c.shot_id,
                "job_id": c.job_id,
                "video_path": c.video_path,
                "thumbnail_path": c.thumbnail_path,
                "duration_seconds": c.duration_seconds,
                "resolution": c.resolution or "",
                "version": c.version,
                "is_active": c.is_active,
                "created_at": _serialize_datetime(c.created_at),
            }
            for c in clips
        ],
    }


@router.post("/api/shots/{shot_id}/clips/{clip_id}/activate")
async def activate_shot_clip(
    shot_id: int,
    clip_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    shot = db.get(VideoShot, shot_id)
    if not shot:
        raise HTTPException(404, "分镜未找到")
    if not shot.scene:
        raise HTTPException(404, "场景未找到")
    _require_chapter_for_user(shot.scene.chapter_id, user, db)

    clip = db.get(RenderedClip, clip_id)
    if not clip or clip.shot_id != shot_id:
        raise HTTPException(404, "此分镜未找到片段")

    # Deactivate all clips for this shot
    db.query(RenderedClip).filter(RenderedClip.shot_id == shot_id).update(
        {"is_active": False}, synchronize_session=False,
    )

    # Activate the specified clip
    clip.is_active = True
    db.commit()

    return {
        "shot_id": shot_id,
        "active_clip_id": clip.id,
        "ok": True,
    }


# 鈹€鈹€鈹€ Video Job Endpoints 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

@router.get("/api/video-jobs/{job_id}")
async def get_video_job(
    job_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    job = db.get(VideoGenerationJob, job_id)
    if not job:
        raise HTTPException(404, "视频生成任务未找到")

    # Validate ownership via shot -> scene -> chapter
    shot = job.shot
    if not shot or not shot.scene:
        raise HTTPException(404, "关联分镜未找到")
    _require_chapter_for_user(shot.scene.chapter_id, user, db)

    # 读取终态任务时补做幂等退款，覆盖进程在状态提交后、退款提交前退出的窗口。
    if job.status in {"failed", "cancelled"}:
        _refund_video_billing(
            db,
            job=job,
            reason=f"provider_{job.status}",
            commit=False,
        )
        db.commit()

    # 内部 task_id 时尝试从 task_manager 获取真实 API task_id
    task_fields = _flatten_task_status(None)
    if job.provider_job_id and job.provider_job_id.startswith("video_render_"):
        task_status = task_manager.get_task_status(job.provider_job_id)
        task_fields = _flatten_task_status(task_status)
        if task_status and task_status.get("result_json"):
            result = task_status.get("result_json", {})
            real_id = result.get("provider_job_id", "")
            task_fields["provider_status"] = result.get("provider_status") or task_fields.get("provider_status")
            if result.get("status"):
                task_fields["message"] = task_fields.get("message") or "视频任务已提交到上游"
            if real_id and real_id != job.provider_job_id:
                job.provider_job_id = real_id
                job.provider_result_json = _sanitize_video_provider_result({
                    **(job.provider_result_json or {}),
                    **result,
                })
                db.commit()
        if task_status and task_status.get("status") == "failed":
            job.status = "failed"
            job.error_message = task_status.get("error_message") or task_fields.get("message") or "视频任务提交失败"
            job.completed_at = job.completed_at or datetime.datetime.utcnow()
            shot.status = "failed"
            shot.updated_at = datetime.datetime.utcnow()
            _refund_video_billing(db, job=job, reason="submission_failed", commit=False)
            db.commit()
        # task_manager 还没完成提交，跳过本次查询，下次轮询重试
        if job.provider_job_id and job.provider_job_id.startswith("video_render_"):
            logger.info("Video job %s: task submission pending, skip external query", job_id)
            return {
                "id": job.id, "shot_id": job.shot_id, "provider": job.provider,
                "provider_job_id": job.provider_job_id, "model": job.model,
                "request_payload": _sanitize_video_job_request_payload(job.request_payload_json), "status": job.status,
                "progress": job.progress, "duration_seconds": job.duration_seconds,
                "aspect_ratio": job.aspect_ratio or "",
                "error_message": job.error_message or "",
                **task_fields,
                "submitted_at": _serialize_datetime(job.submitted_at),
                "completed_at": _serialize_datetime(job.completed_at),
            }

    if job.status not in {"succeeded", "failed", "cancelled"} and job.provider_job_id:
        api_key, base_url, runtime_model = _resolve_video_job_runtime(job, request, db)
        latest = await video_gen_service.query_job_status(
            provider=job.provider,
            provider_job_id=job.provider_job_id,
            api_key=api_key,
            base_url=base_url,
            model=runtime_model,
            adapter_type=_video_job_adapter_type(job),
        )

        job.status = latest.get("status", job.status) or job.status
        job.progress = int(latest.get("progress", job.progress) or 0)
        job.provider_result_json = _sanitize_video_provider_result({
            **(job.provider_result_json or {}),
            **latest,
        })
        task_fields.update({
            "provider_status": latest.get("provider_status") or latest.get("status") or task_fields.get("provider_status"),
            "stage": "generating" if latest.get("status") in {"queued", "running"} else latest.get("status") or task_fields.get("stage"),
            "message": latest.get("message") or task_fields.get("message"),
        })
        if latest.get("error"):
            job.error_message = public_error_message(
                latest["error"],
                "视频生成失败，请稍后重试",
            )

        if job.status == "succeeded":
            if not job.completed_at:
                job.completed_at = datetime.datetime.utcnow()
            shot.status = "ready"
        elif job.status in {"failed", "cancelled"}:
            if not job.completed_at:
                job.completed_at = datetime.datetime.utcnow()
            shot.status = "failed"
            _refund_video_billing(
                db,
                job=job,
                reason=f"provider_{job.status}",
                commit=False,
            )
        elif job.status == "running":
            shot.status = "rendering"

        shot.updated_at = datetime.datetime.utcnow()
        db.commit()
        db.refresh(job)

    # Find associated clip if job succeeded
    clip = None
    if job.status == "succeeded":
        clip = (
            db.query(RenderedClip)
            .filter(RenderedClip.job_id == job_id)
            .first()
        )
        if clip is None and job.provider_job_id:
            api_key, base_url, runtime_model = _resolve_video_job_runtime(job, request, db)
            try:
                fetched = await video_gen_service.fetch_job_result(
                    provider=job.provider,
                    provider_job_id=job.provider_job_id,
                    shot_id=job.shot_id,
                    api_key=api_key,
                    base_url=base_url,
                    model=runtime_model,
                    adapter_type=_video_job_adapter_type(job),
                )
            except Exception as exc:
                error_msg = f"视频结果下载失败: {exc}"
                shot.status = "failed"
                shot.updated_at = datetime.datetime.utcnow()
                _fail_video_job_and_refund(
                    db,
                    job,
                    error_message=error_msg,
                    reason="result_download_failed",
                )
                db.refresh(job)
                fetched = {}
            video_path_abs = str(fetched.get("video_path") or "").strip()
            video_path = _to_video_url(video_path_abs) if video_path_abs else ""
            if video_path:
                db.query(RenderedClip).filter(RenderedClip.shot_id == shot.id).update(
                    {"is_active": False},
                    synchronize_session=False,
                )
                next_version = (
                    (db.query(RenderedClip).filter(RenderedClip.shot_id == shot.id).count() or 0) + 1
                )
                clip = RenderedClip(
                    shot_id=shot.id,
                    job_id=job.id,
                    video_path=video_path,
                    thumbnail_path=fetched.get("thumbnail_path") or None,
                    duration_seconds=fetched.get("duration_seconds") or job.duration_seconds,
                    resolution=fetched.get("resolution") or "1280x720",
                    version=next_version,
                    is_active=True,
                )
                try:
                    char_assets = _select_character_reference_assets_for_scene(shot.scene, db)
                    char_prompts = [str(a.prompt or "") for a in char_assets]
                    shot_dict = {
                        "video_prompt": str(shot.video_prompt or ""),
                        "action_description": str(shot.action_description or ""),
                        "shot_type": str(shot.shot_type or ""),
                        "camera_angle": str(shot.camera_angle or ""),
                        "camera_movement": str(shot.camera_movement or ""),
                    }
                    for field in ("focal_length", "lighting", "color_palette",
                                  "transition", "action_segments", "frame_composition"):
                        val = getattr(shot, field, None)
                        if val is not None:
                            shot_dict[field] = str(val)

                    qa_result = video_qa.score_video_shot(shot_dict, char_prompts)
                    clip.continuity_score = qa_result["character_consistency"]
                    clip.quality_score = qa_result["overall"]
                    clip.review_status = "auto_passed" if qa_result["overall"] >= 60 else "needs_review"
                    logger.info(
                        "璐ㄦ: shot=%s char=%d struct=%d action=%d overall=%d",
                        shot.id,
                        qa_result["character_consistency"],
                        qa_result["prompt_structure"],
                        qa_result["action_alignment"],
                        qa_result["overall"],
                    )
                except Exception as qa_err:
                    logger.warning("璐ㄦ璇勫垎澶辫触 (涓嶉樆鏂祦绋?: %s", qa_err)

                db.add(clip)
                _settle_video_billing(
                    db,
                    job=job,
                    video_seconds=clip.duration_seconds or job.duration_seconds,
                    commit=False,
                )
                db.commit()
                db.refresh(clip)
                logger.info(
                    "Video job %s created clip id=%s path=%s version=%s",
                    job_id,
                    clip.id,
                    safe_media_url_for_log(clip.video_path),
                    clip.version,
                )
                shot.status = "ready"
                shot.updated_at = datetime.datetime.utcnow()
                db.commit()
            elif job.status == "succeeded":
                error_msg = "视频生成成功但未返回可下载文件"
                shot.status = "failed"
                shot.updated_at = datetime.datetime.utcnow()
                _fail_video_job_and_refund(
                    db,
                    job,
                    error_message=error_msg,
                    reason="result_missing_video_path",
                )
                db.refresh(job)
        else:
            clip = (
                db.query(RenderedClip)
                .filter(RenderedClip.job_id == job_id)
                .first()
            )

    if job.status == "succeeded" and clip is not None:
        _settle_video_billing(
            db,
            job=job,
            video_seconds=clip.duration_seconds or job.duration_seconds,
        )

    result = {
        "id": job.id,
        "shot_id": job.shot_id,
        "provider": job.provider,
        "provider_job_id": job.provider_job_id,
        "model": job.model,
        "request_payload": _sanitize_video_job_request_payload(job.request_payload_json),
        "status": job.status,
        "progress": job.progress,
        "duration_seconds": job.duration_seconds,
        "aspect_ratio": job.aspect_ratio or "",
        "error_message": public_error_message(job.error_message, "视频生成失败，请稍后重试") if job.error_message else "",
        "stage": task_fields.get("stage") or (job.provider_result_json or {}).get("stage"),
        "message": (
            public_error_message(job.error_message, "视频生成失败，请稍后重试")
            if job.status in {"failed", "cancelled"}
            else task_fields.get("message") or (job.provider_result_json or {}).get("message") or ""
        ),
        "provider_status": task_fields.get("provider_status") or (job.provider_result_json or {}).get("provider_status"),
        "retry_count": task_fields.get("retry_count", 0),
        "max_retries": task_fields.get("max_retries", 0),
        "next_retry_at": task_fields.get("next_retry_at"),
        "submitted_at": _serialize_datetime(job.submitted_at),
        "completed_at": _serialize_datetime(job.completed_at),
    }

    if clip:
        result["clip"] = {
            "id": clip.id,
            "video_path": clip.video_path,
            "thumbnail_path": clip.thumbnail_path,
            "duration_seconds": clip.duration_seconds,
            "resolution": clip.resolution or "",
            "version": clip.version,
        }
        logger.info(
            "Video job %s returning clip: id=%s path=%s",
            job_id,
            clip.id,
            safe_media_url_for_log(clip.video_path),
        )

    return result


@router.get("/api/shots/{shot_id}/video-jobs/latest")
async def get_latest_video_job_for_shot(
    shot_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    _require_shot_for_user(shot_id, user, db)
    job = (
        db.query(VideoGenerationJob)
        .filter(VideoGenerationJob.shot_id == shot_id)
        .order_by(
            VideoGenerationJob.submitted_at.desc(),
            VideoGenerationJob.id.desc(),
        )
        .first()
    )
    if not job:
        raise HTTPException(404, "视频生成任务未找到")
    return await get_video_job(job.id, request, db)


@router.post("/api/video-jobs/{job_id}/retry")
async def retry_video_job(
    job_id: int,
    body: RetryJobRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    old_job = db.get(VideoGenerationJob, job_id)
    if not old_job:
        raise HTTPException(404, "视频生成任务未找到")

    shot = old_job.shot
    if not shot or not shot.scene:
        raise HTTPException(404, "关联分镜未找到")
    _require_chapter_for_user(shot.scene.chapter_id, user, db)

    retry_duration = max(
        1,
        min(
            MAX_VIDEO_DURATION_SECONDS,
            int(body.duration_seconds or old_job.duration_seconds or DEFAULT_VIDEO_DURATION_SECONDS),
        ),
    )
    request_payload = _sanitize_video_job_request_payload(
        body.request_payload or old_job.request_payload_json or {}
    )
    api_key, base_url, runtime_model = _user_video_api_key(request)
    retry_provider = _resolve_video_provider(body.provider, db)
    retry_model = body.model or runtime_model
    video_capabilities = _current_video_capabilities(request, db, retry_model)
    adapter_type = _current_video_adapter_type(request)
    retry_reference_ids = list(dict.fromkeys(
        request_payload.get("reference_asset_ids")
        or getattr(old_job, "reference_asset_ids_json", None)
        or []
    ))
    _validate_video_reference_count(len(retry_reference_ids))
    story_id = shot.scene.chapter.story_id
    _require_reference_assets_for_story(retry_reference_ids, story_id, db)
    retry_reference_inputs = _resolve_asset_reference_urls(retry_reference_ids, db, request)
    retry_references = _prepare_video_reference_images(retry_reference_inputs)
    _validate_video_request_before_billing(
        adapter_type=adapter_type,
        model=retry_model,
        video_capabilities=video_capabilities,
        aspect_ratio=body.aspect_ratio or old_job.aspect_ratio or "16:9",
        duration_seconds=retry_duration,
        reference_count=len(retry_references),
    )
    quota_result = _reserve_video_billing(
        request,
        db,
        user_id=user.id,
        video_seconds=retry_duration,
        detach=False,
    )
    runtime_snapshot = _build_video_runtime_snapshot(
        request,
        db,
        api_key=api_key,
        base_url=base_url,
        model=retry_model,
    )
    task_id = f"video_retry_{old_job.shot_id}_{uuid.uuid4().hex[:10]}"
    try:
        await task_manager.submit_task(
            task_id=task_id,
            task_type="video_render",
            coro_func=_submit_and_monitor_video_job,
            billing_usage_event_id=quota_result.get("usage_event_id"),
            shot_id=old_job.shot_id,
            provider=retry_provider,
            model=retry_model,
            prompt=str(request_payload.get("prompt") or ""),
            negative_prompt=str(request_payload.get("negative_prompt") or ""),
            duration_seconds=retry_duration,
            aspect_ratio=body.aspect_ratio or old_job.aspect_ratio or "16:9",
            reference_images=retry_references or None,
            api_key=api_key,
            base_url=base_url,
            input_mode=str(request_payload.get("input_mode") or old_job.input_mode or "text_to_video"),
            video_capabilities=video_capabilities,
            adapter_type=adapter_type,
            timeout=600,
            max_retries=0,
            quota_user_id=user.id,
            quota_feature_key="video.generate.count.monthly_limit",
            quota_amount=retry_duration,
            quota_usage_event_id=quota_result.get("usage_event_id"),
            metadata={
                "stage": "submitting",
                "message": "正在重新提交视频生成任务...",
                "provider_status": "submitting",
            },
        )
        _detach_video_billing(request, quota_result)
    except Exception:
        refund_db = SessionLocal()
        try:
            _refund_video_billing(
                refund_db,
                usage_event_id=quota_result.get("usage_event_id"),
                reason="retry_submission_failed",
            )
        finally:
            refund_db.close()
        raise

    # Create new job with same shot_id
    provider_metadata = _video_provider_metadata(
        runtime_snapshot,
        quota_result.get("usage_event_id"),
    )

    new_job = VideoGenerationJob(
        shot_id=old_job.shot_id,
        provider=retry_provider,
        provider_job_id=task_id,
        model=retry_model,
        request_payload_json=_sanitize_video_job_request_payload({
            **request_payload,
            "reference_asset_ids": retry_reference_ids,
            "reference_sources": ["video_asset" for _ in retry_reference_ids],
        }),
        provider_payload_json=provider_metadata or None,
        status="pending",
        progress=0,
        duration_seconds=retry_duration,
        aspect_ratio=body.aspect_ratio or old_job.aspect_ratio or "16:9",
        input_mode=str(request_payload.get("input_mode") or old_job.input_mode or "text_to_video"),
        source_storyboard_asset_id=old_job.source_storyboard_asset_id,
        reference_asset_ids_json=retry_reference_ids,
    )
    db.add(new_job)
    db.commit()
    db.refresh(new_job)

    return {
        "job": {
            "id": new_job.id,
            "shot_id": new_job.shot_id,
            "provider": new_job.provider,
            "provider_job_id": new_job.provider_job_id,
            "model": new_job.model,
            "status": new_job.status,
            "progress": new_job.progress,
            "duration_seconds": new_job.duration_seconds,
            "aspect_ratio": new_job.aspect_ratio,
            "request_payload": _sanitize_video_job_request_payload(new_job.request_payload_json),
            "error_message": new_job.error_message,
            "submitted_at": _serialize_datetime(new_job.submitted_at),
            "completed_at": _serialize_datetime(new_job.completed_at),
        },
    }


# 鈹€鈹€鈹€ Video Asset Endpoints 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

@router.get("/api/chapters/{chapter_id}/video-assets")
async def list_chapter_video_assets(
    chapter_id: int,
    request: Request,
    asset_type: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    chapter = _require_chapter_for_user(chapter_id, user, db)

    if chapter.story_id:
        _backfill_storyboard_assets_for_story(db, chapter.story_id)

    query = db.query(VideoAsset).filter(VideoAsset.chapter_id == chapter_id, VideoAsset.status == "active")
    if asset_type:
        query = query.filter(VideoAsset.asset_type == asset_type)

    assets = list(query.order_by(VideoAsset.created_at.desc()).all())

    if chapter.story_id:
        same_story_types = _same_story_video_asset_types(asset_type)
        if same_story_types:
            same_story_assets = (
                db.query(VideoAsset)
                .filter(
                    VideoAsset.story_id == chapter.story_id,
                    VideoAsset.asset_type.in_(same_story_types),
                    VideoAsset.status == "active",
                )
                .order_by(VideoAsset.created_at.desc())
                .all()
            )
            existing_ids = {a.id for a in assets}
            for asset in same_story_assets:
                if asset.id not in existing_ids:
                    assets.append(asset)
                    existing_ids.add(asset.id)

    # 查询角色资产时，补充 Story 级角色库中的参考图
    if asset_type == "character_reference" and chapter.story_id:
        story_char_assets = (
            db.query(VideoAsset)
            .join(StoryCharacterVersion, StoryCharacterVersion.ref_asset_id == VideoAsset.id)
            .filter(
                StoryCharacterVersion.story_id == chapter.story_id,
                StoryCharacterVersion.is_default == True,
                VideoAsset.status == "active",
            )
            .all()
        )
        existing_ids = {a.id for a in assets}
        for a in story_char_assets:
            if a.id not in existing_ids:
                assets.append(a)

    return {
        "chapter_id": chapter_id,
        "assets": [
            {
                "id": a.id,
                "story_id": a.story_id,
                "chapter_id": a.chapter_id,
                "scene_id": a.scene_id,
                "shot_id": a.shot_id,
                "asset_type": a.asset_type,
                "name": a.name,
                "file_path": _to_video_url(a.file_path),
                "provider": a.provider,
                "prompt": a.prompt or "",
                "meta": a.meta_json or {},
                "created_at": _serialize_datetime(a.created_at),
            }
            for a in assets
        ],
    }


@router.post("/api/chapters/{chapter_id}/video-assets")
async def create_video_asset(
    chapter_id: int,
    body: CreateVideoAssetRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    chapter = _require_chapter_for_user(chapter_id, user, db)

    if body.story_id is not None and body.story_id != chapter.story_id:
        raise HTTPException(400, "素材作品与章节不一致")

    scene = None
    if body.scene_id is not None:
        scene = db.get(ScriptScene, body.scene_id)
        if not scene or scene.chapter_id != chapter_id:
            raise HTTPException(400, "素材场景与章节不一致")

    shot_id = body.shot_id
    if shot_id is not None:
        shot = db.get(VideoShot, shot_id)
        if not shot or not shot.scene or shot.scene.chapter_id != chapter_id:
            raise HTTPException(400, "素材分镜与章节不一致")
        if scene is not None and shot.scene_id != scene.id:
            raise HTTPException(400, "素材分镜与场景不一致")

    asset = VideoAsset(
        story_id=chapter.story_id,
        chapter_id=chapter_id,
        scene_id=body.scene_id,
        shot_id=shot_id,
        asset_type=body.asset_type,
        name=body.name,
        file_path=_validate_video_asset_storage_path(body.file_path),
        provider=body.provider or "",
        prompt=body.prompt or "",
        style_preset=body.style_preset or None,
        meta_json=body.meta or {},
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)

    return {
        "id": asset.id,
        "story_id": asset.story_id,
        "chapter_id": asset.chapter_id,
        "scene_id": asset.scene_id,
        "shot_id": asset.shot_id,
        "asset_type": asset.asset_type,
        "name": asset.name,
        "file_path": asset.file_path,
        "provider": asset.provider,
        "prompt": asset.prompt or "",
        "meta": asset.meta_json or {},
        "created_at": _serialize_datetime(asset.created_at),
    }


@router.get("/api/video-assets/{asset_id}")
async def get_video_asset(
    asset_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    asset = _require_video_asset_for_user(asset_id, user, db)

    return {
        "id": asset.id,
        "story_id": asset.story_id,
        "chapter_id": asset.chapter_id,
        "scene_id": asset.scene_id,
        "shot_id": asset.shot_id,
        "asset_type": asset.asset_type,
        "asset_subtype": asset.asset_subtype,
        "name": asset.name,
        "file_path": asset.file_path,
        "provider": asset.provider,
        "prompt": asset.prompt or "",
        "style_preset": asset.style_preset,
        "meta": asset.meta_json or {},
        "locked": asset.locked,
        "revision": asset.revision,
        "is_master": asset.is_master,
        "status": asset.status,
        "usage_scope": asset.usage_scope,
        "inherit_to_next_shot": asset.inherit_to_next_shot,
        "source_type": asset.source_type,
        "story_level_default": asset.story_level_default,
        "chapter_level_default": asset.chapter_level_default,
        "created_at": _serialize_datetime(asset.created_at),
    }


@router.delete("/api/video-assets/{asset_id}")
async def delete_video_asset(
    asset_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    asset = _require_video_asset_for_user(asset_id, user, db)

    # 清空 script_scenes 对该 asset 的外键引用
    db.query(ScriptScene).filter(
        ScriptScene.concept_art_asset_id == asset_id
    ).update({"concept_art_asset_id": None})

    # 从 OSS 删除（如已配置）
    from services.oss import delete_by_url
    delete_by_url(asset.file_path)

    db.delete(asset)
    db.commit()

    return {"ok": True, "asset_id": asset_id}


@router.put("/api/video-assets/{asset_id}")
async def update_video_asset(asset_id: int, request: Request, db: Session = Depends(get_db)):
    """更新视频资产的基本信息（名称等）"""
    user = _require_user(request, db)
    asset = _require_video_asset_for_user(asset_id, user, db)

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="请求体必须是 JSON")

    if "name" in body and body["name"]:
        asset.name = str(body["name"]).strip()

    db.commit()
    db.refresh(asset)

    return {"id": asset.id, "name": asset.name, "message": "资产已更新"}


@router.post("/api/video-assets/{asset_id}/replace")
async def replace_video_asset(asset_id: int, request: Request, db: Session = Depends(get_db)):
    """上传本地图片替换资产文件。"""
    user = _require_user(request, db)
    asset = _require_video_asset_for_user(asset_id, user, db)

    content_type = request.headers.get("content-type", "")
    if "multipart/form-data" not in content_type:
        raise HTTPException(400, "Expected multipart/form-data upload")

    form = await request.form()
    uploaded = form.get("file")
    if uploaded is None or not hasattr(uploaded, "filename"):
        raise HTTPException(400, "No file uploaded")

    filename = getattr(uploaded, "filename", "") or "replaced.png"
    data = await uploaded.read()

    asset_dir = _VIDEO_OUTPUTS_DIR / f"asset_{asset_id}"
    asset_dir.mkdir(parents=True, exist_ok=True)
    ext = Path(filename).suffix or ".png"
    output_path = asset_dir / f"replaced_{datetime.datetime.utcnow().strftime('%Y%m%d_%H%M%S')}{ext}"
    await run_blocking(output_path.write_bytes, data)

    # OSS 上传（如已配置）
    from services import oss as oss_service
    _configure_oss_from_db(db)
    oss_url = await run_blocking(oss_service.upload_file, str(output_path)) if oss_service.is_enabled() else None
    if oss_url:
        try:
            output_path.unlink(missing_ok=True)
        except Exception:
            pass
        rel_path = oss_url
    else:
        rel_path = str(output_path.relative_to(_VIDEO_OUTPUTS_DIR.resolve()))

    asset.file_path = rel_path
    asset.name = filename
    asset.revision = (asset.revision or 0) + 1
    db.commit()
    db.refresh(asset)

    return {
        "ok": True,
        "asset": {
            "id": asset.id, "name": asset.name,
            "file_path": _to_video_url(asset.file_path),
            "revision": asset.revision,
        },
    }


@router.post("/api/video-assets/{asset_id}/regen")
async def regenerate_video_asset(
    asset_id: int,
    body: dict,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    asset = _require_video_asset_for_user(asset_id, user, db)

    prompt = str(body.get("prompt") or "").strip()
    if not prompt:
        raise HTTPException(400, "提示词必填")
    requested_style_preset = _normalize_style_name(str(body.get("style_preset") or ""))
    effective_style_preset = requested_style_preset or _normalize_style_name(asset.style_preset)
    if not effective_style_preset and asset.chapter_id:
        workflow = (
            db.query(ChapterVideoWorkflow)
            .filter(ChapterVideoWorkflow.chapter_id == asset.chapter_id)
            .order_by(ChapterVideoWorkflow.created_at.desc())
            .first()
        )
        effective_style_preset = _normalize_style_name(workflow.video_style if workflow else None)
    if not effective_style_preset and asset.chapter_id:
        chapter = db.get(Chapter, asset.chapter_id)
        if chapter and chapter.video_style_preset_id:
            chapter_preset = db.get(VideoStylePreset, chapter.video_style_preset_id)
            effective_style_preset = _normalize_style_name(chapter_preset.name if chapter_preset else None)
    style_template = ""
    if effective_style_preset:
        preset = (
            db.query(VideoStylePreset)
            .filter(VideoStylePreset.name == effective_style_preset)
            .first()
        )
        if preset:
            effective_style_preset = preset.name
            style_template = preset.prompt_template or ""
    generation_prompt = _merge_style_prompt(prompt, style_template, effective_style_preset)
    style_ref_path = (
        _resolve_workflow_style_ref_path(asset.chapter_id, db, effective_style_preset)
        if asset.chapter_id
        else None
    )
    style_reference_path = Path(style_ref_path) if style_ref_path else None
    mode = str(body.get("mode") or "full").strip().lower()
    if mode not in {"full", "partial"}:
        mode = "full"
    mask = body.get("mask")

    source_path = ensure_local_media_path(asset.file_path, "video")
    source_path_obj = Path(source_path) if source_path else None
    has_source = source_path_obj is not None and source_path_obj.exists()
    logger.info(
        "[regen_asset] asset_id=%s chapter_id=%s story_id=%s file_path=%r source_path=%s has_source=%s style_preset=%s mode=%s",
        asset_id,
        asset.chapter_id,
        asset.story_id,
        asset.file_path,
        source_path,
        bool(has_source),
        effective_style_preset,
        mode,
    )

    api_key = _user_image_api_key(request)
    _configure_image_service_from_db(request, db)
    regen_dir = _VIDEO_OUTPUTS_DIR / "regen_assets"
    regen_dir.mkdir(parents=True, exist_ok=True)
    output_filename = f"asset_{asset.id}_regen_{uuid.uuid4().hex[:8]}.png"
    output_path = regen_dir / output_filename

    # 配额预检
    _check_and_consume_quota_wrapper(
        user.id,
        "manga.image.generate.monthly_limit",
        1,
        db,
        deduct=False,
        request=request,
        provider_kind="image",
    )

    try:
        if has_source:
            if mode == "partial" and mask:
                import base64
                mask_bytes = base64.b64decode(str(mask))
                saved_path = await image2_service.edit_existing_image(
                    prompt=prompt,
                    source_image_path=source_path_obj,
                    output_path=output_path,
                    mask_bytes=mask_bytes,
                    api_key=api_key or None,
                    style_reference_path=style_reference_path,
                    style_prompt=style_template or effective_style_preset or None,
                )
            else:
                saved_path = await image2_service.edit_existing_image(
                    prompt=prompt,
                    source_image_path=source_path_obj,
                    output_path=output_path,
                    api_key=api_key or None,
                    style_reference_path=style_reference_path,
                    style_prompt=style_template or effective_style_preset or None,
                )
        else:
            if asset.asset_type not in {"character_reference", "story_character_reference", "scene_reference", "prop_reference"}:
                raise HTTPException(404, "素材原图不存在，无法重绘")
            saved_path = await generate_visual_asset_image(
                prompt=generation_prompt,
                output_path=output_path,
                asset_type=asset.asset_type,
                api_key=api_key or None,
                size="1920x1080",
                reference_paths=[str(style_reference_path)] if style_reference_path else None,
                reference_labels=[effective_style_preset] if style_reference_path else None,
                reference_roles=["style"] if style_reference_path else None,
            )
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Regenerate video asset failed: asset_id=%s err=%s", asset_id, exc)
        raise HTTPException(502, f"重绘失败: {exc}")

    new_revision = (asset.revision or 1) + 1
    new_asset = VideoAsset(
        story_id=asset.story_id,
        chapter_id=asset.chapter_id,
        scene_id=asset.scene_id,
        shot_id=asset.shot_id,
        asset_type=asset.asset_type,
        asset_subtype=asset.asset_subtype,
        name=asset.name,
        file_path=_to_video_url(str(output_path)) if not (saved_path and str(saved_path).startswith("http")) else str(saved_path),
        provider=asset.provider or "image2",
        prompt=prompt,
        style_preset=effective_style_preset or None,
        source_type=getattr(asset, "source_type", "ai_generated"),
        source_asset_ids_json=[asset.id],
        revision=new_revision,
        is_master=True,
        status="active",
    )
    db.add(new_asset)
    db.flush()
    asset.status = "replaced"

    if asset.asset_type == "storyboard_frame" and asset.shot_id:
        shot = db.get(VideoShot, asset.shot_id)
        if shot:
            shot.storyboard_asset_id = new_asset.id
            shot.updated_at = datetime.datetime.utcnow()

    db.commit()
    # 配额扣减
    _check_and_consume_quota_wrapper(
        user.id,
        "manga.image.generate.monthly_limit",
        1,
        db,
        deduct=True,
        request=request,
        provider_kind="image",
    )
    db.refresh(new_asset)

    return {
        "asset": {
            "id": new_asset.id,
            "name": new_asset.name,
            "file_path": _to_video_url(new_asset.file_path),
            "asset_type": new_asset.asset_type,
            "asset_subtype": new_asset.asset_subtype,
            "prompt": new_asset.prompt,
            "style_preset": new_asset.style_preset,
            "revision": new_asset.revision,
            "source_asset_ids_json": new_asset.source_asset_ids_json,
        }
    }


# 鈹€鈹€鈹€ Video Style Preset Endpoints 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

@router.get("/api/video-style-presets")
async def list_video_style_presets(
    request: Request,
    db: Session = Depends(get_db),
):
    presets = (
        db.query(VideoStylePreset)
        .order_by(VideoStylePreset.sort_order.asc())
        .all()
    )
    return {
        "presets": [
            {
                "id": p.id,
                "name": p.name,
                "category": p.category,
                "image_url": p.image_url,
                "prompt_template": p.prompt_template,
                "image_style_params": p.image_style_params,
                "video_style_params": p.video_style_params,
                "sort_order": p.sort_order,
            }
            for p in presets
        ],
    }


@router.post("/api/video-style-presets/upload-image")
async def upload_style_preset_image(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """上传风格预设图片。"""
    user = _require_user(request, db)

    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(400, "请上传图片文件")

    import os
    from datetime import datetime
    upload_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "manga_outputs", "style-presets")
    os.makedirs(upload_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    ext = os.path.splitext(file.filename or "style.png")[1] or ".png"
    filename = f"style_{user.id}_{timestamp}{ext}"
    file_path = os.path.join(upload_dir, filename)

    content = await file.read()
    await run_blocking(Path(file_path).write_bytes, content)

    relative_path = f"style-presets/{filename}"

    from services import oss as oss_service
    _configure_oss_from_db(db)
    oss_url = await run_blocking(oss_service.upload_file, str(file_path))
    if oss_url:
        logger.info("风格预设图片已上传到 OSS: %s", safe_media_url_for_log(oss_url))
        relative_path = oss_url
    else:
        logger.info("风格预设图片未上传到 OSS（未配置或上传失败），使用本地路径: %s", relative_path)

    logger.info("上传风格预设图片完成，返回 URL: %s", safe_media_url_for_log(relative_path))
    return {"success": True, "url": relative_path}


@router.post("/api/video-style-presets")
async def create_video_style_preset(
    body: VideoStylePresetCreate,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)

    preset = VideoStylePreset(
        name=body.name,
        category=body.category,
        image_url=body.image_url,
        prompt_template=body.prompt_template,
        image_style_params=body.image_style_params,
        video_style_params=body.video_style_params,
        sort_order=body.sort_order,
    )
    db.add(preset)
    db.commit()
    db.refresh(preset)

    return {
        "id": preset.id,
        "name": preset.name,
        "category": preset.category,
        "image_url": preset.image_url,
        "prompt_template": preset.prompt_template,
        "image_style_params": preset.image_style_params,
        "video_style_params": preset.video_style_params,
        "sort_order": preset.sort_order,
    }


@router.put("/api/video-style-presets/{preset_id}")
async def update_video_style_preset(
    preset_id: int,
    body: VideoStylePresetUpdate,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    preset = db.get(VideoStylePreset, preset_id)
    if not preset:
        raise HTTPException(404, "视频风格预设未找到")

    update_data = body.model_dump(exclude_unset=True)
    logger.info(
        "更新风格预设 %s: received fields=%s image_url=%s",
        preset_id,
        list(update_data.keys()),
        safe_media_url_for_log(update_data.get("image_url", "(未发送)")),
    )
    for field, value in update_data.items():
        setattr(preset, field, value)

    db.commit()
    db.refresh(preset)

    return {
        "id": preset.id,
        "name": preset.name,
        "category": preset.category,
        "image_url": preset.image_url,
        "prompt_template": preset.prompt_template,
        "image_style_params": preset.image_style_params,
        "video_style_params": preset.video_style_params,
        "sort_order": preset.sort_order,
    }


@router.delete("/api/video-style-presets/{preset_id}")
async def delete_video_style_preset(
    preset_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    preset = db.get(VideoStylePreset, preset_id)
    if not preset:
        raise HTTPException(404, "视频风格预设未找到")

    # 检查是否有章节引用此预设，如果有则清除引用
    from models import Chapter
    chapters_with_preset = db.query(Chapter).filter(Chapter.video_style_preset_id == preset_id).all()
    for chapter in chapters_with_preset:
        chapter.video_style_preset_id = None

    db.delete(preset)
    db.commit()

    return {"ok": True, "cleared_references": len(chapters_with_preset)}


# 鈹€鈹€鈹€ Chapter Style Preset Selection 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

@router.get("/api/chapters/{chapter_id}/video-style-preset")
async def get_chapter_video_style_preset(
    chapter_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    chapter = _require_chapter_for_user(chapter_id, user, db)

    preset = None
    if chapter.video_style_preset_id:
        preset = db.get(VideoStylePreset, chapter.video_style_preset_id)

    return {
        "chapter_id": chapter_id,
        "style_preset_id": chapter.video_style_preset_id,
        "style_preset": {
            "id": preset.id,
            "name": preset.name,
            "category": preset.category,
            "image_url": preset.image_url,
            "prompt_template": preset.prompt_template,
            "image_style_params": preset.image_style_params,
            "video_style_params": preset.video_style_params,
            "sort_order": preset.sort_order,
        } if preset else None,
    }


@router.put("/api/chapters/{chapter_id}/video-style-preset")
async def set_chapter_video_style_preset(
    chapter_id: int,
    body: ChapterStylePresetUpdate,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    chapter = _require_chapter_for_user(chapter_id, user, db)

    preset = db.get(VideoStylePreset, body.style_preset_id)
    if not preset:
        raise HTTPException(404, "视频风格预设未找到")

    chapter.video_style_preset_id = body.style_preset_id
    db.commit()

    return {
        "chapter_id": chapter_id,
        "style_preset_id": chapter.video_style_preset_id,
        "style_preset": {
            "id": preset.id,
            "name": preset.name,
            "category": preset.category,
            "image_url": preset.image_url,
        },
    }


@router.get("/api/stories/{story_id}/video-style-preset")
async def get_story_video_style_preset(
    story_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    story = _require_story_for_user(story_id, user, db)

    preset = None
    if hasattr(story, "video_style_preset_id") and story.video_style_preset_id:
        preset = db.get(VideoStylePreset, story.video_style_preset_id)

    return {
        "story_id": story_id,
        "style_preset_id": getattr(story, "video_style_preset_id", None),
        "style_preset": {
            "id": preset.id,
            "name": preset.name,
            "category": preset.category,
            "image_url": preset.image_url,
            "prompt_template": preset.prompt_template,
            "image_style_params": preset.image_style_params,
            "video_style_params": preset.video_style_params,
            "sort_order": preset.sort_order,
        } if preset else None,
    }


@router.put("/api/stories/{story_id}/video-style-preset")
async def set_story_video_style_preset(
    story_id: int,
    body: StoryStylePresetUpdate,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    story = _require_story_for_user(story_id, user, db)

    preset = db.get(VideoStylePreset, body.style_preset_id)
    if not preset:
        raise HTTPException(404, "视频风格预设未找到")

    story.video_style_preset_id = body.style_preset_id
    db.commit()

    return {
        "story_id": story_id,
        "style_preset_id": story.video_style_preset_id,
        "style_preset": {
            "id": preset.id,
            "name": preset.name,
            "category": preset.category,
            "image_url": preset.image_url,
        },
    }


# ─── Story Character Library (Phase 2) ──────────────────────────────

def _get_story_character_reference_asset_ids(story_id: int, db: Session) -> list[int]:
    """获取 Story 级所有角色默认版本的参考图 asset_id。

    优先级：
    1. StoryCharacterVersion 中 is_default=True 且有 ref_asset_id 的版本（角色库生成）
    2. VideoAsset 中 story_character_reference / character_reference 类型的活跃资产（兜底，覆盖镜头级生成）
    """
    versions = db.query(StoryCharacterVersion).filter(
        StoryCharacterVersion.story_id == story_id,
        StoryCharacterVersion.is_default == True,
        StoryCharacterVersion.ref_asset_id.isnot(None),
    ).all()
    result_ids = list({v.ref_asset_id for v in versions if v.ref_asset_id})

    # 兜底：直接从 VideoAsset 表查找该故事的角色参考图
    # 覆盖以下场景：
    # - 用户通过镜头级界面生成角色参考图（asset_type="character_reference"），未设置 StoryCharacterVersion.ref_asset_id
    # - StoryCharacterVersion 的 ref_asset_id 因故丢失
    if not result_ids:
        assets = db.query(VideoAsset).filter(
            VideoAsset.story_id == story_id,
            VideoAsset.asset_type.in_(["story_character_reference", "character_reference"]),
            VideoAsset.status == "active",
        ).all()
        result_ids = [a.id for a in assets]

    return result_ids


def _serialize_character_versions(db: Session, story_id: int, character_name: str) -> list[dict]:
    versions = db.query(StoryCharacterVersion).filter(
        StoryCharacterVersion.story_id == story_id,
        StoryCharacterVersion.character_name == character_name,
    ).order_by(StoryCharacterVersion.sort_order.asc()).all()
    result: list[dict] = []
    for v in versions:
        ref_url = ""
        if v.ref_asset_id:
            asset = db.get(VideoAsset, v.ref_asset_id)
            if asset:
                ref_url = _to_video_url(asset.file_path)
        result.append({
            "id": v.id,
            "label": v.version_label,
            "is_default": v.is_default,
            "ref_asset_id": v.ref_asset_id,
            "ref_asset_url": ref_url,
            "appearance_card": v.appearance_card or "",
            "sort_order": v.sort_order,
        })
    return result


@router.get("/api/stories/{story_id}/video-characters")
async def list_video_characters(
    story_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    story = _require_story_for_user(story_id, user, db)

    versions = db.query(StoryCharacterVersion).filter(
        StoryCharacterVersion.story_id == story_id,
    ).order_by(StoryCharacterVersion.sort_order.asc()).all()

    char_map: dict[str, list[dict]] = {}
    for v in versions:
        ref_url = ""
        if v.ref_asset_id:
            asset = db.get(VideoAsset, v.ref_asset_id)
            if asset:
                ref_url = _to_video_url(asset.file_path)
        char_map.setdefault(v.character_name, []).append({
            "id": v.id,
            "label": v.version_label,
            "is_default": v.is_default,
            "ref_asset_id": v.ref_asset_id,
            "ref_asset_url": ref_url,
            "appearance_card": v.appearance_card or "",
            "sort_order": v.sort_order,
        })

    characters = [{"name": name, "versions": vers} for name, vers in char_map.items()]
    return {"characters": characters, "video_character_profiles": story.video_character_profiles or ""}


@router.post("/api/stories/{story_id}/video-characters/generate")
async def generate_video_characters(
    story_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """从 story.characters 调用 DeepSeek 生成角色外貌卡，存入 story.video_character_profiles 并创建默认版本。"""
    user = _require_user(request, db)
    story = _require_story_for_user(story_id, user, db)

    characters_data = story.characters or []
    if not characters_data:
        raise HTTPException(400, "故事尚无角色数据，请先在故事框架中生成角色")

    character_names: list[str] = []
    char_descriptions: list[str] = []
    for c in characters_data:
        if isinstance(c, dict):
            name = str(c.get("name") or "").strip()
            if not name:
                continue
            character_names.append(name)
            parts = [name]
            for k in ("role", "personality", "arc", "appearance"):
                v = str(c.get(k) or "").strip()
                if v:
                    parts.append(f"{k}: {v[:300]}")
            bf = c.get("big_five")
            if isinstance(bf, dict):
                parts.append(f"big_five: {json.dumps(bf, ensure_ascii=False)}")
            char_descriptions.append("\n".join(parts))
        elif isinstance(c, str) and c.strip():
            character_names.append(c.strip())
            char_descriptions.append(c.strip())

    if not character_names:
        raise HTTPException(400, "无法从角色数据中提取角色名")

    api_key = _user_deepseek_api_key(request, db)
    ai_succeeded = False
    if api_key:
        _check_and_consume_quota_wrapper(
            user.id,
            "ai.text.advanced_calls.monthly_limit",
            1,
            db,
            deduct=False,
            request=request,
            provider_kind="text",
        )
        import httpx
        prompt_text = f"""你是一名专业的影视动画角色设计主管。请为以下每个角色生成一份详细的角色设计表（Character Design Sheet）文本描述。

角色数据：
{chr(10).join(f"--- {d}" for d in char_descriptions)}

输出格式（每个角色必须包含以下字段，按顺序输出）：

角色名：xxx
身份定位：xxx（角色在故事中的职业/身份/阵营，1-2句）
外貌描述：xxx（必须详细描述：发色、发型、眼型、瞳色、脸型、肤色、体型、身高特征、标志性面部特征如伤疤/痣等。至少100字，足够画师直接落笔）
服装要点：xxx（上身、下身、鞋履、配饰、材质说明、主色调、辅助色。包含服装层次和剪裁特点）
气质与表情：xxx（招牌表情、眼神特征、整体气场、标志性动作/姿态、情绪基调）
大五人格：O:xx C:xx E:xx A:xx N:xx（基于角色数据中的 big_five 推断，数值范围0-100）
绘制注意：xxx（必须包含可验证的面部几何特征——脸型基准、眼距比例、鼻梁轮廓、唇形、下颌线角度、发缝位置、标志色号。不可使用模糊描述）

输出规则：
1. 纯文本输出，不要 markdown 代码块
2. 每个角色之间用空行分隔
3. 「外貌描述」至少 100 字，要足够详细让画师能直接落笔
4. 「绘制注意」必须包含具体的面部几何测量或比例描述（如"眼距约为眼宽的1.2倍"）
5. 「大五人格」用数值标注，格式固定为 O:xx C:xx E:xx A:xx N:xx
6. 角色设计表用于视频动画的一致性参考，所有帧必须严格匹配这些标记"""

        try:
            async with httpx.AsyncClient(timeout=300) as client:
                response = await client.post(
                    f"{deepseek_service.runtime_base_url()}/chat/completions",
                    json={
                        "model": deepseek_service.runtime_model(),
                        "messages": [
                            {"role": "system", "content": "你是专业的影视角色设计师。直接输出纯文本角色卡。"},
                            {"role": "user", "content": prompt_text},
                        ],
                        "stream": False,
                        "max_tokens": 4096,
                    },
                    headers=deepseek_service._deepseek_auth_headers(api_key),
                )
                response.raise_for_status()
                data = response.json()
                deepseek_service._record_response_usage(data)
                content = str(data["choices"][0]["message"]["content"] or "").strip()
                ai_succeeded = True
        except Exception as e:
            logger.warning("AI generate character profiles failed: %s", e)
            content = ""
    else:
        content = ""

    if not content:
        cards: list[str] = []
        for c in characters_data:
            if not isinstance(c, dict):
                continue
            name = str(c.get("name") or "").strip()
            if not name:
                continue
            role = str(c.get("role") or "").strip()
            arc = str(c.get("arc") or "").strip()
            appearance = str(c.get("appearance") or "").strip()
            personality = str(c.get("personality") or "").strip()
            bf = c.get("big_five")
            bf_str = ""
            if isinstance(bf, dict):
                bf_str = f"O:{bf.get('O',50)} C:{bf.get('C',50)} E:{bf.get('E',50)} A:{bf.get('A',50)} N:{bf.get('N',50)}"
            cards.append(
                f"角色名：{name}\n"
                f"身份定位：{role}\n"
                f"外貌描述：{appearance or '发色、发型、眼型、瞳色、脸型、肤色、体型需补充'}\n"
                f"服装要点：{arc[:60] if arc else '需补充上衣、下装、鞋履、配饰'}\n"
                f"气质与表情：{personality or '需补充招牌表情、眼神特征、整体气场'}\n"
                + (f"大五人格：{bf_str}\n" if bf_str else "") +
                f"绘制注意：保持面部特征一致——脸型、眼距、鼻型、唇形、标志色固定不变\n"
            )
        content = "\n\n".join(cards)

    story.video_character_profiles = content
    db.flush()

    # 解析外貌卡创建版本
    import re
    created: list[dict] = []
    blocks = re.split(r'\n(?=角色名[：:])', content)
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        name_match = re.search(r'角色名[：:]\s*(.+)', block)
        if not name_match:
            continue
        name = name_match.group(1).strip()
        existing = db.query(StoryCharacterVersion).filter(
            StoryCharacterVersion.story_id == story_id,
            StoryCharacterVersion.character_name == name,
        ).first()
        if existing:
            existing.appearance_card = block
            db.flush()
            created.append({"name": name, "versions": _serialize_character_versions(db, story_id, name)})
        else:
            version = StoryCharacterVersion(
                story_id=story_id,
                character_name=name,
                version_label="v1-默认",
                appearance_card=block,
                is_default=True,
                sort_order=0,
            )
            db.add(version)
            db.flush()
            created.append({"name": name, "versions": _serialize_character_versions(db, story_id, name)})

    db.commit()
    if ai_succeeded:
        _check_and_consume_quota_wrapper(
            user.id,
            "ai.text.advanced_calls.monthly_limit",
            1,
            db,
            deduct=True,
            request=request,
            provider_kind="text",
        )
    return {"characters": created, "video_character_profiles": content}


@router.post("/api/stories/{story_id}/video-characters/{character_name}/versions")
async def create_character_version(
    story_id: int,
    character_name: str,
    body: dict,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    story = _require_story_for_user(story_id, user, db)

    version_label = str(body.get("version_label") or "v1-默认").strip()
    appearance_card = str(body.get("appearance_card") or "").strip()
    set_default = bool(body.get("set_default", False))

    existing = db.query(StoryCharacterVersion).filter(
        StoryCharacterVersion.story_id == story_id,
        StoryCharacterVersion.character_name == character_name,
        StoryCharacterVersion.version_label == version_label,
    ).first()
    if existing:
        existing.appearance_card = appearance_card
        if set_default:
            db.query(StoryCharacterVersion).filter(
                StoryCharacterVersion.story_id == story_id,
                StoryCharacterVersion.character_name == character_name,
            ).update({"is_default": False})
            existing.is_default = True
        db.commit()
        return {"version": {"id": existing.id, "label": existing.version_label, "is_default": existing.is_default, "ref_asset_id": existing.ref_asset_id, "appearance_card": existing.appearance_card}}

    if set_default:
        db.query(StoryCharacterVersion).filter(
            StoryCharacterVersion.story_id == story_id,
            StoryCharacterVersion.character_name == character_name,
        ).update({"is_default": False})

    next_order = (
        db.query(sa_func.max(StoryCharacterVersion.sort_order))
        .filter(StoryCharacterVersion.story_id == story_id, StoryCharacterVersion.character_name == character_name)
        .scalar() or 0
    ) + 1

    version = StoryCharacterVersion(
        story_id=story_id,
        character_name=character_name,
        version_label=version_label,
        appearance_card=appearance_card,
        is_default=set_default or not db.query(StoryCharacterVersion).filter(
            StoryCharacterVersion.story_id == story_id,
            StoryCharacterVersion.character_name == character_name,
        ).count(),
        sort_order=next_order,
    )
    db.add(version)
    db.commit()
    db.refresh(version)
    return {"version": {"id": version.id, "label": version.version_label, "is_default": version.is_default, "ref_asset_id": version.ref_asset_id, "appearance_card": version.appearance_card}}


@router.delete("/api/stories/{story_id}/video-characters/{character_name}/versions/{version_id}")
async def delete_character_version(
    story_id: int,
    character_name: str,
    version_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    story = _require_story_for_user(story_id, user, db)

    version = db.get(StoryCharacterVersion, version_id)
    if not version or version.story_id != story_id or version.character_name != character_name:
        raise HTTPException(404, "版本未找到")

    remaining = db.query(StoryCharacterVersion).filter(
        StoryCharacterVersion.story_id == story_id,
        StoryCharacterVersion.character_name == character_name,
    ).count()
    if remaining <= 1:
        raise HTTPException(400, "每个角色至少保留一个版本")

    db.delete(version)
    if version.is_default:
        fallback = db.query(StoryCharacterVersion).filter(
            StoryCharacterVersion.story_id == story_id,
            StoryCharacterVersion.character_name == character_name,
        ).first()
        if fallback:
            fallback.is_default = True
    db.commit()
    return {"ok": True}


@router.post("/api/stories/{story_id}/video-characters/{character_name}/versions/{version_id}/generate-ref")
async def generate_character_ref_image(
    story_id: int,
    character_name: str,
    version_id: int,
    body: dict,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    story = _require_story_for_user(story_id, user, db)

    version = db.get(StoryCharacterVersion, version_id)
    if not version or version.story_id != story_id or version.character_name != character_name:
        raise HTTPException(404, "版本未找到")
    if not (version.appearance_card or "").strip():
        raise HTTPException(400, "该版本尚无外貌卡，请先生成或编辑")

    del body
    final_prompt = str(version.appearance_card or "")
    # 追加角色设计表布局和一致性锁定指令
    final_prompt = (
        f"Character design sheet, one-page turnaround board. {final_prompt}. "
        "Required layout: front view portrait, side view portrait, back view portrait, full-body standing pose, "
        "4 facial expressions (neutral, surprised, smiling, focused), "
        "outfit detail callouts with accessories and material notes, costume breakdown panel, color palette chips. "
        "Orthographic character-sheet composition, clean labels, consistent proportions, clean light background. "
        "Mandatory consistency: lock face shape, eye distance, nose bridge contour, lip shape, jawline angle, "
        "hair parting, and 3 signature color swatches across ALL frames. "
        "Master reference sheet for video animation consistency."
    )
    char_dir = _VIDEO_OUTPUTS_DIR / f"story_{story_id}" / "characters"
    char_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}_{version.id}.png"
    full_path = char_dir / filename

    api_key = _user_image_api_key(request)

    # 配额预检
    _check_and_consume_quota_wrapper(user.id, "manga.image.generate.monthly_limit", 1, db, deduct=False)

    try:
        saved_path = await generate_visual_asset_image(
            prompt=final_prompt,
            output_path=full_path,
            asset_type="character_reference",
            api_key=api_key or None,
            size="1920x1080",
        )
    except Exception as e:
        logger.warning("Character ref generation failed for %s/%s: %s", character_name, version.version_label, e)
        raise HTTPException(502, f"角色参考图生成失败: {e}")

    file_path = saved_path if str(saved_path).startswith(("http://", "https://")) else str(full_path)
    ref_asset = VideoAsset(
        story_id=story_id,
        asset_type="story_character_reference",
        name=f"Character - {character_name} ({version.version_label})",
        file_path=file_path,
        provider="image2",
        prompt=final_prompt,
        style_preset=None,
        status="active",
    )
    db.add(ref_asset)
    db.flush()
    version.ref_asset_id = ref_asset.id
    db.commit()
    # 配额扣减
    _check_and_consume_quota_wrapper(user.id, "manga.image.generate.monthly_limit", 1, db, deduct=True)
    db.refresh(ref_asset)

    return {
        "ref_asset_id": ref_asset.id,
        "file_path": _to_video_url(ref_asset.file_path),
    }


@router.delete("/api/stories/{story_id}/video-characters/{character_name}/versions/{version_id}/ref")
async def delete_character_ref_image(
    story_id: int,
    character_name: str,
    version_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    story = _require_story_for_user(story_id, user, db)

    version = db.get(StoryCharacterVersion, version_id)
    if not version or version.story_id != story_id or version.character_name != character_name:
        raise HTTPException(404, "版本未找到")
    if not version.ref_asset_id:
        raise HTTPException(404, "该版本尚无参考图")

    asset = db.get(VideoAsset, version.ref_asset_id)
    if asset:
        # 从 OSS 删除（如已配置）
        from services.oss import delete_by_url
        delete_by_url(asset.file_path)
        # 删除物理文件
        local = resolve_local_media_path(asset.file_path, "video") or _from_video_url(asset.file_path) or str(_VIDEO_OUTPUTS_DIR / (asset.file_path or ""))
        try:
            os.remove(local)
        except OSError:
            pass
        db.delete(asset)

    version.ref_asset_id = None
    db.commit()
    return {"ok": True}


@router.post("/api/stories/{story_id}/video-characters/{character_name}/versions/{version_id}/ref/redraw")
async def redraw_character_ref_image(
    story_id: int,
    character_name: str,
    version_id: int,
    body: dict,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    story = _require_story_for_user(story_id, user, db)

    version = db.get(StoryCharacterVersion, version_id)
    if not version or version.story_id != story_id or version.character_name != character_name:
        raise HTTPException(404, "版本未找到")
    if not version.ref_asset_id:
        raise HTTPException(400, "该版本尚无参考图")

    redraw_prompt = str(body.get("prompt") or "").strip()
    if not redraw_prompt:
        raise HTTPException(400, "重绘提示词不能为空")

    mode = str(body.get("mode") or "full")
    mask_base64 = str(body.get("mask") or "")

    old_asset = db.get(VideoAsset, version.ref_asset_id)
    if not old_asset:
        raise HTTPException(404, "参考图资源不存在")

    source_path = ensure_local_media_path(old_asset.file_path, "video") or _from_video_url(old_asset.file_path) or str(_VIDEO_OUTPUTS_DIR / (old_asset.file_path or ""))
    source_path_obj = Path(source_path)
    if not source_path_obj.exists():
        raise HTTPException(404, "参考图文件不存在，请重新生成")

    char_dir = _VIDEO_OUTPUTS_DIR / f"story_{story_id}" / "characters"
    char_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}_{version.id}.png"
    full_path = char_dir / filename

    api_key = _user_image_api_key(request)

    _check_and_consume_quota_wrapper(user.id, "manga.image.generate.monthly_limit", 1, db, deduct=False)

    try:
        mask_bytes = None
        if mode == "partial" and mask_base64:
            import base64
            mask_bytes = base64.b64decode(mask_base64.split(",")[-1] if "," in mask_base64 else mask_base64)
        saved_path = await image2_service.edit_existing_image(
            prompt=redraw_prompt,
            source_image_path=source_path_obj,
            output_path=full_path,
            mask_bytes=mask_bytes,
            api_key=api_key or None,
        )
    except Exception as e:
        logger.warning("Character ref redraw failed for %s/%s: %s", character_name, version.version_label, e)
        raise HTTPException(502, f"角色参考图重绘失败: {e}")

    new_asset = VideoAsset(
        story_id=story_id,
        asset_type="story_character_reference",
        name=f"Character - {character_name} ({version.version_label})",
        file_path=saved_path if str(saved_path).startswith(("http://", "https://")) else str(full_path),
        provider="image2",
        prompt=redraw_prompt,
        style_preset=None,
        status="active",
    )
    db.add(new_asset)
    db.flush()
    version.ref_asset_id = new_asset.id
    db.commit()
    _check_and_consume_quota_wrapper(user.id, "manga.image.generate.monthly_limit", 1, db, deduct=True)
    db.refresh(new_asset)

    return {
        "ref_asset_id": new_asset.id,
        "file_path": _to_video_url(new_asset.file_path),
    }


# ─── Shot Style Preset Override ─────────────────────────────────────

@router.put("/api/shots/{shot_id}/video-style-preset")
async def set_shot_video_style_preset(
    shot_id: int,
    body: ShotStylePresetUpdate,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    shot = _require_shot_for_user(shot_id, user, db)

    shot.style_preset = _normalize_style_name(body.style_preset) or None
    db.commit()

    return {
        "shot_id": shot_id,
        "style_preset": shot.style_preset,
    }


@router.delete("/api/shots/{shot_id}/video-style-preset")
async def delete_shot_video_style_preset(
    shot_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    shot = _require_shot_for_user(shot_id, user, db)

    shot.style_preset = None
    db.commit()

    return {
        "shot_id": shot_id,
        "style_preset": None,
    }


# 鈹€鈹€鈹€ Shot Asset Bundle 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

@router.get("/api/shots/{shot_id}/asset-bundle")
async def get_shot_asset_bundle(
    shot_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    shot = _require_shot_for_user(shot_id, user, db)

    storyboard_asset = None
    if shot.storyboard_asset_id:
        asset = db.get(VideoAsset, shot.storyboard_asset_id)
        if asset:
            storyboard_asset = {
                "id": asset.id,
                "asset_type": asset.asset_type,
                "asset_subtype": asset.asset_subtype,
                "name": asset.name,
                "file_path": asset.file_path,
                "prompt": asset.prompt,
                "style_preset": asset.style_preset,
                "locked": asset.locked,
                "is_master": asset.is_master,
                "revision": asset.revision,
                "created_at": _serialize_datetime(asset.created_at),
            }

    first_frame = None
    last_frame = None
    frame_assets = (
        db.query(VideoAsset)
        .filter(
            VideoAsset.shot_id == shot_id,
            VideoAsset.asset_type == "shot_frame",
        )
        .order_by(VideoAsset.revision.desc())
        .all()
    )
    for a in frame_assets:
        ad = {
            "id": a.id,
            "asset_type": a.asset_type,
            "asset_subtype": a.asset_subtype,
            "name": a.name,
            "file_path": a.file_path,
            "prompt": a.prompt,
            "style_preset": a.style_preset,
            "locked": a.locked,
            "is_master": a.is_master,
            "revision": a.revision,
            "created_at": _serialize_datetime(a.created_at),
        }
        if a.asset_subtype == "first_frame" and first_frame is None:
            first_frame = ad
        elif a.asset_subtype == "last_frame" and last_frame is None:
            last_frame = ad

    char_assets = (
        db.query(VideoAsset)
        .filter(
            VideoAsset.shot_id == shot_id,
            VideoAsset.asset_type == "character_reference",
            VideoAsset.status == "active",
        )
        .order_by(VideoAsset.created_at.desc())
        .all()
    )
    character_references = [
        {
            "id": a.id,
            "name": a.name,
            "file_path": a.file_path,
            "prompt": a.prompt,
            "style_preset": a.style_preset,
            "locked": a.locked,
            "source_type": getattr(a, "source_type", "ai_generated"),
            "created_at": _serialize_datetime(a.created_at),
        }
        for a in char_assets
    ]

    scene_assets_q = (
        db.query(VideoAsset)
        .filter(
            VideoAsset.shot_id == shot_id,
            VideoAsset.asset_type == "scene_reference",
            VideoAsset.status == "active",
        )
        .order_by(VideoAsset.created_at.desc())
        .all()
    )
    scene_references = [
        {
            "id": a.id,
            "name": a.name,
            "file_path": a.file_path,
            "prompt": a.prompt,
            "style_preset": a.style_preset,
            "created_at": _serialize_datetime(a.created_at),
        }
        for a in scene_assets_q
    ]

    scene = db.get(ScriptScene, shot.scene_id)
    chapter_id = scene.chapter_id if scene else None
    available_char_assets = []
    available_scene_assets = []
    if chapter_id:
        available_char_assets = [
            {
                "id": a.id,
                "name": a.name,
                "file_path": a.file_path,
                "prompt": a.prompt,
                "style_preset": a.style_preset,
                "source_type": getattr(a, "source_type", "ai_generated"),
            }
            for a in db.query(VideoAsset).filter(
                VideoAsset.chapter_id == chapter_id,
                VideoAsset.asset_type == "character_reference",
                VideoAsset.status == "active",
                VideoAsset.shot_id != shot_id,
            ).order_by(VideoAsset.created_at.desc()).limit(10).all()
        ]
        available_scene_assets = [
            {
                "id": a.id,
                "name": a.name,
                "file_path": a.file_path,
                "prompt": a.prompt,
                "style_preset": a.style_preset,
            }
            for a in db.query(VideoAsset).filter(
                VideoAsset.chapter_id == chapter_id,
                VideoAsset.asset_type == "scene_reference",
                VideoAsset.status == "active",
            ).order_by(VideoAsset.created_at.desc()).limit(10).all()
        ]

    return {
        "shot_id": shot_id,
        "shot_number": shot.shot_number,
        "scene_id": shot.scene_id,
        "style_preset": shot.style_preset,
        "storyboard_asset": storyboard_asset,
        "storyboard_locked": shot.storyboard_locked,
        "first_frame": first_frame,
        "last_frame": last_frame,
        "character_references": character_references,
        "scene_references": scene_references,
        "available_character_assets": available_char_assets,
        "available_scene_assets": available_scene_assets,
    }


# 鈹€鈹€鈹€ Asset Scope & Promote 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

@router.put("/api/video-assets/{asset_id}/scope")
async def update_asset_scope(
    asset_id: int,
    body: UpdateAssetScopeRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    asset = _require_video_asset_for_user(asset_id, user, db)

    asset.usage_scope = body.usage_scope
    asset.inherit_to_next_shot = body.inherit_to_next_shot
    db.commit()

    return {
        "id": asset.id,
        "usage_scope": asset.usage_scope,
        "inherit_to_next_shot": asset.inherit_to_next_shot,
    }


@router.post("/api/video-assets/{asset_id}/promote")
async def promote_asset(
    asset_id: int,
    body: PromoteAssetRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    asset = _require_video_asset_for_user(asset_id, user, db)

    level = body.level
    if level == "scene_shared":
        asset.usage_scope = "scene_shared"
    elif level == "chapter_global":
        asset.usage_scope = "chapter_global"
        asset.chapter_level_default = True
    elif level == "story_default":
        asset.usage_scope = "chapter_global"
        asset.story_level_default = True
        asset.chapter_level_default = True

    asset.inherit_to_next_shot = body.inherit_to_next_shot
    db.commit()

    return {
        "id": asset.id,
        "usage_scope": asset.usage_scope,
        "inherit_to_next_shot": asset.inherit_to_next_shot,
        "chapter_level_default": asset.chapter_level_default,
        "story_level_default": asset.story_level_default,
    }


# 鈹€鈹€鈹€ Shot CRUD Endpoints 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€--------------

@router.post("/api/scenes/{scene_id}/shots")
async def create_scene_shot(
    scene_id: int,
    body: VideoShotUpdate,
    request: Request,
    db: Session = Depends(get_db),
):
    """Create a single shot in a scene."""
    user = _require_user(request, db)
    scene = db.get(ScriptScene, scene_id)
    if not scene:
        raise HTTPException(404, "场景未找到")
    _require_chapter_for_user(scene.chapter_id, user, db)

    max_shot = (
        db.query(sa_func.max(VideoShot.shot_number))
        .filter(VideoShot.scene_id == scene_id)
        .scalar()
    )
    next_number = (max_shot or 0) + 1

    shot = VideoShot(
        scene_id=scene_id,
        shot_number=next_number,
        title=body.title or f"Shot {next_number}",
        shot_type=body.shot_type or "",
        camera_angle=body.camera_angle or "",
        camera_movement=body.camera_movement or "",
        composition=body.composition or "",
        action_description=body.action_description or "",
        dialogue=body.dialogue or "",
        sound_design=body.sound_design or "",
            duration_seconds=min(SHOT_DURATION_SECONDS, body.duration_seconds or SHOT_DURATION_SECONDS),
        storyboard_prompt=body.storyboard_prompt or "",
        video_prompt=body.video_prompt or "",
        negative_prompt=body.negative_prompt or "",
        continuity_notes=body.continuity_notes or "",
        status=body.status or "draft",
    )
    db.add(shot)
    db.commit()
    db.refresh(shot)
    return _serialize_shot(shot)


@router.delete("/api/shots/{shot_id}")
async def delete_shot(
    shot_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Delete a shot and its associated assets/jobs/clips."""
    user = _require_user(request, db)
    shot = db.get(VideoShot, shot_id)
    if not shot:
        raise HTTPException(404, "分镜未找到")
    if not shot.scene:
        raise HTTPException(404, "场景未找到")
    _require_chapter_for_user(shot.scene.chapter_id, user, db)

    shot_id_val = shot.id
    db.delete(shot)
    db.commit()
    return {"ok": True, "shot_id": shot_id_val}


@router.post("/api/scenes/{scene_id}/shots/reorder")
async def reorder_scene_shots(
    scene_id: int,
    body: dict,
    request: Request,
    db: Session = Depends(get_db),
):
    """Reorder shots within a scene."""
    user = _require_user(request, db)
    scene = db.get(ScriptScene, scene_id)
    if not scene:
        raise HTTPException(404, "场景未找到")
    _require_chapter_for_user(scene.chapter_id, user, db)

    shot_ids = body.get("shot_ids", [])
    for idx, shot_id in enumerate(shot_ids):
        shot = db.get(VideoShot, shot_id)
        if shot and shot.scene_id == scene_id:
            shot.shot_number = idx + 1
    db.commit()

    shots = (
        db.query(VideoShot)
        .filter(VideoShot.scene_id == scene_id)
        .order_by(VideoShot.shot_number.asc())
        .all()
    )
    return {
        "scene_id": scene_id,
        "shots": [_serialize_shot(s) for s in shots],
    }


# 鈹€鈹€鈹€ Prompt Generation Endpoints 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

@router.post("/api/shots/{shot_id}/prompts/generate")
async def generate_shot_prompts(
    shot_id: int,
    body: GeneratePromptsRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """Generate storyboard/video prompts for a shot via AI."""
    user = _require_user(request, db)
    shot = db.get(VideoShot, shot_id)
    if not shot:
        raise HTTPException(404, "分镜未找到")
    if not shot.scene:
        raise HTTPException(404, "场景未找到")
    _require_chapter_for_user(shot.scene.chapter_id, user, db)

    shot_info = {
        "shot_type": shot.shot_type,
        "camera_angle": shot.camera_angle,
        "camera_movement": shot.camera_movement,
        "action_description": shot.action_description,
    }

    # 配额预检
    _check_and_consume_quota_wrapper(user.id, "ai.text.advanced_calls.monthly_limit", 1, db, deduct=False)

    prompts = await generate_shot_prompts_service(
        shot_info=shot_info,
        style=body.style or "cinematic",
        provider=body.provider or "sora",
        continuity_notes=body.continuity_notes or shot.continuity_notes or "",
        api_key=_user_deepseek_api_key(request, db),
        strict_ai=True,
    )

    shot.storyboard_prompt = prompts.get("storyboard_prompt", "")
    shot.video_prompt = prompts.get("video_prompt", "")
    shot.continuity_notes = prompts.get("continuity_notes", shot.continuity_notes or "")
    shot.updated_at = datetime.datetime.utcnow()
    db.commit()
    # 配额扣减
    _check_and_consume_quota_wrapper(user.id, "ai.text.advanced_calls.monthly_limit", 1, db, deduct=True)
    db.refresh(shot)

    reference_assets = []
    if body.include_references and shot.scene:
        assets = (
            db.query(VideoAsset)
            .filter(
                VideoAsset.scene_id == shot.scene_id,
                VideoAsset.asset_type.in_(["character_reference", "scene_reference"]),
                VideoAsset.status == "active",
            )
            .all()
        )
        reference_assets = [
            {"id": a.id, "asset_type": a.asset_type, "file_path": a.file_path}
            for a in assets
        ]

    return {
        "shot": _serialize_shot(shot),
        "reference_assets": reference_assets,
    }


# 鈹€鈹€鈹€ Storyboard Endpoints 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

@router.post("/api/shots/{shot_id}/storyboard/render")
async def render_shot_storyboard(
    shot_id: int,
    body: StoryboardRenderRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """Render (create) a storyboard frame asset for a shot."""
    user = _require_user(request, db)
    shot = db.get(VideoShot, shot_id)
    if not shot:
        raise HTTPException(404, "分镜未找到")
    if not shot.scene:
        raise HTTPException(404, "场景未找到")
    _require_chapter_for_user(shot.scene.chapter_id, user, db)

    ref_asset_ids = _collect_shot_reference_asset_ids(
        shot,
        db,
        include_characters=True,
        include_scene=True,
        include_storyboard=False,
        include_frames=False,
        explicit_asset_ids=body.reference_asset_ids or [],
    )
    ref_assets = db.query(VideoAsset).filter(VideoAsset.id.in_(ref_asset_ids)).all() if ref_asset_ids else []
    resolved_refs = _resolve_visual_asset_references(ref_assets)
    ref_asset_ids = [asset.id for asset, _, _, _ in resolved_refs]
    ref_paths = [path for _, path, _, _ in resolved_refs]
    ref_labels = [label for _, _, label, _ in resolved_refs]
    ref_roles = [role for _, _, _, role in resolved_refs]

    storyboards_dir = _VIDEO_OUTPUTS_DIR / "storyboards" / f"chapter_{shot.scene.chapter_id}" / f"shot_{shot_id}"
    storyboards_dir.mkdir(parents=True, exist_ok=True)
    file_name = f"storyboard_{datetime.datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}.png"
    full_path = storyboards_dir / file_name

    # 构建故事版 prompt（精简，避免图片 API 超时）
    duration = min(10, shot.duration_seconds or 10)
    content_full = _strip_storyboard_style_directives(
        shot.storyboard_prompt or shot.action_description or f"Shot {shot.shot_number}"
    )
    # 专业电影导演故事板 prompt — 中文输出，9:16 纵向，角色形象由参考图决定
    storyboard_prompt = (
        f"你是一位拥有20年经验的好莱坞电影导演和分镜导演。请将以下剧情转换为一张完整的电影级故事板展示图。\n\n"
        f"【剧情内容】\n{content_full}\n\n"
        f"【镜头信息】\n"
        f"镜头：{shot.shot_number} - {shot.title or ''}\n"
        f"时长：{duration}s | 景别：{shot.shot_type or 'medium'} | 角度：{shot.camera_angle or 'eye level'} | 运镜：{shot.camera_movement or 'static'}\n"
        f"动作：{shot.action_description or ''}\n"
        f"对白：{shot.dialogue or '无'}\n\n"
        f"【核心规则】\n"
        f"1. 角色外观完全由上传的参考图决定。禁止输出人物长相、发型、服装、五官等外貌描述。参考图中角色长什么样就画什么样。\n"
        f"2. 自动拆解剧情为5-8个关键镜头，形成完整故事节奏：开始→发展→冲突→高潮→结局。\n"
        f"3. 每个镜头包含：镜头编号、时间节点、剧情摘要、人物动作、情绪状态、关键对白、运镜方式、景别。\n\n"
        f"【画面布局】\n"
        f"整张图必须包含以下区域：\n"
        f"① 标题区：故事名称、类型、一句话简介\n"
        f"② 剧情概述区：故事背景、人物关系、核心矛盾\n"
        f"③ 时间轴区：开始→发展→冲突→高潮→结局，真实电影时间轴设计\n"
        f"④ 分镜展示区：5-8个Frame，每个含缩略图、编号、时间、摘要、对白、运镜、情绪标签\n"
        f"⑤ 对白展示区：关键对白摘录和情感表达\n"
        f"⑥ 情绪曲线区：人物情绪变化、情感递进、高潮节点\n"
        f"⑦ 导演批注区：镜头设计意图、叙事重点、节奏设计\n"
        f"⑧ 镜头语言区：远景/全景/中景/近景/特写/推进/拉远/跟拍等说明\n\n"
        f"【输出规则】\n"
        f"- 所有文字必须使用简体中文，禁止英文\n"
        f"- 图片比例：16:9横向\n"
        f"- 文字排版：真实可读的电影提案板风格，禁止乱码和占位符\n"
        f"- 画面占比：60%分镜画面 + 40%文字信息\n"
        f"- 统一留白、统一网格布局、高级质感\n"
        f"- 只输出一张完整的中文电影故事板展示图\n"
        f"- 角色形象严格匹配参考图"
    )
    prompt = storyboard_prompt.strip()
    api_key = _user_image_api_key(request)

    # 配额预检
    _check_and_consume_quota_wrapper(user.id, "manga.image.generate.monthly_limit", 1, db, deduct=False)

    try:
        saved_path = await image2_service.generate_reference_image(
            prompt=prompt,
            output_path=full_path,
            api_key=api_key,
            size="1920x1080",
            ref_image_paths=ref_paths if ref_paths else None,
            ref_type="storyboard",
            ref_labels=ref_labels if ref_labels else None,
            ref_roles=ref_roles if ref_roles else None,
        )
    except Exception as e:
        logger.warning("Storyboard render failed (shot=%s): %s", shot_id, e)
        raise HTTPException(502, f"分镜图生成失败: {e}")

    relative_path = f"storyboards/chapter_{shot.scene.chapter_id}/shot_{shot_id}/{file_name}"
    file_path = saved_path if str(saved_path).startswith(("http://", "https://")) else relative_path
    asset = VideoAsset(
        story_id=shot.scene.chapter.story_id if shot.scene.chapter else None,
        chapter_id=shot.scene.chapter_id,
        scene_id=shot.scene_id,
        shot_id=shot_id,
        asset_type="storyboard_frame",
        name=f"Storyboard - Shot {shot.shot_number}",
        file_path=file_path,
        provider=body.provider or "image2",
        prompt=prompt,
        source_asset_ids_json=ref_asset_ids or None,
        style_preset=None,
    )
    db.add(asset)

    shot.status = "storyboard_ready"
    shot.updated_at = datetime.datetime.utcnow()
    db.commit()
    # 配额扣减
    _check_and_consume_quota_wrapper(user.id, "manga.image.generate.monthly_limit", 1, db, deduct=True)
    db.refresh(shot)
    db.refresh(asset)

    return {
        "shot_id": shot_id,
        "asset": {
            "id": asset.id,
            "name": asset.name,
            "file_path": _to_video_url(asset.file_path),
            "asset_type": asset.asset_type,
        },
        "shot_status": shot.status,
    }


@router.post("/api/shots/{shot_id}/storyboard/approve")
async def approve_shot_storyboard(
    shot_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Approve and lock the storyboard for a shot."""
    user = _require_user(request, db)
    shot = db.get(VideoShot, shot_id)
    if not shot:
        raise HTTPException(404, "分镜未找到")
    if not shot.scene:
        raise HTTPException(404, "场景未找到")
    _require_chapter_for_user(shot.scene.chapter_id, user, db)

    shot.storyboard_locked = True
    shot.updated_at = datetime.datetime.utcnow()
    db.commit()

    return {
        "shot_id": shot_id,
        "storyboard_locked": True,
        "storyboard_asset_id": shot.storyboard_asset_id,
    }


@router.post("/api/shots/{shot_id}/storyboard/reject")
async def reject_shot_storyboard(
    shot_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Reject/unlock the storyboard for a shot."""
    user = _require_user(request, db)
    shot = db.get(VideoShot, shot_id)
    if not shot:
        raise HTTPException(404, "分镜未找到")
    if not shot.scene:
        raise HTTPException(404, "场景未找到")
    _require_chapter_for_user(shot.scene.chapter_id, user, db)

    shot.storyboard_locked = False
    shot.updated_at = datetime.datetime.utcnow()
    db.commit()

    return {
        "shot_id": shot_id,
        "storyboard_locked": False,
    }


@router.post("/api/shots/{shot_id}/storyboard/set-master")
async def set_master_storyboard(
    shot_id: int,
    body: StoryboardActionRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """Set the master storyboard asset for a shot."""
    user = _require_user(request, db)
    shot = db.get(VideoShot, shot_id)
    if not shot:
        raise HTTPException(404, "分镜未找到")
    if not shot.scene:
        raise HTTPException(404, "场景未找到")
    _require_chapter_for_user(shot.scene.chapter_id, user, db)

    asset_id = body.asset_id
    if not asset_id:
        raise HTTPException(400, "素材 ID 必填")

    asset = db.get(VideoAsset, asset_id)
    if not asset:
        raise HTTPException(404, "素材未找到")
    if asset.shot_id != shot_id or asset.asset_type != "storyboard_frame":
        raise HTTPException(400, "素材不是当前分镜的故事板")
    _require_reference_assets_for_story([asset.id], shot.scene.chapter.story_id, db)

    shot.storyboard_asset_id = asset_id
    shot.updated_at = datetime.datetime.utcnow()
    db.commit()

    return {
        "shot_id": shot_id,
        "storyboard_asset_id": asset_id,
        "is_master": True,
    }


@router.get("/api/shots/{shot_id}/storyboards")
async def get_shot_storyboards(
    shot_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """List all storyboard assets for a shot."""
    user = _require_user(request, db)
    shot = db.get(VideoShot, shot_id)
    if not shot:
        raise HTTPException(404, "分镜未找到")
    if not shot.scene:
        raise HTTPException(404, "场景未找到")
    _require_chapter_for_user(shot.scene.chapter_id, user, db)

    assets = (
        db.query(VideoAsset)
        .filter(
            VideoAsset.shot_id == shot_id,
            VideoAsset.asset_type == "storyboard_frame",
        )
        .order_by(VideoAsset.created_at.desc())
        .all()
    )

    return {
        "shot_id": shot_id,
        "assets": [
            {
                "id": a.id,
                "name": a.name,
                "file_path": a.file_path,
                "asset_type": a.asset_type,
                "prompt": a.prompt or "",
                "is_master": a.is_master,
                "revision": a.revision,
                "style_preset": a.style_preset,
                "status": a.status,
                "created_at": _serialize_datetime(a.created_at),
            }
            for a in assets
        ],
        "active_storyboard_asset_id": shot.storyboard_asset_id,
        "storyboard_locked": shot.storyboard_locked or False,
    }


# 鈹€鈹€鈹€ Shot Frame Endpoints 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

@router.post("/api/shots/{shot_id}/frames/generate")
async def generate_shot_frames(
    shot_id: int,
    body: GenerateShotFramesRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """Generate first/last frame images for a shot using Image2 API."""
    user = _require_user(request, db)
    shot = db.get(VideoShot, shot_id)
    if not shot:
        raise HTTPException(404, "分镜未找到")
    if not shot.scene:
        raise HTTPException(404, "场景未找到")
    _require_chapter_for_user(shot.scene.chapter_id, user, db)

    frame_type = body.frame_type or "both"
    prompt_base = body.prompt or shot.storyboard_prompt or shot.video_prompt or ""
    overwrite = body.overwrite or False

    # Resolve style context
    style_ctx = _resolve_effective_style_for_shot(shot, db, body.style_preset)
    image_style_params = style_ctx.get("image_style_params", {}) or {}
    style_template = style_ctx.get("prompt_template", "") or ""
    ref_asset_ids = _collect_shot_reference_asset_ids(
        shot,
        db,
        include_characters=body.inherit_character_assets,
        include_scene=body.inherit_scene_assets,
        include_storyboard=body.inherit_storyboard_asset,
        include_frames=False,
        explicit_asset_ids=body.reference_asset_ids or [],
    )
    ref_assets = db.query(VideoAsset).filter(VideoAsset.id.in_(ref_asset_ids)).all() if ref_asset_ids else []
    ref_block = _build_reference_constraints_block(ref_assets)
    # 追加风格预设参考图，确保首尾帧风格统一
    style_ref_path = _resolve_workflow_style_ref_path(shot.scene.chapter_id, db)
    ref_paths, ref_labels, ref_roles = _resolve_frame_reference_inputs(ref_assets, style_ref_path)

    api_key, _base_url, _model = _user_video_api_key(request)
    frames_dir = _VIDEO_OUTPUTS_DIR / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    # 配额预检（按实际生成帧数）
    frame_count = 2 if frame_type == "both" else 1
    _check_and_consume_quota_wrapper(user.id, "manga.image.generate.monthly_limit", frame_count, db, deduct=False)

    assets = []

    for subtype in (["first_frame", "last_frame"] if frame_type == "both" else [frame_type]):
        if subtype == "first_frame":
            frame_phase = "first frame key visual, pre-action state"
        else:
            frame_phase = "last frame key visual, post-action state"
        prompt_seed = f"{frame_phase}. {prompt_base}".strip()
        prompt = _merge_style_prompt_for_reference_image(
            f"{prompt_seed} {ref_block}".strip(),
            style_ref_path,
            style_template,
            style_ctx.get("name", ""),
        )
        prompt = prompt or "shot frame"

        filename = f"shot_{shot_id}_{subtype}_{uuid.uuid4().hex[:8]}.png"
        full_path = frames_dir / filename

        try:
            await image2_service.generate_reference_image(
                prompt=prompt,
                output_path=full_path,
                api_key=api_key or None,
                size=image_style_params.get("size", "1920x1080"),
                ref_image_paths=ref_paths if ref_paths else None,
                ref_type="frame",
                ref_labels=ref_labels if ref_labels else None,
                ref_roles=ref_roles if ref_roles else None,
            )
        except Exception as e:
            logger.warning("Frame %s generation failed for shot %s: %s", subtype, shot_id, e)
            # Still create the record with a placeholder so user can retry
            file_path = f"frames/{filename}"
        else:
            file_path = f"frames/{filename}"

        if overwrite:
            db.query(VideoAsset).filter(
                VideoAsset.shot_id == shot_id,
                VideoAsset.asset_subtype == subtype,
                VideoAsset.status == "active",
            ).update({"status": "replaced"})

        asset = VideoAsset(
            story_id=shot.scene.chapter.story_id if shot.scene.chapter else None,
            chapter_id=shot.scene.chapter_id,
            scene_id=shot.scene_id,
            shot_id=shot_id,
            asset_type="frame",
            asset_subtype=subtype,
            name=f"{'First' if subtype == 'first_frame' else 'Last'} Frame - Shot {shot.shot_number}",
            file_path=file_path,
            provider="image2",
            prompt=prompt,
            source_asset_ids_json=ref_asset_ids or None,
            style_preset=style_ctx.get("name") or None,
            status="active",
        )
        db.add(asset)
        db.flush()
        assets.append(asset)

    db.commit()
    # 配额扣减
    _check_and_consume_quota_wrapper(user.id, "manga.image.generate.monthly_limit", frame_count, db, deduct=True)
    for a in assets:
        db.refresh(a)

    return {
        "shot_id": shot_id,
        "assets": [
            {
                "id": a.id,
                "name": a.name,
                "file_path": _to_video_url(str(_VIDEO_OUTPUTS_DIR / str(a.file_path))) if a.file_path else "",
                "asset_type": a.asset_type,
                "asset_subtype": a.asset_subtype or "",
                "prompt": a.prompt or "",
                "style_preset": a.style_preset,
                "revision": a.revision,
                "is_master": a.is_master,
                "created_at": _serialize_datetime(a.created_at),
            }
            for a in assets
        ],
    }


@router.post("/api/shots/{shot_id}/frames/regen")
async def regenerate_shot_frame(
    shot_id: int,
    body: RegenerateShotFrameRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """Regenerate a specific shot frame asset using Image2 API."""
    user = _require_user(request, db)
    shot = db.get(VideoShot, shot_id)
    if not shot:
        raise HTTPException(404, "分镜未找到")
    if not shot.scene:
        raise HTTPException(404, "场景未找到")
    _require_chapter_for_user(shot.scene.chapter_id, user, db)

    old_asset = db.get(VideoAsset, body.asset_id)
    if not old_asset or old_asset.shot_id != shot_id:
        raise HTTPException(404, "帧素材未找到")

    new_revision = (old_asset.revision or 1) + 1
    frames_dir = _VIDEO_OUTPUTS_DIR / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    filename = f"shot_{shot_id}_{old_asset.asset_subtype}_{uuid.uuid4().hex[:8]}.png"
    full_path = frames_dir / filename
    file_path = f"frames/{filename}"

    api_key = _user_image_api_key(request)
    prompt = body.prompt or old_asset.prompt or ""
    style_ctx = _resolve_effective_style_for_shot(shot, db, body.style_preset)
    ref_asset_ids = _collect_shot_reference_asset_ids(
        shot,
        db,
        include_characters=False,
        include_scene=False,
        include_storyboard=False,
        include_frames=False,
        explicit_asset_ids=body.reference_asset_ids or [],
    )
    ref_assets = db.query(VideoAsset).filter(VideoAsset.id.in_(ref_asset_ids)).all() if ref_asset_ids else []
    ref_block = _build_reference_constraints_block(ref_assets)
    # 追加风格预设参考图，确保帧重绘风格统一
    style_ref_path = _resolve_workflow_style_ref_path(shot.scene.chapter_id, db)
    ref_paths, ref_labels, ref_roles = _resolve_frame_reference_inputs(ref_assets, style_ref_path)
    prompt = _merge_style_prompt_for_reference_image(
        f"{prompt} {ref_block}".strip(),
        style_ref_path,
        style_ctx.get("prompt_template"),
        style_ctx.get("name"),
    )
    _check_and_consume_quota_wrapper(user.id, "manga.image.generate.monthly_limit", 1, db, deduct=False)
    try:
        await image2_service.generate_reference_image(
            prompt=prompt,
            output_path=full_path,
            api_key=api_key or None,
            size=(style_ctx.get("image_style_params") or {}).get("size", "1920x1080"),
            ref_image_paths=ref_paths if ref_paths else None,
            ref_type="frame",
            ref_labels=ref_labels if ref_labels else None,
            ref_roles=ref_roles if ref_roles else None,
        )
    except Exception as e:
        logger.warning("Frame regen failed for shot %s asset %s: %s", shot_id, body.asset_id, e)
        raise HTTPException(502, f"閲嶇粯甯уけ璐? {e}")

    new_asset = VideoAsset(
        story_id=old_asset.story_id,
        chapter_id=old_asset.chapter_id,
        scene_id=old_asset.scene_id,
        shot_id=shot_id,
        asset_type=old_asset.asset_type,
        asset_subtype=old_asset.asset_subtype,
        name=old_asset.name,
        file_path=file_path,
        provider=old_asset.provider,
        prompt=prompt,
        revision=new_revision,
        source_asset_ids_json=list(dict.fromkeys(([old_asset.id] + ref_asset_ids))),
        style_preset=style_ctx.get("name") or old_asset.style_preset,
        status="active",
    )
    db.add(new_asset)
    old_asset.status = "replaced"
    db.commit()
    _check_and_consume_quota_wrapper(user.id, "manga.image.generate.monthly_limit", 1, db, deduct=True)
    db.refresh(new_asset)

    return {
        "asset": {
            "id": new_asset.id,
            "name": new_asset.name,
            "file_path": _to_video_url(str(_VIDEO_OUTPUTS_DIR / file_path)),
            "asset_type": new_asset.asset_type,
            "asset_subtype": new_asset.asset_subtype or "",
            "prompt": new_asset.prompt or "",
            "style_preset": new_asset.style_preset,
            "revision": new_asset.revision,
            "is_master": new_asset.is_master,
            "source_asset_ids_json": new_asset.source_asset_ids_json,
            "created_at": _serialize_datetime(new_asset.created_at),
        },
    }


@router.get("/api/shots/{shot_id}/frames")
async def get_shot_frames(
    shot_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Get all first/last frame assets for a shot."""
    user = _require_user(request, db)
    shot = db.get(VideoShot, shot_id)
    if not shot:
        raise HTTPException(404, "分镜未找到")
    if not shot.scene:
        raise HTTPException(404, "场景未找到")
    _require_chapter_for_user(shot.scene.chapter_id, user, db)

    assets = (
        db.query(VideoAsset)
        .filter(
            VideoAsset.shot_id == shot_id,
            VideoAsset.asset_type == "frame",
            VideoAsset.status == "active",
        )
        .order_by(VideoAsset.created_at.desc())
        .all()
    )

    def _to_frame_json(a: VideoAsset) -> dict:
        return {
            "id": a.id,
            "name": a.name,
            "file_path": _to_video_url(a.file_path),
            "asset_type": a.asset_type,
            "asset_subtype": a.asset_subtype or "",
            "is_master": a.is_master,
            "revision": a.revision,
            "prompt": a.prompt or "",
            "style_preset": a.style_preset,
            "source_asset_ids_json": a.source_asset_ids_json,
            "created_at": _serialize_datetime(a.created_at),
        }

    return {
        "shot_id": shot_id,
        "first_frames": [_to_frame_json(a) for a in assets if a.asset_subtype == "first_frame"],
        "last_frames": [_to_frame_json(a) for a in assets if a.asset_subtype == "last_frame"],
    }


@router.get("/api/chapters/{chapter_id}/shot-frames")
async def list_chapter_shot_frames(
    chapter_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """List all shot frames grouped by shot for a chapter."""
    user = _require_user(request, db)
    chapter = _require_chapter_for_user(chapter_id, user, db)

    shots = (
        db.query(VideoShot)
        .join(ScriptScene, VideoShot.scene_id == ScriptScene.id)
        .filter(ScriptScene.chapter_id == chapter_id)
        .order_by(ScriptScene.scene_number.asc(), VideoShot.shot_number.asc())
        .all()
    )

    result = []
    for shot in shots:
        first_frames = (
            db.query(VideoAsset)
            .filter(
                VideoAsset.shot_id == shot.id,
                VideoAsset.asset_type == "frame",
                VideoAsset.asset_subtype == "first_frame",
                VideoAsset.status == "active",
            )
            .all()
        )
        last_frames = (
            db.query(VideoAsset)
            .filter(
                VideoAsset.shot_id == shot.id,
                VideoAsset.asset_type == "frame",
                VideoAsset.asset_subtype == "last_frame",
                VideoAsset.status == "active",
            )
            .all()
        )
        result.append({
            "shot_id": shot.id,
            "shot_number": shot.shot_number,
            "scene_id": shot.scene_id,
            "frames": {
                "first_frames": [
                    {"id": a.id, "name": a.name, "file_path": a.file_path, "asset_type": a.asset_type, "asset_subtype": a.asset_subtype or ""}
                    for a in first_frames
                ],
                "last_frames": [
                    {"id": a.id, "name": a.name, "file_path": a.file_path, "asset_type": a.asset_type, "asset_subtype": a.asset_subtype or ""}
                    for a in last_frames
                ],
            },
        })

    return {"shots": result}


# 鈹€鈹€鈹€ Asset Endpoints 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

@router.post("/api/shots/{shot_id}/asset-prompts/parse")
async def parse_shot_asset_prompts(
    shot_id: int,
    body: dict,
    request: Request,
    db: Session = Depends(get_db),
):
    """Parse shot context into production-grade prompts for character/scene/frame/video assets."""
    user = _require_user(request, db)
    shot = db.get(VideoShot, shot_id)
    if not shot:
        raise HTTPException(404, "分镜未找到")
    if not shot.scene:
        raise HTTPException(404, "场景未找到")
    _require_chapter_for_user(shot.scene.chapter_id, user, db)

    scene = shot.scene
    chapter = db.get(Chapter, scene.chapter_id) if scene.chapter_id else None
    story = db.get(Story, chapter.story_id) if chapter else None

    scene_summary = (scene.summary or "").strip()
    scene_location = (scene.location or "").strip()
    scene_mood = (scene.mood or "").strip()

    characters_raw = scene.characters_json or []
    character_names: list[str] = []
    for c in characters_raw:
        if isinstance(c, str) and c.strip():
            character_names.append(c.strip())
        elif isinstance(c, dict):
            name = str(c.get("name") or "").strip()
            if name:
                character_names.append(name)
    character_names = list(dict.fromkeys(character_names))

    style_ctx = _resolve_effective_style_for_shot(shot, db, body.get("style_preset"))
    style_name = style_ctx.get("name") or ""

    character_notes = _extract_character_notes(
        getattr(story, "character_profiles", None) if story else None,
        character_names,
    )
    inherited_char_assets = _select_character_reference_assets_for_scene(scene, db, limit=8)
    inherited_constraints = _build_reference_constraints_block(inherited_char_assets)
    shot_grounding = _build_shot_asset_grounding_block(story, chapter, scene, shot)

    # 优先从 Story 级角色库读取角色 prompt，无角色库时才实时构建
    story_char_versions = (
        db.query(StoryCharacterVersion)
        .filter(
            StoryCharacterVersion.story_id == story.id,
            StoryCharacterVersion.is_default == True,
        )
        .all()
        if story else []
    )
    version_map = {v.character_name: v for v in story_char_versions}
    logger.info("Shot %s parse_prompts: scene_chars=%s story_has_library=%s",
                shot_id, character_names, bool(story_char_versions))

    default_character_prompts: list[dict] = []
    for name in character_names:
        v = version_map.get(name)
        if v and (v.appearance_card or "").strip():
            default_character_prompts.append({
                "name": name,
                "prompt": str(v.appearance_card or "").strip(),
                "grounding": "",
            })
        else:
            note = character_notes.get(name, "")
            inherited_prompt = ""
            for asset in inherited_char_assets:
                if name in (asset.name or "") or name in (asset.prompt or ""):
                    inherited_prompt = (asset.prompt or "")[:260]
                    break
            design_grounding = _build_character_design_grounding_block(story, name, note)
            default_character_prompts.append({
                "name": name,
                "prompt": _build_character_sheet_prompt(
                    character_name=name,
                    story=story,
                    note_from_profiles=note,
                    inherited_prompt=inherited_prompt,
                ),
                "grounding": design_grounding,
            })

    duration = min(10, shot.duration_seconds or 10)
    segments = max(3, min(5, duration // 2))  # 10s → 5段×2s, 8s → 4段×2s
    seg_dur = duration // segments
    base_storyboard = (
        f"SHOT TIMELINE STORYBOARD for shot {shot.shot_number} ({duration}s total, {shot.shot_type or 'medium'}, {shot.camera_angle or 'eye_level'}, {shot.camera_movement or 'static'}). "
        f"Characters: {', '.join(character_names) if character_names else 'N/A'}. "
        f"Action: {shot.action_description or ''}. Dialogue: {shot.dialogue or 'none'}. "
        f"Break this {duration}s shot into exactly {segments} time segments of {seg_dur}s each. "
        f"For EACH segment describe: (a) timestamp range, (b) character positions and expressions at that moment, "
        f"(c) camera framing at that moment (wide/medium/close-up), (d) what action happens in this segment, "
        f"(e) any dialogue spoken in this segment. "
        f"Format as:\n"
        f"[0-{seg_dur}s] ...\n[{seg_dur}-{2*seg_dur}s] ...\n...\n"
        f"End with camera/director notes for video generation reference."
    )
    base_first = _merge_style_prompt(
        (
            f"First frame key visual for shot {shot.shot_number}. "
            f"Starting state before action peak. {shot.action_description or ''}. "
            f"Camera: {shot.shot_type or 'medium'} / {shot.camera_angle or 'eye_level'} / {shot.camera_movement or 'static'}. "
            f"Composition: {shot.composition or ''}. "
            f"Scene mood {scene_mood}, location {scene_location}. "
            "Keep identity and wardrobe fully consistent with character reference assets."
        ),
        style_ctx.get("prompt_template"),
        style_name,
    )
    base_last = _merge_style_prompt(
        (
            f"Last frame key visual for shot {shot.shot_number}. "
            f"Ending state after action beat resolves. {shot.action_description or ''}. "
            "Camera continuity preserved from first frame. "
            f"Emotional state and environmental change should match scene mood: {scene_mood}. "
            "Keep character identity, outfit, and props consistent with references."
        ),
        style_ctx.get("prompt_template"),
        style_name,
    )
    # 获取前镜头尾帧用于连贯上下文
    prev_last = _get_previous_shot_last_frame(shot, db) if shot else None
    prev_context = ""
    if prev_last:
        prev_context = (
            f" SEAMLESS TRANSITION FROM PREVIOUS SHOT: "
            f"video must begin from the state shown in the preceding shot's last frame, "
            f"creating continuous visual flow."
        )

    # 首尾帧插值指令
    frame_guidance = ""
    if shot.first_frame_prompt or shot.last_frame_prompt:
        frame_guidance = (
            " FRAME-GUIDED VIDEO: The first reference image is the START frame and "
            "the last reference image is the END frame. Generate smooth animated "
            "transition between these two states, showing the described action unfold. "
            "Do NOT output a static image - animate the scene with realistic motion."
        )

    # 运镜改写：static → subtle motion，让视频有生命力
    camera_desc = shot.camera_movement or "static"
    if camera_desc == "static":
        camera_desc = "subtle handheld micro-movements with breathing camera feel"

    base_video = _merge_style_prompt(
        (
            f"Shot {shot.shot_number} - {shot.title or ''}. "
            f"Scene context: {scene_summary}. Location: {scene_location}. Mood: {scene_mood}. "
            f"Characters: {', '.join(character_names) if character_names else 'none'}. "
            f"Action: {shot.action_description or 'no action specified'}. "
            f"Dialogue: {shot.dialogue or 'none'}. "
            f"Camera: {shot.shot_type or 'medium'} shot, {shot.camera_angle or 'eye_level'} angle, {camera_desc}. "
            f"Duration: {min(10, shot.duration_seconds or 10)}s. "
            f"Sound: {shot.sound_design or 'ambient'}. "
            f"Continuity: {shot.continuity_notes or 'strict visual continuity'}.{prev_context}{frame_guidance} "
            "Video must accurately depict the described action with realistic motion, "
            "proper camera work matching the specified movement/framing, "
            "character behavior consistent with personality and scene mood, "
            "and seamless visual flow from first frame to last frame."
        ),
        style_ctx.get("prompt_template"),
        style_name,
    )

    api_key = _user_deepseek_api_key(request, db)
    if api_key:
        _check_and_consume_quota_wrapper(
            user.id,
            "ai.text.advanced_calls.monthly_limit",
            1,
            db,
            deduct=False,
            request=request,
            provider_kind="text",
        )
        import httpx

        ai_character_json = json.dumps(
            [
                {"name": item["name"], "base_prompt": item["prompt"], "grounding": item.get("grounding", "")}
                for item in default_character_prompts
            ],
            ensure_ascii=False,
        )
        prompt_text = f"""Generate production-ready shot asset prompts as strict JSON only.

Return JSON schema:
{{
  "character_prompts": [{{"name":"...", "prompt":"..."}}],
  "scene_prompt": "...",
  "prop_prompts": [{{"name":"...", "prompt":"..."}}],
  "storyboard_prompt": "...",
  "first_frame_prompt": "...",
  "last_frame_prompt": "...",
  "video_prompt": "..."
}}

Rules:
1. Character prompts are CHARACTER DESIGN SHEETS ONLY. No scene events, no system UI text overlays, no chapter plot reenactment.
2. Character prompts must request one-page turnaround sheet with: front portrait, side portrait, full-body, expression set, outfit/accessory callouts.
3. Scene prompt must describe the ENVIRONMENT ONLY (location, architecture, lighting, atmosphere, color palette). No characters, no actions. Example: "A dimly lit medieval tavern with wooden beams, candlelight, stone walls, warm amber tones".
4. Prop prompts are OBJECT DESIGN SHEETS for key props appearing in this shot. Each prop needs: name, detailed visual description (material, size, color, condition, distinctive features). Only include props that are visually important or appear repeatedly. Example: [{{"name": "Ancient Sword", "prompt": "A weathered double-edged sword with ornate golden hilt, leather-wrapped grip, blade shows battle scratches, 90cm overall length"}}].
5. Storyboard prompt MUST be a time-segmented shot breakdown covering ALL content that will appear in the final video. Requirements:
   a. Divide the shot into 3-5 equal time segments with [X-Ys] timestamps.
   b. For EACH segment describe: exact camera framing and movement state, precise character positions (foreground/background/left/right), facial expressions, body language, lighting changes, any props or environment details visible.
   c. Each segment description must be 2-4 sentences with vivid visual detail (not just one line).
   d. Include all dialogue/exactly when it occurs, with speaker and tone.
   e. End with complete camera/director notes: lens choice, focus pull, lighting setup, color temperature, depth of field.
4. Video prompt must describe the COMPLETE continuous action of the shot from start to end, including all camera movement, character blocking, lighting progression, and sound design. It must be consistent with the storyboard segments.
5. First/last frame prompts must capture the exact visual state at the beginning and end of the shot.
6. Character, scene, prop and storyboard prompts must not contain style preset names or art-style instructions. Their visual consistency is supplied by reference assets during image generation.
7. Output valid JSON object only.

Shot grounding: {shot_grounding}
Inherited character constraints: {inherited_constraints}

Character seeds (keep and improve, do not add scene event):
{ai_character_json}

Base storyboard prompt:
{base_storyboard}

Base first frame prompt:
{base_first}

Base last frame prompt:
{base_last}

Base video prompt:
{base_video}
"""

        payload = {
            "model": deepseek_service.runtime_model(),
            "messages": [
                {"role": "system", "content": "You are a film production prompt engineer. Return strict JSON only."},
                {"role": "user", "content": prompt_text},
            ],
            "stream": False,
            "max_tokens": 4096,
            "response_format": {"type": "json_object"},
        }
        try:
            async with httpx.AsyncClient(timeout=300) as client:
                response = await client.post(
                    f"{deepseek_service.runtime_base_url()}/chat/completions",
                    json=payload,
                    headers=deepseek_service._deepseek_auth_headers(api_key),
                )
                response.raise_for_status()
                data = response.json()
                deepseek_service._record_response_usage(data)
                content = str(data["choices"][0]["message"]["content"] or "").strip()
            result = deepseek_service._extract_json_object(content)

            ai_char_prompts = result.get("character_prompts", [])
            cleaned_char_prompts: list[dict] = []
            if isinstance(ai_char_prompts, list):
                for item in ai_char_prompts:
                    if not isinstance(item, dict):
                        continue
                    name = str(item.get("name") or "").strip()
                    prompt = str(item.get("prompt") or "").strip()
                    if name and prompt:
                        cleaned_char_prompts.append({"name": name, "prompt": prompt})

            if not cleaned_char_prompts:
                cleaned_char_prompts = [{"name": i["name"], "prompt": i["prompt"]} for i in default_character_prompts]

            final_scene_prompt = str(result.get("scene_prompt") or "").strip() or f"Scene at {scene_location}. Mood: {scene_mood}."

            ai_prop_prompts = result.get("prop_prompts", [])
            cleaned_prop_prompts: list[dict] = []
            if isinstance(ai_prop_prompts, list):
                for item in ai_prop_prompts:
                    if not isinstance(item, dict):
                        continue
                    name = str(item.get("name") or "").strip()
                    prompt = str(item.get("prompt") or "").strip()
                    if name and prompt:
                        cleaned_prop_prompts.append({"name": name, "prompt": prompt})

            final_storyboard = _strip_storyboard_style_directives(
                str(result.get("storyboard_prompt") or "").strip() or base_storyboard
            )
            final_first = str(result.get("first_frame_prompt") or "").strip() or base_first
            final_last = str(result.get("last_frame_prompt") or "").strip() or base_last
            final_video = str(result.get("video_prompt") or "").strip() or base_video

            # 持久化到数据库
            shot.storyboard_prompt = final_storyboard
            shot.video_prompt = final_video
            shot.first_frame_prompt = final_first
            shot.last_frame_prompt = final_last
            shot.character_prompts_json = cleaned_char_prompts  # pyright: ignore[reportAttributeAccessIssue]
            shot.scene_prompt = final_scene_prompt
            shot.prop_prompts_json = cleaned_prop_prompts
            db.commit()
            _check_and_consume_quota_wrapper(
                user.id,
                "ai.text.advanced_calls.monthly_limit",
                1,
                db,
                deduct=True,
                request=request,
                provider_kind="text",
            )

            logger.info("Shot %s parse_prompts AI OK: char_count=%d storyboard_len=%d",
                        shot_id, len(cleaned_char_prompts), len(final_storyboard))

            return {
                "shot_id": shot_id,
                "style_preset": style_name,
                "character_prompts": cleaned_char_prompts,
                "scene_prompt": final_scene_prompt,
                "prop_prompts": cleaned_prop_prompts,
                "storyboard_prompt": final_storyboard,
                "first_frame_prompt": final_first,
                "last_frame_prompt": final_last,
                "video_prompt": final_video,
                "grounding_used": {
                    "shot": shot_grounding,
                    "inheritance_constraints_present": bool(inherited_constraints),
                    "character_count": len(default_character_prompts),
                },
            }
        except Exception as e:
            logger.warning("AI parse failed for shot %s: %s, using deterministic prompts", shot_id, e)

    # 构造确定性回退
    fallback_char = [{"name": i["name"], "prompt": i["prompt"]} for i in default_character_prompts]
    fallback_storyboard = _strip_storyboard_style_directives(shot.storyboard_prompt or base_storyboard)
    fallback_first = base_first
    fallback_last = base_last
    fallback_video = shot.video_prompt or base_video

    # 持久化到数据库
    shot.storyboard_prompt = fallback_storyboard
    shot.video_prompt = fallback_video
    shot.first_frame_prompt = fallback_first
    shot.last_frame_prompt = fallback_last
    shot.character_prompts_json = fallback_char  # pyright: ignore[reportAttributeAccessIssue]
    shot.scene_prompt = f"Scene at {scene_location}. Mood: {scene_mood}."
    shot.prop_prompts_json = []
    db.commit()

    logger.info("Shot %s parse_prompts DONE: char_count=%d storyboard_len=%d video_len=%d",
                shot_id, len(fallback_char), len(fallback_storyboard), len(fallback_video))

    return {
        "shot_id": shot_id,
        "style_preset": style_name,
        "character_prompts": fallback_char,
        "scene_prompt": f"Scene at {scene_location}. Mood: {scene_mood}.",
        "prop_prompts": [],
        "storyboard_prompt": fallback_storyboard,
        "first_frame_prompt": fallback_first,
        "last_frame_prompt": fallback_last,
        "video_prompt": fallback_video,
        "grounding_used": {
            "shot": shot_grounding,
            "inheritance_constraints_present": bool(inherited_constraints),
            "character_count": len(default_character_prompts),
        },
    }


@router.post("/api/shots/{shot_id}/character-assets/generate")
async def generate_shot_character_asset(
    shot_id: int,
    body: dict,
    request: Request,
    db: Session = Depends(get_db),
):
    """Generate a character reference asset for a shot."""
    user = _require_user(request, db)
    shot = db.get(VideoShot, shot_id)
    if not shot:
        raise HTTPException(404, "分镜未找到")
    if not shot.scene:
        raise HTTPException(404, "场景未找到")
    _require_chapter_for_user(shot.scene.chapter_id, user, db)

    character_name = str(body.get("character_name") or "Unknown").strip() or "Unknown"
    prompt = str(body.get("prompt") or "").strip()
    if not prompt:
        raise HTTPException(400, "角色提示词必填")

    chapter_id = shot.scene.chapter_id
    char_dir = _VIDEO_OUTPUTS_DIR / "character_refs" / f"chapter_{chapter_id}" / f"shot_{shot_id}"
    char_dir.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", character_name)
    file_name = f"{safe_name}_{uuid.uuid4().hex[:8]}.png"
    full_path = char_dir / file_name

    final_prompt = prompt
    context = _build_shot_asset_context(shot, "character", character_name)
    if context:
        final_prompt = f"{final_prompt}\n\n---\n上下文参考（确保形象与时代背景一致）：\n{context}"
    api_key = _user_image_api_key(request)
    _configure_image_service_from_db(request, db)

    # 配额预检
    _check_and_consume_quota_wrapper(user.id, "manga.image.generate.monthly_limit", 1, db, deduct=False)

    try:
        saved_path = await generate_visual_asset_image(
            prompt=final_prompt,
            output_path=full_path,
            asset_type="character_reference",
            api_key=api_key or None,
            size="1920x1080",
        )
    except Exception as e:
        logger.warning("Character reference generation failed (shot=%s, name=%s): %s", shot_id, character_name, e)
        raise HTTPException(502, f"角色参考图生成失败: {e}")

    relative_path = f"character_refs/chapter_{chapter_id}/shot_{shot_id}/{file_name}"
    asset_path = saved_path if str(saved_path).startswith(("http://", "https://")) else relative_path
    source_asset_ids = body.get("source_asset_ids")
    if not isinstance(source_asset_ids, list):
        source_asset_ids = None

    asset = VideoAsset(
        story_id=shot.scene.chapter.story_id if shot.scene.chapter else None,
        chapter_id=shot.scene.chapter_id,
        scene_id=shot.scene_id,
        shot_id=shot_id,
        asset_type="character_reference",
        name=f"Character - {character_name}",
        file_path=asset_path,
        provider="image2",
        prompt=final_prompt,
        source_asset_ids_json=source_asset_ids,
        style_preset=None,
    )
    db.add(asset)
    db.commit()
    # 配额扣减
    _check_and_consume_quota_wrapper(user.id, "manga.image.generate.monthly_limit", 1, db, deduct=True)
    db.refresh(asset)

    return {
        "shot_id": shot_id,
        "asset": {
            "id": asset.id,
            "name": asset.name,
            "file_path": _to_video_url(asset.file_path),
            "asset_type": asset.asset_type,
            "prompt": asset.prompt or "",
            "style_preset": asset.style_preset,
            "status": asset.status,
            "created_at": _serialize_datetime(asset.created_at),
        },
    }


@router.post("/api/shots/{shot_id}/prop-assets/generate")
async def generate_shot_prop_asset(
    shot_id: int,
    body: dict,
    request: Request,
    db: Session = Depends(get_db),
):
    """Generate a prop reference asset for a shot."""
    user = _require_user(request, db)
    shot = db.get(VideoShot, shot_id)
    if not shot:
        raise HTTPException(404, "Shot not found")
    if not shot.scene:
        raise HTTPException(404, "Scene not found")
    _require_chapter_for_user(shot.scene.chapter_id, user, db)

    prop_name = str(body.get("prop_name") or "Prop").strip() or "Prop"
    prompt = str(body.get("prompt") or "").strip()
    if not prompt:
        raise HTTPException(400, "Prop prompt is required")

    chapter_id = shot.scene.chapter_id
    prop_dir = _VIDEO_OUTPUTS_DIR / "prop_refs" / f"chapter_{chapter_id}" / f"shot_{shot_id}"
    prop_dir.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", prop_name)
    file_name = f"{safe_name}_{uuid.uuid4().hex[:8]}.png"
    full_path = prop_dir / file_name

    final_prompt = prompt
    context = _build_shot_asset_context(shot, "prop", prop_name)
    if context:
        final_prompt = f"{final_prompt}\n\n---\n上下文参考（确保形象与时代背景一致）：\n{context}"
    api_key = _user_image_api_key(request)
    _configure_image_service_from_db(request, db)

    _check_and_consume_quota_wrapper(user.id, "manga.image.generate.monthly_limit", 1, db, deduct=False)

    try:
        saved_path = await generate_visual_asset_image(
            prompt=final_prompt,
            output_path=full_path,
            asset_type="prop_reference",
            api_key=api_key or None,
            size="1920x1080",
        )
    except Exception as e:
        logger.warning("Prop reference generation failed (shot=%s, name=%s): %s", shot_id, prop_name, e)
        raise HTTPException(502, f"道具参考图生成失败: {e}")

    relative_path = f"prop_refs/chapter_{chapter_id}/shot_{shot_id}/{file_name}"
    asset_path = saved_path if str(saved_path).startswith(("http://", "https://")) else relative_path
    source_asset_ids = body.get("source_asset_ids")
    if not isinstance(source_asset_ids, list):
        source_asset_ids = None

    asset = VideoAsset(
        story_id=shot.scene.chapter.story_id if shot.scene.chapter else None,
        chapter_id=shot.scene.chapter_id,
        scene_id=shot.scene_id,
        shot_id=shot_id,
        asset_type="prop_reference",
        name=f"Prop - {prop_name}",
        file_path=asset_path,
        provider="image2",
        prompt=final_prompt,
        source_asset_ids_json=source_asset_ids,
        style_preset=None,
    )
    db.add(asset)
    db.commit()
    _check_and_consume_quota_wrapper(user.id, "manga.image.generate.monthly_limit", 1, db, deduct=True)
    db.refresh(asset)

    return {
        "shot_id": shot_id,
        "asset": {
            "id": asset.id,
            "name": asset.name,
            "file_path": _to_video_url(asset.file_path),
            "asset_type": asset.asset_type,
            "prompt": asset.prompt or "",
            "style_preset": asset.style_preset,
            "status": asset.status,
            "created_at": _serialize_datetime(asset.created_at),
        },
    }


@router.post("/api/shots/{shot_id}/scene-assets/generate")
async def generate_shot_scene_asset(
    shot_id: int,
    body: dict,
    request: Request,
    db: Session = Depends(get_db),
):
    """Generate a scene reference asset for a shot (shot-level scene, not scene-level concept art)."""
    user = _require_user(request, db)
    shot = db.get(VideoShot, shot_id)
    if not shot:
        raise HTTPException(404, "Shot not found")
    if not shot.scene:
        raise HTTPException(404, "Scene not found")
    _require_chapter_for_user(shot.scene.chapter_id, user, db)

    prompt = str(body.get("prompt") or "").strip()
    if not prompt:
        prompt = shot.scene_prompt or f"Scene at {shot.scene.location or 'unknown'}. Mood: {shot.scene.mood or 'neutral'}."

    chapter_id = shot.scene.chapter_id
    scene_dir = _VIDEO_OUTPUTS_DIR / "scene_refs" / f"chapter_{chapter_id}" / f"shot_{shot_id}"
    scene_dir.mkdir(parents=True, exist_ok=True)
    file_name = f"scene_{uuid.uuid4().hex[:8]}.png"
    full_path = scene_dir / file_name

    final_prompt = prompt
    context = _build_shot_asset_context(shot, "scene", "")
    if context:
        final_prompt = f"{final_prompt}\n\n---\n上下文参考（确保形象与时代背景一致）：\n{context}"
    api_key = _user_image_api_key(request)
    _configure_image_service_from_db(request, db)

    _check_and_consume_quota_wrapper(user.id, "manga.image.generate.monthly_limit", 1, db, deduct=False)

    try:
        saved_path = await generate_visual_asset_image(
            prompt=final_prompt,
            output_path=full_path,
            asset_type="scene_reference",
            api_key=api_key or None,
            size="1920x1080",
        )
    except Exception as e:
        logger.warning("Scene reference generation failed (shot=%s): %s", shot_id, e)
        raise HTTPException(502, f"场景参考图生成失败: {e}")

    relative_path = f"scene_refs/chapter_{chapter_id}/shot_{shot_id}/{file_name}"
    asset_path = saved_path if str(saved_path).startswith(("http://", "https://")) else relative_path
    source_asset_ids = body.get("source_asset_ids")
    if not isinstance(source_asset_ids, list):
        source_asset_ids = None

    asset = VideoAsset(
        story_id=shot.scene.chapter.story_id if shot.scene.chapter else None,
        chapter_id=shot.scene.chapter_id,
        scene_id=shot.scene_id,
        shot_id=shot_id,
        asset_type="scene_reference",
        name=f"Scene - {shot.scene.title or f'Scene {shot.scene.scene_number}'}",
        file_path=asset_path,
        provider="image2",
        prompt=final_prompt,
        source_asset_ids_json=source_asset_ids,
        style_preset=None,
    )
    db.add(asset)
    db.commit()
    _check_and_consume_quota_wrapper(user.id, "manga.image.generate.monthly_limit", 1, db, deduct=True)
    db.refresh(asset)

    return {
        "shot_id": shot_id,
        "asset": {
            "id": asset.id,
            "name": asset.name,
            "file_path": _to_video_url(asset.file_path),
            "asset_type": asset.asset_type,
            "prompt": asset.prompt or "",
            "style_preset": asset.style_preset,
            "status": asset.status,
            "created_at": _serialize_datetime(asset.created_at),
        },
    }


# 鈹€鈹€鈹€ Video Render (non-streaming) 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

@router.post("/api/shots/{shot_id}/video/render")
async def render_shot_video(
    shot_id: int,
    body: VideoRenderRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """Submit a video generation job for a shot (non-streaming JSON response)."""
    user = _require_user(request, db)
    shot = db.get(VideoShot, shot_id)
    if not shot:
        raise HTTPException(404, "分镜未找到")
    if not shot.scene:
        raise HTTPException(404, "场景未找到")
    _require_chapter_for_user(shot.scene.chapter_id, user, db)

    effective_provider = _resolve_video_provider(body.provider, db)

    duration = max(
        1,
        min(
            MAX_VIDEO_DURATION_SECONDS,
            int(body.duration_seconds or shot.duration_seconds or DEFAULT_VIDEO_DURATION_SECONDS),
        ),
    )
    source_storyboard_asset_id = body.source_storyboard_asset_id or shot.storyboard_asset_id
    auto_reference_asset_ids = _collect_shot_reference_asset_ids(
        shot,
        db,
        include_characters=False,
        include_scene=False,
        include_storyboard=False,
        include_frames=False,
        explicit_asset_ids=body.reference_asset_ids or [],
    )
    auto_reference_asset_ids = list(dict.fromkeys(auto_reference_asset_ids))
    if body.use_reference_assets:
        reference_image_urls = _resolve_asset_reference_urls(auto_reference_asset_ids, db, request)
    else:
        auto_reference_asset_ids = []
        reference_image_urls = []
    input_mode = body.input_mode
    if not input_mode:
        has_ref_images = bool(reference_image_urls)
        has_storyboard = source_storyboard_asset_id and shot.storyboard_locked
        if has_storyboard:
            input_mode = "image_to_video"
        else:
            input_mode = "text_to_video"

    ref_assets = db.query(VideoAsset).filter(VideoAsset.id.in_(auto_reference_asset_ids)).all() if auto_reference_asset_ids else []
    first_frame_asset, last_frame_asset, other_refs = _split_frame_assets(ref_assets)
    ref_block = _build_reference_constraints_block(ref_assets)

    # 构建图片列表：首帧→主图(image[0])，其他→中间，尾帧→最后
    ordered_reference_inputs: list[str] = []
    # 用户未选首帧时，自动继承前一个镜头的尾帧作为连贯参考
    prev_last_frame = _get_previous_shot_last_frame(shot, db) if not first_frame_asset else None
    if prev_last_frame:
        p = _resolve_asset_file_paths([prev_last_frame])
        if p:
            ordered_reference_inputs.append(p[0])
            if not first_frame_asset:
                logger.info("Shot %s: 继承前镜头尾帧作为首帧连贯参考", shot_id)
    if first_frame_asset:
        path = _resolve_asset_file_paths([first_frame_asset])
        if path:
            ordered_reference_inputs.append(path[0])
    ordered_reference_inputs.extend(
        _resolve_asset_reference_urls([a.id for a in other_refs], db, request)
        if other_refs else []
    )
    if last_frame_asset:
        path = _resolve_asset_file_paths([last_frame_asset])
        if path:
            ordered_reference_inputs.append(path[0])

    style_ctx = _resolve_effective_style_for_shot(shot, db, requested_style_name=body.style)
    style_name = style_ctx["name"]
    video_style_params = style_ctx["video_style_params"]
    style_template = style_ctx["prompt_template"]

    style_ref_path = _resolve_workflow_style_ref_path(shot.scene.chapter_id, db, style_name)
    if style_ref_path:
        if style_ref_path not in ordered_reference_inputs:
            ordered_reference_inputs.append(style_ref_path)
    ordered_images = _prepare_video_reference_images(ordered_reference_inputs)
    if ordered_images:
        input_mode = "image_to_video"

    api_key, base_url, resolved_model = _user_video_api_key(request)
    resolved_model = body.model or resolved_model
    video_capabilities = _current_video_capabilities(request, db, resolved_model)
    adapter_type = _current_video_adapter_type(request)
    runtime_snapshot = _build_video_runtime_snapshot(
        request,
        db,
        api_key=api_key,
        base_url=base_url,
        model=resolved_model,
    )
    aspect_ratio = body.aspect_ratio or video_style_params.get("aspect_ratio") or "16:9"
    _validate_video_request_before_billing(
        adapter_type=adapter_type,
        model=resolved_model,
        video_capabilities=video_capabilities,
        aspect_ratio=aspect_ratio,
        duration_seconds=duration,
        reference_count=len(ordered_images),
    )
    quota_result = _reserve_video_billing(
        request,
        db,
        user_id=user.id,
        video_seconds=duration,
        detach=False,
    )
    grounding = _build_story_grounding_block(shot.scene.chapter.story if shot.scene and shot.scene.chapter else None, shot.scene.chapter if shot.scene else None, shot.scene)
    storyboard_guide = ""
    if shot.storyboard_prompt:
        storyboard_guide = (
            f"\n\n<<<故事版蓝图_STORYBOARD_BLUEPRINT>>>\n"
            f"以下分镜脚本是视频生成的导演蓝图，视频必须严格遵循：\n"
            f"{shot.storyboard_prompt}\n"
            f"<<<蓝图结束_END_BLUEPRINT>>>\n"
            f"核心要求：生成的视频必须严格匹配蓝图中的每一个时间段、镜头运动方式、"
            f"角色动作和情绪变化，不得偏离分镜脚本的任何细节。"
        )
    full_prompt = _merge_style_prompt(
        f"{body.prompt or storyboard_guide} {ref_block} Grounding: {grounding}".strip(),
        style_template, style_name,
    )
    logger.info("视频提交提示词 shot=%s:\n%s", shot_id, full_prompt)

    task_id = f"video_render_{shot_id}_{int(datetime.datetime.utcnow().timestamp())}"
    await task_manager.submit_task(
        task_id=task_id,
        task_type="video_render",
        coro_func=_submit_and_monitor_video_job,
        billing_usage_event_id=quota_result.get("usage_event_id"),
        shot_id=shot_id,
        provider=effective_provider,
        model=resolved_model,
        prompt=full_prompt,
        negative_prompt=body.negative_prompt or shot.negative_prompt or "",
        duration_seconds=duration,
        aspect_ratio=aspect_ratio,
        reference_images=ordered_images if ordered_images else None,
        api_key=api_key,
        base_url=base_url,
        input_mode=input_mode,
        video_capabilities=video_capabilities,
        adapter_type=adapter_type,
            timeout=600,
            max_retries=0,
            quota_user_id=user.id,
            quota_feature_key="video.generate.count.monthly_limit",
            quota_amount=duration,
            quota_usage_event_id=quota_result.get("usage_event_id"),
            metadata={
                "stage": "submitting",
                "message": "正在提交视频生成任务...",
                "provider_status": "submitting",
                "running_stage": "submitting",
                "running_message": "正在提交视频生成任务...",
            },
        )
    _detach_video_billing(request, quota_result)

    job_status = "pending"
    job = VideoGenerationJob(
        shot_id=shot_id,
        provider=effective_provider,
        provider_job_id=task_id,
        model=resolved_model,
        request_payload_json=_sanitize_video_job_request_payload({
            "model": resolved_model,
            "prompt": full_prompt,
            "negative_prompt": body.negative_prompt or shot.negative_prompt or "",
            "duration_seconds": duration,
            "aspect_ratio": aspect_ratio,
            "style": style_name,
            "input_mode": input_mode,
            "reference_asset_ids": auto_reference_asset_ids,
            "reference_sources": [
                {"asset_id": asset_id, "source": "video_asset"}
                for asset_id in auto_reference_asset_ids
            ],
        }),
        provider_payload_json=_video_provider_metadata(runtime_snapshot, quota_result.get("usage_event_id")),
        status=job_status,
        progress=0,
        duration_seconds=duration,
        aspect_ratio=aspect_ratio,
        error_message=None,
        input_mode=input_mode,
        source_storyboard_asset_id=source_storyboard_asset_id if input_mode == "image_to_video" else None,
        reference_asset_ids_json=auto_reference_asset_ids,
    )
    db.add(job)
    db.flush()

    shot.status = "rendering"
    shot.updated_at = datetime.datetime.utcnow()

    db.commit()

    return {
        "job": {
            "id": job.id,
            "shot_id": job.shot_id,
            "provider": job.provider,
            "provider_job_id": job.provider_job_id,
            "model": job.model,
            "status": job.status,
            "progress": job.progress,
            "duration_seconds": job.duration_seconds,
            "aspect_ratio": job.aspect_ratio,
            "request_payload": _sanitize_video_job_request_payload(job.request_payload_json),
            "error_message": job.error_message,
            "input_mode": job.input_mode,
            "source_storyboard_asset_id": job.source_storyboard_asset_id,
            "submitted_at": _serialize_datetime(job.submitted_at),
        },
        "shot_status": shot.status,
    }


# 鈹€鈹€鈹€ Video Project Endpoints 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

@router.post("/api/chapters/{chapter_id}/video-projects")
async def create_video_project(
    chapter_id: int,
    body: CreateVideoProjectRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    chapter = _require_chapter_for_user(chapter_id, user, db)

    project = VideoProject(
        story_id=chapter.story_id,
        chapter_id=chapter_id,
        name=body.name or f"Project - {chapter.title or f'Chapter {chapter.chapter_number}'}",
        timeline_json=[item.model_dump() for item in body.timeline],
        subtitle_json=[item.model_dump() for item in (body.subtitle or [])],
        bgm_path=_validate_video_asset_storage_path(body.bgm_path),
        cover_path=_validate_video_asset_storage_path(body.cover_path),
        status="draft",
    )
    db.add(project)
    db.commit()
    db.refresh(project)

    return {
        "id": project.id,
        "story_id": project.story_id,
        "chapter_id": project.chapter_id,
        "name": project.name,
        "timeline": project.timeline_json or [],
        "subtitle": project.subtitle_json or [],
        "bgm_path": project.bgm_path or "",
        "cover_path": project.cover_path or "",
        "status": project.status,
        "output_path": project.output_path or "",
        "created_at": _serialize_datetime(project.created_at),
        "updated_at": _serialize_datetime(project.updated_at),
    }


@router.get("/api/video-projects/{project_id}")
async def get_video_project(
    project_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    project = db.get(VideoProject, project_id)
    if not project:
        raise HTTPException(404, "视频项目未找到")

    # Validate ownership via chapter
    if project.chapter_id:
        _require_chapter_for_user(project.chapter_id, user, db)
    elif project.story_id:
        _require_story_for_user(project.story_id, user, db)
    else:
        raise HTTPException(403, "无法确定项目所有权")

    return {
        "id": project.id,
        "story_id": project.story_id,
        "chapter_id": project.chapter_id,
        "name": project.name,
        "timeline": project.timeline_json or [],
        "subtitle": project.subtitle_json or [],
        "bgm_path": project.bgm_path or "",
        "cover_path": project.cover_path or "",
        "status": project.status,
        "output_path": project.output_path or "",
        "created_at": _serialize_datetime(project.created_at),
        "updated_at": _serialize_datetime(project.updated_at),
    }


@router.patch("/api/video-projects/{project_id}")
async def update_video_project(
    project_id: int,
    body: VideoProjectUpdate,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    project = db.get(VideoProject, project_id)
    if not project:
        raise HTTPException(404, "视频项目未找到")

    if project.chapter_id:
        _require_chapter_for_user(project.chapter_id, user, db)
    elif project.story_id:
        _require_story_for_user(project.story_id, user, db)
    else:
        raise HTTPException(403, "无法确定项目所有权")

    update_data = body.model_dump(exclude_unset=True)
    field_map = {
        "name": "name",
        "timeline": "timeline_json",
        "subtitle": "subtitle_json",
        "bgm_path": "bgm_path",
        "cover_path": "cover_path",
        "status": "status",
    }
    for body_field, model_field in field_map.items():
        if body_field in update_data and update_data[body_field] is not None:
            value = update_data[body_field]
            if body_field in {"bgm_path", "cover_path"}:
                value = _validate_video_asset_storage_path(value)
            setattr(project, model_field, value)

    project.updated_at = datetime.datetime.utcnow()
    db.commit()
    db.refresh(project)

    return {
        "id": project.id,
        "story_id": project.story_id,
        "chapter_id": project.chapter_id,
        "name": project.name,
        "timeline": project.timeline_json or [],
        "subtitle": project.subtitle_json or [],
        "bgm_path": project.bgm_path or "",
        "cover_path": project.cover_path or "",
        "status": project.status,
        "output_path": project.output_path or "",
        "created_at": _serialize_datetime(project.created_at),
        "updated_at": _serialize_datetime(project.updated_at),
    }


@router.post("/api/video-projects/{project_id}/compile")
async def compile_video_project(
    project_id: int,
    body: CompileProjectRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    project = db.get(VideoProject, project_id)
    if not project:
        raise HTTPException(404, "视频项目未找到")

    if project.chapter_id:
        _require_chapter_for_user(project.chapter_id, user, db)
    elif project.story_id:
        _require_story_for_user(project.story_id, user, db)
    else:
        raise HTTPException(403, "无法确定项目所有权")

    timeline = project.timeline_json or []
    clips = []
    for item in sorted(timeline, key=lambda x: x.get("order", 0)):
        if not item.get("enabled", True):
            continue
        clip_id = item.get("clip_id")
        if not clip_id:
            continue

        clip = db.get(RenderedClip, clip_id)
        if not clip or not clip.is_active:
            logger.warning("Clip %s not found or inactive, skipping", clip_id)
            continue

        clip_shot = db.get(VideoShot, clip.shot_id)
        clip_scene = db.get(ScriptScene, clip_shot.scene_id) if clip_shot else None
        clip_chapter = db.get(Chapter, clip_scene.chapter_id) if clip_scene else None
        if not clip_chapter:
            raise HTTPException(404, f"视频片段 {clip_id} 未关联有效章节")
        if project.chapter_id and clip_chapter.id != project.chapter_id:
            raise HTTPException(403, "视频片段不属于当前项目章节")
        if project.story_id and clip_chapter.story_id != project.story_id:
            raise HTTPException(403, "视频片段不属于当前项目作品")

        video_path = ensure_local_media_path(clip.video_path, "video")
        if not video_path:
            logger.warning(
                "Could not resolve path for clip %s: %s",
                clip_id,
                safe_media_url_for_log(clip.video_path),
            )
            continue

        clips.append({
            "video_path": video_path,
            "duration_seconds": clip.duration_seconds or 0,
        })

    output_dir = _VIDEO_OUTPUTS_DIR / "projects"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_filename = f"video_project_{project_id}_{uuid.uuid4().hex[:8]}.mp4"
    fs_output_path = str(output_dir / output_filename)

    subtitle_data = project.subtitle_json or [] if body.burn_subtitle else []

    bgm_path = None
    if body.include_bgm and project.bgm_path:
        bgm_path = ensure_local_media_path(project.bgm_path, "video")
        if not bgm_path:
            raise HTTPException(422, "背景音乐文件不存在或地址不可用")

    result = await compile_project(
        output_path=fs_output_path,
        clips=clips,
        resolution=body.resolution,
        fps=body.fps,
        burn_subtitle=body.burn_subtitle,
        subtitle_data=subtitle_data,
        bgm_path=bgm_path,
    )

    project.status = result.get("status", "compiled")
    project.output_path = _to_video_url(fs_output_path)
    project.updated_at = datetime.datetime.utcnow()
    db.commit()
    db.refresh(project)

    return {
        "project": {
            "id": project.id,
            "story_id": project.story_id,
            "chapter_id": project.chapter_id,
            "name": project.name,
            "status": project.status,
            "output_path": project.output_path,
            "updated_at": _serialize_datetime(project.updated_at),
        },
        "compilation": result,
    }


# 鈹€鈹€鈹€ Internal helpers 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

_FEATURE_NAME_MAP: dict[str, str] = {
    "manga.image.generate.monthly_limit": "生图配额",
    "video.shot.split.monthly_limit": "拆镜次数",
    "video.generate.count.monthly_limit": "视频生成次数",
    "ai.text.advanced_calls.monthly_limit": "高级文本 AI 调用次数",
    "manga.max_image_count_per_chapter": "单章节最大出图数",
    "scene.generate.monthly_limit": "分镜生成次数",
    "framework.generate.monthly_limit": "小说框架生成次数",
    "chapter.expand.monthly_limit": "章节扩写次数",
}


def _check_and_consume_quota_wrapper(
    user_id: int,
    feature_key: str,
    amount: int,
    db: Session,
    deduct: bool,
    request: Request | None = None,
    provider_kind: str | None = None,
) -> dict:
    if amount <= 0:
        amount = 1

    try:
        import main as main_mod

        if main_mod._points_dual_track_enabled(db):
            request = request or getattr(db, "info", {}).get("request")
            modality = provider_kind if provider_kind in {"text", "image", "video"} else (
                "text"
                if feature_key == "video.shot.split.monthly_limit"
                else main_mod._feature_key_to_modality(feature_key)
            )
            if request is not None:
                return main_mod._check_and_consume_feature_quota(
                    request,
                    user_id,
                    feature_key,
                    amount,
                    db,
                    deduct=deduct,
                    provider_kind=modality,
                )
            mode = "platform"
            try:
                from models import UserAiPreference

                pref = db.query(UserAiPreference).filter(UserAiPreference.user_id == user_id).first()
                if pref and pref.credential_mode in {"platform", "user_key"}:
                    mode = pref.credential_mode
            except Exception:
                pass
            charged = 0
            usage_event_id = None
            billing_request_id = None
            if deduct and mode == "platform":
                from decimal import Decimal as _Decimal
                import uuid as _uuid
                from services.ai.resolver import begin_ai_call, complete_ai_call, resolve_model

                model = resolve_model(db, user_id, modality=modality, model_id=None, task_type=None)
                rid = str(_uuid.uuid4())
                estimate_kwargs = {}
                units = max(1, int(amount or 1))
                if modality == "image":
                    estimate_kwargs["image_count"] = units
                elif modality == "video":
                    estimate_kwargs["video_seconds"] = units
                ctx = begin_ai_call(
                    db,
                    user_id=user_id,
                    modality=modality,
                    task_type=feature_key,
                    credential_mode="platform",
                    model_id=model.id,
                    request_id=rid,
                    estimate_kwargs=estimate_kwargs,
                )
                complete_ai_call(
                    db,
                    ctx,
                    success=True,
                    image_count=units if modality == "image" else 0,
                    video_seconds=units if modality == "video" else 0,
                    usage_source="estimated",
                )
                charged = float(ctx.estimated_points or ctx.reserved_points or _Decimal("0"))
                usage_event_id = ctx.usage_event_id
                billing_request_id = ctx.request_id
            return {
                "skipped": True,
                "reason": "points_dual_track",
                "credential_mode": mode,
                "feature_key": feature_key,
                "points_charged": charged,
                "usage_event_id": usage_event_id,
                "billing_request_id": billing_request_id,
                "used": 0,
                "limit": 0,
                "period_key": "",
                "base_limit": 0,
                "granted": 0,
            }
    except HTTPException:
        raise
    except Exception:
        logger.exception("video 双轨配额失败（旧配额系统已移除，无 fallback）")
        raise


def _reserve_text_billing(
    request: Request,
    db: Session,
    *,
    user_id: int,
    feature_key: str = "ai.text.advanced_calls.monthly_limit",
) -> tuple[dict, object | None]:
    quota_result = _check_and_consume_quota_wrapper(
        user_id,
        feature_key,
        1,
        db,
        deduct=False,
        request=request,
        provider_kind="text",
    )
    import main as main_mod

    billing_ctx = main_mod._detach_pending_platform_points(
        request,
        quota_result.get("usage_event_id"),
    )
    return quota_result, billing_ctx


def _reserve_video_billing(
    request: Request,
    db: Session,
    *,
    user_id: int,
    video_seconds: int,
    detach: bool = True,
) -> dict:
    quota_result = _check_and_consume_quota_wrapper(
        user_id,
        "video.generate.count.monthly_limit",
        video_seconds,
        db,
        deduct=False,
    )
    if detach:
        import main as main_mod

        main_mod._detach_pending_platform_points(
            request,
            quota_result.get("usage_event_id"),
        )
    return quota_result


def _detach_video_billing(request: Request, quota_result: dict) -> None:
    if not quota_result.get("usage_event_id"):
        return
    import main as main_mod

    main_mod._detach_pending_platform_points(
        request,
        quota_result.get("usage_event_id"),
    )


async def _run_billed_text_task(
    *,
    billed_coro,
    billing_ctx,
    task_id: str | None = None,
    **kwargs,
):
    """统一执行后台文本 AI 任务，并按最终结果结算或释放预留积分。"""
    import main as main_mod

    try:
        result = await billed_coro(task_id=task_id, **kwargs)
        failed = bool(
            isinstance(result, dict)
            and (
                result.get("success") is False
                or result.get("status") in {"failed", "cancelled"}
                or result.get("workflow_status") in {"failed", "cancelled"}
                or bool(result.get("error"))
            )
        )
        main_mod._finish_streaming_platform_points(
            billing_ctx,
            success=not failed,
            error_code="background_task_failed" if failed else None,
        )
        return result
    except Exception as exc:
        main_mod._finish_streaming_platform_points(
            billing_ctx,
            success=False,
            error_code=type(exc).__name__,
        )
        raise


async def _run_billed_media_task(
    *,
    billed_coro,
    billing_usage_event_id: int | None,
    billing_modality: str,
    billing_units: int,
    task_id: str | None = None,
    **kwargs,
):
    """执行后台图片或视频任务，并按成功产出量结算预留积分。"""
    try:
        result = await billed_coro(task_id=task_id, **kwargs)
    except Exception as exc:
        if billing_usage_event_id:
            from services.ai.resolver import complete_ai_call_by_usage_event

            billing_db = SessionLocal()
            try:
                complete_ai_call_by_usage_event(
                    billing_db,
                    billing_usage_event_id,
                    success=False,
                    error_code=type(exc).__name__,
                )
            finally:
                billing_db.close()
        raise
    failed = bool(
        isinstance(result, dict)
        and (
            result.get("success") is False
            or result.get("status") in {"failed", "cancelled", "canceled"}
            or result.get("workflow_status") in {"failed", "cancelled", "canceled"}
            or bool(result.get("error"))
        )
    )
    if failed and billing_usage_event_id:
        from services.ai.resolver import complete_ai_call_by_usage_event

        billing_db = SessionLocal()
        try:
            complete_ai_call_by_usage_event(
                billing_db,
                billing_usage_event_id,
                success=False,
                error_code="background_task_failed",
            )
        finally:
            billing_db.close()
    if failed or not billing_usage_event_id:
        return result

    actual_units = max(0, int(billing_units or 0))
    if isinstance(result, dict) and billing_modality == "image":
        actual_units = max(0, int(result.get("shot_count") or 0))
    elif isinstance(result, dict) and billing_modality == "video" and kwargs.get("workflow_id"):
        failed_ids = {int(item) for item in (result.get("failed_shot_ids") or [])}
        billing_db = SessionLocal()
        try:
            query = billing_db.query(ChapterVideoShot).filter(
                ChapterVideoShot.workflow_id == int(kwargs["workflow_id"]),
            )
            shot_ids = kwargs.get("shot_ids")
            if shot_ids:
                query = query.filter(ChapterVideoShot.id.in_(shot_ids))
            actual_units = sum(
                max(1, min(MAX_VIDEO_DURATION_SECONDS, int(shot.duration_seconds or DEFAULT_VIDEO_DURATION_SECONDS)))
                for shot in query.all()
                if shot.id not in failed_ids
            )
        finally:
            billing_db.close()

    from services.ai.resolver import complete_ai_call_by_usage_event

    billing_db = SessionLocal()
    try:
        complete_ai_call_by_usage_event(
            billing_db,
            billing_usage_event_id,
            success=True,
            image_count=actual_units if billing_modality == "image" else 0,
            video_seconds=actual_units if billing_modality == "video" else 0,
        )
    finally:
        billing_db.close()
    return result


async def _submit_and_monitor_video_job(
    *,
    shot_id: int,
    provider: str,
    model: str,
    prompt: str,
    negative_prompt: str,
    duration_seconds: int,
    aspect_ratio: str,
    reference_images: list[str] | None,
    api_key: str | None,
    base_url: str | None,
    input_mode: str,
    video_capabilities: dict | None = None,
    adapter_type: str = video_adapter_service.VIDEO_ADAPTER_LINGDONG,
    billing_usage_event_id: int | None = None,
    task_id: str | None = None,
    story_id: int | None = None,
    chapter_id: int | None = None,
) -> dict:
    """提交视频任务并在后台完成轮询、下载、入库和最终计费。"""
    del story_id, chapter_id
    submit_result = await video_gen_service.submit_video_job(
        shot_id=shot_id,
        provider=provider,
        model=model,
        prompt=prompt,
        negative_prompt=negative_prompt,
        duration_seconds=duration_seconds,
        aspect_ratio=aspect_ratio,
        reference_images=reference_images,
        api_key=api_key,
        base_url=base_url,
        input_mode=input_mode,
        video_capabilities=video_capabilities,
        adapter_type=adapter_type,
    )
    provider_job_id = str(submit_result.get("provider_job_id") or "").strip()
    if not provider_job_id:
        raise RuntimeError("视频上游未返回任务 ID")

    db_job: VideoGenerationJob | None = None
    for _ in range(50):
        billing_db = SessionLocal()
        try:
            db_job = billing_db.query(VideoGenerationJob).filter(
                VideoGenerationJob.provider_job_id == task_id,
            ).first()
            if db_job:
                db_job.provider_job_id = provider_job_id
                db_job.status = "running"
                db_job.progress = max(1, int(submit_result.get("progress") or 1))
                billing_db.commit()
                break
        finally:
            billing_db.close()
        await asyncio.sleep(0.1)

    consecutive_poll_errors = 0
    for _ in range(200):
        if task_id and task_manager.is_cancellation_requested(task_id):
            raise asyncio.CancelledError
        try:
            latest = await video_gen_service.query_job_status(
                provider=provider,
                provider_job_id=provider_job_id,
                api_key=api_key,
                base_url=base_url,
                model=model,
                adapter_type=adapter_type,
            )
            consecutive_poll_errors = 0
        except Exception as exc:
            consecutive_poll_errors += 1
            if consecutive_poll_errors >= 5:
                raise
            if task_id:
                task_manager.update_task_metadata(
                    task_id,
                    stage="generating",
                    message=f"状态查询暂时失败，正在重试（{consecutive_poll_errors}/5）...",
                    last_error=public_error_message(exc, "视频状态查询失败，正在重试"),
                    provider_job_id=provider_job_id,
                )
            await asyncio.sleep(min(10, 2 ** consecutive_poll_errors))
            continue
        status = str(latest.get("status") or "queued").lower()
        progress = max(1, min(100, int(latest.get("progress") or 1)))
        if task_id:
            task_manager.update_task_metadata(
                task_id,
                stage="generating" if status not in {"succeeded", "failed", "cancelled"} else status,
                message="视频正在生成..." if status not in {"succeeded", "failed", "cancelled"} else "视频生成已完成",
                provider_status=latest.get("provider_status") or status,
                progress=progress,
                provider_job_id=provider_job_id,
            )

        billing_db = SessionLocal()
        try:
            db_job = billing_db.query(VideoGenerationJob).filter(
                VideoGenerationJob.provider_job_id == provider_job_id,
            ).first()
            if db_job:
                db_job.status = status
                db_job.progress = progress
                if latest.get("error"):
                    db_job.error_message = public_error_message(
                        latest["error"],
                        "视频生成失败，请稍后重试",
                    )
                billing_db.commit()
        finally:
            billing_db.close()

        if status in {"failed", "cancelled", "canceled"}:
            billing_db = SessionLocal()
            try:
                db_job = billing_db.query(VideoGenerationJob).filter(
                    VideoGenerationJob.provider_job_id == provider_job_id,
                ).first()
                if db_job:
                    _fail_video_job_and_refund(
                        billing_db,
                        db_job,
                        error_message=public_error_message(
                            latest.get("error"),
                            "视频生成失败，请稍后重试",
                        ),
                        reason=f"provider_{status}",
                    )
                else:
                    _refund_video_billing(
                        billing_db,
                        usage_event_id=billing_usage_event_id,
                        reason=f"provider_{status}",
                    )
            finally:
                billing_db.close()
            return {**submit_result, **latest, "status": "failed"}

        if status == "succeeded":
            fetched = await video_gen_service.fetch_job_result(
                provider=provider,
                provider_job_id=provider_job_id,
                shot_id=shot_id,
                api_key=api_key,
                base_url=base_url,
                model=model,
                adapter_type=adapter_type,
            )
            video_path_abs = str(fetched.get("video_path") or "").strip()
            if not video_path_abs:
                billing_db = SessionLocal()
                try:
                    db_job = billing_db.query(VideoGenerationJob).filter(
                        VideoGenerationJob.provider_job_id == provider_job_id,
                    ).first()
                    if db_job:
                        _fail_video_job_and_refund(
                            billing_db,
                            db_job,
                            error_message="视频生成成功但未返回可下载文件",
                            reason="result_missing_video_path",
                        )
                    else:
                        _refund_video_billing(
                            billing_db,
                            usage_event_id=billing_usage_event_id,
                            reason="result_missing_video_path",
                        )
                finally:
                    billing_db.close()
                return {**submit_result, "status": "failed", "error": "视频生成成功但未返回可下载文件"}

            billing_db = SessionLocal()
            try:
                db_job = billing_db.query(VideoGenerationJob).filter(
                    VideoGenerationJob.provider_job_id == provider_job_id,
                ).first()
                shot = billing_db.get(VideoShot, shot_id)
                if not db_job or not shot:
                    raise RuntimeError("视频任务记录不存在")
                clip = billing_db.query(RenderedClip).filter(RenderedClip.job_id == db_job.id).first()
                if clip is None:
                    billing_db.query(RenderedClip).filter(RenderedClip.shot_id == shot_id).update(
                        {"is_active": False},
                        synchronize_session=False,
                    )
                    next_version = billing_db.query(RenderedClip).filter(RenderedClip.shot_id == shot_id).count() + 1
                    clip = RenderedClip(
                        shot_id=shot_id,
                        job_id=db_job.id,
                        video_path=_to_video_url(video_path_abs),
                        duration_seconds=duration_seconds,
                        resolution=aspect_ratio,
                        version=next_version,
                        is_active=True,
                        source_storyboard_asset_id=db_job.source_storyboard_asset_id,
                    )
                    billing_db.add(clip)
                db_job.status = "succeeded"
                db_job.progress = 100
                db_job.completed_at = datetime.datetime.utcnow()
                shot.status = "ready"
                shot.updated_at = datetime.datetime.utcnow()
                _settle_video_billing(
                    billing_db,
                    job=db_job,
                    usage_event_id=billing_usage_event_id,
                    video_seconds=duration_seconds,
                    commit=False,
                )
                billing_db.commit()
                billing_db.refresh(clip)
                return {
                    **submit_result,
                    "status": "succeeded",
                    "progress": 100,
                    "video_path": clip.video_path,
                    "clip_id": clip.id,
                }
            finally:
                billing_db.close()

        await asyncio.sleep(3)

    raise TimeoutError("视频生成超时")


# ── 章节视频工作流 API ────────────────────────────────────


@router.post("/api/video/chapter-workflows", response_model=ChapterVideoWorkflowOut)
async def api_create_chapter_workflow(
    body: ChapterVideoWorkflowCreate,
    request: Request,
    db: Session = Depends(get_db),
):
    """创建并启动章节视频工作流。"""
    user = _require_user(request, db)
    chapter = _require_chapter_for_user(body.chapter_id, user, db)

    # 若未传入参考图 ID，从角色库默认版本自动填充
    ref_ids = body.character_reference_ids
    if not ref_ids:
        ref_ids = _get_story_character_reference_asset_ids(chapter.story_id, db)
    if ref_ids:
        _require_reference_assets_for_story(ref_ids, chapter.story_id, db)

    # 创建工作流
    wf = create_chapter_workflow(
        chapter_id=body.chapter_id,
        story_id=chapter.story_id,
        source_text=chapter.novel_content or "",
        character_reference_ids=ref_ids,
        video_style=body.video_style,
        style_reference_image_url=body.style_reference_image_url,
    )

    # 不自动启动后台工作流，由前端控制每个阶段（拆镜→故事版→视频）
    # 前端会单独调用 /parse、/generate-storyboards、/generate-videos 端点

    refreshed_workflow = get_chapter_workflow(wf.id)
    return refreshed_workflow or wf


@router.get("/api/video/chapter-workflows/{workflow_id}", response_model=ChapterVideoWorkflowOut)
async def api_get_chapter_workflow(
    workflow_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """获取章节视频工作流详情（含所有 shots）。"""
    user = _require_user(request, db)
    wf = get_chapter_workflow(workflow_id)
    if not wf:
        raise HTTPException(404, "工作流不存在")

    # 验证所有权
    story = db.get(Story, wf.story_id)
    if not story or story.owner_user_id != user.id:
        raise HTTPException(403, "无权访问此工作流")

    return wf


@router.post("/api/video/chapter-workflows/{workflow_id}/shots", response_model=ChapterVideoShotOut)
async def api_create_chapter_workflow_shot(
    workflow_id: int,
    body: ChapterVideoShotCreate,
    request: Request,
    db: Session = Depends(get_db),
):
    """在章节视频工作流末尾手动添加一个分镜。"""
    user = _require_user(request, db)
    workflow = db.get(ChapterVideoWorkflow, workflow_id)
    if not workflow:
        raise HTTPException(404, "工作流不存在")

    story = db.get(Story, workflow.story_id)
    if not story or story.owner_user_id != user.id:
        raise HTTPException(403, "无权访问此工作流")

    summary = body.story_summary.strip()
    if not summary:
        raise HTTPException(422, "镜头情节不能为空")

    active_statuses = {
        "parsing_shots",
        "generating_details",
        "generating_storyboards",
        "generating_videos",
        "reanalyzing_prompts",
    }
    if workflow.workflow_status in active_statuses:
        raise HTTPException(409, "工作流任务执行中，暂时无法添加镜头")

    shot_query = db.query(ChapterVideoShot).filter(ChapterVideoShot.workflow_id == workflow_id)
    max_index = db.query(sa_func.max(ChapterVideoShot.shot_index)).filter(
        ChapterVideoShot.workflow_id == workflow_id
    ).scalar() or 0
    shot = ChapterVideoShot(
        workflow_id=workflow_id,
        shot_index=max_index + 1,
        source_text_span=(body.source_text_span or summary).strip(),
        scene_location=(body.scene_location or "").strip() or None,
        time_of_day=(body.time_of_day or "").strip() or None,
        characters=[name.strip() for name in body.characters if name.strip()],
        story_summary=summary,
        dialogue_or_narration=(body.dialogue_or_narration or "").strip() or None,
        camera_plan=(body.camera_plan or "").strip() or None,
        motion_plan=(body.motion_plan or "").strip() or None,
        emotion_plan=(body.emotion_plan or "").strip() or None,
        continuity_notes=(body.continuity_notes or "").strip() or None,
        character_reference_ids=list(workflow.character_reference_ids or []),
        storyboard_prompt_stale=False,
        status="pending",
    )
    db.add(shot)
    workflow.total_shots = shot_query.count() + 1
    workflow.completed_shots = shot_query.filter(ChapterVideoShot.status == "video_ready").count()
    workflow.failed_shots = shot_query.filter(ChapterVideoShot.status == "failed").count()
    workflow.workflow_status = "shots_ready"
    workflow.error_message = None
    db.commit()
    db.refresh(shot)
    return shot


@router.get("/api/video/chapter-workflows/by-chapter/{chapter_id}", response_model=ChapterVideoWorkflowListOut)
async def api_list_chapter_workflows(
    chapter_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """获取章节的所有视频工作流。"""
    user = _require_user(request, db)
    chapter = _require_chapter_for_user(chapter_id, user, db)

    workflows = get_chapter_workflows(chapter_id)
    validated: list[ChapterVideoWorkflowOut] = []
    for w in workflows:
        try:
            validated.append(ChapterVideoWorkflowOut.model_validate(w))
        except Exception as exc:
            logger.warning("工作流 %s 数据验证失败（跳过）: %s", w.id, exc)
    return ChapterVideoWorkflowListOut(
        workflows=validated,
        total=len(validated),
    )


@router.get("/api/video/chapter-workflows/{workflow_id}/status", response_model=ChapterVideoWorkflowStatusOut)
async def api_get_chapter_workflow_status(
    workflow_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """获取工作流轻量状态（不含 shots 详情）。"""
    user = _require_user(request, db)
    wf = get_chapter_workflow(workflow_id)
    if not wf:
        raise HTTPException(404, "工作流不存在")

    story = db.get(Story, wf.story_id)
    if not story or story.owner_user_id != user.id:
        raise HTTPException(403, "无权访问")

    latest_task = _latest_chapter_workflow_task(db, workflow_id)
    task_fields = _flatten_background_task(latest_task)
    workflow_status = wf.workflow_status
    error_message = wf.error_message
    active_statuses = {
        "parsing_shots",
        "generating_details",
        "generating_storyboards",
        "generating_videos",
        "reanalyzing_prompts",
    }
    if (
        workflow_status in active_statuses
        and task_fields.get("task_status") in {"failed", "cancelled", "canceled"}
    ):
        workflow_status = "failed"
        error_message = task_fields.get("error_message") or task_fields.get("message") or "后台任务失败"
        persisted_wf = db.get(ChapterVideoWorkflow, workflow_id)
        if persisted_wf:
            persisted_wf.workflow_status = workflow_status
            persisted_wf.error_message = error_message
            db.commit()

    message = task_fields.get("message") or error_message
    if not message:
        status_messages = {
            "pending": "等待开始",
            "parsing_shots": "正在拆解章节分镜...",
            "shots_ready": "分镜已准备好",
            "generating_details": "正在补全镜头细节...",
            "generating_storyboards": "正在生成故事版图片...",
            "storyboards_ready": "故事版已准备好",
            "generating_videos": "正在生成镜头视频...",
            "videos_ready": "镜头视频已准备好",
            "completed": "章节视频已完成",
            "failed": "章节视频任务已失败",
        }
        message = status_messages.get(workflow_status, workflow_status)

    return ChapterVideoWorkflowStatusOut(
        id=wf.id,
        chapter_id=wf.chapter_id,
        workflow_status=workflow_status,
        total_shots=wf.total_shots,
        completed_shots=wf.completed_shots,
        failed_shots=wf.failed_shots,
        error_message=error_message,
        task_id=task_fields.get("task_id"),
        stage=task_fields.get("stage") or workflow_status,
        message=message,
        retry_count=task_fields.get("retry_count", 0),
        max_retries=task_fields.get("max_retries", 0),
        next_retry_at=task_fields.get("next_retry_at"),
    )


@router.post("/api/video/chapter-workflows/{workflow_id}/cancel")
async def api_cancel_chapter_workflow(
    workflow_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """取消运行中的章节视频工作流。"""
    user = _require_user(request, db)
    wf = get_chapter_workflow(workflow_id)
    if not wf:
        raise HTTPException(404, "工作流不存在")

    story = db.get(Story, wf.story_id)
    if not story or story.owner_user_id != user.id:
        raise HTTPException(403, "无权访问")

    task_ids = task_manager.request_cancellation_by_prefix(f"chapter_video_{workflow_id}_")
    latest_task = _latest_chapter_workflow_task(db, workflow_id)
    if latest_task and latest_task.task_id not in task_ids:
        task_manager.request_cancellation(latest_task.task_id)
        task_ids.append(latest_task.task_id)
    if latest_task:
        meta = latest_task.metadata_json if isinstance(latest_task.metadata_json, dict) else {}
        latest_task.metadata_json = {
            **meta,
            "stage": "cancelled",
            "message": "用户已请求取消章节视频工作流",
            "next_retry_at": None,
        }
        db.commit()
    update_chapter_workflow_status(workflow_id, "failed", "用户取消")
    return {"ok": True, "message": "已请求取消章节视频工作流", "task_ids": task_ids}


@router.post("/api/video/chapter-workflows/shots/{shot_id}/regenerate-storyboard")
async def api_regenerate_shot_storyboard(
    shot_id: int,
    body: RegenerateShotRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """重新生成单镜头的故事版图片。"""
    user = _require_user(request, db)
    shot = db.get(ChapterVideoShot, shot_id)
    if not shot:
        raise HTTPException(404, "镜头不存在")

    wf = get_chapter_workflow(shot.workflow_id)
    if not wf:
        raise HTTPException(404, "工作流不存在")

    story = db.get(Story, wf.story_id)
    if not story or story.owner_user_id != user.id:
        raise HTTPException(403, "无权访问")

    api_key = _user_image_api_key(request)
    _configure_image_service_from_db(request, db)
    ref_asset_ids = body.reference_asset_ids or None
    if ref_asset_ids:
        _require_reference_assets_for_story(ref_asset_ids, wf.story_id, db)
    _check_and_consume_quota_wrapper(user.id, "manga.image.generate.monthly_limit", 1, db, deduct=False)
    updated_shot = await regenerate_shot_storyboard(
        shot_id,
        api_key,
        body.prompt_override,
        ref_asset_ids=ref_asset_ids,
    )

    if not updated_shot:
        raise HTTPException(500, "重新生成故事版失败")

    _check_and_consume_quota_wrapper(user.id, "manga.image.generate.monthly_limit", 1, db, deduct=True)
    return ChapterVideoShotOut.model_validate(updated_shot)


@router.post("/api/video/chapter-workflows/shots/{shot_id}/clear-storyboard")
async def api_clear_shot_storyboard(
    shot_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """清除镜头故事版图片。"""
    user = _require_user(request, db)
    shot = db.get(ChapterVideoShot, shot_id)
    if not shot:
        raise HTTPException(404, "镜头不存在")
    wf = get_chapter_workflow(shot.workflow_id)
    if not wf:
        raise HTTPException(404, "工作流不存在")
    story = db.get(Story, wf.story_id)
    if not story or story.owner_user_id != user.id:
        raise HTTPException(403, "无权访问")

    from services.oss import delete_by_url
    delete_by_url(shot.storyboard_image_url)
    shot.storyboard_image_url = None
    shot.status = "pending"
    db.commit()
    db.refresh(shot)
    return {"ok": True, "shot": ChapterVideoShotOut.model_validate(shot)}


@router.post("/api/video/chapter-workflows/shots/{shot_id}/clear-video")
async def api_clear_shot_video(
    shot_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """清除镜头视频。"""
    user = _require_user(request, db)
    shot = db.get(ChapterVideoShot, shot_id)
    if not shot:
        raise HTTPException(404, "镜头不存在")
    wf = get_chapter_workflow(shot.workflow_id)
    if not wf:
        raise HTTPException(404, "工作流不存在")
    story = db.get(Story, wf.story_id)
    if not story or story.owner_user_id != user.id:
        raise HTTPException(403, "无权访问")

    from services.oss import delete_by_url
    delete_by_url(shot.video_url)
    shot.video_url = None
    shot.status = "storyboard_ready"
    db.commit()
    db.refresh(shot)
    return {"ok": True, "shot": ChapterVideoShotOut.model_validate(shot)}


@router.post("/api/video/chapter-workflows/shots/{shot_id}/regenerate-video")
async def api_regenerate_shot_video(
    shot_id: int,
    body: RegenerateShotRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    shot = db.get(ChapterVideoShot, shot_id)
    if not shot:
        raise HTTPException(404, "镜头不存在")

    wf = get_chapter_workflow(shot.workflow_id)
    if not wf:
        raise HTTPException(404, "工作流不存在")

    story = db.get(Story, wf.story_id)
    if not story or story.owner_user_id != user.id:
        raise HTTPException(403, "无权访问")

    regen_duration = max(
        1,
        min(
            MAX_VIDEO_DURATION_SECONDS,
            int(
                getattr(body, "duration_seconds", None)
                or getattr(shot, "duration_seconds", None)
                or DEFAULT_VIDEO_DURATION_SECONDS
            ),
        ),
    )
    _configure_video_service_from_db(request, db)
    deepseek_api_key = _user_deepseek_api_key(request, db)

    api_key, base_url, model = _user_video_api_key(request)
    video_capabilities = _current_video_capabilities(request, db, model)
    adapter_type = _current_video_adapter_type(request)
    ref_asset_ids = body.reference_asset_ids or None
    if ref_asset_ids:
        _require_reference_assets_for_story(ref_asset_ids, wf.story_id, db)
    try:
        _validate_video_request_before_billing(
            adapter_type=adapter_type,
            model=model,
            video_capabilities=video_capabilities,
            aspect_ratio=body.aspect_ratio or "16:9",
            duration_seconds=regen_duration,
            reference_count=_chapter_video_reference_count(shot, wf, ref_asset_ids, db),
        )
    except ValueError as exc:
        if "时长" in str(exc):
            raise HTTPException(400, str(exc)) from exc
        raise
    quota_result = _reserve_video_billing(
        request,
        db,
        user_id=user.id,
        video_seconds=regen_duration,
    )
    try:
        updated_shot = await regenerate_shot_video(shot_id, api_key, body.prompt_override, ref_asset_ids=ref_asset_ids, base_url=base_url, model=model, deepseek_api_key=deepseek_api_key, aspect_ratio=body.aspect_ratio or "16:9", video_capabilities=video_capabilities, adapter_type=adapter_type, duration_seconds=regen_duration)
    except UpstreamServiceError as exc:
        _refund_video_billing(
            db,
            usage_event_id=quota_result.get("usage_event_id"),
            reason="regenerate_upstream_failed",
        )
        logger.warning("Regenerate shot video upstream failed: shot_id=%s provider=%s err=%s", shot_id, exc.provider, exc)
        raise HTTPException(502, str(exc))
    except Exception as exc:
        _refund_video_billing(
            db,
            usage_event_id=quota_result.get("usage_event_id"),
            reason="regenerate_failed",
        )
        if "视频 API 地址未配置" in str(exc) or "视频生成模型未配置" in str(exc):
            raise HTTPException(400, str(exc))
        raise

    if not updated_shot:
        _refund_video_billing(
            db,
            usage_event_id=quota_result.get("usage_event_id"),
            reason="regenerate_empty_result",
        )
        raise HTTPException(500, "重新生成视频失败")

    _settle_video_billing(
        db,
        usage_event_id=quota_result.get("usage_event_id"),
        video_seconds=regen_duration,
    )

    return ChapterVideoShotOut.model_validate(updated_shot)


@router.post("/api/video/chapter-workflows/shots/{shot_id}/save-prompts")
async def api_save_shot_prompts(
    shot_id: int,
    body: dict,
    request: Request,
    db: Session = Depends(get_db),
):
    """保存镜头的手动编辑提示词。"""
    user = _require_user(request, db)
    shot = db.get(ChapterVideoShot, shot_id)
    if not shot:
        raise HTTPException(404, "镜头不存在")
    wf = get_chapter_workflow(shot.workflow_id)
    if not wf:
        raise HTTPException(404, "工作流不存在")
    story = db.get(Story, wf.story_id)
    if not story or story.owner_user_id != user.id:
        raise HTTPException(403, "无权访问")

    if "storyboard_prompt" in body:
        shot.storyboard_prompt = body["storyboard_prompt"]
        shot.storyboard_prompt_stale = False
        shot.storyboard_generation_token = None
    if "video_prompt" in body:
        shot.video_prompt = body["video_prompt"]
    db.commit()
    db.refresh(shot)
    return {"ok": True, "shot": ChapterVideoShotOut.model_validate(shot)}


@router.get("/api/video/chapter-workflows/shots/{shot_id}/preview-video-prompt")
async def api_preview_video_prompt(
    shot_id: int,
    reference_asset_ids: str = Query(default="", description="逗号分隔的参考资产 ID"),
    prompt_override: str | None = Query(default=None, description="用户编辑的 prompt 覆写"),
    request: Request = None,
    db: Session = Depends(get_db),
):
    """预览组装后的视频提示词（不提交生成）。"""
    user = _require_user(request, db)
    shot = db.get(ChapterVideoShot, shot_id)
    if not shot:
        raise HTTPException(404, "镜头不存在")
    wf = get_chapter_workflow(shot.workflow_id)
    if not wf:
        raise HTTPException(404, "工作流不存在")
    story = db.get(Story, wf.story_id)
    if not story or story.owner_user_id != user.id:
        raise HTTPException(403, "无权访问")

    ref_ids = None
    if reference_asset_ids:
        try:
            ref_ids = [int(x) for x in reference_asset_ids.split(",") if x.strip()]
        except ValueError:
            raise HTTPException(400, "reference_asset_ids 格式无效")

    result = assemble_video_prompt_text(shot_id, ref_asset_ids=ref_ids, prompt_override=prompt_override)
    return result


@router.post("/api/video/chapter-workflows/shots/{shot_id}/reanalyze-prompts")
async def api_reanalyze_shot_prompts(
    shot_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """重新分析单镜头的全部提示词。"""
    user = _require_user(request, db)
    shot = db.get(ChapterVideoShot, shot_id)
    if not shot:
        raise HTTPException(404, "镜头不存在")

    wf = get_chapter_workflow(shot.workflow_id)
    if not wf:
        raise HTTPException(404, "工作流不存在")

    story = db.get(Story, wf.story_id)
    if not story or story.owner_user_id != user.id:
        raise HTTPException(403, "无权访问")

    deepseek_api_key = _user_deepseek_api_key(request, db)
    _check_and_consume_quota_wrapper(
        user.id,
        "ai.text.advanced_calls.monthly_limit",
        1,
        db,
        deduct=False,
        request=request,
        provider_kind="text",
    )
    try:
        result = await reanalyze_shot_prompts(shot_id, deepseek_api_key=deepseek_api_key)
    except Exception as exc:
        raise HTTPException(500, f"重新分析失败: {exc}")

    _check_and_consume_quota_wrapper(
        user.id,
        "ai.text.advanced_calls.monthly_limit",
        1,
        db,
        deduct=True,
        request=request,
        provider_kind="text",
    )

    return result


@router.post("/api/video/chapter-workflows/shots/{shot_id}/upload-storyboard")
async def api_upload_shot_storyboard(
    shot_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """上传本地图片替换镜头的故事版图片。"""
    user = _require_user(request, db)
    shot = db.get(ChapterVideoShot, shot_id)
    if not shot:
        raise HTTPException(404, "镜头不存在")
    wf = get_chapter_workflow(shot.workflow_id)
    if not wf:
        raise HTTPException(404, "工作流不存在")
    story = db.get(Story, wf.story_id)
    if not story or story.owner_user_id != user.id:
        raise HTTPException(403, "无权访问")

    content_type = request.headers.get("content-type", "")
    if "multipart/form-data" not in content_type:
        raise HTTPException(400, "Expected multipart/form-data upload")
    form = await request.form()
    uploaded = form.get("file")
    if uploaded is None or not hasattr(uploaded, "filename"):
        raise HTTPException(400, "No file uploaded")

    filename = getattr(uploaded, "filename", "") or "storyboard.png"
    data = await uploaded.read()
    output_dir = _VIDEO_OUTPUTS_DIR / f"storyboard_{shot_id}"
    output_dir.mkdir(parents=True, exist_ok=True)
    ext = Path(filename).suffix or ".png"
    output_path = output_dir / f"uploaded_{datetime.datetime.utcnow().strftime('%Y%m%d_%H%M%S')}{ext}"
    await run_blocking(output_path.write_bytes, data)
    rel_path = str(output_path.relative_to(_VIDEO_OUTPUTS_DIR.resolve()))
    shot.storyboard_image_url = f"/static/video/{rel_path}"

    # OSS 上传（如已配置，上传成功后更新 URL 并删除本地文件）
    from services.oss import upload_and_cleanup as _oss_upload
    oss_url = await run_blocking(_oss_upload, str(output_path))
    if oss_url:
        shot.storyboard_image_url = oss_url

    asset = _build_chapter_storyboard_asset(
        workflow=wf,
        shot=shot,
        file_path=shot.storyboard_image_url or "",
        prompt=shot.storyboard_prompt,
        provider="manual_upload",
        source_asset_ids=None,
        source_type="manual_upload",
    )
    db.add(asset)
    shot.status = "storyboard_ready"
    db.commit()
    db.refresh(shot)
    return ChapterVideoShotOut.model_validate(shot)


@router.post("/api/video/chapter-workflows/shots/{shot_id}/upload-video")
async def api_upload_shot_video(
    shot_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """上传本地视频替换镜头的视频。"""
    user = _require_user(request, db)
    shot = db.get(ChapterVideoShot, shot_id)
    if not shot:
        raise HTTPException(404, "镜头不存在")
    wf = get_chapter_workflow(shot.workflow_id)
    if not wf:
        raise HTTPException(404, "工作流不存在")
    story = db.get(Story, wf.story_id)
    if not story or story.owner_user_id != user.id:
        raise HTTPException(403, "无权访问")

    content_type = request.headers.get("content-type", "")
    if "multipart/form-data" not in content_type:
        raise HTTPException(400, "Expected multipart/form-data upload")
    form = await request.form()
    uploaded = form.get("file")
    if uploaded is None or not hasattr(uploaded, "filename"):
        raise HTTPException(400, "No file uploaded")

    filename = getattr(uploaded, "filename", "") or "video.mp4"
    data = await uploaded.read()
    output_dir = _VIDEO_OUTPUTS_DIR / f"video_{shot_id}"
    output_dir.mkdir(parents=True, exist_ok=True)
    ext = Path(filename).suffix or ".mp4"
    output_path = output_dir / f"uploaded_{datetime.datetime.utcnow().strftime('%Y%m%d_%H%M%S')}{ext}"
    await run_blocking(output_path.write_bytes, data)
    rel_path = str(output_path.relative_to(_VIDEO_OUTPUTS_DIR.resolve()))
    shot.video_url = f"/static/video/{rel_path}"

    # OSS 上传（如已配置，上传成功后更新 URL 并删除本地文件）
    from services.oss import upload_and_cleanup as _oss_upload
    oss_url = await run_blocking(_oss_upload, str(output_path))
    if oss_url:
        shot.video_url = oss_url

    shot.status = "video_ready"
    db.commit()
    db.refresh(shot)
    return ChapterVideoShotOut.model_validate(shot)


@router.post("/api/video/chapter-workflows/{workflow_id}/storyboards/reanalyze-prompt")
async def api_reanalyze_storyboard_prompts(
    workflow_id: int,
    body: dict,
    request: Request,
    db: Session = Depends(get_db),
):
    """重新分析故事版提示词。"""
    user = _require_user(request, db)
    wf = get_chapter_workflow(workflow_id)
    if not wf:
        raise HTTPException(404, "工作流不存在")

    story = db.get(Story, wf.story_id)
    if not story or story.owner_user_id != user.id:
        raise HTTPException(403, "无权访问")

    deepseek_api_key = _user_deepseek_api_key(request, db)
    shot_ids = body.get("shot_ids")
    if not shot_ids:
        raise HTTPException(400, "请指定至少一个镜头")
    quota_result, billing_ctx = _reserve_text_billing(
        request,
        db,
        user_id=user.id,
    )

    task_id = f"chapter_video_{workflow_id}_reanalyze_{uuid.uuid4().hex[:8]}"

    update_chapter_workflow_status(workflow_id, "reanalyzing_prompts")

    try:
        await task_manager.submit_task(
            task_id=task_id,
            task_type="chapter_video_reanalyze",
            coro_func=_run_billed_text_task,
            billed_coro=reanalyze_storyboard_prompts,
            billing_ctx=billing_ctx,
            workflow_id=workflow_id,
            shot_ids=shot_ids,
            deepseek_api_key=deepseek_api_key,
            timeout=300.0,
            max_retries=1,
            quota_user_id=user.id,
            quota_feature_key="ai.text.advanced_calls.monthly_limit",
            quota_amount=1,
            quota_usage_event_id=quota_result.get("usage_event_id"),
        )
    except Exception as exc:
        import main as main_mod

        main_mod._finish_streaming_platform_points(
            billing_ctx,
            success=False,
            error_code="task_submission_failed",
        )
        raise HTTPException(500, f"提交后台任务失败: {exc}")

    return {
        "task_id": task_id,
        "workflow_status": "reanalyzing_prompts",
        "message": "提示词重新分析任务已提交后台执行",
    }


@router.post("/api/video/chapter-workflows/{workflow_id}/reset")
async def api_reset_chapter_workflow(
    workflow_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """重置工作流：清除所有镜头和故事版/视频数据，回到初始状态。"""
    user = _require_user(request, db)
    wf = get_chapter_workflow(workflow_id)
    if not wf:
        raise HTTPException(404, "工作流不存在")
    story = db.get(Story, wf.story_id)
    if not story or story.owner_user_id != user.id:
        raise HTTPException(403, "无权访问")

    from models import ChapterVideoShot
    db.query(ChapterVideoShot).filter(ChapterVideoShot.workflow_id == workflow_id).delete()
    update_chapter_workflow_status(workflow_id, "pending")
    wf.total_shots = 0
    wf.completed_shots = 0
    wf.failed_shots = 0
    wf.error_message = None
    db.commit()

    return {"ok": True, "workflow_status": "pending"}


@router.post("/api/video/chapter-workflows/{workflow_id}/concat")
async def api_concat_chapter_videos(
    workflow_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """拼接工作流中所有已完成镜头的视频为完整的章节视频。"""
    user = _require_user(request, db)
    wf = get_chapter_workflow(workflow_id)
    if not wf:
        raise HTTPException(404, "工作流不存在")
    story = db.get(Story, wf.story_id)
    if not story or story.owner_user_id != user.id:
        raise HTTPException(403, "无权访问")

    try:
        result = await run_blocking(concat_chapter_videos, workflow_id)
        return result
    except ValueError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        raise HTTPException(500, str(e))


@router.get("/api/video/chapter-workflows/{workflow_id}/consistency")
async def api_check_chapter_consistency(
    workflow_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """检查章节工作流的角色一致性。"""
    user = _require_user(request, db)
    wf = get_chapter_workflow(workflow_id)
    if not wf:
        raise HTTPException(404, "工作流不存在")
    story = db.get(Story, wf.story_id)
    if not story or story.owner_user_id != user.id:
        raise HTTPException(403, "无权访问")

    return validate_character_consistency(workflow_id)


# ── 短剧剧本 API ──────────────────────────────────────────


@router.post("/api/video/chapter-workflows/{workflow_id}/screenplay/generate")
async def api_generate_screenplay(
    workflow_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """生成短剧剧本：读取章节正文，调用 AI 生成影视剧本和场次列表。"""
    user = _require_user(request, db)
    wf = get_chapter_workflow(workflow_id)
    if not wf:
        raise HTTPException(404, "工作流不存在")
    story = db.get(Story, wf.story_id)
    if not story or story.owner_user_id != user.id:
        raise HTTPException(403, "无权访问")

    chapter = db.get(Chapter, wf.chapter_id)
    if not chapter or not (chapter.novel_content or "").strip():
        raise HTTPException(400, "章节正文为空，请先在工作台中生成章节内容后再生成剧本")

    deepseek_api_key = _user_deepseek_api_key(request, db)
    if not deepseek_api_key:
        raise HTTPException(400, "请配置 DeepSeek API Key")
    _check_and_consume_quota_wrapper(
        user.id,
        "ai.text.advanced_calls.monthly_limit",
        1,
        db,
        deduct=False,
        request=request,
        provider_kind="text",
    )

    result = await generate_workflow_screenplay(
        workflow_id=workflow_id,
        deepseek_api_key=deepseek_api_key,
    )
    _check_and_consume_quota_wrapper(
        user.id,
        "ai.text.advanced_calls.monthly_limit",
        1,
        db,
        deduct=True,
        request=request,
        provider_kind="text",
    )
    return result


@router.put("/api/video/chapter-workflows/{workflow_id}/screenplay")
async def api_save_screenplay(
    workflow_id: int,
    body: dict,
    request: Request,
    db: Session = Depends(get_db),
):
    """保存/编辑短剧剧本：手动更新 screenplay_text 和 screenplay_json。"""
    user = _require_user(request, db)
    wf = get_chapter_workflow(workflow_id)
    if not wf:
        raise HTTPException(404, "工作流不存在")
    story = db.get(Story, wf.story_id)
    if not story or story.owner_user_id != user.id:
        raise HTTPException(403, "无权访问")

    screenplay_text = str(body.get("screenplay_text", "") or "").strip()
    screenplay_json = body.get("screenplay_json")

    if not screenplay_text:
        raise HTTPException(400, "screenplay_text 不能为空")

    wf_in_db = db.get(ChapterVideoWorkflow, workflow_id)
    if not wf_in_db:
        raise HTTPException(404, "工作流不存在")

    wf_in_db.screenplay_text = screenplay_text
    wf_in_db.screenplay_json = screenplay_json
    wf_in_db.screenplay_status = "draft"
    wf_in_db.screenplay_version = (wf_in_db.screenplay_version or 0) + 1
    wf_in_db.screenplay_updated_at = datetime.datetime.now(datetime.timezone.utc)
    db.commit()
    db.refresh(wf_in_db)

    return {
        "screenplay_text": wf_in_db.screenplay_text,
        "screenplay_json": wf_in_db.screenplay_json,
        "screenplay_status": wf_in_db.screenplay_status,
        "screenplay_version": wf_in_db.screenplay_version,
        "screenplay_updated_at": wf_in_db.screenplay_updated_at.isoformat() if wf_in_db.screenplay_updated_at else None,
    }


@router.post("/api/video/chapter-workflows/{workflow_id}/screenplay/approve")
async def api_approve_screenplay(
    workflow_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """批准短剧剧本：将剧本状态设为 approved，后续拆镜等操作需要批准状态。"""
    user = _require_user(request, db)
    wf = get_chapter_workflow(workflow_id)
    if not wf:
        raise HTTPException(404, "工作流不存在")
    story = db.get(Story, wf.story_id)
    if not story or story.owner_user_id != user.id:
        raise HTTPException(403, "无权访问")

    if not (wf.screenplay_text or "").strip():
        raise HTTPException(400, "剧本内容为空，请先生成或编辑剧本后再批准")

    wf_in_db = db.get(ChapterVideoWorkflow, workflow_id)
    if not wf_in_db:
        raise HTTPException(404, "工作流不存在")

    wf_in_db.screenplay_status = "approved"
    wf_in_db.screenplay_approved_at = datetime.datetime.now(datetime.timezone.utc)
    db.commit()
    db.refresh(wf_in_db)

    return {
        "screenplay_status": wf_in_db.screenplay_status,
        "screenplay_approved_at": wf_in_db.screenplay_approved_at.isoformat() if wf_in_db.screenplay_approved_at else None,
        "message": "剧本已批准",
    }


@router.post("/api/video/chapter-workflows/{workflow_id}/screenplay/regenerate")
async def api_regenerate_screenplay(
    workflow_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """重新生成短剧剧本：重新调用 AI 生成，状态设为 draft（不自动批准）。"""
    user = _require_user(request, db)
    wf = get_chapter_workflow(workflow_id)
    if not wf:
        raise HTTPException(404, "工作流不存在")
    story = db.get(Story, wf.story_id)
    if not story or story.owner_user_id != user.id:
        raise HTTPException(403, "无权访问")

    chapter = db.get(Chapter, wf.chapter_id)
    if not chapter or not (chapter.novel_content or "").strip():
        raise HTTPException(400, "章节正文为空，请先在工作台中生成章节内容后再重新生成剧本")

    deepseek_api_key = _user_deepseek_api_key(request, db)
    if not deepseek_api_key:
        raise HTTPException(400, "请配置 DeepSeek API Key")
    _check_and_consume_quota_wrapper(
        user.id,
        "ai.text.advanced_calls.monthly_limit",
        1,
        db,
        deduct=False,
        request=request,
        provider_kind="text",
    )

    result = await generate_workflow_screenplay(
        workflow_id=workflow_id,
        deepseek_api_key=deepseek_api_key,
    )
    _check_and_consume_quota_wrapper(
        user.id,
        "ai.text.advanced_calls.monthly_limit",
        1,
        db,
        deduct=True,
        request=request,
        provider_kind="text",
    )
    return result


# ── 阶段 API ────────────────────────────────────────────


@router.post("/api/video/chapter-workflows/{workflow_id}/parse")
async def api_parse_chapter_shots(
    workflow_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """阶段1-拆镜：将章节正文解析为 10s 镜头列表，停在 shots_ready。"""
    user = _require_user(request, db)
    wf = get_chapter_workflow(workflow_id)
    if not wf:
        raise HTTPException(404, "工作流不存在")
    story = db.get(Story, wf.story_id)
    if not story or story.owner_user_id != user.id:
        raise HTTPException(403, "无权访问")

    if getattr(wf, "screenplay_status", "approved") != "approved":
        raise HTTPException(409, "请先批准剧本后再执行拆镜操作")

    if wf.workflow_status == "parsing_shots":
        raise HTTPException(400, "当前工作流正在拆镜中，请稍候刷新结果")

    if wf.workflow_status not in ("pending", "shots_ready", "failed"):
        raise HTTPException(400, f"当前状态 {wf.workflow_status} 不允许拆镜操作")

    deepseek_api_key = _user_deepseek_api_key(request, db)
    if not deepseek_api_key:
        raise HTTPException(400, "请配置 DeepSeek API Key")

    # 从 DB 读取最新章节内容（替代工作流创建时的快照）
    chapter = db.get(Chapter, wf.chapter_id)
    current_source_text = (chapter.novel_content or "").strip() if chapter else ""

    # 如果剧本已批准，优先使用剧本作为拆镜输入源
    wf_in_db = db.get(ChapterVideoWorkflow, workflow_id)
    if wf_in_db and getattr(wf_in_db, "screenplay_status", None) == "approved":
        screenplay_source = build_shot_source_from_screenplay(wf_in_db)
        if screenplay_source.strip():
            current_source_text = screenplay_source
            logger.info("拆镜使用已批准剧本作为输入源 workflow=%s", workflow_id)

    if not current_source_text:
        raise HTTPException(400, "章节正文为空，请先在工作台中生成章节内容后再拆镜")

    # 同步更新工作流 source_text，确保后续阶段（补全提示词等）使用一致内容
    if wf_in_db:
        if wf_in_db.source_text != current_source_text:
            wf_in_db.source_text = current_source_text
        # 刷新角色参考图 asset_id：当 workflow 创建时可能尚无参考图，
        # 但用户在第一章已生成后，这里需要从 DB 重新获取最新数据
        if not wf_in_db.character_reference_ids:
            fresh_ref_ids = _get_story_character_reference_asset_ids(wf_in_db.story_id, db)
            if fresh_ref_ids:
                wf_in_db.character_reference_ids = fresh_ref_ids
                logger.info("拆镜前刷新角色参考图 asset_ids=%s", fresh_ref_ids)
        # 刷新风格：用户可能在重置工作流后更换了章节风格预设，或创建时未选风格
        if chapter and getattr(chapter, "video_style_preset_id", None):
            preset = db.get(VideoStylePreset, chapter.video_style_preset_id)
            if preset and preset.name != wf_in_db.video_style:
                wf_in_db.video_style = preset.name
                logger.info("拆镜前刷新工作流风格 %s -> %s", wf_in_db.video_style, preset.name)
        db.commit()

    # 拆镜使用文本模型：先冻结积分，后台成功后按真实 token 结算。
    quota_result = _check_and_consume_quota_wrapper(
        user.id,
        "video.shot.split.monthly_limit",
        1,
        db,
        deduct=False,
    )
    import main as main_mod

    billing_ctx = main_mod._detach_pending_platform_points(
        request,
        quota_result.get("usage_event_id"),
    )

    task_id = f"chapter_video_{workflow_id}_stage_{uuid.uuid4().hex[:8]}"

    update_chapter_workflow_status(workflow_id, "parsing_shots")
    try:
        await task_manager.submit_task(
            task_id=task_id,
            task_type="chapter_video_parse",
            coro_func=parse_chapter_shots,
            workflow_id=workflow_id,
            chapter_id=wf.chapter_id,
            story_id=wf.story_id,
            source_text=current_source_text,
            deepseek_api_key=deepseek_api_key,
            billing_ctx=billing_ctx,
            timeout=None,
            max_retries=1,
            quota_user_id=user.id,
            quota_feature_key="video.shot.split.monthly_limit",
            quota_amount=1,
            quota_usage_event_id=quota_result.get("usage_event_id"),
            metadata={
                "workflow_id": workflow_id,
                "stage": "parsing_shots",
                "message": "拆镜任务已提交后台执行...",
                "running_stage": "parsing_shots",
                "running_message": "正在拆解章节分镜...",
            },
        )
        main_mod._detach_pending_platform_points(request, quota_result.get("usage_event_id"))
    except Exception as exc:
        error_message = f"提交后台任务失败: {public_error_message(exc)}"
        update_chapter_workflow_status(workflow_id, "failed", error_message)
        refund_db = SessionLocal()
        try:
            task_manager.refund_quota(
                user.id,
                "video.shot.split.monthly_limit",
                1,
                refund_db,
                usage_event_id=quota_result.get("usage_event_id"),
            )
            refund_db.commit()
        finally:
            refund_db.close()
        raise HTTPException(500, error_message)

    return {
        "task_id": task_id,
        "workflow_status": "parsing_shots",
        "message": "拆镜任务已提交后台执行",
    }


@router.post("/api/video/chapter-workflows/{workflow_id}/generate-details")
async def api_generate_shot_details(
    workflow_id: int,
    body: ChapterWorkflowStageActionRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """批量生成镜头详情：为选中的镜头生成运镜/动作/情绪/故事版等详细信息。"""
    user = _require_user(request, db)
    wf = get_chapter_workflow(workflow_id)
    if not wf:
        raise HTTPException(404, "工作流不存在")
    story = db.get(Story, wf.story_id)
    if not story or story.owner_user_id != user.id:
        raise HTTPException(403, "无权访问")

    if not body.shot_ids:
        raise HTTPException(400, "请选择至少一个镜头")

    if len(body.shot_ids) > 5:
        raise HTTPException(400, f"最多支持 5 个镜头，当前 {len(body.shot_ids)} 个")

    deepseek_api_key = _user_deepseek_api_key(request, db)
    if not deepseek_api_key:
        raise HTTPException(400, "请配置 DeepSeek API Key")
    quota_result, billing_ctx = _reserve_text_billing(
        request,
        db,
        user_id=user.id,
    )

    task_id = f"chapter_video_{workflow_id}_detail_{uuid.uuid4().hex[:8]}"

    update_chapter_workflow_status(workflow_id, "generating_details")

    try:
        await task_manager.submit_task(
            task_id=task_id,
            task_type="chapter_video_generate_details",
            coro_func=_run_billed_text_task,
            billed_coro=generate_shot_details_batch,
            billing_ctx=billing_ctx,
            workflow_id=workflow_id,
            shot_ids=body.shot_ids,
            chapter_text=wf.source_text or "",
            story_id=wf.story_id,
            deepseek_api_key=deepseek_api_key,
            timeout=120.0,
            max_retries=1,
            quota_user_id=user.id,
            quota_feature_key="ai.text.advanced_calls.monthly_limit",
            quota_amount=1,
            quota_usage_event_id=quota_result.get("usage_event_id"),
            metadata={
                "workflow_id": workflow_id,
                "stage": "generating_details",
                "message": "镜头详情生成任务已排队...",
                "running_stage": "generating_details",
                "running_message": "正在生成镜头详情...",
            },
        )
    except Exception as exc:
        import main as main_mod

        main_mod._finish_streaming_platform_points(
            billing_ctx,
            success=False,
            error_code="task_submission_failed",
        )
        raise HTTPException(500, f"提交后台任务失败: {exc}")

    return {
        "task_id": task_id,
        "workflow_status": "generating_details",
        "message": "镜头详情生成任务已提交后台执行",
    }


@router.post("/api/video/chapter-workflows/{workflow_id}/style-reference")
async def api_upload_style_reference(
    workflow_id: int,
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """上传风格参考图到工作流。"""
    user = _require_user(request, db)
    wf = get_chapter_workflow(workflow_id)
    if not wf:
        raise HTTPException(404, "工作流不存在")
    story = db.get(Story, wf.story_id)
    if not story or story.owner_user_id != user.id:
        raise HTTPException(403, "无权访问")

    # 验证文件类型
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(400, "请上传图片文件")

    # 保存文件
    import os
    from datetime import datetime
    upload_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "manga_outputs", "style_references")
    os.makedirs(upload_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    ext = os.path.splitext(file.filename or "ref.png")[1] or ".png"
    filename = f"style_ref_{workflow_id}_{timestamp}{ext}"
    file_path = os.path.join(upload_dir, filename)

    content = await file.read()
    await run_blocking(Path(file_path).write_bytes, content)

    # 更新工作流
    relative_path = f"style_references/{filename}"

    from services import oss as oss_service
    _configure_oss_from_db(db)
    oss_url = await run_blocking(oss_service.upload_file, str(file_path))
    if oss_url:
        logger.info("工作流风格参考图已上传到 OSS: %s", safe_media_url_for_log(oss_url))
        relative_path = oss_url
    else:
        logger.info("工作流风格参考图未上传到 OSS（未配置或上传失败），使用本地路径: %s", relative_path)

    wf.style_reference_image_url = relative_path
    db.commit()

    return {"success": True, "style_reference_image_url": relative_path}


@router.put("/api/video/chapter-workflows/{workflow_id}/style-reference-url")
async def api_update_style_reference_url(
    workflow_id: int,
    body: dict,
    request: Request,
    db: Session = Depends(get_db),
):
    """更新工作流的风格参考图 URL。"""
    user = _require_user(request, db)
    wf = get_chapter_workflow(workflow_id)
    if not wf:
        raise HTTPException(404, "工作流不存在")
    story = db.get(Story, wf.story_id)
    if not story or story.owner_user_id != user.id:
        raise HTTPException(403, "无权访问")

    style_reference_image_url = body.get("style_reference_image_url")
    if "video_style" in body:
        wf.video_style = str(body.get("video_style") or "").strip() or None
    wf.style_reference_image_url = style_reference_image_url
    db.commit()

    return {"success": True, "style_reference_image_url": style_reference_image_url}


@router.post("/api/video/chapter-workflows/{workflow_id}/storyboards")
async def api_generate_storyboards(
    workflow_id: int,
    body: ChapterWorkflowStageActionRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """阶段2-故事版：为指定镜头生成故事版图片。"""
    user = _require_user(request, db)
    wf = get_chapter_workflow(workflow_id)
    if not wf:
        raise HTTPException(404, "工作流不存在")
    story = db.get(Story, wf.story_id)
    if not story or story.owner_user_id != user.id:
        raise HTTPException(403, "无权访问")

    if wf.workflow_status not in ("shots_ready", "generating_storyboards", "failed"):
        raise HTTPException(400, f"当前状态 {wf.workflow_status} 不允许故事版操作")

    deepseek_api_key = _user_deepseek_api_key(request, db)
    image_api_key = _user_image_api_key(request)

    if not image_api_key:
        raise HTTPException(400, "请配置 Image API Key")

    task_id = f"chapter_video_{workflow_id}_stage_{uuid.uuid4().hex[:8]}"

    # 刷新角色参考图 asset_id：确保使用最新的角色资产（用户在第一章可能已生成）
    ref_ids = wf.character_reference_ids
    if not ref_ids:
        ref_ids = _get_story_character_reference_asset_ids(wf.story_id, db)
        if ref_ids:
            db_wf = db.get(ChapterVideoWorkflow, workflow_id)
            if db_wf:
                db_wf.character_reference_ids = ref_ids
                db.commit()
    if ref_ids:
        _require_reference_assets_for_story(ref_ids, wf.story_id, db)

    try:
        storyboard_conditions = [ChapterVideoShot.workflow_id == workflow_id]
        if body.shot_ids:
            storyboard_conditions.append(ChapterVideoShot.id.in_(body.shot_ids))
        else:
            storyboard_conditions.append(ChapterVideoShot.status == "pending")
        shot_count = db.query(ChapterVideoShot).filter(*storyboard_conditions).count()
    except AttributeError:
        shot_count = len(body.shot_ids or []) or int(getattr(wf, "total_shots", 0) or 0)
    if shot_count <= 0:
        raise HTTPException(400, "没有可生成的故事版镜头")
    quota_result = _check_and_consume_quota_wrapper(
        user.id,
        "manga.image.generate.monthly_limit",
        shot_count,
        db,
        deduct=False,
    )
    import main as main_mod

    update_chapter_workflow_status(workflow_id, "generating_storyboards")

    try:
        await task_manager.submit_task(
            task_id=task_id,
            task_type="chapter_video_storyboards",
            coro_func=_run_billed_media_task,
            billed_coro=generate_storyboards_for_shots,
            billing_usage_event_id=quota_result.get("usage_event_id"),
            billing_modality="image",
            billing_units=shot_count,
            workflow_id=workflow_id,
            story_id=wf.story_id,
            shot_ids=body.shot_ids or None,
            image_api_key=image_api_key,
            deepseek_api_key=deepseek_api_key,
            character_reference_ids=ref_ids,
            timeout=600.0,
            max_retries=1,
            quota_user_id=user.id,
            quota_feature_key="manga.image.generate.monthly_limit",
            quota_amount=shot_count,
            quota_usage_event_id=quota_result.get("usage_event_id"),
            metadata={
                "workflow_id": workflow_id,
                "stage": "generating_storyboards",
                "message": "故事版生成任务已排队...",
                "running_stage": "generating_storyboards",
                "running_message": "正在生成故事版图片...",
            },
        )
        main_mod._detach_pending_platform_points(request, quota_result.get("usage_event_id"))
    except Exception as exc:
        if shot_count > 0:
            refund_db = SessionLocal()
            try:
                task_manager.refund_quota(
                    user.id,
                    "manga.image.generate.monthly_limit",
                    shot_count,
                    refund_db,
                    usage_event_id=quota_result.get("usage_event_id"),
                )
                refund_db.commit()
            finally:
                refund_db.close()
        raise HTTPException(500, f"提交后台任务失败: {exc}")

    return {
        "task_id": task_id,
        "workflow_status": "generating_storyboards",
        "message": "故事版生成任务已提交后台执行",
    }


@router.post("/api/video/chapter-workflows/{workflow_id}/videos")
async def api_generate_videos(
    workflow_id: int,
    body: ChapterWorkflowStageActionRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """阶段3-视频：为指定镜头生成视频。"""
    user = _require_user(request, db)
    wf = get_chapter_workflow(workflow_id)
    if not wf:
        raise HTTPException(404, "工作流不存在")
    story = db.get(Story, wf.story_id)
    if not story or story.owner_user_id != user.id:
        raise HTTPException(403, "无权访问")

    if wf.workflow_status not in ("storyboards_ready", "generating_videos", "failed"):
        raise HTTPException(400, f"当前状态 {wf.workflow_status} 不允许视频操作")

    deepseek_api_key = _user_deepseek_api_key(request, db)
    image_api_key = _user_image_api_key(request)

    # 从数据库读取视频 API 配置并注入运行时
    _configure_video_service_from_db(request, db)
    video_api_key, video_base_url, video_model = _user_video_api_key(request)
    video_capabilities = _current_video_capabilities(request, db, video_model)
    adapter_type = _current_video_adapter_type(request)

    task_id = f"chapter_video_{workflow_id}_stage_{uuid.uuid4().hex[:8]}"

    # 刷新角色参考图 asset_id：视频阶段依赖 shot.character_reference_ids，
    # 若用户在拆镜后新增了参考图，确保 worklfow 和 shots 拿到最新数据
    ref_ids = wf.character_reference_ids
    if not ref_ids:
        ref_ids = _get_story_character_reference_asset_ids(wf.story_id, db)
        if ref_ids:
            db_wf = db.get(ChapterVideoWorkflow, workflow_id)
            if db_wf:
                db_wf.character_reference_ids = ref_ids
                # 同步更新尚无参考图 ID 的 shots
                stale_shots = db.query(ChapterVideoShot).filter(
                    ChapterVideoShot.workflow_id == workflow_id,
                    ChapterVideoShot.character_reference_ids == None,
                ).all()
                for s in stale_shots:
                    s.character_reference_ids = ref_ids
                db.commit()
                logger.info("视频生成前刷新角色参考图 asset_ids=%s (影响 %d 个镜头)", ref_ids, len(stale_shots))

    try:
        billed_shots = _chapter_video_target_shots(db, workflow_id, body.shot_ids or None)
    except AttributeError:
        billed_shots = []
    if not billed_shots:
        raise HTTPException(400, "没有可生成的视频镜头")
    total_duration = sum(
        max(1, min(MAX_VIDEO_DURATION_SECONDS, int(shot.duration_seconds or DEFAULT_VIDEO_DURATION_SECONDS)))
        for shot in billed_shots
    )
    target_shot_ids = [shot.id for shot in billed_shots]
    for billed_shot in billed_shots:
        _validate_video_request_before_billing(
            adapter_type=adapter_type,
            model=video_model,
            video_capabilities=video_capabilities,
            aspect_ratio="16:9",
            duration_seconds=max(1, min(MAX_VIDEO_DURATION_SECONDS, int(billed_shot.duration_seconds or DEFAULT_VIDEO_DURATION_SECONDS))),
            reference_count=_chapter_video_reference_count(billed_shot, wf, None, db),
        )
    quota_result = _reserve_video_billing(
        request,
        db,
        user_id=user.id,
        video_seconds=total_duration,
        detach=False,
    )
    update_chapter_workflow_status(workflow_id, "generating_videos")

    try:
        await task_manager.submit_task(
            task_id=task_id,
            task_type="chapter_video_videos",
            coro_func=_run_billed_media_task,
            billed_coro=generate_videos_for_shots,
            billing_usage_event_id=quota_result.get("usage_event_id"),
            billing_modality="video",
            billing_units=total_duration,
            workflow_id=workflow_id,
            shot_ids=target_shot_ids,
            image_api_key=image_api_key,
            deepseek_api_key=deepseek_api_key,
            video_api_key=video_api_key,
            video_base_url=video_base_url,
            video_model=video_model,
            video_capabilities=video_capabilities,
            adapter_type=adapter_type,
            timeout=1800.0,
            max_retries=1,
            quota_user_id=user.id,
            quota_feature_key="video.generate.count.monthly_limit",
            quota_amount=total_duration,
            quota_usage_event_id=quota_result.get("usage_event_id"),
            metadata={
                "workflow_id": workflow_id,
                "stage": "generating_videos",
                "message": "视频生成任务已排队...",
                "running_stage": "generating_videos",
                "running_message": "正在生成镜头视频...",
            },
        )
        _detach_video_billing(request, quota_result)
    except Exception as exc:
        refund_db = SessionLocal()
        try:
            task_manager.refund_quota(
                user.id,
                "video.generate.count.monthly_limit",
                total_duration,
                refund_db,
                usage_event_id=quota_result.get("usage_event_id"),
            )
            refund_db.commit()
        finally:
            refund_db.close()
        raise HTTPException(500, f"提交后台任务失败: {exc}")

    return {
        "task_id": task_id,
        "workflow_status": "generating_videos",
        "message": "视频生成任务已提交后台执行",
    }



