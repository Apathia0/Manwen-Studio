from __future__ import annotations

import datetime
from pathlib import Path
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, model_validator


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


class StoryKnowledgeMutation(BaseModel):
    """作品知识工作台的统一新增与编辑载荷。"""

    category_id: Optional[int] = Field(default=None, ge=1)

    resource_type: Optional[str] = Field(default=None, max_length=50)
    resource_key: Optional[str] = Field(default=None, max_length=160)
    title: Optional[str] = Field(default=None, max_length=255)
    summary: Optional[str] = None
    content_json: Any = None
    content_text: Optional[str] = None
    importance: Optional[int] = Field(default=None, ge=0, le=100)
    valid_from_chapter: Optional[int] = Field(default=None, ge=1)
    valid_to_chapter: Optional[int] = Field(default=None, ge=1)
    triggers_json: Optional[list[str]] = None
    is_constant: Optional[bool] = None
    status: Optional[str] = Field(default=None, max_length=20)

    entity_key: Optional[str] = Field(default=None, max_length=160)
    entity_type: Optional[str] = Field(default=None, max_length=40)
    canonical_name: Optional[str] = Field(default=None, max_length=255)
    aliases_json: Optional[list[str]] = None
    profile_json: Optional[dict[str, Any]] = None
    first_chapter: Optional[int] = Field(default=None, ge=1)
    last_chapter: Optional[int] = Field(default=None, ge=1)

    subject_key: Optional[str] = Field(default=None, max_length=160)
    predicate: Optional[str] = Field(default=None, max_length=100)
    object_key: Optional[str] = Field(default=None, max_length=160)
    value_json: Any = None
    value_text: Optional[str] = None
    confidence: Optional[float] = Field(default=None, ge=0, le=1)

    thread_key: Optional[str] = Field(default=None, max_length=160)
    thread_type: Optional[str] = Field(default=None, max_length=30)
    description: Optional[str] = None
    setup_chapter: Optional[int] = Field(default=None, ge=1)
    expected_payoff_from: Optional[int] = Field(default=None, ge=1)
    expected_payoff_to: Optional[int] = Field(default=None, ge=1)
    actual_payoff_chapter: Optional[int] = Field(default=None, ge=1)
    related_entity_keys: Optional[list[str]] = None
    priority: Optional[int] = Field(default=None, ge=0, le=100)
    expected_version: Optional[int] = Field(default=None, ge=1)

    model_config = {"extra": "forbid"}


class StoryKnowledgeCategoryMutation(BaseModel):
    """作品知识分类的新增与编辑载荷。"""

    name: Optional[str] = Field(default=None, max_length=80)
    color: Optional[str] = Field(default=None, max_length=20)
    sort_order: Optional[int] = Field(default=None, ge=0)
    expected_version: Optional[int] = Field(default=None, ge=1)

    model_config = {"extra": "forbid"}


class ChapterCreationPackUpdate(BaseModel):
    """用户编辑后的章节创作包原文。"""

    content: str = Field(min_length=1)
    expected_version: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_content(self):
        if not self.content.strip():
            raise ValueError("创作包不能为空")
        return self

    model_config = {"extra": "forbid"}


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
    story_type: str = "novel"
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


AgentWorkflowType = Literal["novel", "manga", "video", "video_canvas"]
AgentSkillName = Literal[
    "chapter_writer",
    "framework_designer",
    "manga_workflow",
    "quality_reviewer",
    "video_workflow",
    "video_canvas_workflow",
    "deconstruction_reader",
]


class AgentChatIn(BaseModel):
    conversation_id: int
    message: str
    chapter_id: Optional[int] = 0
    chapter_number: Optional[int] = 0
    workflow_type: Optional[AgentWorkflowType] = None
    workflow_id: Optional[int] = Field(default=None, gt=0)
    shot_id: Optional[int] = None
    session_id: Optional[str] = None
    enabled_skills: Optional[list[AgentSkillName]] = None
    attachment_ids: Optional[list[str]] = None

    @model_validator(mode="after")
    def validate_workflow_context(self):
        if self.workflow_type == "video" and (self.workflow_id is None or not self.chapter_id):
            raise ValueError("视频工作流必须提供 workflow_id 和 chapter_id")
        if self.workflow_type == "video_canvas" and self.workflow_id is None:
            raise ValueError("视频画布必须提供 workflow_id")
        if self.workflow_type == "manga" and not self.chapter_id:
            raise ValueError("漫画工作流必须提供 chapter_id")
        return self


