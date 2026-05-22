"""Video production workflow router.

Handles screenplay, shot breakdown, storyboard, video generation,
asset management, and video project compilation endpoints.
"""

import datetime
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from database import get_db
from models import (
    Chapter,
    PlatformSetting,
    ScriptScene,
    Story,
    User,
    UserSession,
    VideoAsset,
    VideoGenerationJob,
    VideoProject,
    RenderedClip,
    VideoShot,
)
from schemas import (
    CreateVideoAssetRequest,
    CreateVideoProjectRequest,
    CompileProjectRequest,
    GeneratePromptsRequest,
    GenerateScreenplayRequest,
    GenerateShotsRequest,
    RegenerateScenesRequest,
    RetryJobRequest,
    ScriptSceneUpdate,
    StoryboardRenderRequest,
    VideoProjectUpdate,
    VideoRenderRequest,
    VideoShotUpdate,
)
from services.screenplay import generate_screenplay, regenerate_scenes
from services.storyboard import generate_shots, generate_shot_prompts as generate_shot_prompts_service
from services import deepseek as deepseek_service
from services import video_generation as video_gen_service
from services import video_api as video_api_service

logger = logging.getLogger("video_router")

router = APIRouter()


# ─── Helper functions (mirrored from main.py patterns) ────────────────

def _user_video_api_key(request: Request) -> str | None:
    key = (request.headers.get("x-video-api-key") or "").strip()
    db = getattr(request.state, "db", None)
    if db is None:
        return key or None

    user = getattr(request.state, "current_user", None)
    capabilities = _user_api_override_capabilities(user, db)
    override_base_url = request.headers.get("x-video-base-url") or None
    override_model = request.headers.get("x-video-model") or None
    admin_base_url = str(_get_platform_setting("api.video.base_url", db, video_api_service.VIDEO_API_BASE_URL)).strip()
    admin_model = str(_get_platform_setting("api.video.model", db, video_api_service.DEFAULT_MODEL)).strip()
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

    if resolved_base_url:
        video_api_service.VIDEO_API_BASE_URL = resolved_base_url.rstrip("/")
    if resolved_model:
        video_api_service.DEFAULT_MODEL = resolved_model

    if capabilities["can_override_api_key"] and key:
        video_api_service.VIDEO_API_KEY = key
        return key

    if admin_api_key:
        video_api_service.VIDEO_API_KEY = admin_api_key
        return admin_api_key

    return key or None


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
    deepseek_service.DEEPSEEK_BASE_URL = resolved_base_url.rstrip("/") or deepseek_service.DEEPSEEK_BASE_URL
    deepseek_service.DEEPSEEK_MODEL = resolved_model or deepseek_service.DEEPSEEK_MODEL
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
        "continuity_notes": shot.continuity_notes or "",
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


