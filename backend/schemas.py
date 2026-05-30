from __future__ import annotations

import datetime
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, model_validator


# --- Story ---
class StoryCreate(BaseModel):
    title: str = "未命名故事"
    description: str = ""


class StoryUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[dict[str, Any]] = None
    outline: Optional[dict[str, Any]] = None
    characters: Optional[list[dict[str, Any]]] = None


class OutlineChapterPlanPayload(BaseModel):
    title: str
    summary: Optional[str] = None
    key_events: Optional[list[str]] = None
    act: Optional[str] = None
    goal: Optional[str] = None
    conflict: Optional[str] = None
    hook: Optional[str] = None
    payoff: Optional[str] = None
    highlight: Optional[str] = None


class OutlineChapterPlanUpdate(BaseModel):
    mode: str
    target_chapter_number: Optional[int] = None
    after_chapter_number: Optional[int] = None
    chapter: OutlineChapterPlanPayload


class StoryOut(BaseModel):
    id: int
    title: str
    description: Optional[str] = ""
    cover_image: Optional[str] = None
    tags: Optional[dict[str, Any]] = None
    outline: Optional[dict[str, Any]] = None
    characters: Optional[list[dict[str, Any]]] = None
    story_bible: Optional[dict[str, Any]] = None
    story_memory: Optional[dict[str, Any]] = None
    onboarding_completed: bool = False
    source_type: str = "manual"
    import_context_completed: bool = True
    has_character_profiles: bool = False
    has_ref_image: bool = False
    created_at: datetime.datetime

    model_config = {"from_attributes": True}

    @model_validator(mode='before')
    @classmethod
    def _extract_computed_flags(cls, data):
        if hasattr(data, 'character_profiles'):
            cp = getattr(data, 'character_profiles', '') or ''
            d = dict(data.__dict__) if hasattr(data, '__dict__') else dict(data)
            d['has_character_profiles'] = bool(cp.strip())
            # Check for story-level ref image on disk
            story_id = getattr(data, 'id', None)
            if story_id:
                story_dir = Path(__file__).resolve().parent / "manga_outputs" / f"story_{story_id}"
                ref_dir = story_dir / "ref_images"
                has_multi_ref = ref_dir.exists() and any(
                    p.is_file() and p.suffix.lower() == ".png"
                    for p in ref_dir.iterdir()
                )
                d['has_ref_image'] = has_multi_ref or (story_dir / "ref_image.png").exists()
            return d
        return data


# --- Chapter ---
class ChapterOut(BaseModel):
    id: int
    story_id: int
    chapter_number: int
    title: Optional[str] = None
    novel_content: Optional[str] = None
    content_source: Optional[str] = None
    act: Optional[str] = None
    key_events: Optional[list[Any]] = None
    quality_score: Optional[dict[str, Any]] = None
    memory_summary: Optional[dict[str, Any]] = None
    status: str = "pending"
    word_count: Optional[int] = None
    created_at: datetime.datetime
    messages: list[ChatMessageOut] = []
    images: list[MangaImageOut] = []

    model_config = {"from_attributes": True}


# --- Chat ---
class ChatMessageIn(BaseModel):
    content: str


class ChatMessageOut(BaseModel):
    id: int
    chapter_id: int
    role: str
    content: str
    created_at: datetime.datetime

    model_config = {"from_attributes": True}


class AgentConversationCreateIn(BaseModel):
    title: Optional[str] = None
    chapter_id: Optional[int] = None


class AgentConversationMessageCreateIn(BaseModel):
    conversation_id: int
    content: str
    chapter_id: Optional[int] = None


class AgentConversationMessageOut(BaseModel):
    id: int
    conversation_id: int
    role: str
    content: str
    created_at: datetime.datetime

    model_config = {"from_attributes": True}


class AgentConversationSummaryOut(BaseModel):
    id: int
    story_id: int
    chapter_id: Optional[int] = None
    title: str
    last_message_preview: str = ""
    message_count: int = 0
    created_at: datetime.datetime
    updated_at: datetime.datetime


class AgentConversationOut(BaseModel):
    id: int
    story_id: int
    chapter_id: Optional[int] = None
    title: str
    created_at: datetime.datetime
    updated_at: datetime.datetime
    messages: list[AgentConversationMessageOut] = []

    model_config = {"from_attributes": True}


