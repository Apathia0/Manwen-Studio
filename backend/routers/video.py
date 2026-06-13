"""Video production workflow router.

Handles screenplay, shot breakdown, storyboard, video generation,
asset management, and video project compilation endpoints.
"""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
import os
import uuid
from pathlib import Path
import re
import httpx

from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile, File
from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from database import SessionLocal, get_db, init_db
_VIDEO_OUTPUTS_DIR = Path(__file__).resolve().parent.parent / "video_outputs"

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


from models import (
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
    VideoShot,
)
from schemas import (
    ChapterStylePresetUpdate,
    ChapterVideoWorkflowCreate,
    ChapterVideoWorkflowOut,
    ChapterVideoWorkflowListOut,
    ChapterVideoWorkflowStatusOut,
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
from services import video_generation as video_gen_service
from services.media_locator import ensure_local_media_path, resolve_local_media_path, resolve_reference_input
from services import video_api as video_api_service
from services import video_qa
from services.video_compiler import compile_project
from services.task_manager import task_manager
from services.video_chapter_pipeline import (
    create_workflow as create_chapter_workflow,
    get_workflow as get_chapter_workflow,
    get_workflows_for_chapter as get_chapter_workflows,
    start_workflow_background,
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
    run_all_stages,
)

# 模块级标记：init_db 在整个进程生命周期中只调用一次
_db_schema_verified: bool = False

logger = logging.getLogger("video_router")

router = APIRouter()

SHOT_DURATION_SECONDS = 15


# 鈹€鈹€鈹€ Helper functions (mirrored from main.py patterns) 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

def _user_video_api_key(request: Request) -> tuple[str | None, str, str]:
    """Return (api_key, base_url, model) for current request/user context."""
    key = (request.headers.get("x-video-api-key") or "").strip()
    db = getattr(request.state, "db", None)
    if db is None:
        return key or None, video_api_service._resolved_base_url(), video_api_service._resolved_model()

    user = getattr(request.state, "current_user", None)
    capabilities = _user_api_override_capabilities(user, db)
    override_base_url = request.headers.get("x-video-base-url") or None
    override_model = request.headers.get("x-video-model") or None
    admin_base_url = str(_get_platform_setting("api.video.base_url", db, video_api_service._resolved_base_url())).strip()
    admin_model = str(_get_platform_setting("api.video.model", db, video_api_service._resolved_model())).strip()
    admin_api_key = str(_get_platform_setting("api.video.api_key", db, "") or "").strip()

    resolved_base_url = (
        override_base_url.strip()
        if capabilities["can_override_api_url"] and override_base_url and override_base_url.strip()
        else admin_base_url
    )
    resolved_model = (
        override_model.strip()
        if capabilities["can_override_api_url"] and override_model and override_model.strip()
        else admin_model
    )

    if capabilities["can_override_api_key"] and key:
        effective_key = key
    elif admin_api_key:
        effective_key = admin_api_key
    else:
        effective_key = key or None

    return effective_key, resolved_base_url.rstrip("/"), resolved_model


def _user_image_api_key(request: Request) -> str | None:
    """Return image API key for current request/user context.

    同时自动配置 image2 服务的 base_url 和 model，确保后续调用不会报错。
    """
    from services import image2 as image_service

    override = request.headers.get("x-image-api-key") or None
    db = getattr(request.state, "db", None)
    if db is None:
        return override
    user = getattr(request.state, "current_user", None)
    capabilities = _user_api_override_capabilities(user, db)
    if capabilities["can_override_api_key"] and override:
        return override

    # 自动配置 image2 服务
    base_url = str(_get_platform_setting("api.image.base_url", db, "") or "").strip()
    model = str(_get_platform_setting("api.image.model", db, "") or "").strip()
    if base_url:
        image_service.configure_runtime(base_url=base_url, model=model)

    return _get_platform_setting("api.image.api_key", db, "") or None


def _get_platform_setting(key: str, db: Session, default=None):
    setting = db.query(PlatformSetting).filter(PlatformSetting.setting_key == key).first()
    if not setting:
        return default
    payload = setting.value_json or {}
    return payload.get("value", default)


def _user_api_override_capabilities(user: User | None, db: Session) -> dict[str, bool]:
    key_global = bool(_get_platform_setting("api.enable_user_override", db, True))
    url_global = bool(_get_platform_setting("api.enable_user_url_override", db, False))
    return {
        "can_override_api_key": key_global and bool(user and user.allow_api_key_override),
        "can_override_api_url": url_global and bool(user and user.allow_api_url_override),
    }


def _configure_image_service_from_db(request: Request, db: Session) -> None:
    """从数据库读取图片 API 配置并注入 image2 服务。

    ⚠️ 必须在调用任何图片生成函数前调用此函数！
    否则 image2._image_auth_headers 会抛出 '图片 API 地址未配置' 错误。
    """
    from services import image2 as image_service

    base_url = str(_get_platform_setting("api.image.base_url", db, "") or "").strip()
    model = str(_get_platform_setting("api.image.model", db, "") or "").strip()
    api_key = _user_image_api_key(request)

    if base_url:
        image_service.configure_runtime(base_url=base_url, model=model)
    elif api_key:
        image_service.configure_runtime(api_key=api_key)


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
    override = request.headers.get("x-deepseek-api-key") or None
    override_base_url = request.headers.get("x-deepseek-base-url") or None
    override_model = request.headers.get("x-deepseek-model") or None
    user = getattr(request.state, "current_user", None)
    capabilities = _user_api_override_capabilities(user, db)
    admin_base_url = str(_get_platform_setting("api.deepseek.base_url", db, deepseek_service.DEEPSEEK_BASE_URL)).strip()
    admin_model = str(_get_platform_setting("api.deepseek.model", db, deepseek_service.DEEPSEEK_MODEL)).strip()
    resolved_base_url = override_base_url.strip() if capabilities["can_override_api_url"] and override_base_url and override_base_url.strip() else admin_base_url
    resolved_model = override_model.strip() if capabilities["can_override_api_url"] and override_model and override_model.strip() else admin_model

    # 使用 configure_runtime 而不是直接设置全局变量
    deepseek_service.configure_runtime(base_url=resolved_base_url, model=resolved_model)

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
    token = _parse_auth_token(request)
    if not token:
        raise HTTPException(401, "Unauthorized")
    session = db.query(UserSession).filter(
        UserSession.token == token,
        UserSession.revoked_at.is_(None),
    ).first()
    if not session:
        raise HTTPException(401, "Session expired or invalid token")
    user = db.get(User, session.user_id)
    if not user or user.status != "active":
        raise HTTPException(403, "User unavailable")
    request.state.current_user = user
    return user


def _require_chapter(chapter_id: int, db: Session) -> Chapter:
    chapter = db.get(Chapter, chapter_id)
    if not chapter:
        raise HTTPException(404, "Chapter not found")
    return chapter


def _require_story_for_user(story_id: int, user: User, db: Session) -> Story:
    story = db.get(Story, story_id)
    if not story:
        raise HTTPException(404, "Story not found")
    if story.owner_user_id != user.id:
        raise HTTPException(403, "Story access denied")
    return story


def _require_chapter_for_user(chapter_id: int, user: User, db: Session) -> Chapter:
    chapter = _require_chapter(chapter_id, db)
    story = chapter.story
    if not story:
        raise HTTPException(404, "Story not found")
    if story.owner_user_id != user.id:
        raise HTTPException(403, "Chapter access denied")
    return chapter





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
    # 视频/故事版提示词：将风格自然融入末尾作为视觉质量要求
    if len(base) > 300:
        return f"{base}\n\nVisual style: {style_text}."
    # 短提示词：前缀方式
    return f"{style_text}. {base}"


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
    style_ctx: dict,
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
        f"Style requirement: apply selected anime/illustration style, cel-shaded rendering, clean line art, vibrant color palette. "
        "Mandatory consistency: lock face shape, eye distance, nose bridge contour, lip shape, jawline angle, hair parting, and 3 signature color swatches across ALL generated frames. "
        "This is a master reference sheet for video animation consistency. Every subsequent frame MUST match these identity markers exactly."
    )
    return _merge_style_prompt(card, style_ctx.get("prompt_template"), style_ctx.get("name"))


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
        ids.extend([int(x) for x in explicit_asset_ids if str(x).isdigit()])
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
    """构建参考资产使用说明，按资产类型给出明确角色标注。"""
    if not character_assets:
        return ""

    type_roles = {
        "character_reference": "角色身份参考图",
        "story_character_reference": "角色身份参考图",
        "scene_reference": "场景氛围参考图",
        "prop_reference": "道具参考图",
        "storyboard_frame": "分镜构图参考图",
        "frame": "首尾帧参考图",
    }

    groups: dict[str, list[VideoAsset]] = {}
    for a in character_assets:
        at = a.asset_type or "reference"
        groups.setdefault(at, []).append(a)

    parts = ["<<<REFERENCE_ASSET_GUIDE>>>"]
    parts.append("以下图片已作为视觉参考传入。各图片用途如下：")

    for at, assets in groups.items():
        role = type_roles.get(at, f"{at}参考图")
        names = ", ".join(a.name or "unnamed" for a in assets[:5])
        parts.append(f"- {role} ({len(assets)}张): {names}")

    parts.append(
        "<<<END_GUIDE>>> "
        "MANDATORY USAGE RULES: "
        "1. Character reference images: lock face shape, hairstyle, eye color, outfit, body type for each character. All identity markers must match exactly. "
        "2. Storyboard reference image: use as the authoritative shot plan -- follow the panel-by-panel camera framing, character blocking, action progression, and timing shown in the storyboard. The storyboard defines the exact visual sequence to generate. "
        "3. Scene reference images: match atmosphere, color palette, lighting setup, architecture, and environmental details. Keep the same location perspective and spatial layout. "
        "4. Prop reference images: maintain exact prop appearance -- material, color, size, shape, texture, wear marks, and distinctive features must be identical. Props must stay visually consistent across all shots. "
        "5. Frame reference images: first frame = start state, last frame = end state. Generate smooth transition between them. "
        "CRITICAL: The storyboard image is the director's blueprint. The generated video must faithfully follow the shot breakdown, camera movements, and character actions depicted in the storyboard panels. "
        "CONSISTENCY RULE: All visual elements (characters, scene, props) must remain identical to their reference images throughout the entire video. No drift, no variation, no reinterpretation."
    )
    return " ".join(parts)


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