class AgentConversationCreateIn(BaseModel):
    title: Optional[str] = None
    chapter_id: Optional[int] = None
    workflow_type: Optional[AgentWorkflowType] = None
    workflow_id: Optional[int] = Field(default=None, gt=0)
    shot_id: Optional[int] = None

    @model_validator(mode="after")
    def validate_workflow_context(self):
        if self.workflow_type == "video" and (self.workflow_id is None or self.chapter_id is None):
            raise ValueError("视频工作流必须提供 workflow_id 和 chapter_id")
        if self.workflow_type == "video_canvas" and self.workflow_id is None:
            raise ValueError("视频画布必须提供 workflow_id")
        if self.workflow_type == "manga" and self.chapter_id is None:
            raise ValueError("漫画工作流必须提供 chapter_id")
        return self


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


class MangaStoryboardImportPreviewIn(BaseModel):
    source_kind: Literal["paste", "chapter_content"]
    content: Optional[str] = None


class MangaStoryboardImportCommitIn(BaseModel):
    scenes: list[str]
    expected_revision: str
    canonical_hash: str


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


class Understanding(BaseModel):
    """AI 对用户创意的理解（结构化）"""
    concept: str = ""      # 故事概念
    setting: str = ""      # 世界观/设定
    tone: str = ""         # 风格基调
    goals: str = ""        # 创作目标
    synthesis: str = ""    # 综合理解


class OnboardingMessageIn(BaseModel):
    """用户发送的引导对话消息"""
    messages: list[dict[str, str]]  # [{role, content}, ...]


class OnboardingConfirmIn(BaseModel):
    """确认引导结果"""
    messages: list[dict[str, str]]


class OnboardingMessageOut(BaseModel):
    """AI 引导回复"""
    reply: str
    # 新字段：结构化理解
    understanding: Understanding = Understanding()
    understanding_depth: int = 0
    phase: str = "exploring"  # exploring | refining | synthesizing
    has_brief: bool = False
    creative_brief: dict[str, Any] | None = None
    active_field: str | None = None
    incomplete_fields: list[str] = Field(default_factory=list)
    decision: dict[str, Any] | None = None
    # 保留兼容字段
    collected_info: dict[str, Any] = {}
    step: int = 1
    total_steps: int = 5
    is_complete: bool = False


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
    image_url: Optional[str] = None
    prompt_template: Optional[str] = None
    image_style_params: Optional[dict[str, Any]] = None
    video_style_params: Optional[dict[str, Any]] = None
    sort_order: int = 0

    model_config = {"from_attributes": True}


class VideoStylePresetCreate(BaseModel):
    name: str
    category: str = "realistic"
    image_url: Optional[str] = None
    prompt_template: Optional[str] = None
    image_style_params: Optional[dict[str, Any]] = None
    video_style_params: Optional[dict[str, Any]] = None
    sort_order: int = 0