# --- Manga ---
class MangaImageOut(BaseModel):
    id: int
    chapter_id: int
    image_number: int
    image_path: str
    prompt: Optional[str] = None
    created_at: datetime.datetime

    model_config = {"from_attributes": True}


class GenerateNovelRequest(BaseModel):
    pass


class GenerateMangaRequest(BaseModel):
    pass


# --- Framework (InkAI) ---
class TagsSchema(BaseModel):
    type: Optional[str] = None
    theme: Optional[str] = None
    style: Optional[str] = None
    audience: Optional[str] = None


class CharacterSchema(BaseModel):
    name: str = ""
    role: str = ""
    big_five: Optional[dict[str, Any]] = None
    arc: Optional[dict[str, Any]] = None
    relationships: Optional[list[dict[str, Any]]] = None


class OutlineSchema(BaseModel):
    three_acts: Optional[list[dict[str, Any]]] = None
    themes: Optional[list[str]] = None
    foreshadowing: Optional[list[str]] = None


class QualityScoreSchema(BaseModel):
    content: Optional[int] = None
    writing: Optional[int] = None
    character: Optional[int] = None
    plot: Optional[int] = None
    overall: Optional[int] = None


class FrameworkGenerateResponse(BaseModel):
    tags: Optional[dict[str, Any]] = None
    characters: Optional[list[dict[str, Any]]] = None
    outline: Optional[dict[str, Any]] = None
    chapters: Optional[list[dict[str, Any]]] = None


class RewriteSelectionRequest(BaseModel):
    selected_text: str
    chapter_context: Optional[str] = None
    instruction: Optional[str] = None


class ChapterContentUpdate(BaseModel):
    content: str


class QualityAssessResponse(BaseModel):
    scores: Optional[QualityScoreSchema] = None
    suggestions: Optional[list[str]] = None
    overall_comment: Optional[str] = None


class ScenesFromSelectionRequest(BaseModel):
    selected_text: str
    chapter_context: Optional[str] = None
    character_profiles: Optional[str] = None
    page_count: int = 4


class ScenesFromSelectionResponse(BaseModel):
    scenes: list[dict[str, Any]] = []


# --- Import/Export ---
class ImportParseResponse(BaseModel):
    detected_title: str = ""
    chapters: list[ImportChapterInfo] = []
    total_word_count: int = 0


class ImportChapterInfo(BaseModel):
    chapter_number: int
    title: str = ""
    content: str = ""
    detection_method: str = "regex"  # "regex" | "ai"


class ImportCreateRequest(BaseModel):
    title: str
    description: str = ""
    chapters: list[ImportChapterCreate] = []
    analyze_framework: bool = True


class ImportChapterCreate(BaseModel):
    chapter_number: int
    title: str = ""
    content: str = ""
    act: str | None = None
    key_events: list[str] = []


class FrameworkAnalyzeResponse(BaseModel):
    tags: dict | None = None
    characters: list[dict] | None = None
    outline: dict | None = None


# ─── Onboarding / Story Bible ────────────────────────────────


class OnboardingMessageIn(BaseModel):
    """用户发送的引导对话消息"""
    messages: list[dict[str, str]]  # [{role, content}, ...]


class OnboardingConfirmIn(BaseModel):
    """确认引导结果"""
    messages: list[dict[str, str]]


class OnboardingMessageOut(BaseModel):
    """AI 引导回复"""
    reply: str
    collected_info: dict[str, Any] = {}
    step: int = 1
    total_steps: int = 5
    is_complete: bool = False
    creative_brief: dict[str, Any] | None = None


class CreativeBriefOut(BaseModel):
    """创意理解卡（用户确认前预览）"""
    project_positioning: str = ""
    genre: str = ""
    audience: str = ""
    tone: str = ""
    core_hook: str = ""
    one_line_premise: str = ""
    protagonist_core: str = ""
    main_conflict: str = ""
    longline_mystery: str = ""
    serial_length_target: str = ""
    must_keep_rules: list[str] = []
    reveal_strategy: str = ""
    pacing_strategy: str = ""


class StoryBibleSchema(BaseModel):
    """完整的 Story Bible 数据结构"""
    story_bible: dict[str, Any] = {}