def _encode_file_to_base64_data_uri(file_path: str) -> str | None:
    """读取本地文件并编码为 base64 data URI。"""
    import base64 as b64
    try:
        with open(file_path, "rb") as fh:
            data = fh.read()
        ext = os.path.splitext(file_path)[1].lower()
        mime_map = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
            ".gif": "image/gif",
        }
        mime = mime_map.get(ext, "image/png")
        return f"data:{mime};base64,{b64.b64encode(data).decode()}"
    except Exception:
        logger.warning("无法读取参考图片文件: %s", file_path)
        return None


def _resolve_asset_file_paths(assets: list[VideoAsset]) -> list[str]:
    """将资产 file_path 解析为绝对磁盘路径（兼容相对路径、/static/video/ 前缀、绝对路径）。"""
    paths: list[str] = []
    for asset in assets:
        fp = (asset.file_path or "").strip()
        if not fp:
            continue
        # 多级 fallback 查找文件
        candidates: list[str] = []
        if os.path.isabs(fp):
            candidates.append(fp)
        if fp.startswith("/static/video/"):
            candidates.append(str(_VIDEO_OUTPUTS_DIR / fp[len("/static/video/"):]))
        candidates.append(str(_VIDEO_OUTPUTS_DIR / fp))
        candidates.append(str(Path(__file__).resolve().parent.parent / fp))
        for local in candidates:
            if os.path.isfile(local):
                paths.append(local)
                break
        else:
            logger.warning("找不到参考图片文件: %s", fp)
    return paths


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
) -> str | None:
    """解析工作流的风格参考图文件绝对路径。

    用于图生图模式：将顶部预选的风格参考图作为 img2img 源图传入 Image2 API，
    确保生成的角色/场景/道具图片的画风与风格参考图完全一致。
    """
    wf = db.query(ChapterVideoWorkflow).filter(
        ChapterVideoWorkflow.chapter_id == chapter_id
    ).order_by(ChapterVideoWorkflow.created_at.desc()).first()
    if not wf:
        return None

    ref_url = None
    if wf.style_reference_image_url:
        ref_url = wf.style_reference_image_url.strip()

    # 回退：使用章节绑定的风格预设的 image_url
    if not ref_url:
        chapter = db.query(Chapter).filter(Chapter.id == chapter_id).first()
        if chapter and chapter.video_style_preset_id:
            preset = db.get(VideoStylePreset, chapter.video_style_preset_id)
            if preset and preset.image_url:
                ref_url = preset.image_url.strip()

    if not ref_url:
        return None

    resolved_path = ensure_local_media_path(ref_url, "manga")
    if resolved_path:
        return resolved_path
    logger.warning("风格参考图文件不存在或无法下载: %s", ref_url)
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

    # Check quota (screenplay.generate.monthly_limit)
    _check_and_consume_quota_wrapper(user.id, "screenplay.generate.monthly_limit", 1, db, deduct=False)

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

    # Consume quota
    _check_and_consume_quota_wrapper(user.id, "screenplay.generate.monthly_limit", 1, db, deduct=True)

    # Refresh to get IDs
    for scene in scenes:
        db.refresh(scene)

    quota_result = _check_and_consume_quota_wrapper(user.id, "screenplay.generate.monthly_limit", 0, db, deduct=False)

    return {
        "chapter_id": chapter_id,
        "screenplay": chapter.screenplay_text or "",
        "scenes": [_serialize_scene(s) for s in scenes],
        "usage": _serialize_usage(quota_result["used"], quota_result["limit"]),
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

    _clear_chapter_scenes(chapter_id, db)

    # 配额预检
    _check_and_consume_quota_wrapper(user.id, "screenplay.generate.monthly_limit", 1, db, deduct=False)

    # Generate new scenes
    scenes_data = await regenerate_scenes(
        existing_screenplay=chapter.screenplay_text or chapter.novel_content or "",
        instruction=body.instruction or "閲嶆柊鐢熸垚",
        scene_count_hint=body.scene_count_hint or 4,
        api_key=_user_deepseek_api_key(request, db),
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
    # 配额扣减
    _check_and_consume_quota_wrapper(user.id, "screenplay.generate.monthly_limit", 1, db, deduct=True)

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
    _check_and_consume_quota_wrapper(user.id, "shot.generate.monthly_limit", 1, db, deduct=False)

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
        "model": deepseek_service.DEEPSEEK_MODEL,
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
                f"{deepseek_service.DEEPSEEK_BASE_URL}/chat/completions",
                json=payload,
                headers=deepseek_service._deepseek_auth_headers(api_key),
            )
            resp.raise_for_status()
            ai_data = resp.json()
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
    _check_and_consume_quota_wrapper(user.id, "shot.generate.monthly_limit", 1, db, deduct=True)
    for shot in shots:
        db.refresh(shot)
    quota_result = _check_and_consume_quota_wrapper(user.id, "shot.generate.monthly_limit", 0, db, deduct=False)
    return {
        "chapter_id": chapter_id, "shots": [_serialize_shot(s) for s in shots],
        "total_count": len(shots),
        "usage": _serialize_usage(quota_result["used"], quota_result["limit"]),
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
        raise HTTPException(404, "Scene not found")
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
        raise HTTPException(404, "Scene not found")
    _require_chapter_for_user(scene.chapter_id, user, db)

    # Check quota (shot.generate.monthly_limit)
    _check_and_consume_quota_wrapper(user.id, "shot.generate.monthly_limit", 1, db, deduct=False)

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

    # Consume quota
    _check_and_consume_quota_wrapper(user.id, "shot.generate.monthly_limit", 1, db, deduct=True)

    for shot in shots:
        db.refresh(shot)

    quota_result = _check_and_consume_quota_wrapper(user.id, "shot.generate.monthly_limit", 0, db, deduct=False)

    return {
        "scene_id": scene_id,
        "shots": [_serialize_shot(s) for s in shots],
        "usage": _serialize_usage(quota_result["used"], quota_result["limit"]),
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
        raise HTTPException(404, "Scene not found")
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
        raise HTTPException(404, "Scene not found")
    _require_chapter_for_user(scene.chapter_id, user, db)

    style_preset_name = (body.get("style_preset") or "").strip()
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

    style_ctx = _resolve_effective_style_for_scene(scene, db, requested_style_name=style_preset_name or None)
    style_name = style_ctx["name"]
    image_style_params = style_ctx["image_style_params"]
    grounding = _build_story_grounding_block(story, chapter, scene)
    prompt_base = (
        f"Scene concept art: {scene_summary}. Location: {scene_location}. Mood: {scene_mood}. "
        f"Characters involved: {', '.join(str(c) for c in characters)}. "
        f"{character_profiles[:300] if character_profiles else ''}. "
        f"Grounding context: {grounding}"
    )
    ref_assets = _select_character_reference_assets_for_scene(scene, db)
    if explicit_ref_ids:
        explicit_assets = db.query(VideoAsset).filter(VideoAsset.id.in_(explicit_ref_ids)).all()
        id_set = {a.id for a in ref_assets}
        for a in explicit_assets:
            if a.id not in id_set:
                ref_assets.append(a)
                id_set.add(a.id)
    ref_block = _build_reference_constraints_block(ref_assets)
    ref_paths = _resolve_asset_file_paths(ref_assets)
    prompt = _merge_style_prompt(f"{prompt_base} {ref_block}".strip(), style_ctx["prompt_template"], style_name)

    scene_dir = _VIDEO_OUTPUTS_DIR / f"scene_{scene_id}"
    scene_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"concept_art_{timestamp}.png"
    full_path = scene_dir / filename

    api_key = _user_image_api_key(request)

    # 配额预检
    _check_and_consume_quota_wrapper(user.id, "manga.image.monthly_limit", 1, db, deduct=False)

    try:
        await image2_service.generate_reference_image(
            prompt=prompt,
            output_path=full_path,
            api_key=api_key or None,
            size=image_style_params.get("size", "1792x1024"),
            ref_image_paths=ref_paths if ref_paths else None,
        )
    except Exception as e:
        logger.warning("Concept art generation failed: %s", e)
        raise HTTPException(502, f"姒傚康鍥剧敓鎴愬け璐? {e}")

    file_path = f"scene_{scene_id}/{filename}"

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
        style_preset=style_name,
        status="active",
    )
    db.add(asset)
    db.flush()

    scene.concept_art_asset_id = asset.id

    db.commit()
    # 配额扣减
    _check_and_consume_quota_wrapper(user.id, "manga.image.monthly_limit", 1, db, deduct=True)
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
        raise HTTPException(404, "Scene not found")
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

@router.get("/api/video/models")
async def list_video_models():
    return {"models": video_api_service.get_supported_models()}


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
        raise HTTPException(404, "Shot not found")
    if not shot.scene:
        raise HTTPException(404, "Scene not found")

    effective_provider = _resolve_video_provider(body.provider, db)

    # Check quota for video generation (by seconds)
    duration = max(1, min(SHOT_DURATION_SECONDS, body.duration_seconds or shot.duration_seconds or SHOT_DURATION_SECONDS))
    _check_and_consume_quota_wrapper(
        user.id, "video.generate.seconds.monthly_limit", duration, db, deduct=False,
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

    # Warn if storyboard exists but not locked
    if source_storyboard_asset_id and not shot.storyboard_locked and input_mode == "image_to_video":
        logger.warning(
            "Shot %s storyboard not locked, but image_to_video requested. "
            "Consider approving the storyboard first.", shot_id
        )

    ref_assets = db.query(VideoAsset).filter(VideoAsset.id.in_(auto_reference_asset_ids)).all() if auto_reference_asset_ids else []
    first_frame_asset, last_frame_asset, other_refs = _split_frame_assets(ref_assets)
    ref_block = _build_reference_constraints_block(ref_assets)

    ordered_images: list[str] = []
    # 用户未选首帧时，自动继承前一个镜头的尾帧作为连贯参考
    prev_last_frame = _get_previous_shot_last_frame(shot, db) if not first_frame_asset else None
    if prev_last_frame:
        p = _resolve_asset_file_paths([prev_last_frame])
        b = _encode_file_to_base64_data_uri(p[0]) if p else None
        if b:
            ordered_images.append(b)
            if not first_frame_asset:
                first_frame_url_text = b[:80] + "..."
                logger.info("Shot %s: 继承前镜头尾帧作为首帧连贯参考", shot_id)
    if first_frame_asset:
        path = _resolve_asset_file_paths([first_frame_asset])
        b64 = _encode_file_to_base64_data_uri(path[0]) if path else None
        if b64:
            ordered_images.append(b64)
    ordered_images.extend(_resolve_asset_reference_urls([a.id for a in other_refs], db, request) if other_refs else [])
    if last_frame_asset:
        path = _resolve_asset_file_paths([last_frame_asset])
        b64 = _encode_file_to_base64_data_uri(path[0]) if path else None
        if b64:
            ordered_images.append(b64)

    style_ctx = _resolve_effective_style_for_shot(shot, db, requested_style_name=body.style)
    style_name = style_ctx["name"]
    video_style_params = style_ctx["video_style_params"]
    style_template = style_ctx["prompt_template"]

    api_key, base_url, resolved_model = _user_video_api_key(request)
    resolved_model = body.model or resolved_model
    aspect_ratio = body.aspect_ratio or video_style_params.get("aspect_ratio") or "16:9"
    grounding = _build_story_grounding_block(shot.scene.chapter.story if shot.scene and shot.scene.chapter else None, shot.scene.chapter if shot.scene else None, shot.scene)
    storyboard_guide = ""
    if shot.storyboard_prompt:
        storyboard_guide = (
            f"\n\n<<<STORYBOARD_BLUEPRINT>>>\n"
            f"This is the shot-by-shot storyboard that the video MUST follow:\n"
            f"{shot.storyboard_prompt}\n"
            f"<<<END_BLUEPRINT>>>\n"
            f"CRITICAL: Generate video matching EVERY time segment, camera movement, "
            f"character action, and dialogue in the storyboard blueprint above."
        )
    full_prompt = _merge_style_prompt(
        f"{body.prompt or shot.video_prompt or ''}{storyboard_guide} {ref_block} Grounding: {grounding}".strip(),
        style_template, style_name,
    )

    task_id = f"video_render_{shot_id}_{int(datetime.datetime.utcnow().timestamp())}"
    await task_manager.submit_task(
        task_id=task_id,
        task_type="video_render",
        coro_func=video_gen_service.submit_video_job,
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
        timeout=600,
        max_retries=2,
    )

    job_status = "pending"
    job = VideoGenerationJob(
        shot_id=shot_id,
        provider=effective_provider,
        provider_job_id=task_id,
        model=resolved_model,
        request_payload_json={
            "model": resolved_model,
            "prompt": full_prompt,
            "negative_prompt": body.negative_prompt or shot.negative_prompt or "",
            "duration_seconds": duration,
            "aspect_ratio": aspect_ratio,
            "style": style_name,
            "reference_asset_ids": auto_reference_asset_ids,
            "reference_image_urls": reference_image_urls,
        },
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

    # Update shot status
    shot.status = "rendering"
    shot.updated_at = datetime.datetime.utcnow()

    _check_and_consume_quota_wrapper(
        user.id, "video.generate.seconds.monthly_limit", duration, db, deduct=True,
    )

    db.commit()
    db.refresh(job)

    quota_result = _check_and_consume_quota_wrapper(
        user.id, "video.generate.seconds.monthly_limit", 0, db, deduct=False,
    )

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
            "request_payload": job.request_payload_json or {},
            "error_message": job.error_message,
            "input_mode": job.input_mode,
            "source_storyboard_asset_id": job.source_storyboard_asset_id,
            "submitted_at": _serialize_datetime(job.submitted_at),
            "completed_at": _serialize_datetime(job.completed_at),
        },
        "shot_status": shot.status,
        "usage": _serialize_usage(quota_result["used"], quota_result["limit"]),
    }


@router.post("/api/shots/{shot_id}/video/render-stream")
async def render_shot_video_stream(
    shot_id: int,
    body: VideoRenderRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """SSE-streaming video render endpoint.
    
    Events:
      event: progress 鈫?{ job_id, progress, stage, message }
      event: done     鈫?{ job_id, clip }
      event: error    鈫?{ job_id, error }
    """
    user = _require_user(request, db)
    shot = db.get(VideoShot, shot_id)
    if not shot:
        raise HTTPException(404, "Shot not found")
    if not shot.scene:
        raise HTTPException(404, "Scene not found")
    _require_chapter_for_user(shot.scene.chapter_id, user, db)

    effective_provider = _resolve_video_provider(body.provider, db)

    duration = max(1, min(SHOT_DURATION_SECONDS, body.duration_seconds or shot.duration_seconds or SHOT_DURATION_SECONDS))
    _check_and_consume_quota_wrapper(
        user.id, "video.generate.seconds.monthly_limit", duration, db, deduct=False,
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

    ordered_images: list[str] = []
    # 用户未选首帧时，自动继承前一个镜头的尾帧作为连贯参考
    prev_last_frame = _get_previous_shot_last_frame(shot, db) if not first_frame_asset else None
    if prev_last_frame:
        p = _resolve_asset_file_paths([prev_last_frame])
        b = _encode_file_to_base64_data_uri(p[0]) if p else None
        if b:
            ordered_images.append(b)
            if not first_frame_asset:
                first_frame_url_text = b[:80] + "..."
                logger.info("Shot %s: 继承前镜头尾帧作为首帧连贯参考", shot_id)
    if first_frame_asset:
        path = _resolve_asset_file_paths([first_frame_asset])
        b64 = _encode_file_to_base64_data_uri(path[0]) if path else None
        if b64:
            ordered_images.append(b64)
    ordered_images.extend(_resolve_asset_reference_urls([a.id for a in other_refs], db, request) if other_refs else [])
    if last_frame_asset:
        path = _resolve_asset_file_paths([last_frame_asset])
        b64 = _encode_file_to_base64_data_uri(path[0]) if path else None
        if b64:
            ordered_images.append(b64)

    style_ctx = _resolve_effective_style_for_shot(shot, db, requested_style_name=body.style)
    style_name = style_ctx["name"]
    video_style_params = style_ctx["video_style_params"]
    style_template = style_ctx["prompt_template"]

    api_key, base_url, resolved_model = _user_video_api_key(request)
    resolved_model = body.model or resolved_model
    aspect_ratio = body.aspect_ratio or video_style_params.get("aspect_ratio") or "16:9"
    grounding = _build_story_grounding_block(shot.scene.chapter.story if shot.scene and shot.scene.chapter else None, shot.scene.chapter if shot.scene else None, shot.scene)
    storyboard_guide = ""
    if shot.storyboard_prompt:
        storyboard_guide = (
            f"\n\n<<<STORYBOARD_BLUEPRINT>>>\n"
            f"This is the shot-by-shot storyboard that the video MUST follow:\n"
            f"{shot.storyboard_prompt}\n"
            f"<<<END_BLUEPRINT>>>\n"
            f"CRITICAL: Generate video matching EVERY time segment, camera movement, "
            f"character action, and dialogue in the storyboard blueprint above."
        )
    full_prompt = _merge_style_prompt(
        f"{body.prompt or shot.video_prompt or ''}{storyboard_guide} {ref_block} Grounding: {grounding}".strip(),
        style_template, style_name,
    )

    async def event_generator():
        nonlocal db, base_url
        job_id = None
        
        try:
            yield {"event": "progress", "data": json.dumps({"progress": 0, "stage": "submitting", "message": "正在提交视频生成任务..."})}

            task_id = f"video_render_{shot_id}_{int(datetime.datetime.utcnow().timestamp())}"
            await task_manager.submit_task(
                task_id=task_id,
                task_type="video_render",
                coro_func=video_gen_service.submit_video_job,
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
                timeout=600,
                max_retries=2,
            )

            job_status = "pending"
            provider_job_id = task_id

            from models import VideoGenerationJob
            job = VideoGenerationJob(
                shot_id=shot_id,
                provider=effective_provider,
                provider_job_id=provider_job_id,
                model=resolved_model,
                request_payload_json={
                    "model": resolved_model,
                    "prompt": full_prompt,
                    "duration_seconds": duration,
                    "aspect_ratio": aspect_ratio,
                    "style": style_name,
                    "reference_asset_ids": auto_reference_asset_ids,
                    "reference_image_urls": reference_image_urls,
                },
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

            _check_and_consume_quota_wrapper(
                user.id, "video.generate.seconds.monthly_limit", duration, db, deduct=True,
            )

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
                if task_status is None:
                    current_status = "queued"
                    progress = 0
                elif task_status["status"] == "succeeded":
                    # 任务成功，获取 provider_job_id 用于后续轮询
                    result = task_status.get("result_json") or {}
                    provider_job_id = result.get("provider_job_id", provider_job_id)
                    current_status = "succeeded"
                    progress = 100
                elif task_status["status"] == "failed":
                    error_msg = task_status.get("error_message", "Generation failed")
                    yield {"event": "error", "data": json.dumps({"job_id": job_id, "error": error_msg})}
                    
                    write_db = SessionLocal()
                    try:
                        db_job = write_db.get(VideoGenerationJob, job_id)
                        if db_job:
                            db_job.status = "failed"
                            db_job.error_message = error_msg
                            db_job.completed_at = datetime.datetime.utcnow()
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
                    if not download_attempted:
                        progress_val = max(progress, 80)
                        yield {"event": "progress", "data": json.dumps({"job_id": job_id, "progress": progress_val, "stage": "downloading", "message": "瑙嗛鐢熸垚瀹屾垚锛屾鍦ㄤ笅杞?.."})}
                        download_attempted = True
                    
                    from models import RenderedClip
                    result = await video_gen_service.fetch_job_result(
                        provider=provider,
                        provider_job_id=provider_job_id,
                        shot_id=shot_id,
                        api_key=api_key,
                        base_url=base_url,
                    )
                    
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
                        yield {"event": "error", "data": json.dumps({"job_id": job_id, "error": "Failed to download video"})}
                    return
                
                progress_val = max(15, min(75, int(progress) or (poll_count * 5 + 15)))
                # 根据 current_status 动态映射 stage 和 message
                if current_status == "queued":
                    stage = "queued"
                    message = "等待执行..."
                elif current_status == "retrying":
                    stage = "retrying"
                    message = "生成失败，正在重试..."
                else:
                    stage = "generating"
                    message = f"瑙嗛鐢熸垚涓?.. ({progress_val}%)"
                yield {"event": "progress", "data": json.dumps({
                    "job_id": job_id,
                    "progress": progress_val,
                    "stage": stage,
                    "message": message,
                })}
                
                await asyncio.sleep(3)
            
            yield {"event": "error", "data": json.dumps({"job_id": job_id, "error": "Generation timed out"})}
            
        except asyncio.CancelledError:
            yield {"event": "error", "data": json.dumps({"job_id": job_id, "error": "cancelled"})}
            raise
        except Exception as e:
            logger.exception("SSE video render failed")
            yield {"event": "error", "data": json.dumps({"job_id": job_id, "error": str(e)})}

    return EventSourceResponse(event_generator())


@router.get("/api/shots/{shot_id}/clips")
async def list_shot_clips(
    shot_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    shot = db.get(VideoShot, shot_id)
    if not shot:
        raise HTTPException(404, "Shot not found")
    if not shot.scene:
        raise HTTPException(404, "Scene not found")
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
        raise HTTPException(404, "Shot not found")
    if not shot.scene:
        raise HTTPException(404, "Scene not found")
    _require_chapter_for_user(shot.scene.chapter_id, user, db)

    clip = db.get(RenderedClip, clip_id)
    if not clip or clip.shot_id != shot_id:
        raise HTTPException(404, "Clip not found for this shot")

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
        raise HTTPException(404, "Video generation job not found")

    # Validate ownership via shot -> scene -> chapter
    shot = job.shot
    if not shot or not shot.scene:
        raise HTTPException(404, "Associated shot not found")
    _require_chapter_for_user(shot.scene.chapter_id, user, db)

    # 内部 task_id 时尝试从 task_manager 获取真实 API task_id
    if job.provider_job_id and job.provider_job_id.startswith("video_render_"):
        task_status = task_manager.get_task_status(job.provider_job_id)
        if task_status and task_status.get("result_json"):
            result = task_status.get("result_json", {})
            real_id = result.get("provider_job_id", "")
            if real_id and real_id != job.provider_job_id:
                job.provider_job_id = real_id
                db.commit()
        # task_manager 还没完成提交，跳过本次查询，下次轮询重试
        if job.provider_job_id and job.provider_job_id.startswith("video_render_"):
            logger.info("Video job %s: task submission pending, skip external query", job_id)
            return {
                "id": job.id, "shot_id": job.shot_id, "provider": job.provider,
                "provider_job_id": job.provider_job_id, "model": job.model,
                "request_payload": job.request_payload_json or {}, "status": job.status,
                "progress": job.progress, "duration_seconds": job.duration_seconds,
                "aspect_ratio": job.aspect_ratio or "",
                "error_message": job.error_message or "",
                "submitted_at": _serialize_datetime(job.submitted_at),
                "completed_at": _serialize_datetime(job.completed_at),
            }

    if job.status not in {"succeeded", "failed", "cancelled"} and job.provider_job_id:
        api_key, base_url, _model = _user_video_api_key(request)
        latest = await video_gen_service.query_job_status(
            provider=job.provider,
            provider_job_id=job.provider_job_id,
            api_key=api_key,
            base_url=base_url,
        )

        job.status = latest.get("status", job.status) or job.status
        job.progress = int(latest.get("progress", job.progress) or 0)
        if latest.get("error"):
            job.error_message = str(latest["error"])

        if job.status == "succeeded":
            if not job.completed_at:
                job.completed_at = datetime.datetime.utcnow()
            shot.status = "ready"
        elif job.status == "failed":
            if not job.completed_at:
                job.completed_at = datetime.datetime.utcnow()
            shot.status = "failed"
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
            api_key, base_url, _model = _user_video_api_key(request)
            fetched = await video_gen_service.fetch_job_result(
                provider=job.provider,
                provider_job_id=job.provider_job_id,
                shot_id=job.shot_id,
                api_key=api_key,
                base_url=base_url,
            )
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
                db.commit()
                db.refresh(clip)
                logger.info("Video job %s created clip id=%s path=%s version=%s", job_id, clip.id, clip.video_path, clip.version)
                shot.status = "ready"
                shot.updated_at = datetime.datetime.utcnow()
                db.commit()
        else:
            clip = (
                db.query(RenderedClip)
                .filter(RenderedClip.job_id == job_id)
                .first()
            )

    result = {
        "id": job.id,
        "shot_id": job.shot_id,
        "provider": job.provider,
        "provider_job_id": job.provider_job_id,
        "model": job.model,
        "request_payload": job.request_payload_json or {},
        "status": job.status,
        "progress": job.progress,
        "duration_seconds": job.duration_seconds,
        "aspect_ratio": job.aspect_ratio or "",
        "error_message": job.error_message or "",
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
        logger.info("Video job %s returning clip: id=%s path=%s", job_id, clip.id, clip.video_path)

    return result


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
        raise HTTPException(404, "Video generation job not found")

    shot = old_job.shot
    if not shot or not shot.scene:
        raise HTTPException(404, "Associated shot not found")
    _require_chapter_for_user(shot.scene.chapter_id, user, db)

    # 配额预检
    _check_and_consume_quota_wrapper(
        user.id, "video.generate.seconds.monthly_limit",
        min(10, old_job.duration_seconds or 10), db, deduct=False,
    )

    # Create new job with same shot_id
    new_job = VideoGenerationJob(
        shot_id=old_job.shot_id,
        provider=body.provider or old_job.provider,
        provider_job_id=f"mock_job_{uuid.uuid4().hex[:12]}",
        model=body.model or old_job.model,
        request_payload_json=body.request_payload or old_job.request_payload_json or {},
        status="queued",
        progress=0,
        duration_seconds=old_job.duration_seconds,
        aspect_ratio=body.aspect_ratio or old_job.aspect_ratio or "16:9",
    )
    db.add(new_job)
    db.commit()
    # 配额扣减
    _check_and_consume_quota_wrapper(
        user.id, "video.generate.seconds.monthly_limit",
        min(10, old_job.duration_seconds or 10), db, deduct=True,
    )
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
            "request_payload": new_job.request_payload_json or {},
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

    query = db.query(VideoAsset).filter(VideoAsset.chapter_id == chapter_id, VideoAsset.status == "active")
    if asset_type:
        query = query.filter(VideoAsset.asset_type == asset_type)

    assets = list(query.order_by(VideoAsset.created_at.desc()).all())

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
    _require_chapter_for_user(chapter_id, user, db)

    chapter = _require_chapter_for_user(chapter_id, user, db)

    # 验证 shot_id：如果提供了但对应的 VideoShot 不存在，设 None 避免外键冲突
    shot_id = body.shot_id
    if shot_id is not None:
        shot_exists = db.get(VideoShot, shot_id)
        if not shot_exists:
            shot_id = None

    asset = VideoAsset(
        story_id=body.story_id if body.story_id is not None else chapter.story_id,
        chapter_id=chapter_id,
        scene_id=body.scene_id,
        shot_id=shot_id,
        asset_type=body.asset_type,
        name=body.name,
        file_path=body.file_path or "",
        provider=body.provider or "",
        prompt=body.prompt or "",
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
    asset = db.get(VideoAsset, asset_id)
    if not asset:
        raise HTTPException(404, "Video asset not found")

    if asset.chapter_id:
        _require_chapter_for_user(asset.chapter_id, user, db)
    elif asset.story_id:
        _require_story_for_user(asset.story_id, user, db)
    else:
        raise HTTPException(403, "Cannot determine asset ownership")

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
    asset = db.get(VideoAsset, asset_id)
    if not asset:
        raise HTTPException(404, "Video asset not found")

    # Validate ownership via chapter
    if asset.chapter_id:
        _require_chapter_for_user(asset.chapter_id, user, db)
    elif asset.story_id:
        _require_story_for_user(asset.story_id, user, db)
    else:
        raise HTTPException(403, "Cannot determine asset ownership")

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


@router.post("/api/video-assets/{asset_id}/replace")
async def replace_video_asset(asset_id: int, request: Request, db: Session = Depends(get_db)):
    """上传本地图片替换资产文件。"""
    user = _require_user(request, db)
    asset = db.get(VideoAsset, asset_id)
    if not asset:
        raise HTTPException(404, "Video asset not found")
    if asset.chapter_id:
        _require_chapter_for_user(asset.chapter_id, user, db)
    elif asset.story_id:
        _require_story_for_user(asset.story_id, user, db)
    else:
        raise HTTPException(403, "Cannot determine asset ownership")

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
    output_path.write_bytes(data)

    # OSS 上传（如已配置）
    from services import oss as oss_service
    _configure_oss_from_db(db)
    oss_url = oss_service.upload_file(str(output_path)) if oss_service.is_enabled() else None
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
    asset = db.get(VideoAsset, asset_id)
    if not asset:
        raise HTTPException(404, "Video asset not found")

    if asset.chapter_id:
        _require_chapter_for_user(asset.chapter_id, user, db)
    elif asset.story_id:
        _require_story_for_user(asset.story_id, user, db)
    else:
        raise HTTPException(403, "Cannot determine asset ownership")

    prompt = str(body.get("prompt") or "").strip()
    if not prompt:
        raise HTTPException(400, "prompt is required")
    mode = str(body.get("mode") or "full").strip().lower()
    if mode not in {"full", "partial"}:
        mode = "full"
    mask = body.get("mask")

    source_path = ensure_local_media_path(asset.file_path, "video")
    has_source = source_path and Path(source_path).exists()

    api_key = _user_image_api_key(request)
    _configure_image_service_from_db(request, db)
    regen_dir = _VIDEO_OUTPUTS_DIR / "regen_assets"
    regen_dir.mkdir(parents=True, exist_ok=True)
    output_filename = f"asset_{asset.id}_regen_{uuid.uuid4().hex[:8]}.png"
    output_path = regen_dir / output_filename

    # 配额预检
    _check_and_consume_quota_wrapper(user.id, "manga.image.monthly_limit", 1, db, deduct=False)

    try:
        if has_source:
            if mode == "partial" and mask:
                import base64
                mask_bytes = base64.b64decode(str(mask))
                saved_path = await image2_service.edit_existing_image(
                    prompt=prompt,
                    source_image_path=Path(source_path),
                    output_path=output_path,
                    mask_bytes=mask_bytes,
                    api_key=api_key or None,
                )
            else:
                saved_path = await image2_service.edit_existing_image(
                    prompt=prompt,
                    source_image_path=Path(source_path),
                    output_path=output_path,
                    api_key=api_key or None,
                )
        else:
            # 无源图片（首次生成占位资产）：用风格参考图示图生图保证画风一致
            style_ref_path = _resolve_workflow_style_ref_path(asset.chapter_id, db) if asset.chapter_id else None
            ref_paths = [style_ref_path] if style_ref_path else None
            saved_path = await image2_service.generate_reference_image(
                prompt=prompt,
                output_path=output_path,
                api_key=api_key or None,
                size="1792x1024",
                ref_image_paths=ref_paths,
                ref_type="style",
            )
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
        style_preset=asset.style_preset,
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
    _check_and_consume_quota_wrapper(user.id, "manga.image.monthly_limit", 1, db, deduct=True)
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
    with open(file_path, "wb") as f:
        f.write(content)

    relative_path = f"style-presets/{filename}"

    from services import oss as oss_service
    _configure_oss_from_db(db)
    oss_url = oss_service.upload_file(str(file_path))
    if oss_url:
        logger.info("风格预设图片已上传到 OSS: %s", oss_url)
        relative_path = oss_url
    else:
        logger.info("风格预设图片未上传到 OSS（未配置或上传失败），使用本地路径: %s", relative_path)

    logger.info("上传风格预设图片完成，返回 URL: %s", relative_path)
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
        raise HTTPException(404, "Video style preset not found")

    update_data = body.model_dump(exclude_unset=True)
    logger.info("更新风格预设 %s: received fields=%s image_url=%s", preset_id, list(update_data.keys()), update_data.get("image_url", "(未发送)"))
    for field, value in update_data.items():
        if value is not None:
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
        raise HTTPException(404, "Video style preset not found")

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
        raise HTTPException(404, "Video style preset not found")

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
        raise HTTPException(404, "Video style preset not found")

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
    """获取 Story 级所有角色默认版本的参考图 asset_id。"""
    versions = db.query(StoryCharacterVersion).filter(
        StoryCharacterVersion.story_id == story_id,
        StoryCharacterVersion.is_default == True,
        StoryCharacterVersion.ref_asset_id.isnot(None),
    ).all()
    return [v.ref_asset_id for v in versions if v.ref_asset_id]


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
    if api_key:
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

        # 配额预检
        _check_and_consume_quota_wrapper(user.id, "ai.text.advanced_calls.monthly_limit", 1, db, deduct=False)

        try:
            async with httpx.AsyncClient(timeout=300) as client:
                response = await client.post(
                    f"{deepseek_service.DEEPSEEK_BASE_URL}/chat/completions",
                    json={
                        "model": deepseek_service.DEEPSEEK_MODEL,
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
                content = str(data["choices"][0]["message"]["content"] or "").strip()
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
    # 配额扣减
    _check_and_consume_quota_wrapper(user.id, "ai.text.advanced_calls.monthly_limit", 1, db, deduct=True)
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
        raise HTTPException(404, "Version not found")

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
        raise HTTPException(404, "Version not found")
    if not (version.appearance_card or "").strip():
        raise HTTPException(400, "该版本尚无外貌卡，请先生成或编辑")

    style_name = str(body.get("style_preset") or "").strip()
    style_ctx: dict = {}
    if style_name:
        preset = db.query(VideoStylePreset).filter(VideoStylePreset.name == style_name).first()
        if not preset:
            preset = db.get(VideoStylePreset, int(style_name)) if style_name.isdigit() else None
        if preset:
            style_ctx = {
                "name": preset.name,
                "prompt_template": str(preset.image_style_params.get("prompt_template", "") if isinstance(preset.image_style_params, dict) else ""),
                "image_style_params": preset.image_style_params if isinstance(preset.image_style_params, dict) else {},
            }
    if not style_ctx:
        style_ctx = {"name": "", "prompt_template": "", "image_style_params": {}}

    final_prompt = _merge_style_prompt(
        str(version.appearance_card or ""),
        style_ctx.get("prompt_template"),
        style_ctx.get("name", ""),
    )
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
    img_size = style_ctx.get("image_style_params", {}).get("size", "1024x1024")

    char_dir = _VIDEO_OUTPUTS_DIR / f"story_{story_id}" / "characters"
    char_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}_{version.id}.png"
    full_path = char_dir / filename

    api_key = _user_image_api_key(request)

    # 配额预检
    _check_and_consume_quota_wrapper(user.id, "manga.image.monthly_limit", 1, db, deduct=False)

    try:
        await image2_service.generate_reference_image(
            prompt=final_prompt,
            output_path=full_path,
            api_key=api_key or None,
            size=img_size,
        )
    except Exception as e:
        logger.warning("Character ref generation failed for %s/%s: %s", character_name, version.version_label, e)
        raise HTTPException(502, f"角色参考图生成失败: {e}")

    file_path = str(full_path)
    ref_asset = VideoAsset(
        story_id=story_id,
        asset_type="story_character_reference",
        name=f"Character - {character_name} ({version.version_label})",
        file_path=file_path,
        provider="image2",
        prompt=version.appearance_card,
        style_preset=style_name or None,
        status="active",
    )
    db.add(ref_asset)
    db.flush()
    version.ref_asset_id = ref_asset.id
    db.commit()
    # 配额扣减
    _check_and_consume_quota_wrapper(user.id, "manga.image.monthly_limit", 1, db, deduct=True)
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
        raise HTTPException(404, "Version not found")
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
        raise HTTPException(404, "Version not found")
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

    source_path = _from_video_url(old_asset.file_path) or str(_VIDEO_OUTPUTS_DIR / (old_asset.file_path or ""))
    source_path_obj = Path(source_path)
    if not source_path_obj.exists():
        raise HTTPException(404, "参考图文件不存在，请重新生成")

    char_dir = _VIDEO_OUTPUTS_DIR / f"story_{story_id}" / "characters"
    char_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}_{version.id}.png"
    full_path = char_dir / filename

    api_key = _user_image_api_key(request)

    try:
        if mode == "partial" and mask_base64:
            import base64
            mask_bytes = base64.b64decode(mask_base64.split(",")[-1] if "," in mask_base64 else mask_base64)
            await image2_service.edit_existing_image(
                prompt=redraw_prompt,
                source_image_path=source_path_obj,
                output_path=full_path,
                mask_bytes=mask_bytes,
                api_key=api_key or None,
            )
        else:
            await image2_service.generate_reference_image(
                prompt=redraw_prompt,
                output_path=full_path,
                api_key=api_key or None,
            )
    except Exception as e:
        logger.warning("Character ref redraw failed for %s/%s: %s", character_name, version.version_label, e)
        raise HTTPException(502, f"角色参考图重绘失败: {e}")

    new_asset = VideoAsset(
        story_id=story_id,
        asset_type="story_character_reference",
        name=f"Character - {character_name} ({version.version_label})",
        file_path=str(full_path),
        provider="image2",
        prompt=redraw_prompt,
        style_preset=old_asset.style_preset,
        status="active",
    )
    db.add(new_asset)
    db.flush()
    version.ref_asset_id = new_asset.id
    db.commit()
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
    shot = db.get(VideoShot, shot_id)
    if not shot:
        raise HTTPException(404, "Video shot not found")

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
    shot = db.get(VideoShot, shot_id)
    if not shot:
        raise HTTPException(404, "Video shot not found")

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
    shot = db.get(VideoShot, shot_id)
    if not shot:
        raise HTTPException(404, "Video shot not found")

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
    asset = db.get(VideoAsset, asset_id)
    if not asset:
        raise HTTPException(404, "Video asset not found")

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
    asset = db.get(VideoAsset, asset_id)
    if not asset:
        raise HTTPException(404, "Video asset not found")

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
        raise HTTPException(404, "Scene not found")
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
        raise HTTPException(404, "Shot not found")
    if not shot.scene:
        raise HTTPException(404, "Scene not found")
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
        raise HTTPException(404, "Scene not found")
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
        raise HTTPException(404, "Shot not found")
    if not shot.scene:
        raise HTTPException(404, "Scene not found")
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
        raise HTTPException(404, "Shot not found")
    if not shot.scene:
        raise HTTPException(404, "Scene not found")
    _require_chapter_for_user(shot.scene.chapter_id, user, db)

    style_ctx = _resolve_effective_style_for_shot(shot, db, body.style_preset)
    style_name = style_ctx.get("name") or (body.style_preset or "")
    image_style_params = style_ctx.get("image_style_params") or {}
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
    ref_paths = _resolve_asset_file_paths(ref_assets)

    storyboards_dir = _VIDEO_OUTPUTS_DIR / "storyboards" / f"chapter_{shot.scene.chapter_id}" / f"shot_{shot_id}"
    storyboards_dir.mkdir(parents=True, exist_ok=True)
    file_name = f"storyboard_{datetime.datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}.png"
    full_path = storyboards_dir / file_name

    # 构建故事版 prompt（精简，避免图片 API 超时）
    duration = min(10, shot.duration_seconds or 10)
    content_full = shot.storyboard_prompt or shot.action_description or f"Shot {shot.shot_number}"
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
        f"- 视觉风格：专业影视故事板、电影导演提案板、高端电影预制作文档\n"
        f"- 统一留白、统一网格布局、高级质感\n"
        f"- 只输出一张完整的中文电影故事板展示图\n"
        f"- 角色形象严格匹配参考图"
    )
    prompt = _merge_style_prompt(
        storyboard_prompt.strip(),
        style_ctx.get("prompt_template"),
        style_name,
    )
    api_key = _user_image_api_key(request)

    # 配额预检
    _check_and_consume_quota_wrapper(user.id, "manga.image.monthly_limit", 1, db, deduct=False)

    try:
        await image2_service.generate_reference_image(
            prompt=prompt,
            output_path=full_path,
            api_key=api_key,
            size=image_style_params.get("size", "1792x1024"),
            ref_image_paths=ref_paths if ref_paths else None,
        )
    except Exception as e:
        logger.warning("Storyboard render failed (shot=%s): %s", shot_id, e)
        raise HTTPException(502, f"分镜图生成失败: {e}")

    file_path = f"storyboards/chapter_{shot.scene.chapter_id}/shot_{shot_id}/{file_name}"
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
        style_preset=style_name or None,
    )
    db.add(asset)

    shot.status = "storyboard_ready"
    shot.updated_at = datetime.datetime.utcnow()
    db.commit()
    # 配额扣减
    _check_and_consume_quota_wrapper(user.id, "manga.image.monthly_limit", 1, db, deduct=True)
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
        raise HTTPException(404, "Shot not found")
    if not shot.scene:
        raise HTTPException(404, "Scene not found")
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
        raise HTTPException(404, "Shot not found")
    if not shot.scene:
        raise HTTPException(404, "Scene not found")
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
        raise HTTPException(404, "Shot not found")
    if not shot.scene:
        raise HTTPException(404, "Scene not found")
    _require_chapter_for_user(shot.scene.chapter_id, user, db)

    asset_id = body.asset_id
    if not asset_id:
        raise HTTPException(400, "asset_id is required")

    asset = db.get(VideoAsset, asset_id)
    if not asset:
        raise HTTPException(404, "Asset not found")

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
        raise HTTPException(404, "Shot not found")
    if not shot.scene:
        raise HTTPException(404, "Scene not found")
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
        raise HTTPException(404, "Shot not found")
    if not shot.scene:
        raise HTTPException(404, "Scene not found")
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
    ref_paths = _resolve_asset_file_paths(ref_assets)

    api_key, _base_url, _model = _user_video_api_key(request)
    frames_dir = _VIDEO_OUTPUTS_DIR / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    # 配额预检（按实际生成帧数）
    frame_count = 2 if frame_type == "both" else 1
    _check_and_consume_quota_wrapper(user.id, "manga.image.monthly_limit", frame_count, db, deduct=False)

    assets = []

    for subtype in (["first_frame", "last_frame"] if frame_type == "both" else [frame_type]):
        if subtype == "first_frame":
            frame_phase = "first frame key visual, pre-action state"
        else:
            frame_phase = "last frame key visual, post-action state"
        prompt_seed = f"{frame_phase}. {prompt_base}".strip()
        prompt = _merge_style_prompt(f"{prompt_seed} {ref_block}".strip(), style_template, style_ctx.get("name", ""))
        prompt = prompt or "shot frame"

        filename = f"shot_{shot_id}_{subtype}_{uuid.uuid4().hex[:8]}.png"
        full_path = frames_dir / filename

        try:
            await image2_service.generate_reference_image(
                prompt=prompt,
                output_path=full_path,
                api_key=api_key or None,
                size=image_style_params.get("size", "1792x1024"),
                ref_image_paths=ref_paths if ref_paths else None,
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
    _check_and_consume_quota_wrapper(user.id, "manga.image.monthly_limit", frame_count, db, deduct=True)
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
        raise HTTPException(404, "Shot not found")
    if not shot.scene:
        raise HTTPException(404, "Scene not found")
    _require_chapter_for_user(shot.scene.chapter_id, user, db)

    old_asset = db.get(VideoAsset, body.asset_id)
    if not old_asset or old_asset.shot_id != shot_id:
        raise HTTPException(404, "Frame asset not found")

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
    ref_paths = _resolve_asset_file_paths(ref_assets)
    prompt = _merge_style_prompt(f"{prompt} {ref_block}".strip(), style_ctx.get("prompt_template"), style_ctx.get("name"))
    try:
        await image2_service.generate_reference_image(
            prompt=prompt,
            output_path=full_path,
            api_key=api_key or None,
            size=(style_ctx.get("image_style_params") or {}).get("size", "1792x1024"),
            ref_image_paths=ref_paths if ref_paths else None,
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
        raise HTTPException(404, "Shot not found")
    if not shot.scene:
        raise HTTPException(404, "Scene not found")
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
        raise HTTPException(404, "Shot not found")
    if not shot.scene:
        raise HTTPException(404, "Scene not found")
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
                    style_ctx=style_ctx,
                    story=story,
                    note_from_profiles=note,
                    inherited_prompt=inherited_prompt,
                ),
                "grounding": design_grounding,
            })

    duration = min(10, shot.duration_seconds or 10)
    segments = max(3, min(5, duration // 2))  # 10s → 5段×2s, 8s → 4段×2s
    seg_dur = duration // segments
    base_storyboard = _merge_style_prompt(
        (
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
        ),
        style_ctx.get("prompt_template"),
        style_name,
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
6. Keep style consistency with selected style preset.
7. Output valid JSON object only.

Selected style: {style_name}
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
            "model": deepseek_service.DEEPSEEK_MODEL,
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
                    f"{deepseek_service.DEEPSEEK_BASE_URL}/chat/completions",
                    json=payload,
                    headers=deepseek_service._deepseek_auth_headers(api_key),
                )
                response.raise_for_status()
                data = response.json()
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

            final_storyboard = str(result.get("storyboard_prompt") or "").strip() or base_storyboard
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
    fallback_storyboard = shot.storyboard_prompt or base_storyboard
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
        raise HTTPException(404, "Shot not found")
    if not shot.scene:
        raise HTTPException(404, "Scene not found")
    _require_chapter_for_user(shot.scene.chapter_id, user, db)

    character_name = str(body.get("character_name") or "Unknown").strip() or "Unknown"
    prompt = str(body.get("prompt") or "").strip()
    if not prompt:
        raise HTTPException(400, "Character prompt is required")

    style_ctx = _resolve_effective_style_for_shot(shot, db, body.get("style_preset"))
    style_name = style_ctx.get("name") or ""
    image_style_params = style_ctx.get("image_style_params") or {}

    chapter_id = shot.scene.chapter_id
    char_dir = _VIDEO_OUTPUTS_DIR / "character_refs" / f"chapter_{chapter_id}" / f"shot_{shot_id}"
    char_dir.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", character_name)
    file_name = f"{safe_name}_{uuid.uuid4().hex[:8]}.png"
    full_path = char_dir / file_name

    final_prompt = _merge_style_prompt(prompt, style_ctx.get("prompt_template"), style_name)
    api_key = _user_image_api_key(request)
    _configure_image_service_from_db(request, db)

    # 图生图：将顶部预选的风格参考图作为 img2img 源图传入
    style_ref_path = _resolve_workflow_style_ref_path(chapter_id, db)
    ref_paths = [style_ref_path] if style_ref_path else None

    # 配额预检
    _check_and_consume_quota_wrapper(user.id, "manga.image.monthly_limit", 1, db, deduct=False)

    try:
        await image2_service.generate_reference_image(
            prompt=final_prompt,
            output_path=full_path,
            api_key=api_key or None,
            size=image_style_params.get("size", "1792x1024"),
            ref_image_paths=ref_paths,
            ref_type="style",
        )
    except Exception as e:
        logger.warning("Character reference generation failed (shot=%s, name=%s): %s", shot_id, character_name, e)
        raise HTTPException(502, f"角色参考图生成失败: {e}")

    relative_path = f"character_refs/chapter_{chapter_id}/shot_{shot_id}/{file_name}"
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
        file_path=relative_path,
        provider="image2",
        prompt=final_prompt,
        source_asset_ids_json=source_asset_ids,
        style_preset=style_name or None,
    )
    db.add(asset)
    db.commit()
    # 配额扣减
    _check_and_consume_quota_wrapper(user.id, "manga.image.monthly_limit", 1, db, deduct=True)
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

    style_ctx = _resolve_effective_style_for_shot(shot, db, body.get("style_preset"))
    style_name = style_ctx.get("name") or ""
    image_style_params = style_ctx.get("image_style_params") or {}

    chapter_id = shot.scene.chapter_id
    prop_dir = _VIDEO_OUTPUTS_DIR / "prop_refs" / f"chapter_{chapter_id}" / f"shot_{shot_id}"
    prop_dir.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", prop_name)
    file_name = f"{safe_name}_{uuid.uuid4().hex[:8]}.png"
    full_path = prop_dir / file_name

    final_prompt = _merge_style_prompt(prompt, style_ctx.get("prompt_template"), style_name)
    api_key = _user_image_api_key(request)
    _configure_image_service_from_db(request, db)

    # 图生图：将顶部预选的风格参考图作为 img2img 源图传入
    style_ref_path = _resolve_workflow_style_ref_path(chapter_id, db)
    ref_paths = [style_ref_path] if style_ref_path else None

    _check_and_consume_quota_wrapper(user.id, "manga.image.monthly_limit", 1, db, deduct=False)

    try:
        await image2_service.generate_reference_image(
            prompt=final_prompt,
            output_path=full_path,
            api_key=api_key or None,
            size=image_style_params.get("size", "1792x1024"),
            ref_image_paths=ref_paths,
            ref_type="style",
        )
    except Exception as e:
        logger.warning("Prop reference generation failed (shot=%s, name=%s): %s", shot_id, prop_name, e)
        raise HTTPException(502, f"道具参考图生成失败: {e}")

    relative_path = f"prop_refs/chapter_{chapter_id}/shot_{shot_id}/{file_name}"
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
        file_path=relative_path,
        provider="image2",
        prompt=final_prompt,
        source_asset_ids_json=source_asset_ids,
        style_preset=style_name or None,
    )
    db.add(asset)
    db.commit()
    _check_and_consume_quota_wrapper(user.id, "manga.image.monthly_limit", 1, db, deduct=True)
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

    style_ctx = _resolve_effective_style_for_shot(shot, db, body.get("style_preset"))
    style_name = style_ctx.get("name") or ""
    image_style_params = style_ctx.get("image_style_params") or {}

    chapter_id = shot.scene.chapter_id
    scene_dir = _VIDEO_OUTPUTS_DIR / "scene_refs" / f"chapter_{chapter_id}" / f"shot_{shot_id}"
    scene_dir.mkdir(parents=True, exist_ok=True)
    file_name = f"scene_{uuid.uuid4().hex[:8]}.png"
    full_path = scene_dir / file_name

    final_prompt = _merge_style_prompt(prompt, style_ctx.get("prompt_template"), style_name)
    api_key = _user_image_api_key(request)
    _configure_image_service_from_db(request, db)

    # 图生图：将顶部预选的风格参考图作为 img2img 源图传入
    style_ref_path = _resolve_workflow_style_ref_path(chapter_id, db)
    ref_paths = [style_ref_path] if style_ref_path else None

    _check_and_consume_quota_wrapper(user.id, "manga.image.monthly_limit", 1, db, deduct=False)

    try:
        await image2_service.generate_reference_image(
            prompt=final_prompt,
            output_path=full_path,
            api_key=api_key or None,
            size=image_style_params.get("size", "1792x1024"),
            ref_image_paths=ref_paths,
            ref_type="style",
        )
    except Exception as e:
        logger.warning("Scene reference generation failed (shot=%s): %s", shot_id, e)
        raise HTTPException(502, f"场景参考图生成失败: {e}")

    relative_path = f"scene_refs/chapter_{chapter_id}/shot_{shot_id}/{file_name}"
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
        file_path=relative_path,
        provider="image2",
        prompt=final_prompt,
        source_asset_ids_json=source_asset_ids,
        style_preset=style_name or None,
    )
    db.add(asset)
    db.commit()
    _check_and_consume_quota_wrapper(user.id, "manga.image.monthly_limit", 1, db, deduct=True)
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
        raise HTTPException(404, "Shot not found")
    if not shot.scene:
        raise HTTPException(404, "Scene not found")
    _require_chapter_for_user(shot.scene.chapter_id, user, db)

    effective_provider = _resolve_video_provider(body.provider, db)

    duration = max(1, min(SHOT_DURATION_SECONDS, body.duration_seconds or shot.duration_seconds or SHOT_DURATION_SECONDS))
    _check_and_consume_quota_wrapper(
        user.id, "video.generate.seconds.monthly_limit", duration, db, deduct=False,
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
    ordered_images: list[str] = []
    # 用户未选首帧时，自动继承前一个镜头的尾帧作为连贯参考
    prev_last_frame = _get_previous_shot_last_frame(shot, db) if not first_frame_asset else None
    if prev_last_frame:
        p = _resolve_asset_file_paths([prev_last_frame])
        b = _encode_file_to_base64_data_uri(p[0]) if p else None
        if b:
            ordered_images.append(b)
            if not first_frame_asset:
                first_frame_url_text = b[:80] + "..."
                logger.info("Shot %s: 继承前镜头尾帧作为首帧连贯参考", shot_id)
    if first_frame_asset:
        path = _resolve_asset_file_paths([first_frame_asset])
        b64 = _encode_file_to_base64_data_uri(path[0]) if path else None
        if b64:
            ordered_images.append(b64)
    ordered_images.extend(_resolve_asset_reference_urls([a.id for a in other_refs], db, request) if other_refs else [])
    if last_frame_asset:
        path = _resolve_asset_file_paths([last_frame_asset])
        b64 = _encode_file_to_base64_data_uri(path[0]) if path else None
        if b64:
            ordered_images.append(b64)

    style_ctx = _resolve_effective_style_for_shot(shot, db, requested_style_name=body.style)
    style_name = style_ctx["name"]
    video_style_params = style_ctx["video_style_params"]
    style_template = style_ctx["prompt_template"]

    api_key, base_url, resolved_model = _user_video_api_key(request)
    resolved_model = body.model or resolved_model
    aspect_ratio = body.aspect_ratio or video_style_params.get("aspect_ratio") or "16:9"
    grounding = _build_story_grounding_block(shot.scene.chapter.story if shot.scene and shot.scene.chapter else None, shot.scene.chapter if shot.scene else None, shot.scene)
    storyboard_guide = ""
    if shot.storyboard_prompt:
        storyboard_guide = (
            f"\n\n<<<STORYBOARD_BLUEPRINT>>>\n"
            f"This is the shot-by-shot storyboard that the video MUST follow:\n"
            f"{shot.storyboard_prompt}\n"
            f"<<<END_BLUEPRINT>>>\n"
            f"CRITICAL: Generate video matching EVERY time segment, camera movement, "
            f"character action, and dialogue in the storyboard blueprint above."
        )
    full_prompt = _merge_style_prompt(
        f"{body.prompt or shot.video_prompt or ''}{storyboard_guide} {ref_block} Grounding: {grounding}".strip(),
        style_template, style_name,
    )

    task_id = f"video_render_{shot_id}_{int(datetime.datetime.utcnow().timestamp())}"
    await task_manager.submit_task(
        task_id=task_id,
        task_type="video_render",
        coro_func=video_gen_service.submit_video_job,
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
        timeout=600,
        max_retries=2,
    )

    job_status = "pending"
    job = VideoGenerationJob(
        shot_id=shot_id,
        provider=effective_provider,
        provider_job_id=task_id,
        model=resolved_model,
        request_payload_json={
            "model": resolved_model,
            "prompt": full_prompt,
            "negative_prompt": body.negative_prompt or shot.negative_prompt or "",
            "duration_seconds": duration,
            "aspect_ratio": aspect_ratio,
            "style": style_name,
            "reference_asset_ids": auto_reference_asset_ids,
            "reference_image_urls": reference_image_urls,
        },
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

    _check_and_consume_quota_wrapper(
        user.id, "video.generate.seconds.monthly_limit", duration, db, deduct=True,
    )

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
            "request_payload": job.request_payload_json or {},
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
        bgm_path=body.bgm_path or "",
        cover_path=body.cover_path or "",
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
        raise HTTPException(404, "Video project not found")

    # Validate ownership via chapter
    if project.chapter_id:
        _require_chapter_for_user(project.chapter_id, user, db)
    elif project.story_id:
        _require_story_for_user(project.story_id, user, db)
    else:
        raise HTTPException(403, "Cannot determine project ownership")

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
        raise HTTPException(404, "Video project not found")

    if project.chapter_id:
        _require_chapter_for_user(project.chapter_id, user, db)
    elif project.story_id:
        _require_story_for_user(project.story_id, user, db)
    else:
        raise HTTPException(403, "Cannot determine project ownership")

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
            setattr(project, model_field, update_data[body_field])

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
        raise HTTPException(404, "Video project not found")

    if project.chapter_id:
        _require_chapter_for_user(project.chapter_id, user, db)
    elif project.story_id:
        _require_story_for_user(project.story_id, user, db)
    else:
        raise HTTPException(403, "Cannot determine project ownership")

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

        video_path = _from_video_url(clip.video_path)
        if not video_path:
            logger.warning("Could not resolve path for clip %s: %s", clip_id, clip.video_path)
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
        bgm_path = _from_video_url(project.bgm_path)

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

def _check_and_consume_quota_wrapper(
    user_id: int,
    feature_key: str,
    amount: int,
    db: Session,
    deduct: bool,
) -> dict:
    """Minimal quota check/consume inline (avoids circular import from main.py)."""
    if amount <= 0:
        amount = 1

    from models import Plan, PlanFeature, UserSubscription, UserUsageMonthly, UserQuotaGrantMonthly

    sub = db.query(UserSubscription).filter(UserSubscription.user_id == user_id).first()
    plan = None
    if sub:
        plan = db.get(Plan, sub.plan_id)
    if not plan:
        plan = db.query(Plan).filter(Plan.code == "free").first()
    if not plan:
        if not deduct:
            return {"used": 0, "limit": 0, "feature_key": feature_key, "period_key": "", "base_limit": 0, "granted": 0}
        raise HTTPException(500, "No plan configured")

    feature = (
        db.query(PlanFeature)
        .filter(PlanFeature.plan_id == plan.id, PlanFeature.feature_key == feature_key)
        .first()
    )
    base_limit = 0
    if feature and feature.value_json:
        base_limit = int(feature.value_json.get("value", 0))

    period_key = datetime.datetime.utcnow().strftime("%Y%m")

    grant = (
        db.query(UserQuotaGrantMonthly)
        .filter(
            UserQuotaGrantMonthly.user_id == user_id,
            UserQuotaGrantMonthly.feature_key == feature_key,
            UserQuotaGrantMonthly.period_key == period_key,
        )
        .first()
    )
    granted = int(grant.granted_amount) if grant else 0
    limit = base_limit + granted

    usage = (
        db.query(UserUsageMonthly)
        .filter(
            UserUsageMonthly.user_id == user_id,
            UserUsageMonthly.feature_key == feature_key,
            UserUsageMonthly.period_key == period_key,
        )
        .first()
    )
    used = int(usage.used_amount) if usage else 0

    if not deduct:
        return {
            "used": used,
            "limit": limit,
            "feature_key": feature_key,
            "period_key": period_key,
            "base_limit": base_limit,
            "granted": granted,
        }

    if limit <= 0:
        raise HTTPException(403, f"Feature not available in your current plan: {feature_key}")
    if used + amount > limit:
        raise HTTPException(429, f"Quota exceeded for {feature_key} ({used}/{limit})")

    if usage:
        usage.used_amount = used + amount
    else:
        db.add(UserUsageMonthly(
            user_id=user_id,
            feature_key=feature_key,
            period_key=period_key,
            used_amount=amount,
        ))
    db.flush()

    return {
        "used": used + amount,
        "limit": limit,
        "feature_key": feature_key,
        "period_key": period_key,
        "base_limit": base_limit,
        "granted": granted,
    }


# ── 章节视频工作流 API ────────────────────────────────────


@router.post("/api/video/chapter-workflows", response_model=ChapterVideoWorkflowOut)
async def api_create_chapter_workflow(
    body: ChapterVideoWorkflowCreate,
    request: Request,
    db: Session = Depends(get_db),
):
    """创建并启动章节视频工作流。"""
    global _db_schema_verified

    user = _require_user(request, db)
    chapter = _require_chapter_for_user(body.chapter_id, user, db)

    # init_db 在整个进程生命周期中只执行一次
    if not _db_schema_verified:
        init_db(run_migrations=True, raise_errors=True)
        _db_schema_verified = True

    # 若未传入参考图 ID，从角色库默认版本自动填充
    ref_ids = body.character_reference_ids
    if not ref_ids:
        ref_ids = _get_story_character_reference_asset_ids(chapter.story_id, db)

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
    return ChapterVideoWorkflowListOut(
        workflows=[ChapterVideoWorkflowOut.model_validate(w) for w in workflows],
        total=len(workflows),
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

    return ChapterVideoWorkflowStatusOut(
        id=wf.id,
        chapter_id=wf.chapter_id,
        workflow_status=wf.workflow_status,
        total_shots=wf.total_shots,
        completed_shots=wf.completed_shots,
        failed_shots=wf.failed_shots,
        error_message=wf.error_message,
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

    task_manager.request_cancellation(f"chapter_video_{workflow_id}")
    update_chapter_workflow_status(workflow_id, "failed", "用户取消")
    return {"ok": True, "message": "已请求取消章节视频工作流"}


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
    updated_shot = await regenerate_shot_storyboard(
        shot_id,
        api_key,
        body.prompt_override,
        ref_asset_ids=ref_asset_ids,
    )

    if not updated_shot:
        raise HTTPException(500, "重新生成故事版失败")

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
    """重新生成单镜头的视频。"""
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

    # 从数据库读取视频 API 配置并注入运行时
    _configure_video_service_from_db(request, db)
    # 从数据库读取 DeepSeek API 配置并注入运行时
    deepseek_api_key = _user_deepseek_api_key(request, db)

    api_key, base_url, model = _user_video_api_key(request)
    ref_asset_ids = body.reference_asset_ids or None
    try:
        updated_shot = await regenerate_shot_video(shot_id, api_key, body.prompt_override, ref_asset_ids=ref_asset_ids, base_url=base_url, model=model, deepseek_api_key=deepseek_api_key, aspect_ratio=body.aspect_ratio or "16:9")
    except Exception as exc:
        if "视频 API 地址未配置" in str(exc) or "视频生成模型未配置" in str(exc):
            raise HTTPException(400, str(exc))
        raise

    if not updated_shot:
        raise HTTPException(500, "重新生成视频失败")

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
    if "video_prompt" in body:
        shot.video_prompt = body["video_prompt"]
    db.commit()
    db.refresh(shot)
    return {"ok": True, "shot": ChapterVideoShotOut.model_validate(shot)}


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
    try:
        result = await reanalyze_shot_prompts(shot_id, deepseek_api_key=deepseek_api_key)
    except Exception as exc:
        raise HTTPException(500, f"重新分析失败: {exc}")

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
    output_path.write_bytes(data)
    rel_path = str(output_path.relative_to(_VIDEO_OUTPUTS_DIR.resolve()))
    shot.storyboard_image_url = f"/static/video/{rel_path}"

    # OSS 上传（如已配置，上传成功后更新 URL 并删除本地文件）
    from services.oss import upload_and_cleanup as _oss_upload
    oss_url = _oss_upload(str(output_path))
    if oss_url:
        shot.storyboard_image_url = oss_url

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
    output_path.write_bytes(data)
    rel_path = str(output_path.relative_to(_VIDEO_OUTPUTS_DIR.resolve()))
    shot.video_url = f"/static/video/{rel_path}"

    # OSS 上传（如已配置，上传成功后更新 URL 并删除本地文件）
    from services.oss import upload_and_cleanup as _oss_upload
    oss_url = _oss_upload(str(output_path))
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
    try:
        result = await reanalyze_storyboard_prompts(
            workflow_id,
            shot_ids=shot_ids,
            deepseek_api_key=deepseek_api_key,
        )
    except Exception as exc:
        raise HTTPException(500, f"重新分析失败: {exc}")

    return result


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
        result = concat_chapter_videos(workflow_id)
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

    if wf.workflow_status not in ("pending", "shots_ready", "parsing_shots", "failed"):
        raise HTTPException(400, f"当前状态 {wf.workflow_status} 不允许拆镜操作")

    deepseek_api_key = _user_deepseek_api_key(request, db)
    if not deepseek_api_key:
        raise HTTPException(400, "请配置 DeepSeek API Key")

    # 从 DB 读取最新章节内容（替代工作流创建时的快照）
    chapter = db.get(Chapter, wf.chapter_id)
    current_source_text = (chapter.novel_content or "").strip() if chapter else ""
    if not current_source_text:
        raise HTTPException(400, "章节正文为空，请先在工作台中生成章节内容后再拆镜")

    # 同步更新工作流 source_text，确保后续阶段（补全提示词等）使用一致内容
    wf_in_db = db.get(ChapterVideoWorkflow, workflow_id)
    if wf_in_db and wf_in_db.source_text != current_source_text:
        wf_in_db.source_text = current_source_text
        db.commit()

    task_id = f"chapter_video_{workflow_id}_stage_{uuid.uuid4().hex[:8]}"

    result = await parse_chapter_shots(
        workflow_id=workflow_id,
        chapter_id=wf.chapter_id,
        story_id=wf.story_id,
        source_text=current_source_text,
        deepseek_api_key=deepseek_api_key,
        task_id=task_id,
    )

    return result


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

    result = await generate_shot_details_batch(
        workflow_id=workflow_id,
        shot_ids=body.shot_ids,
        chapter_text=wf.source_text or "",
        story_id=wf.story_id,
        deepseek_api_key=deepseek_api_key,
    )

    return result


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
    with open(file_path, "wb") as f:
        f.write(content)

    # 更新工作流
    relative_path = f"style_references/{filename}"

    from services import oss as oss_service
    _configure_oss_from_db(db)
    oss_url = oss_service.upload_file(str(file_path))
    if oss_url:
        logger.info("工作流风格参考图已上传到 OSS: %s", oss_url)
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

    result = await generate_storyboards_for_shots(
        workflow_id=workflow_id,
        story_id=wf.story_id,
        shot_ids=body.shot_ids or None,
        image_api_key=image_api_key,
        deepseek_api_key=deepseek_api_key,
        character_reference_ids=wf.character_reference_ids,
        task_id=task_id,
    )

    return result


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

    if not image_api_key:
        raise HTTPException(400, "请提供 Image API Key")

    # 从数据库读取视频 API 配置并注入运行时
    _configure_video_service_from_db(request, db)
    video_api_key, video_base_url, video_model = _user_video_api_key(request)

    task_id = f"chapter_video_{workflow_id}_stage_{uuid.uuid4().hex[:8]}"

    result = await generate_videos_for_shots(
        workflow_id=workflow_id,
        shot_ids=body.shot_ids or None,
        image_api_key=image_api_key,
        deepseek_api_key=deepseek_api_key,
        video_api_key=video_api_key,
        video_base_url=video_base_url,
        video_model=video_model,
        task_id=task_id,
    )

    return result


@router.post("/api/video/chapter-workflows/{workflow_id}/run-all")
async def api_run_all_stages(
    workflow_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """一键全自动：依次执行拆镜→故事版→视频三个阶段。"""
    user = _require_user(request, db)
    wf = get_chapter_workflow(workflow_id)
    if not wf:
        raise HTTPException(404, "工作流不存在")
    story = db.get(Story, wf.story_id)
    if not story or story.owner_user_id != user.id:
        raise HTTPException(403, "无权访问")

    deepseek_api_key = _user_deepseek_api_key(request, db)
    image_api_key = _user_image_api_key(request)

    if not deepseek_api_key:
        raise HTTPException(400, "请配置 DeepSeek API Key")

    if not image_api_key:
        raise HTTPException(400, "请提供 Image API Key")

    # 从数据库读取视频 API 配置并注入运行时
    _configure_video_service_from_db(request, db)
    video_api_key, video_base_url, video_model = _user_video_api_key(request)

    task_id = f"chapter_video_{workflow_id}_stage_{uuid.uuid4().hex[:8]}"

    result = await run_all_stages(
        workflow_id=workflow_id,
        chapter_id=wf.chapter_id,
        story_id=wf.story_id,
        source_text=wf.source_text or "",
        character_reference_ids=wf.character_reference_ids,
        deepseek_api_key=deepseek_api_key,
        image_api_key=image_api_key,
        video_api_key=video_api_key,
        video_base_url=video_base_url,
        video_model=video_model,
        task_id=task_id,
    )

    return result