class VideoStylePresetUpdate(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    image_url: Optional[str] = None
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
    first_frame_prompt: Optional[str] = None
    last_frame_prompt: Optional[str] = None
    character_prompts_json: Optional[list] = None
    scene_prompt: Optional[str] = None
    prop_prompts_json: Optional[list] = None
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
    reference_asset_ids: list[int] = Field(default_factory=list, max_length=9)
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
    style_preset: Optional[str] = None
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


# ─── Prompt Template Schemas ─────────────────────────────

class TemplateFrameworkParams(BaseModel):
    story_length: str = "long"
    pacing: str = "steady"
    structure: str = "flexible"
    chapter_detail_level: str = "high"
    character_depth: str = "deep"
    world_building: str = "rich"
    tone: str = "serious"
    custom_rules: str = ""


class TemplateChapterParams(BaseModel):
    writing_style: str = "descriptive"
    dialogue_ratio: str = "medium"
    scene_detail: str = "rich"
    inner_monologue: str = "moderate"
    pacing_preference: str = "varied"
    vocabulary_level: str = "advanced"
    custom_style_notes: str = ""


class TemplateCharacterParams(BaseModel):
    detail_level: str = "high"
    appearance_focus: str = "balanced"
    personality_depth: str = "deep"
    relationship_emphasis: str = "high"
    arc_planning: str = "complete"
    custom_requirements: str = ""


class TemplateMangaStyleParams(BaseModel):
    art_style: str = "anime"
    color_scheme: str = "vibrant"
    detail_level: str = "high"
    composition: str = "dynamic"
    lighting: str = "dramatic"
    mood: str = "epic"
    custom_style_prompt: str = ""


class PromptTemplateCreate(BaseModel):
    name: str
    description: str = ""
    category: str = ""
    tags: list[str] = []
    framework_prompt: Optional[str] = None
    chapter_prompt: Optional[str] = None
    character_prompt: Optional[str] = None
    manga_style_prompt: Optional[str] = None
    framework_params: Optional[TemplateFrameworkParams] = None
    chapter_params: Optional[TemplateChapterParams] = None
    character_params: Optional[TemplateCharacterParams] = None
    manga_style_params: Optional[TemplateMangaStyleParams] = None


class PromptTemplateUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    tags: Optional[list[str]] = None
    framework_prompt: Optional[str] = None
    chapter_prompt: Optional[str] = None
    character_prompt: Optional[str] = None
    manga_style_prompt: Optional[str] = None
    framework_params: Optional[TemplateFrameworkParams] = None
    chapter_params: Optional[TemplateChapterParams] = None
    character_params: Optional[TemplateCharacterParams] = None
    manga_style_params: Optional[TemplateMangaStyleParams] = None


class TemplateAuthorOut(BaseModel):
    id: int
    username: str


class PromptTemplateOut(BaseModel):
    id: int
    name: str
    description: Optional[str] = ""
    author: Optional[TemplateAuthorOut] = None
    category: Optional[str] = None
    tags: Optional[list] = None
    status: str
    visibility: str
    is_public: bool
    usage_count: int
    like_count: int
    framework_prompt: Optional[str] = None
    chapter_prompt: Optional[str] = None
    character_prompt: Optional[str] = None
    manga_style_prompt: Optional[str] = None
    framework_params: Optional[dict] = None
    chapter_params: Optional[dict] = None
    character_params: Optional[dict] = None
    manga_style_params: Optional[dict] = None
    forked_from: Optional[int] = None
    submitted_at: Optional[str] = None
    reviewed_at: Optional[str] = None
    review_note: Optional[str] = None
    created_at: str
    updated_at: str


class TemplateListOut(BaseModel):
    templates: list[PromptTemplateOut]
    total: int
    page: int
    page_size: int


class BindTemplateRequest(BaseModel):
    template_id: int


class AdminReviewRequest(BaseModel):
    visibility: str = "public"
    note: str = ""


# ─── 章节视频工作流 Schemas ────────────────────────────


class ChapterVideoWorkflowCreate(BaseModel):
    """创建章节视频工作流"""
    chapter_id: int
    character_reference_ids: list[int] = []
    video_style: str | None = None
    style_reference_image_url: str | None = None


class ChapterVideoShotCreate(BaseModel):
    """手动创建章节视频分镜。"""
    story_summary: str
    source_text_span: str | None = None
    scene_location: str | None = None
    time_of_day: str | None = None
    characters: list[str] = Field(default_factory=list)
    dialogue_or_narration: str | None = None
    camera_plan: str | None = None
    motion_plan: str | None = None
    emotion_plan: str | None = None
    continuity_notes: str | None = None


class ChapterVideoShotOut(BaseModel):
    """15 秒分镜输出"""
    id: int
    workflow_id: int
    shot_index: int
    source_text_span: str | None = None
    scene_location: str | None = None
    time_of_day: str | None = None
    characters: list[Any] | None = None
    story_summary: str | None = None
    dialogue_or_narration: str | None = None
    camera_plan: str | None = None
    motion_plan: str | None = None
    emotion_plan: str | None = None
    continuity_notes: str | None = None
    storyboard_prompt: str | None = None
    storyboard_prompt_stale: bool = False
    video_prompt: str | None = None
    character_prompts_json: list[dict[str, str]] | None = None
    character_prompts: list[dict[str, str]] | None = None
    scene_prompt: str | None = None
    prop_prompts_json: list[dict[str, str]] | None = None
    prop_prompts: list[dict[str, str]] | None = None
    key_props_json: list[str] | None = None
    key_props: list[str] | None = None
    scene_asset_candidates_json: list[str] | None = None
    scene_asset_candidates: list[str] | None = None
    character_reference_ids: list[Any] | None = None
    scene_reference_ids: list[Any] | None = None
    prop_reference_ids: list[Any] | None = None
    storyboard_json: dict[str, Any] | None = None
    storyboard_image_url: str | None = None
    video_url: str | None = None
    status: str = "pending"
    error_message: str | None = None
    screenplay_scene_id: str | None = None
    screenplay_beat_id: str | None = None
    narrative_purpose: str | None = None
    beat_density: str | None = None
    transition_to_next: str | None = None
    continuity_json: dict[str, Any] | None = None
    created_at: datetime.datetime

    model_config = {"from_attributes": True}

    @model_validator(mode='after')
    def _sync_json_fields(self) -> "ChapterVideoShotOut":
        """让 _json 字段和非 _json 字段保持同步，前端用 character_prompts/prop_prompts"""
        if self.character_prompts_json is not None and self.character_prompts is None:
            self.character_prompts = self.character_prompts_json
        if self.prop_prompts_json is not None and self.prop_prompts is None:
            self.prop_prompts = self.prop_prompts_json
        if self.character_prompts is not None and self.character_prompts_json is None:
            self.character_prompts_json = self.character_prompts
        if self.prop_prompts is not None and self.prop_prompts_json is None:
            self.prop_prompts_json = self.prop_prompts
        if self.key_props_json is not None and self.key_props is None:
            self.key_props = self.key_props_json
        if self.key_props is not None and self.key_props_json is None:
            self.key_props_json = self.key_props
        if self.scene_asset_candidates_json is not None and self.scene_asset_candidates is None:
            self.scene_asset_candidates = self.scene_asset_candidates_json
        if self.scene_asset_candidates is not None and self.scene_asset_candidates_json is None:
            self.scene_asset_candidates_json = self.scene_asset_candidates
        return self


class ChapterVideoWorkflowOut(BaseModel):
    """章节视频工作流输出"""
    id: int
    chapter_id: int
    story_id: int
    workflow_status: str = "pending"
    character_reference_ids: list[Any] | None = None
    video_style: str | None = None
    style_reference_image_url: str | None = None
    duration_per_shot: int = 15
    total_shots: int = 0
    completed_shots: int = 0
    failed_shots: int = 0
    error_message: str | None = None
    screenplay_text: str | None = None
    screenplay_json: dict[str, Any] | None = None
    screenplay_status: str = "missing"
    screenplay_updated_at: datetime.datetime | None = None
    screenplay_approved_at: datetime.datetime | None = None
    screenplay_version: int = 0
    created_at: datetime.datetime
    updated_at: datetime.datetime
    shots: list[ChapterVideoShotOut] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class ChapterVideoWorkflowListOut(BaseModel):
    workflows: list[ChapterVideoWorkflowOut]
    total: int


class ChapterVideoWorkflowStatusOut(BaseModel):
    """工作流状态输出（轻量）"""
    id: int
    chapter_id: int
    workflow_status: str
    total_shots: int
    completed_shots: int
    failed_shots: int
    error_message: str | None = None
    task_id: str | None = None
    stage: str | None = None
    message: str | None = None
    retry_count: int = 0
    max_retries: int = 0
    next_retry_at: str | None = None


# ─── 视频无限画布 Schemas ────────────────────────────────


class MangaDramaProjectCreate(BaseModel):
    """漫剧创作项目：story_type=video 的作品 + 初始空白画布一次创建。"""
    title: str = Field(default="未命名漫剧", min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    canvas_name: str = Field(default="主画布", min_length=1, max_length=255)
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=100)


class VideoCanvasCompileScenesRequest(BaseModel):
    """已批准场景节点 → 视频节点组编译请求（新路径需携带 AI 导演方案）。"""
    scene_node_ids: list[str] = Field(min_length=1, max_length=60)
    director_plan: dict[str, Any] | None = None
    director_plan_hash: str | None = Field(default=None, max_length=128)
    expected_definition_revision: int | None = Field(default=None, ge=1)


class VideoCanvasDirectorPlanRequest(BaseModel):
    """画布 AI 导演编排请求：读取已批准场景，返回可审阅方案（不写图、不生成）。"""
    scene_node_id: str = Field(min_length=1, max_length=64)
    user_constraints: str | None = Field(default=None, max_length=2000)
    expected_definition_revision: int | None = Field(default=None, ge=1)


class VideoCanvasAssetAnalysisRequest(BaseModel):
    """画布资产分析请求：剧本 → 角色/场景/道具资产清单与绘图提示词。"""
    scene_node_id: str = Field(min_length=1, max_length=64)
    expected_definition_revision: int | None = Field(default=None, ge=1)


class VideoCanvasScreenplaySplitRequest(BaseModel):
    """剧本节点 AI 拆分请求：读取节点当前内容，返回视频单元列表（不直接写图）。"""
    node_id: str = Field(min_length=1, max_length=64)


class VideoCanvasScreenplayImportSource(BaseModel):
    story_id: int
    chapter_id: int


class VideoCanvasScreenplayImportRequest(BaseModel):
    """小说章节导入：多选章节 → AI 改写为剧本草稿（只读原作品）。"""
    sources: list[VideoCanvasScreenplayImportSource] = Field(min_length=1, max_length=10)


class VideoCanvasCreate(BaseModel):
    story_id: int
    default_chapter_id: int | None = None
    name: str = Field(default="未命名画布", min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=100)


class VideoCanvasUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    status: Literal["draft", "archived"] | None = None


class VideoCanvasGraphSave(BaseModel):
    graph: dict[str, Any]
    expected_definition_revision: int = Field(ge=1)
    change_summary: str | None = Field(default=None, max_length=500)
    source: Literal["manual", "import", "agent"] = "manual"


class VideoCanvasLayoutSave(BaseModel):
    layout: dict[str, Any]
    expected_layout_revision: int = Field(ge=1)


class VideoCanvasPlanCreate(BaseModel):
    chapter_id: int | None = None
    source_snapshot_json: dict[str, Any] | None = None
    screenplay_json: dict[str, Any] | None = None
    shot_json: dict[str, Any] | None = None
    asset_json: dict[str, Any] | None = None
    canvas_json: dict[str, Any] | None = None
    execution_json: dict[str, Any] | None = None


class VideoCanvasPlanUpdate(BaseModel):
    status: Literal["draft", "ready"] | None = None
    source_snapshot_json: dict[str, Any] | None = None
    screenplay_json: dict[str, Any] | None = None
    shot_json: dict[str, Any] | None = None
    asset_json: dict[str, Any] | None = None
    canvas_json: dict[str, Any] | None = None
    execution_json: dict[str, Any] | None = None
    expected_revision: int = Field(ge=1)


class VideoCanvasPlanConfirmRequest(BaseModel):
    confirmed: Literal[True] = True
    expected_revision: int = Field(ge=1)


class VideoCanvasPlanApplyRequest(BaseModel):
    expected_plan_revision: int = Field(ge=1)
    expected_definition_revision: int = Field(ge=1)


class VideoCanvasPlanWorkflowSyncRequest(BaseModel):
    expected_plan_revision: int = Field(ge=1)


class VideoCanvasImportRequest(BaseModel):
    source_workflow_id: int
    mode: Literal["preview", "merge"] = "merge"
    expected_definition_revision: int | None = Field(default=None, ge=1)
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=100)


class VideoCanvasRunRequest(BaseModel):
    target_node_ids: list[str] = Field(default_factory=list, max_length=100)
    expected_definition_revision: int = Field(ge=1)
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=100)


class VideoCanvasRunConfirmRequest(BaseModel):
    """确认画布运行计划；生成节点在此步骤后才允许派发。"""
    confirmed: Literal[True] = True


class ChapterWorkflowStageActionRequest(BaseModel):
    """分阶段操作请求——用于手动触发拆镜/故事版/视频阶段"""
    shot_ids: list[int] = Field(default_factory=list)
    run_all: bool = False
    auto_continue: bool = False


class ChapterWorkflowPromptReanalyzeRequest(BaseModel):
    """重新分析故事版提示词请求"""
    shot_ids: list[int] = Field(default_factory=list)


class RegenerateShotRequest(BaseModel):
    """重新生成单镜头的故事版或视频"""
    target: str = "storyboard"  # "storyboard" | "video"
    prompt_override: str | None = None
    reference_asset_ids: list[int] = Field(default_factory=list)
    aspect_ratio: str | None = "16:9"
    duration_seconds: int | None = None


# Resolve forward references
ChapterOut.model_rebuild()