class StoryBibleUpdate(BaseModel):
    """更新 Story Bible"""
    story_bible: dict[str, Any]


class DialogueLine(BaseModel):
    speaker: str
    text: str


class TimelineItem(BaseModel):
    shot_id: int
    clip_id: int
    order: int
    enabled: bool


class SubtitleItem(BaseModel):
    start_ms: int
    end_ms: int
    text: str


class VideoStylePresetOut(BaseModel):
    id: int
    name: str
    category: str
    prompt_template: Optional[str] = None
    image_style_params: Optional[dict[str, Any]] = None
    video_style_params: Optional[dict[str, Any]] = None
    sort_order: int = 0

    model_config = {"from_attributes": True}


class VideoStylePresetCreate(BaseModel):
    name: str
    category: str = "realistic"
    prompt_template: Optional[str] = None
    image_style_params: Optional[dict[str, Any]] = None
    video_style_params: Optional[dict[str, Any]] = None
    sort_order: int = 0


class VideoStylePresetUpdate(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    prompt_template: Optional[str] = None
    image_style_params: Optional[dict[str, Any]] = None
    video_style_params: Optional[dict[str, Any]] = None
    sort_order: Optional[int] = None


class ScriptSceneOut(BaseModel):
    id: int
    chapter_id: int
    scene_number: int
    title: Optional[str] = None
    location: Optional[str] = None
    time_of_day: Optional[str] = None
    characters: list[str] = []
    summary: Optional[str] = None
    dialogue: list[DialogueLine] = []
    voiceover: Optional[str] = None
    mood: Optional[str] = None
    concept_art_asset_id: Optional[int] = None
    estimated_duration_seconds: Optional[int] = None
    source_type: str = "chapter"
    status: str = "draft"
    created_at: datetime.datetime
    updated_at: datetime.datetime

    model_config = {"from_attributes": True}

    @model_validator(mode='before')
    @classmethod
    def _map_json_fields(cls, data):
        if hasattr(data, 'characters_json'):
            d = dict(data.__dict__) if hasattr(data, '__dict__') else dict(data)
            d['characters'] = data.characters_json or []
            d['dialogue'] = [DialogueLine(**item) for item in (data.dialogue_json or [])]
            return d
        return data


class ScriptSceneUpdate(BaseModel):
    scene_number: Optional[int] = None
    title: Optional[str] = None
    location: Optional[str] = None
    time_of_day: Optional[str] = None
    characters: Optional[list[str]] = None
    summary: Optional[str] = None
    dialogue: Optional[list[DialogueLine]] = None
    voiceover: Optional[str] = None
    mood: Optional[str] = None
    estimated_duration_seconds: Optional[int] = None
    source_type: Optional[str] = None
    status: Optional[str] = None


class GenerateScreenplayRequest(BaseModel):
    mode: str = "from_chapter"
    style: str = "cinematic"
    target_duration_seconds: Optional[int] = None
    scene_count_hint: Optional[int] = None
    regenerate: bool = False


class RegenerateScenesRequest(BaseModel):
    instruction: Optional[str] = None
    scene_count_hint: Optional[int] = None


class VideoShotOut(BaseModel):
    id: int
    scene_id: int
    shot_number: int
    title: Optional[str] = None
    shot_type: Optional[str] = None
    camera_angle: Optional[str] = None
    camera_movement: Optional[str] = None
    composition: Optional[str] = None
    action_description: Optional[str] = None
    dialogue: Optional[str] = None
    sound_design: Optional[str] = None
    duration_seconds: Optional[int] = None
    storyboard_prompt: Optional[str] = None
    video_prompt: Optional[str] = None
    negative_prompt: Optional[str] = None
    continuity_notes: Optional[str] = None
    status: str = "draft"
    style_preset: Optional[str] = None
    storyboard_asset_id: Optional[int] = None
    storyboard_locked: bool = False
    created_at: datetime.datetime
    updated_at: datetime.datetime
    character_involvement: Optional[str] = None
    scene_mood: Optional[str] = None

    model_config = {"from_attributes": True}


class VideoShotUpdate(BaseModel):
    shot_number: Optional[int] = None
    title: Optional[str] = None
    shot_type: Optional[str] = None
    camera_angle: Optional[str] = None
    camera_movement: Optional[str] = None
    composition: Optional[str] = None
    action_description: Optional[str] = None
    dialogue: Optional[str] = None
    sound_design: Optional[str] = None
    duration_seconds: Optional[int] = None
    storyboard_prompt: Optional[str] = None
    video_prompt: Optional[str] = None
    negative_prompt: Optional[str] = None
    continuity_notes: Optional[str] = None
    status: Optional[str] = None
    style_preset: Optional[str] = None


class GenerateShotsRequest(BaseModel):
    style: str = "cinematic"
    shot_count_hint: Optional[int] = None
    duration_budget_seconds: Optional[int] = None
    regenerate: bool = False


class GeneratePromptsRequest(BaseModel):
    style: Optional[str] = None
    provider: Optional[str] = None
    include_references: bool = True
    instruction: Optional[str] = None
    continuity_notes: Optional[str] = None


class StoryboardRenderRequest(BaseModel):
    provider: Optional[str] = "image2"
    aspect_ratio: Optional[str] = "16:9"
    overwrite: bool = False
    output_path: Optional[str] = None
    style_preset: Optional[str] = None
    prompt: Optional[str] = None
    reference_asset_ids: list[int] = []


class VideoRenderRequest(BaseModel):
    provider: str = "sora"
    model: Optional[str] = None
    duration_seconds: int = 5
    aspect_ratio: Optional[str] = "16:9"
    fps: Optional[int] = 24
    use_reference_assets: bool = True
    reference_asset_ids: list[int] = []
    seed: Optional[int] = None
    overwrite_active_clip: bool = False
    prompt: Optional[str] = None
    negative_prompt: Optional[str] = None
    style: Optional[str] = None
    input_mode: Optional[str] = None
    source_storyboard_asset_id: Optional[int] = None


class StoryboardActionRequest(BaseModel):
    action: str
    asset_id: Optional[int] = None


class VideoGenerationJobOut(BaseModel):
    id: int
    shot_id: int
    provider: str
    provider_job_id: Optional[str] = None
    model: Optional[str] = None
    request_payload_json: Optional[dict[str, Any]] = None
    status: str = "pending"
    progress: int = 0
    duration_seconds: Optional[int] = None
    aspect_ratio: Optional[str] = None
    error_message: Optional[str] = None
    input_mode: Optional[str] = None
    source_storyboard_asset_id: Optional[int] = None
    submitted_at: datetime.datetime
    completed_at: Optional[datetime.datetime] = None

    model_config = {"from_attributes": True}


class RetryJobRequest(BaseModel):
    provider: Optional[str] = None
    model: Optional[str] = None
    duration_seconds: Optional[int] = None
    aspect_ratio: Optional[str] = None
    seed: Optional[int] = None
    request_payload: Optional[dict[str, Any]] = None


class RenderedClipOut(BaseModel):
    id: int
    shot_id: int
    job_id: Optional[int] = None
    video_path: str
    thumbnail_path: Optional[str] = None
    duration_seconds: Optional[int] = None
    resolution: Optional[str] = None
    version: int = 1
    is_active: bool = True
    meta_json: Optional[dict[str, Any]] = None
    source_storyboard_asset_id: Optional[int] = None
    style_preset: Optional[str] = None
    continuity_score: Optional[int] = None
    quality_score: Optional[int] = None
    review_status: str = "pending"
    created_at: datetime.datetime

    model_config = {"from_attributes": True}


class VideoAssetOut(BaseModel):
    id: int
    story_id: Optional[int] = None
    chapter_id: Optional[int] = None
    scene_id: Optional[int] = None
    shot_id: Optional[int] = None
    asset_type: str
    name: str
    file_path: str
    provider: Optional[str] = None
    prompt: Optional[str] = None
    meta_json: Optional[dict[str, Any]] = None
    asset_subtype: Optional[str] = None
    source_asset_ids_json: Optional[list[int]] = None
    style_preset: Optional[str] = None
    locked: bool = False
    revision: int = 1
    is_master: bool = False
    status: str = "active"
    hash_key: Optional[str] = None
    created_at: datetime.datetime

    model_config = {"from_attributes": True}


class CreateVideoAssetRequest(BaseModel):
    story_id: Optional[int] = None
    scene_id: Optional[int] = None
    shot_id: Optional[int] = None
    asset_type: str
    name: str
    file_path: str
    provider: Optional[str] = None
    prompt: Optional[str] = None
    meta: Optional[dict[str, Any]] = None


class VideoProjectOut(BaseModel):
    id: int
    story_id: int
    chapter_id: int
    name: str
    timeline: list[TimelineItem] = []
    subtitle: list[SubtitleItem] = []
    bgm_path: Optional[str] = None
    cover_path: Optional[str] = None
    status: str = "draft"
    output_path: Optional[str] = None
    created_at: datetime.datetime
    updated_at: datetime.datetime

    model_config = {"from_attributes": True}

    @model_validator(mode='before')
    @classmethod
    def _map_json_fields(cls, data):
        if hasattr(data, 'timeline_json'):
            d = dict(data.__dict__) if hasattr(data, '__dict__') else dict(data)
            d['timeline'] = [TimelineItem(**item) for item in (data.timeline_json or [])]
            d['subtitle'] = [SubtitleItem(**item) for item in (data.subtitle_json or [])]
            return d
        return data


class GenerateShotFramesRequest(BaseModel):
    frame_type: str = "both"  # "first_frame" | "last_frame" | "both"
    prompt: str | None = None
    overwrite: bool = False
    style_preset: Optional[str] = None
    reference_asset_ids: list[int] = []
    inherit_character_assets: bool = True
    inherit_scene_assets: bool = True
    inherit_storyboard_asset: bool = True


class RegenerateShotFrameRequest(BaseModel):
    asset_id: int
    prompt: str
    mode: str = "full"  # "full" | "partial"
    mask: str | None = None
    style_preset: Optional[str] = None
    reference_asset_ids: list[int] = []


class CreateVideoProjectRequest(BaseModel):
    name: str
    timeline: list[TimelineItem]
    subtitle: Optional[list[SubtitleItem]] = None
    bgm_path: Optional[str] = None
    cover_path: Optional[str] = None


class VideoProjectUpdate(BaseModel):
    name: Optional[str] = None
    timeline: Optional[list[TimelineItem]] = None
    subtitle: Optional[list[SubtitleItem]] = None
    bgm_path: Optional[str] = None
    cover_path: Optional[str] = None
    status: Optional[str] = None


class CompileProjectRequest(BaseModel):
    resolution: str = "1280x720"
    fps: int = 24
    burn_subtitle: bool = True
    include_bgm: bool = True


class UsageInfo(BaseModel):
    feature_key: str
    consumed: int


class ChapterStylePresetOut(BaseModel):
    chapter_id: int
    style_preset_id: Optional[int] = None
    style_preset: Optional[VideoStylePresetOut] = None


class ChapterStylePresetUpdate(BaseModel):
    style_preset_id: int


class StoryStylePresetOut(BaseModel):
    story_id: int
    style_preset_id: Optional[int] = None
    style_preset: Optional[VideoStylePresetOut] = None


class StoryStylePresetUpdate(BaseModel):
    style_preset_id: int


class ShotStylePresetUpdate(BaseModel):
    style_preset: Optional[str] = None


class UpdateAssetScopeRequest(BaseModel):
    usage_scope: str = "shot_only"
    inherit_to_next_shot: bool = False


class PromoteAssetRequest(BaseModel):
    level: str = "chapter_global"
    inherit_to_next_shot: bool = False


class ShotAssetBundleOut(BaseModel):
    shot_id: int
    shot_number: Optional[int] = None
    scene_id: Optional[int] = None
    style_preset: Optional[str] = None
    storyboard_asset: Optional[VideoAssetOut] = None
    storyboard_locked: bool = False
    first_frame: Optional[VideoAssetOut] = None
    last_frame: Optional[VideoAssetOut] = None
    character_references: list[VideoAssetOut] = []
    scene_references: list[VideoAssetOut] = []
    available_character_assets: list[VideoAssetOut] = []
    available_scene_assets: list[VideoAssetOut] = []


class AssetUploadResponse(BaseModel):
    id: int
    asset_type: str
    name: str
    file_path: str


# Resolve forward references
ChapterOut.model_rebuild()