# ─── Chapter Screenplay Endpoints ───────────────────────────

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

    # Generate screenplay via mock service
    result = await generate_screenplay(
        chapter_content=chapter.novel_content or "",
        style=body.style or "cinematic",
        scene_count_hint=body.scene_count_hint or 5,
        target_duration_seconds=body.target_duration_seconds or 90,
        api_key=_user_deepseek_api_key(request, db),
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
            mood=scene_data.get("mood", "中立"),
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

    # Generate new scenes
    scenes_data = await regenerate_scenes(
        existing_screenplay=chapter.screenplay_text or chapter.novel_content or "",
        instruction=body.instruction or "重新生成",
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
            mood=scene_data.get("mood", "中立"),
            estimated_duration_seconds=scene_data["estimated_duration_seconds"],
            source_type="regenerated",
            status="draft",
        )
        db.add(scene)
        scenes.append(scene)

    db.commit()

    for scene in scenes:
        db.refresh(scene)

    return {
        "chapter_id": chapter_id,
        "scenes": [_serialize_scene(s) for s in scenes],
    }


# ─── Scene Endpoints ──────────────────────────────────────

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

    # Generate shots via mock service
    shots_data = await generate_shots(
        scene_title=scene.title or "",
        scene_summary=scene.summary or "",
        scene_dialogue=scene.dialogue_json or [],
        scene_mood=scene.mood or "",
        shot_count_hint=body.shot_count_hint or 4,
        duration_budget_seconds=body.duration_budget_seconds or 18,
        style=body.style or "cinematic",
        api_key=_user_deepseek_api_key(request, db),
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


# ─── Shot Endpoints ──────────────────────────────────────

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
    _require_chapter_for_user(shot.scene.chapter_id, user, db)

    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if value is not None:
            setattr(shot, field, value)

    shot.updated_at = datetime.datetime.utcnow()
    db.commit()
    db.refresh(shot)

    return _serialize_shot(shot)


@router.post("/api/shots/{shot_id}/prompts/generate")
async def generate_shot_prompts(
    shot_id: int,
    body: GeneratePromptsRequest,
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

    shot_info = {
        "shot_type": shot.shot_type,
        "camera_angle": shot.camera_angle,
        "camera_movement": shot.camera_movement,
        "action_description": shot.action_description,
    }

    prompts = await generate_shot_prompts_service(
        shot_info=shot_info,
        style=body.style or "cinematic",
        provider=body.provider or "sora",
        continuity_notes=body.continuity_notes or shot.continuity_notes or "",
        api_key=_user_deepseek_api_key(request, db),
    )

    shot.storyboard_prompt = prompts.get("storyboard_prompt", "")
    shot.video_prompt = prompts.get("video_prompt", "")
    shot.negative_prompt = prompts.get("negative_prompt", "")
    shot.status = "prompt_ready"
    shot.updated_at = datetime.datetime.utcnow()
    db.commit()
    db.refresh(shot)

    # Find reference assets for this shot's scene
    reference_assets = (
        db.query(VideoAsset)
        .filter(
            VideoAsset.scene_id == shot.scene_id,
            VideoAsset.asset_type.in_(["scene_reference", "character_reference", "style_reference"]),
        )
        .all()
    )

    return {
        "shot": _serialize_shot(shot),
        "reference_assets": [
            {
                "id": a.id,
                "name": a.name,
                "file_path": a.file_path,
                "asset_type": a.asset_type,
            }
            for a in reference_assets
        ],
    }


@router.post("/api/shots/{shot_id}/storyboard/render")
async def render_shot_storyboard(
    shot_id: int,
    body: StoryboardRenderRequest,
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

    # Create VideoAsset record for storyboard frame
    file_path = body.output_path or f"/static/video/storyboards/shot_{shot_id}_storyboard.png"
    asset = VideoAsset(
        story_id=shot.scene.chapter.story_id if shot.scene.chapter else None,
        chapter_id=shot.scene.chapter_id,
        scene_id=shot.scene_id,
        shot_id=shot_id,
        asset_type="storyboard_frame",
        name=f"Storyboard - Shot {shot.shot_number}",
        file_path=file_path,
        provider=body.provider or "mock",
        prompt=shot.storyboard_prompt or "",
    )
    db.add(asset)

    # Update shot status
    shot.status = "storyboard_ready"
    shot.updated_at = datetime.datetime.utcnow()
    db.commit()
    db.refresh(shot)
    db.refresh(asset)

    return {
        "shot_id": shot_id,
        "asset": {
            "id": asset.id,
            "name": asset.name,
            "file_path": asset.file_path,
            "asset_type": asset.asset_type,
        },
        "shot_status": shot.status,
    }


@router.post("/api/shots/{shot_id}/video/render")
async def render_shot_video(
    shot_id: int,
    body: VideoRenderRequest,
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

    # Check quota for video generation (by seconds)
    duration = max(1, body.duration_seconds or shot.duration_seconds or 5)
    _check_and_consume_quota_wrapper(
        user.id, "video.generate.seconds.monthly_limit", duration, db, deduct=False,
    )

    # 先解析 API Key 和模型名称（_user_video_api_key 会从数据库读取管理端设置
    # 并更新 video_api_service.DEFAULT_MODEL，因此必须在引用 DEFAULT_MODEL 之前调用）
    api_key = _user_video_api_key(request)
    resolved_model = body.model or video_api_service.DEFAULT_MODEL

    # Submit job to mock provider
    job_result = await video_gen_service.submit_video_job(
        shot_id=shot_id,
        provider=body.provider or "mock",
        model=resolved_model,
        prompt=body.prompt or shot.video_prompt or "",
        negative_prompt=body.negative_prompt or shot.negative_prompt or "",
        duration_seconds=duration,
        aspect_ratio=body.aspect_ratio or "16:9",
        api_key=api_key,
    )

    # Create VideoGenerationJob record
    job_status = job_result.get("status", "queued")
    job = VideoGenerationJob(
        shot_id=shot_id,
        provider=body.provider or "mock",
        provider_job_id=job_result.get("provider_job_id", ""),
        model=resolved_model,
        request_payload_json={
            "model": resolved_model,
            "prompt": body.prompt or shot.video_prompt or "",
            "negative_prompt": body.negative_prompt or shot.negative_prompt or "",
            "duration_seconds": duration,
            "aspect_ratio": body.aspect_ratio or "16:9",
            "style": body.style or "",
        },
        status=job_status,
        progress=int(job_result.get("progress", 0) or 0),
        duration_seconds=duration,
        aspect_ratio=body.aspect_ratio or "16:9",
        error_message=job_result.get("error"),
    )
    db.add(job)
    db.flush()

    # Update shot status
    shot.status = "failed" if job_status == "failed" else "rendering"
    shot.updated_at = datetime.datetime.utcnow()

    if job_status != "failed":
        _check_and_consume_quota_wrapper(
            user.id, "video.generate.seconds.monthly_limit", duration, db, deduct=True,
        )

    db.commit()
    db.refresh(job)

    if job_status == "failed":
        raise HTTPException(
            status_code=502,
            detail=job.error_message or "Video provider rejected the request",
        )

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
            "submitted_at": _serialize_datetime(job.submitted_at),
            "completed_at": _serialize_datetime(job.completed_at),
        },
        "shot_status": shot.status,
        "usage": _serialize_usage(quota_result["used"], quota_result["limit"]),
    }


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


# ─── Video Job Endpoints ──────────────────────────────────

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

    # Find associated clip if job succeeded
    clip = None
    if job.status == "succeeded":
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


# ─── Video Asset Endpoints ────────────────────────────────

@router.get("/api/chapters/{chapter_id}/video-assets")
async def list_chapter_video_assets(
    chapter_id: int,
    request: Request,
    asset_type: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    _require_chapter_for_user(chapter_id, user, db)

    query = db.query(VideoAsset).filter(VideoAsset.chapter_id == chapter_id)
    if asset_type:
        query = query.filter(VideoAsset.asset_type == asset_type)

    assets = query.order_by(VideoAsset.created_at.desc()).all()

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
                "file_path": a.file_path,
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

    asset = VideoAsset(
        story_id=body.story_id if body.story_id is not None else chapter.story_id,
        chapter_id=chapter_id,
        scene_id=body.scene_id,
        shot_id=body.shot_id,
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

    db.delete(asset)
    db.commit()

    return {"ok": True, "asset_id": asset_id}


# ─── Video Project Endpoints ──────────────────────────────

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

    # Mock: set status to compiled, set output path
    output_filename = f"video_project_{project_id}_{uuid.uuid4().hex[:8]}.mp4"
    output_path = f"/static/video/projects/{output_filename}"

    project.status = "compiled"
    project.output_path = output_path
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
    }


# ─── Internal helpers ─────────────────────────────────────

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
