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

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from database import SessionLocal, get_db
_VIDEO_OUTPUTS_DIR = Path(__file__).resolve().parent.parent / "video_outputs"

def _to_video_url(local_path: str) -> str:
    p = Path(local_path)
    try:
        rel = p.relative_to(_VIDEO_OUTPUTS_DIR)
        return f"/static/video/{rel.as_posix()}"
    except ValueError:
        return local_path


def _from_video_url(video_url: str) -> str | None:
    url = video_url.strip()
    if not url:
        return None
    if os.path.isabs(url):
        return url
    if url.startswith("/static/video/"):
        rel = url[len("/static/video/"):]
        return str(_VIDEO_OUTPUTS_DIR / rel)
    return str(Path(__file__).resolve().parent.parent / url)


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
    VideoStylePreset,
    RenderedClip,
    VideoShot,
)
from schemas import (
    ChapterStylePresetUpdate,
    CreateVideoAssetRequest,
    CreateVideoProjectRequest,
    CompileProjectRequest,
    GeneratePromptsRequest,
    GenerateScreenplayRequest,
    GenerateShotsRequest,
    GenerateShotFramesRequest,
    RegenerateScenesRequest,
    RegenerateShotFrameRequest,
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
from services import video_api as video_api_service
from services import video_qa
from services.video_compiler import compile_project

logger = logging.getLogger("video_router")

router = APIRouter()


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
    style_prefix = template or (f"Style: {name}" if name else "")
    if not style_prefix:
        return base
    if not base:
        return style_prefix
    return f"{style_prefix}. {base}"


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
        f"Role: {role}. "
        f"Personality/arc cues: {arc}. "
        f"Trait cues: {traits}. "
        f"Appearance notes: {note_from_profiles}. "
        f"Reference anchor: {inherited_prompt}. "
        "Must keep stable identity markers (face shape, hairstyle, eye shape, signature colors, silhouette). "
        "High-detail character sheet for reusable animation/video consistency."
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
    include_characters: bool = True,
    include_scene: bool = True,
    include_storyboard: bool = True,
    include_frames: bool = True,
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


def _select_character_reference_assets_for_scene(scene: ScriptScene, db: Session, limit: int = 6) -> list[VideoAsset]:
    chapter_id = scene.chapter_id
    scene_characters = [str(c).strip() for c in (scene.characters_json or []) if str(c).strip()]
    all_assets = (
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
        return all_assets[:limit]

    matched: list[VideoAsset] = []
    used_ids: set[int] = set()
    for ch in scene_characters:
        for a in all_assets:
            if a.id in used_ids:
                continue
            name = (a.name or "")
            prompt = (a.prompt or "")
            if ch in name or ch in prompt:
                matched.append(a)
                used_ids.add(a.id)
                break

    if len(matched) < limit:
        for a in all_assets:
            if a.id in used_ids:
                continue
            matched.append(a)
            if len(matched) >= limit:
                break
    return matched[:limit]


def _build_reference_constraints_block(character_assets: list[VideoAsset]) -> str:
    """Build hard character identity constraints from existing reference assets."""
    if not character_assets:
        return ""
    parts = ["<<<CHARACTER_LOCK_PROTOCOL>>>"]
    for a in character_assets:
        asset_id = a.id
        name = a.name or "character"
        prompt_snippet = (a.prompt or "")[:200]
        locked_markers = ""
        if a.locked:
            locked_markers = " [LOCKED-涓嶅彲淇敼]"
        if a.is_master:
            locked_markers += " [MASTER-涓荤増鏈弬鑰僝"
        parts.append(
            f"[CHARACTER_ID:{asset_id}] {name}{locked_markers}: "
            f"{prompt_snippet}"
        )
    parts.append(
        "<<<END_LOCK>>> "
        "MANDATORY: face structure, hairstyle, body proportions, costume silhouette, "
        "and identity colors of the above CHARACTER_ID entries MUST remain exactly as described. "
        "These identity anchors override any conflicting description elsewhere."
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

        if fp.startswith("http://") or fp.startswith("https://"):
            urls.append(fp)
        elif fp.startswith("/"):
            local_path = _from_video_url(fp) or str(_VIDEO_OUTPUTS_DIR / fp.lstrip("/static/video/"))
            b64_data = _encode_file_to_base64_data_uri(local_path)
            if b64_data:
                urls.append(b64_data)
        else:
            # 相对路径 → 基于 video_outputs 目录拼接
            local_path = str(_VIDEO_OUTPUTS_DIR / fp)
            b64_data = _encode_file_to_base64_data_uri(local_path)
            if b64_data:
                urls.append(b64_data)

    logger.info("解析 %d 个参考资产为 %d 个图片数据", len(asset_ids), len(urls))
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

    for scene in scenes:
        db.refresh(scene)

    return {
        "chapter_id": chapter_id,
        "scenes": [_serialize_scene(s) for s in scenes],
    }


# 鈹€鈹€鈹€ Scene Endpoints 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

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
        duration_budget_seconds=body.duration_budget_seconds or 18,
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

    api_key, _base_url, _model = _user_video_api_key(request)
    try:
        await image2_service.generate_reference_image(
            prompt=prompt,
            output_path=full_path,
            api_key=api_key or None,
            size=image_style_params.get("size", "1920x1080"),
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
    duration = max(1, body.duration_seconds or shot.duration_seconds or 5)
    _check_and_consume_quota_wrapper(
        user.id, "video.generate.seconds.monthly_limit", duration, db, deduct=False,
    )

    source_storyboard_asset_id = body.source_storyboard_asset_id or shot.storyboard_asset_id
    auto_reference_asset_ids = _collect_shot_reference_asset_ids(
        shot,
        db,
        include_characters=True,
        include_scene=True,
        include_storyboard=True,
        include_frames=True,
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
        if source_storyboard_asset_id and shot.storyboard_locked:
            input_mode = "image_to_video"
        else:
            input_mode = "text_to_video"

    # Warn if storyboard exists but not locked
    if source_storyboard_asset_id and not shot.storyboard_locked and input_mode == "image_to_video":
        logger.warning(
            "Shot %s storyboard not locked, but image_to_video requested. "
            "Consider approving the storyboard first.", shot_id
        )

    style_ctx = _resolve_effective_style_for_shot(shot, db, requested_style_name=body.style)
    style_name = style_ctx["name"]
    video_style_params = style_ctx["video_style_params"]
    style_template = style_ctx["prompt_template"]

    api_key, base_url, resolved_model = _user_video_api_key(request)
    resolved_model = body.model or resolved_model
    aspect_ratio = body.aspect_ratio or video_style_params.get("aspect_ratio") or "16:9"
    grounding = _build_story_grounding_block(shot.scene.chapter.story if shot.scene and shot.scene.chapter else None, shot.scene.chapter if shot.scene else None, shot.scene)
    full_prompt = _merge_style_prompt(f"{body.prompt or shot.video_prompt or ''} Grounding: {grounding}".strip(), style_template, style_name)

    job_result = await video_gen_service.submit_video_job(
        shot_id=shot_id,
        provider=effective_provider,
        model=resolved_model,
        prompt=full_prompt,
        negative_prompt=body.negative_prompt or shot.negative_prompt or "",
        duration_seconds=duration,
        aspect_ratio=aspect_ratio,
        reference_images=reference_image_urls if reference_image_urls else None,
        api_key=api_key,
        base_url=base_url,
    )

    job_status = job_result.get("status", "queued")
    job = VideoGenerationJob(
        shot_id=shot_id,
        provider=effective_provider,
        provider_job_id=job_result.get("provider_job_id", ""),
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
        progress=int(job_result.get("progress", 0) or 0),
        duration_seconds=duration,
        aspect_ratio=aspect_ratio,
        error_message=job_result.get("error"),
        input_mode=input_mode,
        source_storyboard_asset_id=source_storyboard_asset_id if input_mode == "image_to_video" else None,
        reference_asset_ids_json=auto_reference_asset_ids,
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

    duration = max(1, body.duration_seconds or shot.duration_seconds or 5)
    _check_and_consume_quota_wrapper(
        user.id, "video.generate.seconds.monthly_limit", duration, db, deduct=False,
    )

    source_storyboard_asset_id = body.source_storyboard_asset_id or shot.storyboard_asset_id
    auto_reference_asset_ids = _collect_shot_reference_asset_ids(
        shot,
        db,
        include_characters=True,
        include_scene=True,
        include_storyboard=True,
        include_frames=True,
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
        if source_storyboard_asset_id and shot.storyboard_locked:
            input_mode = "image_to_video"
        else:
            input_mode = "text_to_video"

    style_ctx = _resolve_effective_style_for_shot(shot, db, requested_style_name=body.style)
    style_name = style_ctx["name"]
    video_style_params = style_ctx["video_style_params"]
    style_template = style_ctx["prompt_template"]

    api_key, base_url, resolved_model = _user_video_api_key(request)
    resolved_model = body.model or resolved_model
    aspect_ratio = body.aspect_ratio or video_style_params.get("aspect_ratio") or "16:9"
    grounding = _build_story_grounding_block(shot.scene.chapter.story if shot.scene and shot.scene.chapter else None, shot.scene.chapter if shot.scene else None, shot.scene)
    full_prompt = _merge_style_prompt(f"{body.prompt or shot.video_prompt or ''} Grounding: {grounding}".strip(), style_template, style_name)

    async def event_generator():
        nonlocal db, base_url
        job_id = None
        
        try:
            yield {"event": "progress", "data": json.dumps({"progress": 0, "stage": "submitting", "message": "姝ｅ湪鎻愪氦瑙嗛鐢熸垚浠诲姟..."})}
            
            job_result = await video_gen_service.submit_video_job(
                shot_id=shot_id,
                provider=effective_provider,
                model=resolved_model,
                prompt=full_prompt,
                negative_prompt=body.negative_prompt or shot.negative_prompt or "",
                duration_seconds=duration,
                aspect_ratio=aspect_ratio,
                reference_images=reference_image_urls if reference_image_urls else None,
                api_key=api_key,
                base_url=base_url,
            )

            job_status = job_result.get("status", "queued")
            provider_job_id = job_result.get("provider_job_id", "")

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
                error_message=job_result.get("error"),
                input_mode=input_mode,
                source_storyboard_asset_id=source_storyboard_asset_id if input_mode == "image_to_video" else None,
                reference_asset_ids_json=auto_reference_asset_ids,
            )
            db.add(job)
            db.flush()
            job_id = job.id
            
            shot.status = "failed" if job_status == "failed" else "rendering"
            shot.updated_at = datetime.datetime.utcnow()

            if job_status != "failed":
                _check_and_consume_quota_wrapper(
                    user.id, "video.generate.seconds.monthly_limit", duration, db, deduct=True,
                )

            db.commit()

            if job_status == "failed":
                yield {"event": "error", "data": json.dumps({"job_id": job_id, "error": job.error_message or "Video provider rejected the request"})}
                return

            yield {"event": "progress", "data": json.dumps({"job_id": job_id, "progress": 10, "stage": "submitted", "message": "浠诲姟宸叉彁浜わ紝绛夊緟鐢熸垚..."})}

            poll_count = 0
            max_polls = 120
            download_attempted = False

            provider = effective_provider

            while poll_count < max_polls:
                poll_count += 1
                
                status_result = await video_gen_service.query_job_status(
                    provider=provider,
                    provider_job_id=provider_job_id,
                    api_key=api_key,
                    base_url=base_url,
                )
                
                current_status = status_result.get("status", "queued")
                progress = status_result.get("progress", 0)
                
                if current_status == "failed":
                    error_msg = status_result.get("error", "Generation failed")
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
                yield {"event": "progress", "data": json.dumps({
                    "job_id": job_id,
                    "progress": progress_val,
                    "stage": "generating",
                    "message": f"瑙嗛鐢熸垚涓?.. ({progress_val}%)"
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


# 鈹€鈹€鈹€ Video Asset Endpoints 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

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

    db.delete(asset)
    db.commit()

    return {"ok": True, "asset_id": asset_id}


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

    source_path = _from_video_url(asset.file_path or "")
    if not source_path or not Path(source_path).exists():
        raise HTTPException(404, "Source image not found")

    api_key, _base_url, _model = _user_video_api_key(request)
    regen_dir = _VIDEO_OUTPUTS_DIR / "regen_assets"
    regen_dir.mkdir(parents=True, exist_ok=True)
    output_filename = f"asset_{asset.id}_regen_{uuid.uuid4().hex[:8]}.png"
    output_path = regen_dir / output_filename

    try:
        if mode == "partial" and mask:
            import base64
            mask_bytes = base64.b64decode(str(mask))
            await image2_service.edit_existing_image(
                prompt=prompt,
                source_image_path=Path(source_path),
                output_path=output_path,
                mask_bytes=mask_bytes,
                api_key=api_key or None,
            )
        else:
            await image2_service.edit_existing_image(
                prompt=prompt,
                source_image_path=Path(source_path),
                output_path=output_path,
                api_key=api_key or None,
            )
    except Exception as exc:
        logger.warning("Regenerate video asset failed: asset_id=%s err=%s", asset_id, exc)
        raise HTTPException(502, f"閲嶇粯澶辫触: {exc}")

    new_revision = (asset.revision or 1) + 1
    new_asset = VideoAsset(
        story_id=asset.story_id,
        chapter_id=asset.chapter_id,
        scene_id=asset.scene_id,
        shot_id=asset.shot_id,
        asset_type=asset.asset_type,
        asset_subtype=asset.asset_subtype,
        name=asset.name,
        file_path=_to_video_url(str(output_path)),
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

    if asset.asset_type == "storyboard_frame" and asset.shot_id:
        shot = db.get(VideoShot, asset.shot_id)
        if shot:
            shot.storyboard_asset_id = new_asset.id
            shot.updated_at = datetime.datetime.utcnow()

    db.commit()
    db.refresh(new_asset)

    return {
        "asset": {
            "id": new_asset.id,
            "name": new_asset.name,
            "file_path": new_asset.file_path,
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
                "prompt_template": p.prompt_template,
                "image_style_params": p.image_style_params,
                "video_style_params": p.video_style_params,
                "sort_order": p.sort_order,
            }
            for p in presets
        ],
    }


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
    for field, value in update_data.items():
        if value is not None:
            setattr(preset, field, value)

    db.commit()
    db.refresh(preset)

    return {
        "id": preset.id,
        "name": preset.name,
        "category": preset.category,
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

    db.delete(preset)
    db.commit()

    return {"ok": True}


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
        },
    }


# 鈹€鈹€鈹€ Story Style Preset Selection 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

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
        },
    }


# 鈹€鈹€鈹€ Shot Style Preset Override 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

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
        duration_seconds=body.duration_seconds or 5,
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
        include_characters=True,
        include_scene=True,
        include_storyboard=False,
        include_frames=False,
        explicit_asset_ids=body.reference_asset_ids or [],
    )
    ref_assets = db.query(VideoAsset).filter(VideoAsset.id.in_(ref_asset_ids)).all() if ref_asset_ids else []
    ref_block = _build_reference_constraints_block([a for a in ref_assets if a.asset_type == "character_reference"])
    ref_paths = _resolve_asset_file_paths(ref_assets)

    storyboards_dir = _VIDEO_OUTPUTS_DIR / "storyboards" / f"chapter_{shot.scene.chapter_id}" / f"shot_{shot_id}"
    storyboards_dir.mkdir(parents=True, exist_ok=True)
    file_name = f"storyboard_{datetime.datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}.png"
    full_path = storyboards_dir / file_name

    prompt = _merge_style_prompt(
        f"{shot.storyboard_prompt or shot.video_prompt or f'Storyboard for shot {shot.shot_number}'} {ref_block}".strip(),
        style_ctx.get("prompt_template"),
        style_name,
    )
    api_key, _base_url, _model = _user_video_api_key(request)
    try:
        await image2_service.generate_reference_image(
            prompt=prompt,
            output_path=full_path,
            api_key=api_key or None,
            size=image_style_params.get("size", "1536x1024"),
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
    ref_block = _build_reference_constraints_block([a for a in ref_assets if a.asset_type == "character_reference"])
    ref_paths = _resolve_asset_file_paths(ref_assets)

    api_key, _base_url, _model = _user_video_api_key(request)
    frames_dir = _VIDEO_OUTPUTS_DIR / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

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
                size=image_style_params.get("size", "1920x1080"),
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

    api_key, _base_url, _model = _user_video_api_key(request)
    prompt = body.prompt or old_asset.prompt or ""
    style_ctx = _resolve_effective_style_for_shot(shot, db, body.style_preset)
    ref_asset_ids = _collect_shot_reference_asset_ids(
        shot,
        db,
        include_characters=True,
        include_scene=True,
        include_storyboard=True,
        include_frames=False,
        explicit_asset_ids=body.reference_asset_ids or [],
    )
    ref_assets = db.query(VideoAsset).filter(VideoAsset.id.in_(ref_asset_ids)).all() if ref_asset_ids else []
    ref_block = _build_reference_constraints_block([a for a in ref_assets if a.asset_type == "character_reference"])
    prompt = _merge_style_prompt(f"{prompt} {ref_block}".strip(), style_ctx.get("prompt_template"), style_ctx.get("name"))
    try:
        await image2_service.generate_reference_image(
            prompt=prompt,
            output_path=full_path,
            api_key=api_key or None,
            size=(style_ctx.get("image_style_params") or {}).get("size", "1536x1024"),
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
            "file_path": a.file_path,
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

    default_character_prompts: list[dict] = []
    for name in character_names:
        note = character_notes.get(name, "")
        inherited_prompt = ""
        for asset in inherited_char_assets:
            if name in (asset.name or "") or name in (asset.prompt or ""):
                inherited_prompt = (asset.prompt or "")[:260]
                break
        design_grounding = _build_character_design_grounding_block(story, name, note)
        default_character_prompts.append(
            {
                "name": name,
                "prompt": _build_character_sheet_prompt(
                    character_name=name,
                    style_ctx=style_ctx,
                    story=story,
                    note_from_profiles=note,
                    inherited_prompt=inherited_prompt,
                ),
                "grounding": design_grounding,
            }
        )

    base_storyboard = _merge_style_prompt(
        (
            f"Master storyboard keyframe for shot {shot.shot_number}. "
            f"Scene: {scene_summary}. Location: {scene_location}. Mood: {scene_mood}. "
            f"Shot language: {shot.shot_type or 'medium'}, {shot.camera_angle or 'eye_level'}, "
            f"{shot.camera_movement or 'static'}, composition {shot.composition or 'clear subject hierarchy'}. "
            f"Action: {shot.action_description or ''}. Dialogue cue: {shot.dialogue or 'none'}. "
            f"Continuity: {shot.continuity_notes or 'preserve character identity, outfit and props across frames'}. "
            "One production storyboard frame with clear staging, readable blocking, and consistent costume/props."
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
    base_video = _merge_style_prompt(
        (
            f"Shot video generation prompt. Duration {shot.duration_seconds or 5}s. "
            f"Camera movement: {shot.camera_movement or 'static'}. "
            f"Framing: {shot.shot_type or 'medium'} with {shot.camera_angle or 'eye_level'} angle. "
            f"Action progression: {shot.action_description or ''}. "
            f"Dialogue: {shot.dialogue or 'none'}. Sound cues: {shot.sound_design or 'ambient'}. "
            f"Continuity constraints: {shot.continuity_notes or 'strict continuity with storyboard and frame references'}. "
            "Motion should be coherent, physically plausible, and strictly aligned with storyboard and first/last frame."
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
  "storyboard_prompt": "...",
  "first_frame_prompt": "...",
  "last_frame_prompt": "...",
  "video_prompt": "..."
}}

Rules:
1. Character prompts are CHARACTER DESIGN SHEETS ONLY. No scene events, no system UI text overlays, no chapter plot reenactment.
2. Character prompts must request one-page turnaround sheet with: front portrait, side portrait, full-body, expression set, outfit/accessory callouts.
3. Storyboard/first/last/video prompts must be grounded to shot + scene + story context and keep identity consistency.
4. Keep style consistency with selected style preset.
5. Output valid JSON object only.

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
            async with httpx.AsyncClient(timeout=120) as client:
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
            db.commit()

            return {
                "shot_id": shot_id,
                "style_preset": style_name,
                "character_prompts": cleaned_char_prompts,
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
    db.commit()

    return {
        "shot_id": shot_id,
        "style_preset": style_name,
        "character_prompts": fallback_char,
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
    api_key, _base_url, _model = _user_video_api_key(request)
    try:
        await image2_service.generate_reference_image(
            prompt=final_prompt,
            output_path=full_path,
            api_key=api_key or None,
            size=image_style_params.get("size", "1536x1024"),
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

    duration = max(1, body.duration_seconds or shot.duration_seconds or 5)
    _check_and_consume_quota_wrapper(
        user.id, "video.generate.seconds.monthly_limit", duration, db, deduct=False,
    )

    source_storyboard_asset_id = body.source_storyboard_asset_id or shot.storyboard_asset_id
    auto_reference_asset_ids = _collect_shot_reference_asset_ids(
        shot,
        db,
        include_characters=True,
        include_scene=True,
        include_storyboard=True,
        include_frames=True,
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
        if source_storyboard_asset_id and shot.storyboard_locked:
            input_mode = "image_to_video"
        else:
            input_mode = "text_to_video"

    style_ctx = _resolve_effective_style_for_shot(shot, db, requested_style_name=body.style)
    style_name = style_ctx["name"]
    video_style_params = style_ctx["video_style_params"]
    style_template = style_ctx["prompt_template"]

    api_key, base_url, resolved_model = _user_video_api_key(request)
    resolved_model = body.model or resolved_model
    aspect_ratio = body.aspect_ratio or video_style_params.get("aspect_ratio") or "16:9"
    grounding = _build_story_grounding_block(shot.scene.chapter.story if shot.scene and shot.scene.chapter else None, shot.scene.chapter if shot.scene else None, shot.scene)
    full_prompt = _merge_style_prompt(f"{body.prompt or shot.video_prompt or ''} Grounding: {grounding}".strip(), style_template, style_name)

    job_result = await video_gen_service.submit_video_job(
        shot_id=shot_id,
        provider=effective_provider,
        model=resolved_model,
        prompt=full_prompt,
        negative_prompt=body.negative_prompt or shot.negative_prompt or "",
        duration_seconds=duration,
        aspect_ratio=aspect_ratio,
        reference_images=reference_image_urls if reference_image_urls else None,
        api_key=api_key,
        base_url=base_url,
    )

    job_status = job_result.get("status", "queued")
    provider_job_id = job_result.get("provider_job_id", "")

    job = VideoGenerationJob(
        shot_id=shot_id,
        provider=effective_provider,
        provider_job_id=provider_job_id,
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
        error_message=job_result.get("error"),
        input_mode=input_mode,
        source_storyboard_asset_id=source_storyboard_asset_id if input_mode == "image_to_video" else None,
        reference_asset_ids_json=auto_reference_asset_ids,
    )
    db.add(job)
    db.flush()

    shot.status = "failed" if job_status == "failed" else "rendering"
    shot.updated_at = datetime.datetime.utcnow()

    if job_status != "failed":
        _check_and_consume_quota_wrapper(
            user.id, "video.generate.seconds.monthly_limit", duration, db, deduct=True,
        )

    db.commit()

    if job_status == "failed":
        raise HTTPException(
            status_code=502,
            detail=job.error_message or "Video provider rejected the request",
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



